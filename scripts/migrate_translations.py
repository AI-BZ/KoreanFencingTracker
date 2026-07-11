"""
Batch Migration Script for Multi-Language Translations

Populates translations JSONB columns for:
- Players: 11,000+ records
- Organizations: 500+ records
- Competitions: 130+ records

Usage:
    python scripts/migrate_translations.py --all
    python scripts/migrate_translations.py --players
    python scripts/migrate_translations.py --organizations
    python scripts/migrate_translations.py --competitions
    python scripts/migrate_translations.py --dry-run  # Preview without updating
"""

import argparse
import asyncio
import json
import sys
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client, Client
from dotenv import load_dotenv

from app.translation_service import TranslationService

load_dotenv()

BATCH_SIZE = 500
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


class TranslationMigrator:
    """Batch migrator for translations."""

    def __init__(self, dry_run: bool = False):
        self.supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        self.translation_service = TranslationService()
        self.dry_run = dry_run
        self.stats = {
            "players": {"total": 0, "translated": 0, "skipped": 0, "errors": 0},
            "organizations": {"total": 0, "translated": 0, "skipped": 0, "errors": 0},
            "competitions": {"total": 0, "translated": 0, "skipped": 0, "errors": 0},
        }

    def migrate_players(self) -> None:
        """Migrate player name translations."""
        print("\n" + "=" * 60)
        print("MIGRATING PLAYERS")
        print("=" * 60)

        # Get total count
        count_result = self.supabase.table("players").select("id", count="exact").execute()
        total = count_result.count or 0
        self.stats["players"]["total"] = total
        print(f"Total players: {total:,}")

        # Process in batches
        offset = 0
        batch_num = 0

        while offset < total:
            batch_num += 1
            print(f"\n[Batch {batch_num}] Processing {offset:,} - {min(offset + BATCH_SIZE, total):,}...")

            # Fetch batch
            result = self.supabase.table("players").select(
                "id", "player_name", "translations"
            ).range(offset, offset + BATCH_SIZE - 1).execute()

            players = result.data or []

            # Generate translations
            updates = []
            for player in players:
                # Skip if already has English translation
                existing = player.get("translations") or {}
                if isinstance(existing, dict) and existing.get("en", {}).get("name"):
                    self.stats["players"]["skipped"] += 1
                    continue

                korean_name = player.get("player_name", "")
                if not korean_name:
                    self.stats["players"]["skipped"] += 1
                    continue

                try:
                    translation = self.translation_service.translate_player_name(korean_name)
                    if translation:
                        # Merge with existing translations
                        merged = {**existing, **translation}
                        updates.append({
                            "id": player["id"],
                            "translations": merged,
                        })
                        self.stats["players"]["translated"] += 1
                except Exception as e:
                    print(f"  Error translating '{korean_name}': {e}")
                    self.stats["players"]["errors"] += 1

            # Update batch
            if updates and not self.dry_run:
                self._batch_update("players", updates)
                print(f"  Updated {len(updates)} players")
            elif updates:
                print(f"  [DRY RUN] Would update {len(updates)} players")
                # Show samples
                for sample in updates[:3]:
                    player_id = sample["id"]
                    en_name = sample["translations"].get("en", {}).get("name", "N/A")
                    print(f"    - ID {player_id}: {en_name}")

            offset += BATCH_SIZE

        self._print_stats("players")

    def migrate_organizations(self) -> None:
        """Migrate organization name translations."""
        print("\n" + "=" * 60)
        print("MIGRATING ORGANIZATIONS")
        print("=" * 60)

        # Get total count
        count_result = self.supabase.table("organizations").select("id", count="exact").execute()
        total = count_result.count or 0
        self.stats["organizations"]["total"] = total
        print(f"Total organizations: {total:,}")

        # Process in batches
        offset = 0
        batch_num = 0

        while offset < total:
            batch_num += 1
            print(f"\n[Batch {batch_num}] Processing {offset:,} - {min(offset + BATCH_SIZE, total):,}...")

            # Fetch batch
            result = self.supabase.table("organizations").select(
                "id", "name", "translations"
            ).range(offset, offset + BATCH_SIZE - 1).execute()

            orgs = result.data or []

            # Generate translations
            updates = []
            for org in orgs:
                # Skip if already has English translation
                existing = org.get("translations") or {}
                if isinstance(existing, dict) and existing.get("en", {}).get("name"):
                    self.stats["organizations"]["skipped"] += 1
                    continue

                korean_name = org.get("name", "")
                if not korean_name:
                    self.stats["organizations"]["skipped"] += 1
                    continue

                try:
                    translation = self.translation_service.translate_organization_name(korean_name)
                    if translation:
                        merged = {**existing, **translation}
                        updates.append({
                            "id": org["id"],
                            "translations": merged,
                        })
                        self.stats["organizations"]["translated"] += 1
                except Exception as e:
                    print(f"  Error translating '{korean_name}': {e}")
                    self.stats["organizations"]["errors"] += 1

            # Update batch
            if updates and not self.dry_run:
                self._batch_update("organizations", updates)
                print(f"  Updated {len(updates)} organizations")
            elif updates:
                print(f"  [DRY RUN] Would update {len(updates)} organizations")
                for sample in updates[:3]:
                    org_id = sample["id"]
                    en_name = sample["translations"].get("en", {}).get("name", "N/A")
                    print(f"    - ID {org_id}: {en_name}")

            offset += BATCH_SIZE

        self._print_stats("organizations")

    def migrate_competitions(self) -> None:
        """Migrate competition name translations."""
        print("\n" + "=" * 60)
        print("MIGRATING COMPETITIONS")
        print("=" * 60)

        # Get total count
        count_result = self.supabase.table("competitions").select("id", count="exact").execute()
        total = count_result.count or 0
        self.stats["competitions"]["total"] = total
        print(f"Total competitions: {total:,}")

        # Process in batches
        offset = 0
        batch_num = 0

        while offset < total:
            batch_num += 1
            print(f"\n[Batch {batch_num}] Processing {offset:,} - {min(offset + BATCH_SIZE, total):,}...")

            # Fetch batch
            result = self.supabase.table("competitions").select(
                "id", "comp_name", "translations"
            ).range(offset, offset + BATCH_SIZE - 1).execute()

            comps = result.data or []

            # Generate translations
            updates = []
            for comp in comps:
                # Skip if already has English translation
                existing = comp.get("translations") or {}
                if isinstance(existing, dict) and existing.get("en", {}).get("name"):
                    self.stats["competitions"]["skipped"] += 1
                    continue

                korean_name = comp.get("comp_name", "")
                if not korean_name:
                    self.stats["competitions"]["skipped"] += 1
                    continue

                try:
                    translation = self.translation_service.translate_competition_name(korean_name)
                    if translation:
                        merged = {**existing, **translation}
                        updates.append({
                            "id": comp["id"],
                            "translations": merged,
                        })
                        self.stats["competitions"]["translated"] += 1
                except Exception as e:
                    print(f"  Error translating '{korean_name}': {e}")
                    self.stats["competitions"]["errors"] += 1

            # Update batch
            if updates and not self.dry_run:
                self._batch_update("competitions", updates)
                print(f"  Updated {len(updates)} competitions")
            elif updates:
                print(f"  [DRY RUN] Would update {len(updates)} competitions")
                for sample in updates[:3]:
                    comp_id = sample["id"]
                    en_name = sample["translations"].get("en", {}).get("name", "N/A")
                    print(f"    - ID {comp_id}: {en_name}")

            offset += BATCH_SIZE

        self._print_stats("competitions")

    def _batch_update(self, table: str, updates: List[Dict[str, Any]]) -> None:
        """Update records in batch using upsert."""
        for update in updates:
            try:
                self.supabase.table(table).update({
                    "translations": update["translations"]
                }).eq("id", update["id"]).execute()
            except Exception as e:
                print(f"  Error updating {table} ID {update['id']}: {e}")

    def _print_stats(self, entity: str) -> None:
        """Print statistics for an entity type."""
        stats = self.stats[entity]
        print(f"\n{entity.upper()} SUMMARY:")
        print(f"  Total:      {stats['total']:,}")
        print(f"  Translated: {stats['translated']:,}")
        print(f"  Skipped:    {stats['skipped']:,}")
        print(f"  Errors:     {stats['errors']:,}")

    def print_final_summary(self) -> None:
        """Print final migration summary."""
        print("\n" + "=" * 60)
        print("MIGRATION COMPLETE")
        print("=" * 60)

        total_translated = sum(s["translated"] for s in self.stats.values())
        total_skipped = sum(s["skipped"] for s in self.stats.values())
        total_errors = sum(s["errors"] for s in self.stats.values())

        print(f"\nTotal Records Processed:")
        print(f"  Players:       {self.stats['players']['total']:,}")
        print(f"  Organizations: {self.stats['organizations']['total']:,}")
        print(f"  Competitions:  {self.stats['competitions']['total']:,}")
        print(f"\nTranslation Results:")
        print(f"  Translated: {total_translated:,}")
        print(f"  Skipped:    {total_skipped:,}")
        print(f"  Errors:     {total_errors:,}")

        if self.dry_run:
            print("\n[DRY RUN MODE - No changes were made to the database]")


def main():
    parser = argparse.ArgumentParser(description="Migrate translations for multi-language support")
    parser.add_argument("--all", action="store_true", help="Migrate all entities")
    parser.add_argument("--players", action="store_true", help="Migrate players only")
    parser.add_argument("--organizations", action="store_true", help="Migrate organizations only")
    parser.add_argument("--competitions", action="store_true", help="Migrate competitions only")
    parser.add_argument("--dry-run", action="store_true", help="Preview without updating database")

    args = parser.parse_args()

    # Default to --all if no specific entity selected
    if not any([args.all, args.players, args.organizations, args.competitions]):
        args.all = True

    migrator = TranslationMigrator(dry_run=args.dry_run)

    print("=" * 60)
    print("TRANSLATION MIGRATION")
    print(f"Started at: {datetime.now().isoformat()}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print("=" * 60)

    if args.all or args.players:
        migrator.migrate_players()

    if args.all or args.organizations:
        migrator.migrate_organizations()

    if args.all or args.competitions:
        migrator.migrate_competitions()

    migrator.print_final_summary()


if __name__ == "__main__":
    main()
