"""
대한펜싱협회 공지사항 게시판 모니터

국가대표 선발·교체·후보선수·합산 랭킹·규정 개정은 대회 결과 페이지가 아니라
공지사항 게시판 첨부(PDF/HWP)로만 공개된다. 이 모듈은 게시판 앞쪽 몇 페이지를
읽어 새 글을 data_kfa_notices 에 넣고, 첨부를 내려받아 텍스트를 뽑아 같은 행에
저장하고, 사람이 봐야 하는 태그면 Discord 로 알린다.

설계 메모:
- 대회 스크래핑과 완전히 분리된다. 스케줄러의 `_is_running` 락을 잡지 않고,
  어떤 예외도 밖으로 내보내지 않는다 (공지 수집이 실패했다고 대회 수집이
  멈추는 일은 없어야 한다).
- 첨부 원본은 data/kfa_notices/<boardNo>/ 에 보관만 한다. 코드는 이 파일을
  다시 읽지 않는다 — 텍스트는 DB 컬럼(attachments[].text)에 있다.
- 알림은 competition_detector 와 같은 '허용목록' 방식. ALERT_TAGS 에 있는
  태그가 하나라도 붙고 procurement(견적·채용 등)가 아니면 보낸다.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from loguru import logger

from app.kfa_notices import (
    KFA_BASE_URL,
    NOTICE_LIST_PATH,
    NOTICE_VIEW_PATH,
    NoticeDetail,
    NoticeRow,
    classify_tags,
    extract_text,
    parse_notice_detail,
    parse_notice_list,
    safe_filename,
)

# 사람이 봐야 하는 공지. 여기 없는 태그(youth, kkumnamu, other …)는 저장만 한다.
ALERT_TAGS = {
    "national_team",
    "candidate_u25",
    "ranking_points",
    "replacement",
    "regulation",
    "dispatch",
}
# 이 태그가 붙으면 위 태그가 있어도 알리지 않는다 (용구 견적, 채용 공고 등)
ALERT_SUPPRESS_TAGS = {"procurement"}

# 이 태그의 공지가 새로 들어오면 **우리 데이터에 반영**한다.
#   · 명단 계열 → `data_kfa_rosters` 재적재 (프로필 대표·후보 배지가 이걸 읽는다)
#   · 합산표    → 우리 NT 랭킹과 자동 대조 (협회 표가 정답지다, 제1원칙 5항)
SYNC_ROSTER_TAGS = {"national_team", "candidate_u25", "u23", "youth", "kkumnamu",
                    "replacement", "ranking_points"}
POINTS_TAGS = {"ranking_points"}

ARCHIVE_DIR = Path(__file__).resolve().parent.parent / "data" / "kfa_notices"
ATTACHMENT_MAX_BYTES = 40 * 1024 * 1024


def should_alert(tags: Iterable[str]) -> bool:
    ts = set(tags or [])
    return bool(ts & ALERT_TAGS) and not (ts & ALERT_SUPPRESS_TAGS)


class KfaNoticeMonitor:
    """게시판 스캔 → 저장 → 첨부 추출 → 알림."""

    def __init__(self, db=None, archive_dir: Optional[Path] = None, notify: bool = True):
        if db is None:
            from scheduler.competition_detector import get_supabase_client
            db = get_supabase_client()
        self.db = db
        self.archive_dir = Path(archive_dir) if archive_dir else ARCHIVE_DIR
        self.notify = notify

    # ------------------------------------------------------------------
    # 공개 진입점
    # ------------------------------------------------------------------
    async def run(self, pages: Iterable[int] = (1, 2, 3), refresh: bool = False) -> Dict[str, Any]:
        """지정한 목록 페이지를 훑어 새 공지를 저장한다.

        Args:
            pages: 목록 페이지 번호들
            refresh: True 면 이미 저장된 공지도 상세를 다시 읽어 갱신 (백필·재추출용)

        Returns:
            {"scanned", "new", "updated", "alerted", "attachments", "extracted", "errors"}
        """
        stats: Dict[str, Any] = {
            "scanned": 0, "new": 0, "updated": 0, "alerted": 0,
            "attachments": 0, "extracted": 0, "errors": [], "touched_tags": [],
            "started_at": datetime.now().isoformat(),
        }
        if not self.db:
            stats["errors"].append("Supabase 클라이언트 없음")
            return stats

        from scraper.client import KFFClient

        try:
            async with KFFClient() as client:
                for page in pages:
                    try:
                        html = await client._get(NOTICE_LIST_PATH.format(page=page))
                    except Exception as e:  # noqa: BLE001
                        stats["errors"].append(f"page {page}: {e}")
                        continue
                    rows = parse_notice_list(html)
                    if not rows:
                        logger.info(f"📰 공지 목록 {page}페이지: 행 없음 → 중단")
                        break
                    stats["scanned"] += len(rows)
                    known = self._known_board_nos([r.board_no for r in rows])
                    for row in rows:
                        is_new = row.board_no not in known
                        if not is_new and not refresh:
                            continue
                        try:
                            await self._process(client, row, is_new, stats)
                        except Exception as e:  # noqa: BLE001
                            logger.warning(f"📰 공지 {row.board_no} 처리 오류: {e}")
                            stats["errors"].append(f"{row.board_no}: {e}")
        except Exception as e:  # noqa: BLE001
            logger.error(f"📰 공지 모니터 오류: {e}")
            stats["errors"].append(str(e))

        # ── 수집한 공지를 우리 데이터에 반영 ──────────────────────────────
        # 수집만 하고 끝내면 명단이 와도 배지·랭킹이 그대로다. 아래 두 단계가 "반영"이다.
        # 어느 쪽이 실패해도 수집 결과는 유지한다(각각 예외를 삼킨다).
        touched = set(stats.get("touched_tags") or [])
        if touched & SYNC_ROSTER_TAGS:
            stats["roster_sync"] = self._sync_rosters()
        if touched & POINTS_TAGS:
            stats["points_check"] = self._verify_points_tables()

        stats["finished_at"] = datetime.now().isoformat()
        logger.info(
            f"📰 공지 모니터 완료: 스캔 {stats['scanned']} · 신규 {stats['new']} · 갱신 {stats['updated']} "
            f"· 알림 {stats['alerted']} · 첨부 {stats['attachments']}(추출 {stats['extracted']}) "
            f"· 오류 {len(stats['errors'])}"
        )
        if stats.get("roster_sync"):
            rs = stats["roster_sync"]
            logger.info(f"📰 명단 반영: {rs.get('records')}행 (seed_rank {rs.get('seeded')}건) "
                        f"→ data_kfa_rosters 총 {rs.get('total')}행")
        if stats.get("points_check"):
            logger.info(f"📰 합산표 대조: {stats['points_check'].get('summary')}")
        return stats


    # ------------------------------------------------------------------
    # 우리 데이터에 반영
    # ------------------------------------------------------------------
    def _sync_rosters(self) -> Dict[str, Any]:
        """명단 계열 공지를 `data_kfa_rosters` 에 재적재한다 (멱등 upsert).

        프로필의 '국가대표·후보·23세이하·청소년대표' 배지가 이 표를 읽으므로, 이 단계가
        없으면 새 명단이 공지돼도 사이트에는 반영되지 않는다.
        """
        try:
            import sys
            scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from load_kfa_rosters import sync_rosters
            out = sync_rosters(self.db)
            if out.get("warnings"):
                logger.warning(f"📰 명단 파싱 경고 {len(out['warnings'])}건: {out['warnings'][:3]}")
            return out
        except Exception as e:  # noqa: BLE001
            logger.error(f"📰 명단 반영 실패: {e}")
            return {"error": str(e)[:200]}

    def _verify_points_tables(self) -> Dict[str, Any]:
        """새 합산표를 우리 NT 랭킹과 대조한다.

        협회 표가 정답지다(제1원칙 5항). 자동으로 맞춰 보고 **상위 선발권 인원의 집합·순서**가
        어긋나면 경고한다 — 그 구간이 어긋나면 "누가 대표가 되는가"가 달라지기 때문이다.
        서버 프로세스 안에서만 동작한다(랭킹 계산에 서버의 대회 캐시를 쓴다). 캐시가 없으면
        건너뛴다 — 스케줄러가 이 때문에 실패하지는 않는다.
        """
        try:
            from app.kfa_roster_parser import parse_ranking_points
            from app import server as srv

            calc = getattr(srv, "_ranking_calculator", None)
            if calc is None or not hasattr(calc, "calculate_nt_table"):
                return {"skipped": "랭킹 계산기 없음(서버 프로세스 밖)"}

            rows = (self.db.table("data_kfa_notices")
                    .select("board_no,title,posted_at,attachments")
                    .contains("tags", ["ranking_points"])
                    .order("posted_at", desc=True).limit(1).execute().data or [])
            if not rows:
                return {"skipped": "합산표 공지 없음"}
            notice = rows[0]

            kfa_rows = []
            for att in (notice.get("attachments") or []):
                kfa_rows += parse_ranking_points(att.get("text") or "")
            if not kfa_rows:
                return {"board_no": notice["board_no"], "skipped": "표 파싱 결과 없음"}

            # 협회 표의 (연도, 무기, 성별) 별로 상위 N명을 우리 표와 대조
            groups: Dict[tuple, List[Any]] = {}
            for r in kfa_rows:
                groups.setdefault((r.year, r.weapon, r.gender), []).append(r)

            checked, top_match, mismatches = 0, 0, []
            for (year, weapon, gender), krows in sorted(groups.items()):
                krows.sort(key=lambda x: x.rank)
                try:
                    table = calc.calculate_nt_table(weapon, gender, year)
                except Exception as e:  # noqa: BLE001
                    mismatches.append(f"{year} {weapon}/{gender}: 우리 표 계산 실패 {str(e)[:60]}")
                    continue
                quota = table.quota or 8
                kfa_top = [r.player_name for r in krows[:quota]]
                our_top = [p.player_name for p in table.rankings[:quota]]
                checked += 1
                if kfa_top == our_top:
                    top_match += 1
                else:
                    mismatches.append(
                        f"{year} {weapon}/{gender} 상위{quota}: 협회 {kfa_top} vs 우리 {our_top}")

            out = {
                "board_no": notice["board_no"],
                "title": (notice.get("title") or "")[:60],
                "posted_at": notice.get("posted_at"),
                "checked": checked,
                "top_match": top_match,
                "mismatches": mismatches[:6],
                "summary": f"{top_match}/{checked} 종목 상위 선발권 일치",
            }
            if checked and top_match < checked:
                logger.error(
                    f"🚨 협회 합산표와 우리 NT 랭킹의 상위 선발권이 어긋남 "
                    f"({top_match}/{checked}): {mismatches[:2]}"
                )
            return out
        except Exception as e:  # noqa: BLE001
            logger.error(f"📰 합산표 대조 실패: {e}")
            return {"error": str(e)[:200]}

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------
    def _known_board_nos(self, board_nos: List[int]) -> set:
        if not board_nos:
            return set()
        res = (self.db.table("data_kfa_notices").select("board_no")
               .in_("board_no", board_nos).execute())
        return {r["board_no"] for r in (res.data or [])}

    async def _process(self, client, row: NoticeRow, is_new: bool, stats: Dict[str, Any]) -> None:
        html = await client._get(NOTICE_VIEW_PATH.format(no=row.board_no))
        detail = parse_notice_detail(html, row.board_no)
        title = detail.title or row.title
        posted = detail.posted_at or row.posted_at
        tags = classify_tags(title, detail.body_text)

        attachments = await self._fetch_attachments(client, detail, stats)

        record = {
            "board_no": row.board_no,
            "title": title,
            "posted_at": posted.isoformat() if posted else None,
            "url": row.url or KFA_BASE_URL + NOTICE_VIEW_PATH.format(no=row.board_no),
            "body_text": detail.body_text,
            "is_pinned": row.is_pinned,
            "tags": tags,
            "attachments": attachments,
            "updated_at": datetime.now().isoformat(),
        }
        self.db.table("data_kfa_notices").upsert(record, on_conflict="board_no").execute()
        stats["new" if is_new else "updated"] += 1
        # 어떤 태그가 들어왔는지 모아 둔다 — run() 끝에서 '반영' 단계를 띄우는 기준이다.
        stats.setdefault("touched_tags", []).extend(tags)
        logger.info(f"📰 {'신규' if is_new else '갱신'} 공지 {row.board_no} [{','.join(tags)}] {title[:60]}")

        if is_new and self.notify and should_alert(tags):
            if await self._send_alert(record):
                self.db.table("data_kfa_notices").update(
                    {"notified_at": datetime.now().isoformat()}
                ).eq("board_no", row.board_no).execute()
                stats["alerted"] += 1

    async def _fetch_attachments(self, client, detail: NoticeDetail, stats: Dict[str, Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for idx, att in enumerate(detail.attachments):
            stats["attachments"] += 1
            entry: Dict[str, Any] = {
                "name": att.name, "url": att.url, "local_path": None, "kind": "other",
                "text_extracted": False, "text": "", "extract_note": None,
            }
            try:
                data = await self._download(client, att.url)
                if data is None:
                    entry["extract_note"] = "다운로드 실패"
                else:
                    entry["local_path"] = self._archive(detail.board_no, idx, att.name, data)
                    entry.update(extract_text(data, att.name))
                    if entry["text_extracted"]:
                        stats["extracted"] += 1
            except Exception as e:  # noqa: BLE001
                entry["extract_note"] = f"첨부 처리 오류: {str(e)[:160]}"
            out.append(entry)
        return out

    async def _download(self, client, url: str) -> Optional[bytes]:
        for attempt in range(3):
            try:
                async with client._session.get(url, timeout=90) as r:
                    if r.status != 200:
                        logger.warning(f"📎 첨부 HTTP {r.status}: {url[-80:]}")
                        return None
                    data = await r.read()
                    if len(data) > ATTACHMENT_MAX_BYTES:
                        logger.warning(f"📎 첨부 {len(data)}B 초과, 보관 생략: {url[-80:]}")
                        return None
                    return data
            except asyncio.TimeoutError:
                await asyncio.sleep(2 * (attempt + 1))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"📎 첨부 다운로드 오류: {e}")
                await asyncio.sleep(2 * (attempt + 1))
        return None

    def _archive(self, board_no: int, idx: int, name: str, data: bytes) -> Optional[str]:
        """원본 보관. 실패해도 텍스트 추출은 계속되어야 하므로 None 만 돌려준다."""
        try:
            d = self.archive_dir / str(board_no)
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"{idx}_{safe_filename(name)}"
            p.write_bytes(data)
            return str(p.relative_to(self.archive_dir.parent.parent))
        except Exception as e:  # noqa: BLE001
            logger.debug(f"📎 첨부 보관 실패: {e}")
            return None

    async def _send_alert(self, record: Dict[str, Any]) -> bool:
        try:
            from app.discord_notify import send_alert
            atts = record.get("attachments") or []
            att_text = "\n".join(
                f"- {a['name']} ({a['kind']}{'' if a['text_extracted'] else ', 텍스트 없음'})" for a in atts
            ) or "(없음)"
            return await send_alert(
                severity="info",
                title="협회 공지 감지",
                message=f"**{record['title']}**\n{record['url']}",
                fields=[
                    {"name": "게시일", "value": record.get("posted_at") or "?", "inline": True},
                    {"name": "태그", "value": ", ".join(record.get("tags") or []), "inline": True},
                    {"name": "첨부", "value": att_text[:1000], "inline": False},
                ],
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Discord 알림 오류: {e}")
            return False
