"""
Automatic Player Data Update Pipeline

This module handles automatic updates to player data when competitions end:
1. Detects completed competitions that haven't been processed
2. Validates competition data integrity
3. Updates player team_name to most recent competition's team
4. Updates player team_history with proper date periods
5. Recalculates rankings if needed
6. Logs all changes for audit

Usage:
    # Run as standalone script
    python scheduler/player_data_updater.py --dry-run
    python scheduler/player_data_updater.py --execute

    # Or import and use in scheduler
    from scheduler.player_data_updater import PlayerDataPipeline
    pipeline = PlayerDataPipeline()
    result = pipeline.run()
"""

import os
import sys
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
import json
from loguru import logger

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()


class ProcessingStatus(str, Enum):
    """Processing status for competition updates"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ValidationResult:
    """Result of competition data validation"""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    event_count: int = 0
    events_with_results: int = 0
    events_missing_results: List[str] = field(default_factory=list)


@dataclass
class PlayerUpdateResult:
    """Result of a single player update operation"""
    player_id: int
    player_name: str
    success: bool
    change_type: str  # 'team_update', 'team_history_update', 'no_change'
    old_value: Optional[Dict] = None
    new_value: Optional[Dict] = None
    error: Optional[str] = None


@dataclass
class ProcessingResult:
    """Result of processing a single competition"""
    competition_id: int
    competition_name: str
    status: ProcessingStatus
    validation_result: Optional[ValidationResult] = None
    players_updated: int = 0
    team_histories_updated: int = 0
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class CompletedCompetitionDetector:
    """
    Detects competitions that have ended and need player data processing.

    Detection criteria:
    1. Competition end_date has passed
    2. Competition has not been processed yet (player_updates_processed_at is NULL)
    3. Competition has at least one event with results
    """

    def __init__(self, supabase: Client):
        self.db = supabase

    def detect_completed_competitions(
        self,
        days_lookback: int = 30,
        limit: int = 50
    ) -> List[Dict]:
        """
        Find competitions that ended within the lookback period and need processing.

        Args:
            days_lookback: How many days back to look for completed competitions
            limit: Maximum number of competitions to return

        Returns:
            List of competition records needing processing
        """
        cutoff_date = (date.today() - timedelta(days=days_lookback)).isoformat()

        query = """
            SELECT
                c.id,
                c.comp_idx,
                c.comp_name,
                c.start_date,
                c.end_date,
                c.status,
                c.event_count,
                c.player_updates_processed_at,
                (SELECT COUNT(*) FROM events e WHERE e.competition_id = c.id) as actual_event_count
            FROM competitions c
            WHERE
                c.end_date IS NOT NULL
                AND c.end_date < CURRENT_DATE
                AND c.end_date >= %s
                AND c.player_updates_processed_at IS NULL
            ORDER BY c.end_date DESC
            LIMIT %s
        """

        # Use view if available, otherwise direct query
        try:
            result = self.db.table('competitions') \
                .select('id, comp_idx, comp_name, start_date, end_date, status, event_count, player_updates_processed_at') \
                .is_('player_updates_processed_at', 'null') \
                .lt('end_date', date.today().isoformat()) \
                .gte('end_date', cutoff_date) \
                .order('end_date', desc=True) \
                .limit(limit) \
                .execute()

            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error detecting completed competitions: {e}")
            return []

    def get_competition_events(self, competition_id: int) -> List[Dict]:
        """Get all events for a competition with their result status."""
        try:
            result = self.db.table('events') \
                .select('id, event_cd, event_name, gender, age_group, weapon, raw_data') \
                .eq('competition_id', competition_id) \
                .execute()

            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting events for competition {competition_id}: {e}")
            return []


class CompetitionDataValidator:
    """
    Validates competition data integrity before processing.

    Validation checks:
    1. All events have raw_data with results
    2. Events have proper final_rankings
    3. No critical data inconsistencies
    """

    def __init__(self, supabase: Client):
        self.db = supabase

    def validate_competition(self, competition_id: int) -> ValidationResult:
        """
        Validate that a competition's data is complete and ready for processing.

        Args:
            competition_id: The competition to validate

        Returns:
            ValidationResult with pass/fail status and details
        """
        errors = []
        warnings = []
        events_missing_results = []

        # Get all events for this competition
        events = self.db.table('events') \
            .select('id, event_cd, event_name, raw_data') \
            .eq('competition_id', competition_id) \
            .execute()

        if not events.data:
            return ValidationResult(
                is_valid=False,
                errors=["No events found for competition"],
                event_count=0,
                events_with_results=0
            )

        event_count = len(events.data)
        events_with_results = 0

        for event in events.data:
            raw_data = event.get('raw_data', {})

            if not raw_data:
                events_missing_results.append(event['event_name'])
                continue

            # Check for final_rankings
            final_rankings = raw_data.get('final_rankings', [])
            if not final_rankings:
                warnings.append(f"Event '{event['event_name']}' has no final rankings")
            else:
                events_with_results += 1

            # Check for pool or DE data
            has_pool = bool(raw_data.get('pool_rounds', []))
            has_de = bool(raw_data.get('de_bracket', {}))

            if not has_pool and not has_de:
                warnings.append(f"Event '{event['event_name']}' has no pool or DE data")

        # Determine if validation passed
        # At least 80% of events should have results
        result_ratio = events_with_results / event_count if event_count > 0 else 0
        is_valid = result_ratio >= 0.8 and len(errors) == 0

        if result_ratio < 0.8:
            errors.append(f"Only {events_with_results}/{event_count} events have results ({result_ratio:.0%})")

        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            event_count=event_count,
            events_with_results=events_with_results,
            events_missing_results=events_missing_results
        )


class PlayerDataUpdater:
    """
    Updates player records based on competition data.

    Update operations:
    1. Update team_name to most recent competition's team
    2. Update team_history with proper date periods
    3. Track all changes for audit
    """

    def __init__(self, supabase: Client, dry_run: bool = False):
        self.db = supabase
        self.dry_run = dry_run
        self._events_cache: Dict[str, List[Dict]] = {}
        self._comp_dates_cache: Dict[int, str] = {}

    def _load_competitions_cache(self) -> None:
        """Load competition dates for team history calculation."""
        if self._comp_dates_cache:
            return

        logger.info("Loading competitions cache...")
        result = self.db.table('competitions') \
            .select('id, start_date') \
            .execute()

        if result.data:
            self._comp_dates_cache = {
                c['id']: c['start_date']
                for c in result.data
                if c.get('start_date')
            }
        logger.info(f"Loaded {len(self._comp_dates_cache)} competition dates")

    def _extract_players_from_competition(self, competition_id: int) -> List[Dict]:
        """
        Extract all unique player entries from a competition's events.

        Returns list of dicts with: name, team, date
        """
        self._load_competitions_cache()

        comp_date = self._comp_dates_cache.get(competition_id)
        if not comp_date:
            logger.warning(f"No date found for competition {competition_id}")
            return []

        events = self.db.table('events') \
            .select('id, event_name, raw_data') \
            .eq('competition_id', competition_id) \
            .execute()

        if not events.data:
            return []

        players = []
        seen = set()

        for event in events.data:
            raw_data = event.get('raw_data', {})
            if not raw_data:
                continue

            # Extract from final_rankings
            for r in raw_data.get('final_rankings', []):
                name = r.get('name', '').strip()
                team = r.get('team', '').strip()
                if name and team and (name, team) not in seen:
                    seen.add((name, team))
                    players.append({
                        'name': name,
                        'team': team,
                        'date': comp_date,
                        'event_name': event.get('event_name', '')
                    })

            # Extract from pool_rounds
            for pool in raw_data.get('pool_rounds', []):
                for r in pool.get('results', []):
                    name = r.get('name', '').strip()
                    team = r.get('team', '').strip()
                    if name and team and (name, team) not in seen:
                        seen.add((name, team))
                        players.append({
                            'name': name,
                            'team': team,
                            'date': comp_date,
                            'event_name': event.get('event_name', '')
                        })

            # Extract from DE bracket seeding
            de_bracket = raw_data.get('de_bracket', {})
            for r in de_bracket.get('seeding', []):
                name = r.get('name', '').strip()
                team = r.get('team', '').strip()
                if name and team and (name, team) not in seen:
                    seen.add((name, team))
                    players.append({
                        'name': name,
                        'team': team,
                        'date': comp_date,
                        'event_name': event.get('event_name', '')
                    })

        return players

    def _get_player_by_name(self, name: str) -> Optional[Dict]:
        """Get player record by name (returns most recent active player)."""
        result = self.db.table('players') \
            .select('*') \
            .eq('player_name', name) \
            .is_('merged_into', 'null') \
            .neq('is_active', False) \
            .order('updated_at', desc=True) \
            .limit(1) \
            .execute()

        return result.data[0] if result.data else None

    def _rebuild_team_history(self, player_name: str) -> List[Dict]:
        """
        Rebuild complete team history for a player from all events.

        Returns list of team records:
        [{"team": "...", "first_seen": "...", "last_seen": "..."}, ...]
        """
        self._load_competitions_cache()

        # Get all events where this player participated
        # Using pagination due to potentially large result sets
        all_records = []
        offset = 0
        page_size = 500

        while True:
            result = self.db.table('events') \
                .select('id, event_name, raw_data, competition_id') \
                .range(offset, offset + page_size - 1) \
                .execute()

            if not result.data:
                break

            for event in result.data:
                raw_data = event.get('raw_data', {})
                if not raw_data:
                    continue

                comp_date = self._comp_dates_cache.get(event['competition_id'])
                if not comp_date:
                    continue

                # Check all data sources for this player
                def check_player(records, player_name, comp_date):
                    for r in records:
                        if r.get('name', '').strip() == player_name:
                            team = r.get('team', '').strip()
                            if team:
                                return {'team': team, 'date': comp_date}
                    return None

                # Check final_rankings
                player_entry = check_player(raw_data.get('final_rankings', []), player_name, comp_date)
                if player_entry:
                    all_records.append(player_entry)
                    continue

                # Check pool_rounds
                for pool in raw_data.get('pool_rounds', []):
                    player_entry = check_player(pool.get('results', []), player_name, comp_date)
                    if player_entry:
                        all_records.append(player_entry)
                        break

                # Check DE seeding
                de_bracket = raw_data.get('de_bracket', {})
                player_entry = check_player(de_bracket.get('seeding', []), player_name, comp_date)
                if player_entry:
                    all_records.append(player_entry)

            if len(result.data) < page_size:
                break
            offset += page_size

        if not all_records:
            return []

        # Aggregate by team
        team_records = {}
        for record in all_records:
            team = record['team']
            record_date = record['date']

            if team not in team_records:
                team_records[team] = {
                    'team': team,
                    'first_seen': record_date,
                    'last_seen': record_date
                }
            else:
                if record_date < team_records[team]['first_seen']:
                    team_records[team]['first_seen'] = record_date
                if record_date > team_records[team]['last_seen']:
                    team_records[team]['last_seen'] = record_date

        # Sort by first_seen date
        history = sorted(team_records.values(), key=lambda x: x['first_seen'])
        return history

    def update_player_from_competition(
        self,
        player_name: str,
        new_team: str,
        comp_date: str,
        competition_id: int,
        processing_log_id: Optional[int] = None
    ) -> PlayerUpdateResult:
        """
        Update a single player's team information based on competition data.

        Logic:
        1. If comp_date is more recent than player's last update, update team_name
        2. Always update team_history with new period

        Args:
            player_name: Player's name
            new_team: Team from the competition
            comp_date: Competition start date
            competition_id: Competition ID for audit
            processing_log_id: Processing log ID for audit

        Returns:
            PlayerUpdateResult with change details
        """
        # Get existing player record
        player = self._get_player_by_name(player_name)

        if not player:
            # Player doesn't exist in database yet
            return PlayerUpdateResult(
                player_id=0,
                player_name=player_name,
                success=False,
                change_type='player_not_found',
                error=f"Player '{player_name}' not found in database"
            )

        player_id = player['id']
        current_team = player.get('team_name', '')
        current_history = player.get('team_history', []) or []

        # Determine if we need to update team_name
        # We update if: current is different AND this competition is more recent
        need_team_update = False

        if current_team != new_team:
            # Check if this competition is the most recent
            # by comparing with last_seen dates in history
            last_seen_date = None
            if current_history:
                for h in current_history:
                    if h.get('team') == current_team:
                        last_seen_date = h.get('last_seen')
                        break

            if last_seen_date is None or comp_date >= last_seen_date:
                need_team_update = True

        # Update team_history
        new_history = list(current_history)
        history_updated = False

        # Find or create entry for new_team
        team_entry_found = False
        for entry in new_history:
            if entry.get('team') == new_team:
                team_entry_found = True
                # Update dates if needed
                if comp_date < entry.get('first_seen', comp_date):
                    entry['first_seen'] = comp_date
                    history_updated = True
                if comp_date > entry.get('last_seen', '0000-00-00'):
                    entry['last_seen'] = comp_date
                    history_updated = True
                break

        if not team_entry_found:
            # Add new team entry
            new_history.append({
                'team': new_team,
                'first_seen': comp_date,
                'last_seen': comp_date
            })
            history_updated = True
            # Sort by first_seen
            new_history.sort(key=lambda x: x.get('first_seen', ''))

        # Determine what changes to make
        if not need_team_update and not history_updated:
            return PlayerUpdateResult(
                player_id=player_id,
                player_name=player_name,
                success=True,
                change_type='no_change'
            )

        old_value = {
            'team_name': current_team,
            'team_history': current_history
        }
        new_value = {
            'team_name': new_team if need_team_update else current_team,
            'team_history': new_history
        }

        if self.dry_run:
            change_type = 'team_update' if need_team_update else 'team_history_update'
            return PlayerUpdateResult(
                player_id=player_id,
                player_name=player_name,
                success=True,
                change_type=change_type,
                old_value=old_value,
                new_value=new_value
            )

        # Execute the update
        try:
            update_data = {
                'team_history': new_history,
                'updated_at': datetime.now().isoformat()
            }

            if need_team_update:
                update_data['team_name'] = new_team

            self.db.table('players') \
                .update(update_data) \
                .eq('id', player_id) \
                .execute()

            # Log the change
            if processing_log_id:
                self._log_player_update(
                    player_id=player_id,
                    processing_log_id=processing_log_id,
                    competition_id=competition_id,
                    change_type='team_update' if need_team_update else 'team_history_update',
                    old_value=old_value,
                    new_value=new_value
                )

            return PlayerUpdateResult(
                player_id=player_id,
                player_name=player_name,
                success=True,
                change_type='team_update' if need_team_update else 'team_history_update',
                old_value=old_value,
                new_value=new_value
            )

        except Exception as e:
            logger.error(f"Error updating player {player_name}: {e}")
            return PlayerUpdateResult(
                player_id=player_id,
                player_name=player_name,
                success=False,
                change_type='error',
                error=str(e)
            )

    def _log_player_update(
        self,
        player_id: int,
        processing_log_id: int,
        competition_id: int,
        change_type: str,
        old_value: Dict,
        new_value: Dict
    ) -> None:
        """Log a player update to the history table."""
        try:
            self.db.table('player_update_history').insert({
                'player_id': player_id,
                'processing_log_id': processing_log_id,
                'competition_id': competition_id,
                'change_type': change_type,
                'old_value': old_value,
                'new_value': new_value,
                'reason': f'Automatic update from competition {competition_id}'
            }).execute()
        except Exception as e:
            logger.warning(f"Failed to log player update: {e}")


class PlayerDataPipeline:
    """
    Main pipeline orchestrator for automatic player data updates.

    Pipeline stages:
    1. Detect completed competitions
    2. Validate competition data
    3. Update player records
    4. Mark competition as processed
    5. Log results
    """

    VERSION = "1.0.0"

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.supabase: Client = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_KEY")
        )

        self.detector = CompletedCompetitionDetector(self.supabase)
        self.validator = CompetitionDataValidator(self.supabase)
        self.updater = PlayerDataUpdater(self.supabase, dry_run=dry_run)

        self.results: List[ProcessingResult] = []

    def _create_processing_log(
        self,
        competition_id: int,
        triggered_by: str = 'scheduler'
    ) -> Optional[int]:
        """Create a processing log entry and return its ID."""
        if self.dry_run:
            return None

        try:
            result = self.supabase.table('competition_processing_logs').insert({
                'competition_id': competition_id,
                'processing_type': 'player_update',
                'status': 'processing',
                'triggered_by': triggered_by,
                'processor_version': self.VERSION
            }).execute()

            return result.data[0]['id'] if result.data else None
        except Exception as e:
            logger.error(f"Failed to create processing log: {e}")
            return None

    def _update_processing_log(
        self,
        log_id: int,
        status: str,
        validation_result: Optional[ValidationResult] = None,
        players_updated: int = 0,
        team_histories_updated: int = 0,
        error_message: Optional[str] = None
    ) -> None:
        """Update a processing log with results."""
        if self.dry_run or not log_id:
            return

        try:
            update_data = {
                'status': status,
                'completed_at': datetime.now().isoformat(),
                'players_updated': players_updated,
                'team_histories_updated': team_histories_updated
            }

            if validation_result:
                update_data['validation_passed'] = validation_result.is_valid
                update_data['validation_errors'] = {
                    'errors': validation_result.errors,
                    'warnings': validation_result.warnings,
                    'events_missing_results': validation_result.events_missing_results
                }

            if error_message:
                update_data['error_message'] = error_message

            self.supabase.table('competition_processing_logs') \
                .update(update_data) \
                .eq('id', log_id) \
                .execute()
        except Exception as e:
            logger.error(f"Failed to update processing log: {e}")

    def _mark_competition_processed(self, competition_id: int) -> None:
        """Mark a competition as processed."""
        if self.dry_run:
            return

        try:
            self.supabase.table('competitions') \
                .update({
                    'player_updates_processed_at': datetime.now().isoformat()
                }) \
                .eq('id', competition_id) \
                .execute()
        except Exception as e:
            logger.error(f"Failed to mark competition as processed: {e}")

    def process_competition(
        self,
        competition: Dict,
        triggered_by: str = 'scheduler'
    ) -> ProcessingResult:
        """
        Process a single competition for player data updates.

        Args:
            competition: Competition record dict
            triggered_by: Source of the trigger ('scheduler', 'manual', 'scraper')

        Returns:
            ProcessingResult with details
        """
        start_time = datetime.now()
        comp_id = competition['id']
        comp_name = competition['comp_name']

        logger.info(f"Processing competition: {comp_name} (ID: {comp_id})")

        # Create processing log
        log_id = self._create_processing_log(comp_id, triggered_by)

        # Validate competition data
        validation_result = self.validator.validate_competition(comp_id)

        if not validation_result.is_valid:
            logger.warning(f"Competition {comp_name} failed validation: {validation_result.errors}")

            self._update_processing_log(
                log_id,
                status='failed',
                validation_result=validation_result,
                error_message='; '.join(validation_result.errors)
            )

            return ProcessingResult(
                competition_id=comp_id,
                competition_name=comp_name,
                status=ProcessingStatus.FAILED,
                validation_result=validation_result,
                errors=validation_result.errors,
                duration_seconds=(datetime.now() - start_time).total_seconds()
            )

        # Extract players from competition
        players = self.updater._extract_players_from_competition(comp_id)
        logger.info(f"Found {len(players)} player entries in competition")

        # Update each player
        players_updated = 0
        team_histories_updated = 0
        errors = []

        # Group by player name to avoid duplicate updates
        player_entries = defaultdict(list)
        for p in players:
            player_entries[p['name']].append(p)

        for player_name, entries in player_entries.items():
            # Use the most recent entry for this player
            latest_entry = max(entries, key=lambda x: x['date'])

            result = self.updater.update_player_from_competition(
                player_name=player_name,
                new_team=latest_entry['team'],
                comp_date=latest_entry['date'],
                competition_id=comp_id,
                processing_log_id=log_id
            )

            if result.success:
                if result.change_type == 'team_update':
                    players_updated += 1
                elif result.change_type == 'team_history_update':
                    team_histories_updated += 1
            elif result.error:
                errors.append(f"{player_name}: {result.error}")

        # Mark competition as processed
        self._mark_competition_processed(comp_id)

        # Update processing log
        self._update_processing_log(
            log_id,
            status='completed',
            validation_result=validation_result,
            players_updated=players_updated,
            team_histories_updated=team_histories_updated
        )

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"Completed {comp_name}: {players_updated} team updates, "
            f"{team_histories_updated} history updates in {duration:.1f}s"
        )

        return ProcessingResult(
            competition_id=comp_id,
            competition_name=comp_name,
            status=ProcessingStatus.COMPLETED,
            validation_result=validation_result,
            players_updated=players_updated,
            team_histories_updated=team_histories_updated,
            errors=errors,
            duration_seconds=duration
        )

    def run(
        self,
        days_lookback: int = 30,
        limit: int = 50,
        triggered_by: str = 'scheduler'
    ) -> Dict[str, Any]:
        """
        Run the complete pipeline.

        Args:
            days_lookback: How many days back to look for completed competitions
            limit: Maximum competitions to process in one run
            triggered_by: Source of the trigger

        Returns:
            Summary dict with statistics
        """
        logger.info(f"Starting Player Data Pipeline v{self.VERSION}")
        logger.info(f"Mode: {'DRY-RUN' if self.dry_run else 'EXECUTE'}")

        start_time = datetime.now()

        # Detect completed competitions
        competitions = self.detector.detect_completed_competitions(
            days_lookback=days_lookback,
            limit=limit
        )

        logger.info(f"Found {len(competitions)} competitions to process")

        if not competitions:
            return {
                'status': 'success',
                'message': 'No competitions to process',
                'competitions_found': 0,
                'competitions_processed': 0,
                'total_players_updated': 0,
                'total_histories_updated': 0,
                'duration_seconds': 0
            }

        # Process each competition
        self.results = []
        total_players_updated = 0
        total_histories_updated = 0

        for comp in competitions:
            result = self.process_competition(comp, triggered_by)
            self.results.append(result)

            total_players_updated += result.players_updated
            total_histories_updated += result.team_histories_updated

        # Summary
        completed = sum(1 for r in self.results if r.status == ProcessingStatus.COMPLETED)
        failed = sum(1 for r in self.results if r.status == ProcessingStatus.FAILED)

        duration = (datetime.now() - start_time).total_seconds()

        summary = {
            'status': 'success' if failed == 0 else 'partial',
            'dry_run': self.dry_run,
            'competitions_found': len(competitions),
            'competitions_processed': completed,
            'competitions_failed': failed,
            'total_players_updated': total_players_updated,
            'total_histories_updated': total_histories_updated,
            'duration_seconds': duration,
            'results': [
                {
                    'competition_id': r.competition_id,
                    'competition_name': r.competition_name,
                    'status': r.status.value,
                    'players_updated': r.players_updated,
                    'team_histories_updated': r.team_histories_updated,
                    'errors': r.errors
                }
                for r in self.results
            ]
        }

        logger.info(f"Pipeline completed: {completed}/{len(competitions)} competitions processed")
        logger.info(f"Total: {total_players_updated} player updates, {total_histories_updated} history updates")

        return summary


def main():
    """CLI entry point for the player data pipeline."""
    import argparse

    parser = argparse.ArgumentParser(description='Automatic Player Data Update Pipeline')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='Run without making changes (default)')
    parser.add_argument('--execute', action='store_true',
                        help='Actually execute changes')
    parser.add_argument('--days', type=int, default=30,
                        help='Days to look back for completed competitions')
    parser.add_argument('--limit', type=int, default=50,
                        help='Maximum competitions to process')
    parser.add_argument('--competition-id', type=int,
                        help='Process a specific competition only')

    args = parser.parse_args()

    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

    dry_run = not args.execute

    print(f"\n{'='*60}")
    print(f"Player Data Update Pipeline v{PlayerDataPipeline.VERSION}")
    print(f"Mode: {'DRY-RUN (no changes)' if dry_run else 'EXECUTE (real changes)'}")
    print(f"{'='*60}\n")

    pipeline = PlayerDataPipeline(dry_run=dry_run)

    if args.competition_id:
        # Process specific competition
        comp = pipeline.supabase.table('competitions') \
            .select('*') \
            .eq('id', args.competition_id) \
            .single() \
            .execute()

        if comp.data:
            result = pipeline.process_competition(comp.data, triggered_by='manual')
            print(f"\nResult: {result.status.value}")
            print(f"Players updated: {result.players_updated}")
            print(f"Histories updated: {result.team_histories_updated}")
            if result.errors:
                print(f"Errors: {result.errors}")
        else:
            print(f"Competition {args.competition_id} not found")
    else:
        # Run full pipeline
        summary = pipeline.run(
            days_lookback=args.days,
            limit=args.limit,
            triggered_by='manual'
        )

        print(f"\n{'='*60}")
        print("Summary:")
        print(f"{'='*60}")
        print(f"Competitions found: {summary['competitions_found']}")
        print(f"Competitions processed: {summary['competitions_processed']}")
        print(f"Competitions failed: {summary['competitions_failed']}")
        print(f"Total players updated: {summary['total_players_updated']}")
        print(f"Total histories updated: {summary['total_histories_updated']}")
        print(f"Duration: {summary['duration_seconds']:.1f}s")

        if dry_run:
            print(f"\n[DRY-RUN] No actual changes were made.")
            print(f"Run with --execute to apply changes.")


if __name__ == '__main__':
    main()
