# Change Detection System Architecture

## Executive Summary

This document defines the architecture for a real-time change detection system for the Korean Fencing Federation (KFF) website. The system monitors competition results every 5 minutes and triggers selective scraping only for changed events.

---

## 1. System Overview

### 1.1 Design Goals

| Goal | Description | Priority |
|------|-------------|----------|
| **Efficiency** | Only scrape changed events, not entire competitions | Critical |
| **Resilience** | Continue operation despite individual failures | Critical |
| **Stealth** | Avoid bot detection through human-like patterns | High |
| **Scalability** | Handle multiple concurrent competitions | High |
| **Observability** | Full visibility into detection and scraping operations | Medium |

### 1.2 High-Level Architecture

```
                                    ┌─────────────────────────────────────────┐
                                    │           Fencing Scheduler             │
                                    │  (APScheduler - 5min interval trigger)  │
                                    └─────────────────┬───────────────────────┘
                                                      │
                                                      ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              Change Detection System                                 │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                      │
│   ┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐    │
│   │   ChangeDetector    │───▶│    StateManager     │───▶│   ChangeNotifier    │    │
│   │  (Web Fingerprint)  │    │  (DB + In-Memory)   │    │  (Event Dispatch)   │    │
│   └─────────────────────┘    └─────────────────────┘    └─────────────────────┘    │
│             │                          │                          │                 │
│             │                          │                          │                 │
│             ▼                          ▼                          ▼                 │
│   ┌─────────────────────────────────────────────────────────────────────────────┐  │
│   │                        Fingerprint Comparison Engine                         │  │
│   │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │  │
│   │  │ Pool Count  │  │  DE Count   │  │ Ranking Cnt │  │   Hash Diff │        │  │
│   │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘        │  │
│   └─────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
                            ┌─────────────────────────────────────┐
                            │      Selective Event Scraper        │
                            │  (Only scrape changed sub_events)   │
                            └─────────────────────────────────────┘
                                              │
                                              ▼
                            ┌─────────────────────────────────────┐
                            │           Supabase DB               │
                            │  events, event_fingerprints, logs   │
                            └─────────────────────────────────────┘
```

---

## 2. Change Detection Indicators

### 2.1 Fingerprint Components

Based on the KFF website structure, we track these change indicators:

| Indicator | Source | Change Meaning |
|-----------|--------|----------------|
| `pool_bout_count` | Pool V/D result cells | Pool matches completed |
| `pool_ranking_count` | Pool total ranking rows | Pool phase advancement |
| `de_completed_count` | DE bracket completed matches | DE phase progress |
| `de_bracket_hash` | MD5 of DE bracket HTML | Any DE structure change |
| `final_ranking_count` | Final ranking rows | Event completion |
| `final_ranking_hash` | MD5 of ranking HTML | Any ranking change |

### 2.2 Fingerprint Data Structure

```python
@dataclass
class EventFingerprint:
    """Event state fingerprint for change detection"""

    # Identification
    competition_id: str          # COMPM00679
    sub_event_cd: str            # COMPS00001
    event_name: str              # "남자 플뢰레 일반부 개인"

    # Pool indicators
    pool_bout_count: int         # Number of V/D results in pool
    pool_ranking_count: int      # Rows in pool total ranking
    pool_has_data: bool          # True if pool data exists

    # DE indicators
    de_completed_count: int      # Completed DE bouts
    de_bracket_hash: str         # MD5 hash of DE bracket structure
    de_has_data: bool            # True if DE data exists

    # Final ranking indicators
    final_ranking_count: int     # Rows in final ranking
    final_ranking_hash: str      # MD5 hash of ranking table
    event_completed: bool        # True if final ranking exists

    # Metadata
    captured_at: datetime        # When fingerprint was captured
    raw_html_size: int           # Page HTML size (sanity check)

    def has_changed(self, other: 'EventFingerprint') -> bool:
        """Compare with another fingerprint to detect changes"""
        return (
            self.pool_bout_count != other.pool_bout_count or
            self.pool_ranking_count != other.pool_ranking_count or
            self.de_completed_count != other.de_completed_count or
            self.de_bracket_hash != other.de_bracket_hash or
            self.final_ranking_count != other.final_ranking_count or
            self.final_ranking_hash != other.final_ranking_hash
        )

    def get_change_type(self, other: 'EventFingerprint') -> List[str]:
        """Identify what types of changes occurred"""
        changes = []
        if self.pool_bout_count != other.pool_bout_count:
            changes.append('pool_bouts')
        if self.pool_ranking_count != other.pool_ranking_count:
            changes.append('pool_ranking')
        if self.de_completed_count != other.de_completed_count:
            changes.append('de_bouts')
        if self.de_bracket_hash != other.de_bracket_hash:
            changes.append('de_structure')
        if self.final_ranking_count != other.final_ranking_count:
            changes.append('final_ranking')
        return changes
```

---

## 3. Component Design

### 3.1 ChangeDetector Class

```python
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from datetime import datetime
import hashlib
from enum import Enum


class DetectionStrategy(Enum):
    """Detection strategy based on event state"""
    FULL_CHECK = "full"           # Check all indicators
    POOL_FOCUSED = "pool"         # Focus on pool changes
    DE_FOCUSED = "de"             # Focus on DE changes
    RANKING_ONLY = "ranking"      # Only check final ranking


class ChangeDetector:
    """
    Lightweight change detector for KFF competition events.

    Responsibilities:
    - Fetch minimal fingerprint data from website
    - Compare with stored fingerprints
    - Report changed events for selective scraping

    Usage:
        detector = ChangeDetector()
        async with detector:
            changes = await detector.detect_changes(competition_id)
            for event_cd, change_info in changes.items():
                await scraper.scrape_event(event_cd)
    """

    BASE_URL = "https://fencing.sports.or.kr"

    def __init__(
        self,
        state_manager: 'StateManager',
        stealth_mode: bool = True,
        detection_strategy: DetectionStrategy = DetectionStrategy.FULL_CHECK
    ):
        self.state_manager = state_manager
        self.stealth_mode = stealth_mode
        self.strategy = detection_strategy
        self._browser = None
        self._playwright = None

    async def __aenter__(self):
        """Initialize Playwright browser"""
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled']
        )
        return self

    async def __aexit__(self, *args):
        """Cleanup browser resources"""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def detect_changes(
        self,
        competition_id: str,
        events: Optional[List[str]] = None
    ) -> Dict[str, 'ChangeInfo']:
        """
        Detect changes for a competition.

        Args:
            competition_id: COMPM format competition ID
            events: Optional list of specific sub_event_cd to check
                   If None, checks all events in competition

        Returns:
            Dict mapping sub_event_cd to ChangeInfo for changed events
        """
        changes = {}

        # Get events to check
        if events is None:
            events = await self._get_competition_events(competition_id)

        for sub_event_cd in events:
            try:
                # Capture current fingerprint
                current = await self._capture_fingerprint(
                    competition_id, sub_event_cd
                )

                # Get stored fingerprint
                stored = await self.state_manager.get_fingerprint(
                    competition_id, sub_event_cd
                )

                # Compare
                if stored is None:
                    # New event - always scrape
                    changes[sub_event_cd] = ChangeInfo(
                        sub_event_cd=sub_event_cd,
                        change_type=['new_event'],
                        current_fingerprint=current,
                        previous_fingerprint=None
                    )
                elif current.has_changed(stored):
                    change_types = current.get_change_type(stored)
                    changes[sub_event_cd] = ChangeInfo(
                        sub_event_cd=sub_event_cd,
                        change_type=change_types,
                        current_fingerprint=current,
                        previous_fingerprint=stored
                    )

                # Update stored fingerprint
                await self.state_manager.save_fingerprint(current)

                # Stealth delay
                if self.stealth_mode:
                    await self._stealth_delay()

            except Exception as e:
                logger.error(f"Fingerprint capture failed for {sub_event_cd}: {e}")
                continue

        return changes

    async def _capture_fingerprint(
        self,
        competition_id: str,
        sub_event_cd: str
    ) -> EventFingerprint:
        """
        Capture current fingerprint by extracting counts from page.

        This is a LIGHTWEIGHT operation - we only count elements,
        not parse full data.
        """
        page = await self._browser.new_page()

        try:
            # Navigate to competition and select event
            await self._navigate_to_event(page, competition_id, sub_event_cd)

            # Extract fingerprint data (lightweight)
            fingerprint_data = await page.evaluate("""
                () => {
                    // Pool bout count: count V/D cells in pool results
                    const poolCells = document.querySelectorAll(
                        '.pool-result td.v, .pool-result td.d'
                    );

                    // Pool ranking count: rows in pool total ranking
                    const poolRankingRows = document.querySelectorAll(
                        '.pool-total-ranking tbody tr'
                    );

                    // DE completed count: bouts with scores
                    const deCompletedBouts = document.querySelectorAll(
                        '.de-bracket .bout.completed'
                    );

                    // DE bracket hash source
                    const deBracket = document.querySelector('.de-bracket');
                    const deHtml = deBracket ? deBracket.innerHTML : '';

                    // Final ranking count
                    const finalRankingRows = document.querySelectorAll(
                        '.final-ranking tbody tr'
                    );
                    const finalRankingTable = document.querySelector('.final-ranking');
                    const finalHtml = finalRankingTable ? finalRankingTable.innerHTML : '';

                    return {
                        pool_bout_count: poolCells.length,
                        pool_ranking_count: poolRankingRows.length,
                        de_completed_count: deCompletedBouts.length,
                        de_html: deHtml,
                        final_ranking_count: finalRankingRows.length,
                        final_html: finalHtml,
                        html_size: document.body.innerHTML.length
                    };
                }
            """)

            return EventFingerprint(
                competition_id=competition_id,
                sub_event_cd=sub_event_cd,
                event_name=await self._get_event_name(page),
                pool_bout_count=fingerprint_data['pool_bout_count'],
                pool_ranking_count=fingerprint_data['pool_ranking_count'],
                pool_has_data=fingerprint_data['pool_bout_count'] > 0,
                de_completed_count=fingerprint_data['de_completed_count'],
                de_bracket_hash=self._hash(fingerprint_data['de_html']),
                de_has_data=len(fingerprint_data['de_html']) > 0,
                final_ranking_count=fingerprint_data['final_ranking_count'],
                final_ranking_hash=self._hash(fingerprint_data['final_html']),
                event_completed=fingerprint_data['final_ranking_count'] > 0,
                captured_at=datetime.now(),
                raw_html_size=fingerprint_data['html_size']
            )

        finally:
            await page.close()

    def _hash(self, content: str) -> str:
        """Create MD5 hash of content"""
        if not content:
            return ""
        return hashlib.md5(content.encode()).hexdigest()

    async def _stealth_delay(self):
        """Random delay to appear human-like"""
        import random
        delay = random.uniform(2.0, 5.0)
        await asyncio.sleep(delay)
```

### 3.2 StateManager Class

```python
class StateManager:
    """
    Manages fingerprint state with dual storage:
    - In-memory: Fast access during active detection
    - Database: Persistence across restarts

    Storage Strategy:
    - Active competitions: In-memory + DB sync
    - Historical: DB only
    - Expired fingerprints: Auto-cleanup after 24h
    """

    def __init__(self, db_client: Client, cache_ttl_hours: int = 24):
        self.db = db_client
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self._memory_cache: Dict[str, EventFingerprint] = {}
        self._dirty_keys: Set[str] = set()  # Modified but not synced

    def _make_key(self, competition_id: str, sub_event_cd: str) -> str:
        return f"{competition_id}:{sub_event_cd}"

    async def get_fingerprint(
        self,
        competition_id: str,
        sub_event_cd: str
    ) -> Optional[EventFingerprint]:
        """Get fingerprint, checking memory first then DB"""
        key = self._make_key(competition_id, sub_event_cd)

        # Memory cache first
        if key in self._memory_cache:
            return self._memory_cache[key]

        # Then database
        try:
            result = self.db.table("event_fingerprints").select("*").eq(
                "competition_id", competition_id
            ).eq(
                "sub_event_cd", sub_event_cd
            ).single().execute()

            if result.data:
                fp = self._deserialize(result.data)
                self._memory_cache[key] = fp
                return fp
        except Exception:
            pass

        return None

    async def save_fingerprint(self, fingerprint: EventFingerprint):
        """Save fingerprint to memory and mark for DB sync"""
        key = self._make_key(
            fingerprint.competition_id,
            fingerprint.sub_event_cd
        )
        self._memory_cache[key] = fingerprint
        self._dirty_keys.add(key)

    async def sync_to_db(self):
        """Batch sync dirty fingerprints to database"""
        if not self._dirty_keys:
            return

        batch = []
        for key in list(self._dirty_keys):
            if key in self._memory_cache:
                batch.append(self._serialize(self._memory_cache[key]))

        if batch:
            try:
                self.db.table("event_fingerprints").upsert(
                    batch,
                    on_conflict="competition_id,sub_event_cd"
                ).execute()
                self._dirty_keys.clear()
                logger.info(f"Synced {len(batch)} fingerprints to DB")
            except Exception as e:
                logger.error(f"DB sync failed: {e}")

    async def cleanup_expired(self):
        """Remove fingerprints older than TTL"""
        cutoff = (datetime.now() - self.cache_ttl).isoformat()

        # Clear from memory
        expired = [
            k for k, v in self._memory_cache.items()
            if v.captured_at.isoformat() < cutoff
        ]
        for k in expired:
            del self._memory_cache[k]

        # Clear from DB
        try:
            self.db.table("event_fingerprints").delete().lt(
                "captured_at", cutoff
            ).execute()
        except Exception as e:
            logger.warning(f"Cleanup failed: {e}")

    def _serialize(self, fp: EventFingerprint) -> dict:
        """Convert fingerprint to DB row"""
        return {
            "competition_id": fp.competition_id,
            "sub_event_cd": fp.sub_event_cd,
            "event_name": fp.event_name,
            "pool_bout_count": fp.pool_bout_count,
            "pool_ranking_count": fp.pool_ranking_count,
            "pool_has_data": fp.pool_has_data,
            "de_completed_count": fp.de_completed_count,
            "de_bracket_hash": fp.de_bracket_hash,
            "de_has_data": fp.de_has_data,
            "final_ranking_count": fp.final_ranking_count,
            "final_ranking_hash": fp.final_ranking_hash,
            "event_completed": fp.event_completed,
            "captured_at": fp.captured_at.isoformat(),
            "raw_html_size": fp.raw_html_size,
        }

    def _deserialize(self, row: dict) -> EventFingerprint:
        """Convert DB row to fingerprint"""
        return EventFingerprint(
            competition_id=row["competition_id"],
            sub_event_cd=row["sub_event_cd"],
            event_name=row["event_name"],
            pool_bout_count=row["pool_bout_count"],
            pool_ranking_count=row["pool_ranking_count"],
            pool_has_data=row["pool_has_data"],
            de_completed_count=row["de_completed_count"],
            de_bracket_hash=row["de_bracket_hash"],
            de_has_data=row["de_has_data"],
            final_ranking_count=row["final_ranking_count"],
            final_ranking_hash=row["final_ranking_hash"],
            event_completed=row["event_completed"],
            captured_at=datetime.fromisoformat(row["captured_at"]),
            raw_html_size=row["raw_html_size"],
        )
```

### 3.3 ChangeInfo and ChangeNotifier

```python
@dataclass
class ChangeInfo:
    """Information about detected change"""
    sub_event_cd: str
    change_type: List[str]  # ['pool_bouts', 'de_structure', etc.]
    current_fingerprint: EventFingerprint
    previous_fingerprint: Optional[EventFingerprint]
    detected_at: datetime = field(default_factory=datetime.now)

    @property
    def is_pool_change(self) -> bool:
        return any(t.startswith('pool') for t in self.change_type)

    @property
    def is_de_change(self) -> bool:
        return any(t.startswith('de') for t in self.change_type)

    @property
    def is_completion(self) -> bool:
        return 'final_ranking' in self.change_type


class ChangeNotifier:
    """
    Dispatches change events to handlers.

    Supports multiple notification channels:
    - Direct callback (for immediate scraping)
    - Database logging (for audit trail)
    - Webhook (for external integrations)
    """

    def __init__(self):
        self._handlers: List[Callable] = []
        self.db = get_supabase_client()

    def add_handler(self, handler: Callable[[ChangeInfo], Awaitable[None]]):
        """Register a change handler"""
        self._handlers.append(handler)

    async def notify(self, change: ChangeInfo):
        """Notify all handlers of a change"""
        # Log to database
        await self._log_change(change)

        # Dispatch to handlers
        for handler in self._handlers:
            try:
                await handler(change)
            except Exception as e:
                logger.error(f"Handler failed: {e}")

    async def _log_change(self, change: ChangeInfo):
        """Record change in detection_logs table"""
        if not self.db:
            return

        try:
            self.db.table("detection_logs").insert({
                "competition_id": change.current_fingerprint.competition_id,
                "sub_event_cd": change.sub_event_cd,
                "change_types": change.change_type,
                "detected_at": change.detected_at.isoformat(),
                "fingerprint_before": asdict(change.previous_fingerprint) if change.previous_fingerprint else None,
                "fingerprint_after": asdict(change.current_fingerprint),
            }).execute()
        except Exception as e:
            logger.warning(f"Failed to log change: {e}")
```

---

## 4. Scheduler Integration

### 4.1 Updated FencingScheduler

```python
class FencingScheduler:
    """Extended scheduler with change detection"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._is_running = False
        self.state_manager = None
        self.change_detector = None
        self.change_notifier = None

    def setup(self):
        """Setup all scheduled jobs"""
        # Initialize components
        self.state_manager = StateManager(get_supabase_client())
        self.change_notifier = ChangeNotifier()

        # Register scraping handler
        self.change_notifier.add_handler(self._handle_change)

        # === CHANGE DETECTION JOB (NEW) ===
        # Every 5 minutes during active hours
        self.scheduler.add_job(
            self._run_change_detection,
            CronTrigger(minute="*/5"),  # Every 5 minutes
            id="change_detection",
            name="Change Detection (5min)",
            replace_existing=True
        )
        logger.info("Change detection: Every 5 minutes")

        # === STATE SYNC JOB (NEW) ===
        # Sync fingerprints to DB every 15 minutes
        self.scheduler.add_job(
            self._sync_state,
            CronTrigger(minute="*/15"),
            id="state_sync",
            name="State DB Sync (15min)",
            replace_existing=True
        )

        # ... existing jobs ...

    async def _run_change_detection(self):
        """Run change detection for ongoing competitions"""
        # Check active hours
        current_hour = datetime.now().hour
        if not (8 <= current_hour < 21):
            logger.debug("Outside active hours, skipping detection")
            return

        if self._is_running:
            logger.debug("Another task running, skip detection")
            return

        self._is_running = True

        try:
            # Get ongoing competitions
            comps = await self._get_ongoing_competitions()

            if not comps:
                logger.debug("No ongoing competitions")
                return

            logger.info(f"Detecting changes for {len(comps)} competitions")

            async with ChangeDetector(self.state_manager) as detector:
                for comp in comps:
                    comp_id = comp.get("comp_idx")

                    try:
                        changes = await detector.detect_changes(comp_id)

                        if changes:
                            logger.info(f"Found {len(changes)} changes in {comp['comp_name']}")
                            for sub_event_cd, change_info in changes.items():
                                await self.change_notifier.notify(change_info)
                        else:
                            logger.debug(f"No changes in {comp['comp_name']}")

                    except Exception as e:
                        logger.error(f"Detection failed for {comp_id}: {e}")

        except Exception as e:
            logger.error(f"Change detection error: {e}")
        finally:
            self._is_running = False

    async def _handle_change(self, change: ChangeInfo):
        """Handle detected change by triggering selective scrape"""
        logger.info(
            f"Handling change: {change.sub_event_cd} "
            f"types={change.change_type}"
        )

        try:
            from scraper.full_scraper import KFFFullScraper

            async with KFFFullScraper(headless=True) as scraper:
                # Only scrape the changed event
                result = await scraper.get_full_results(
                    change.current_fingerprint.competition_id,
                    change.sub_event_cd,
                    page_num=1
                )

                if result:
                    await self._save_event_data(
                        change.current_fingerprint.competition_id,
                        change.sub_event_cd,
                        result
                    )
                    logger.info(f"Updated {change.sub_event_cd}")

        except Exception as e:
            logger.error(f"Selective scrape failed: {e}")

    async def _sync_state(self):
        """Sync state manager to database"""
        if self.state_manager:
            await self.state_manager.sync_to_db()
            await self.state_manager.cleanup_expired()
```

---

## 5. Database Schema

### 5.1 New Tables

```sql
-- Event fingerprints for change detection
CREATE TABLE event_fingerprints (
    id SERIAL PRIMARY KEY,
    competition_id VARCHAR(20) NOT NULL,
    sub_event_cd VARCHAR(20) NOT NULL,
    event_name VARCHAR(200),

    -- Pool indicators
    pool_bout_count INTEGER DEFAULT 0,
    pool_ranking_count INTEGER DEFAULT 0,
    pool_has_data BOOLEAN DEFAULT FALSE,

    -- DE indicators
    de_completed_count INTEGER DEFAULT 0,
    de_bracket_hash VARCHAR(32),
    de_has_data BOOLEAN DEFAULT FALSE,

    -- Final ranking indicators
    final_ranking_count INTEGER DEFAULT 0,
    final_ranking_hash VARCHAR(32),
    event_completed BOOLEAN DEFAULT FALSE,

    -- Metadata
    captured_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    raw_html_size INTEGER,

    UNIQUE(competition_id, sub_event_cd)
);

CREATE INDEX idx_fingerprints_comp ON event_fingerprints(competition_id);
CREATE INDEX idx_fingerprints_captured ON event_fingerprints(captured_at);


-- Change detection logs
CREATE TABLE detection_logs (
    id SERIAL PRIMARY KEY,
    competition_id VARCHAR(20) NOT NULL,
    sub_event_cd VARCHAR(20) NOT NULL,
    change_types TEXT[] NOT NULL,
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    fingerprint_before JSONB,
    fingerprint_after JSONB NOT NULL,
    scrape_triggered BOOLEAN DEFAULT FALSE,
    scrape_completed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_detection_logs_time ON detection_logs(detected_at DESC);
CREATE INDEX idx_detection_logs_comp ON detection_logs(competition_id);
```

---

## 6. Error Handling Strategy

### 6.1 Error Categories

| Category | Examples | Handling |
|----------|----------|----------|
| **Network** | Timeout, connection refused | Retry with backoff |
| **Rate Limit** | 429 response, bot detection | Pause 5min, reduce frequency |
| **Parse Error** | Element not found | Log warning, use fallback |
| **State Error** | DB write failed | Queue for retry |
| **Fatal** | Browser crash | Restart component |

### 6.2 Retry Strategy

```python
class RetryStrategy:
    """Exponential backoff with jitter"""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    async def execute(
        self,
        func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """Execute with retry"""
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_error = e

                if attempt < self.max_retries:
                    delay = min(
                        self.base_delay * (2 ** attempt) + random.uniform(0, 1),
                        self.max_delay
                    )
                    logger.warning(
                        f"Attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)

        raise last_error
```

### 6.3 Circuit Breaker

```python
class CircuitBreaker:
    """Prevent cascade failures"""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 300.0  # 5 minutes
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure: Optional[datetime] = None
        self.state = "closed"  # closed, open, half-open

    def record_failure(self):
        self.failures += 1
        self.last_failure = datetime.now()

        if self.failures >= self.failure_threshold:
            self.state = "open"
            logger.warning("Circuit breaker OPEN - too many failures")

    def record_success(self):
        self.failures = 0
        self.state = "closed"

    def can_execute(self) -> bool:
        if self.state == "closed":
            return True

        if self.state == "open":
            # Check if recovery timeout passed
            if self.last_failure:
                elapsed = (datetime.now() - self.last_failure).total_seconds()
                if elapsed > self.recovery_timeout:
                    self.state = "half-open"
                    return True
            return False

        # half-open: allow one request to test
        return True
```

---

## 7. Monitoring and Logging

### 7.1 Metrics to Track

| Metric | Type | Purpose |
|--------|------|---------|
| `detection_runs_total` | Counter | Total detection cycles |
| `changes_detected_total` | Counter | Total changes found |
| `detection_duration_seconds` | Histogram | Detection cycle time |
| `fingerprint_cache_size` | Gauge | Memory cache entries |
| `scrape_triggered_total` | Counter | Scrapes triggered by changes |
| `error_total` | Counter | Errors by type |

### 7.2 Structured Logging

```python
# Use loguru with structured fields
logger.bind(
    component="change_detector",
    competition_id=comp_id,
    sub_event_cd=sub_event_cd
).info("Change detected", change_types=change.change_type)
```

### 7.3 Health Check Endpoint

```python
@app.get("/health/change-detection")
async def health_check():
    """Health check for change detection system"""
    scheduler = get_scheduler()
    state = scheduler.state_manager

    return {
        "status": "healthy",
        "scheduler_running": scheduler.scheduler.running,
        "cache_size": len(state._memory_cache) if state else 0,
        "dirty_keys": len(state._dirty_keys) if state else 0,
        "last_detection": scheduler._last_detection.isoformat() if scheduler._last_detection else None,
        "next_run": scheduler.scheduler.get_job("change_detection").next_run_time.isoformat()
    }
```

---

## 8. Implementation Plan

### Phase 1: Core Components (Week 1)
- [ ] Implement `EventFingerprint` dataclass
- [ ] Implement `StateManager` with DB schema
- [ ] Implement basic `ChangeDetector`
- [ ] Add unit tests

### Phase 2: Integration (Week 2)
- [ ] Integrate with `FencingScheduler`
- [ ] Implement `ChangeNotifier` with handlers
- [ ] Add selective scraping trigger
- [ ] End-to-end testing

### Phase 3: Hardening (Week 3)
- [ ] Add retry and circuit breaker
- [ ] Implement monitoring metrics
- [ ] Performance optimization
- [ ] Load testing

### Phase 4: Production (Week 4)
- [ ] Deploy to staging
- [ ] Monitor behavior during live competition
- [ ] Fine-tune detection thresholds
- [ ] Production deployment

---

## 9. Configuration

```python
# config.py addition

class ChangeDetectionConfig(BaseSettings):
    """Change detection configuration"""

    # Detection schedule
    detection_interval_minutes: int = Field(
        default=5,
        description="How often to check for changes"
    )
    active_hours_start: int = Field(default=8)
    active_hours_end: int = Field(default=21)

    # Fingerprint storage
    fingerprint_cache_ttl_hours: int = Field(
        default=24,
        description="How long to keep fingerprints"
    )
    db_sync_interval_minutes: int = Field(
        default=15,
        description="How often to sync to DB"
    )

    # Stealth settings
    stealth_delay_min: float = Field(default=2.0)
    stealth_delay_max: float = Field(default=5.0)

    # Error handling
    max_retries: int = Field(default=3)
    circuit_breaker_threshold: int = Field(default=5)
    circuit_breaker_timeout: float = Field(default=300.0)

    model_config = SettingsConfigDict(
        env_prefix="CHANGE_DETECTION_",
        case_sensitive=False
    )

change_detection_config = ChangeDetectionConfig()
```

---

## 10. File Structure

```
services/data/
├── scheduler/
│   ├── scheduler.py              # FencingScheduler (updated)
│   ├── competition_detector.py   # Existing competition detector
│   └── change_detection/         # NEW
│       ├── __init__.py
│       ├── detector.py           # ChangeDetector class
│       ├── fingerprint.py        # EventFingerprint dataclass
│       ├── state_manager.py      # StateManager class
│       ├── notifier.py           # ChangeNotifier class
│       └── errors.py             # Error handling utilities
├── scraper/
│   ├── config.py                 # Add ChangeDetectionConfig
│   └── full_scraper.py           # Existing scraper
└── docs/
    └── change-detection-architecture.md  # This document
```

---

## Appendix A: KFF Website Structure Analysis

Based on inspection of the KFF website, the change indicators are extracted from:

```javascript
// Pool results - count V/D cells
document.querySelectorAll('table.pool-matrix td.result-v, td.result-d')

// Pool ranking - count rows
document.querySelectorAll('div.pool-ranking table tbody tr')

// DE bracket - completed bouts have both scores
document.querySelectorAll('.de-match .score:not(:empty)')

// Final ranking - count ranked players
document.querySelectorAll('.final-ranking tbody tr')
```

The exact selectors may need adjustment based on the actual DOM structure observed during implementation.
