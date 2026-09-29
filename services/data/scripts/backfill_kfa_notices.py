"""협회 공지사항 게시판 백필.

data_kfa_notices 는 2026-09-27 에 도입됐다. 스케줄러는 앞쪽 3페이지만 보므로
과거 공지(국가대표 명단 2024·2025, 후보선수, 합산 랭킹, 규정 개정)는 이 스크립트로
한 번 채운다. 재실행하면 이미 저장된 boardNo 는 건너뛰므로(--refresh 가 없으면)
중간에 끊겨도 같은 명령을 다시 돌리면 된다.

알림은 보내지 않는다 (과거 공지 수백 건이 Discord 로 쏟아지면 안 된다).

사용법:
    cd services/data
    PYTHONPATH=".:../../packages" python scripts/backfill_kfa_notices.py --pages 1-10
    PYTHONPATH=".:../../packages" python scripts/backfill_kfa_notices.py --pages 11-40
    PYTHONPATH=".:../../packages" python scripts/backfill_kfa_notices.py --board 10576 10582 --refresh
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from loguru import logger

from app.kfa_notices import NOTICE_VIEW_PATH, NoticeRow
from scheduler.kfa_notice_monitor import KfaNoticeMonitor


def _parse_pages(spec: str):
    out = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


async def _refresh_boards(monitor: KfaNoticeMonitor, board_nos):
    """특정 boardNo 만 다시 읽는다 (파서 개선 후 재추출용)."""
    from scraper.client import KFFClient
    stats = {"scanned": 0, "new": 0, "updated": 0, "alerted": 0, "attachments": 0, "extracted": 0, "errors": []}
    known = monitor._known_board_nos(list(board_nos))
    async with KFFClient() as client:
        for no in board_nos:
            row = NoticeRow(board_no=no, title="", posted_at=None,
                            url="https://fencing.sports.or.kr" + NOTICE_VIEW_PATH.format(no=no))
            stats["scanned"] += 1
            try:
                await monitor._process(client, row, no not in known, stats)
            except Exception as e:  # noqa: BLE001
                stats["errors"].append(f"{no}: {e}")
    return stats


def _reclassify(db) -> int:
    """분류 규칙을 고친 뒤 기존 행의 tags 를 다시 계산한다. 규칙 변경이 잦은 초기에 쓴다."""
    from app.kfa_notices import classify_tags
    changed, page, size = 0, 0, 500
    while True:
        res = (db.table("data_kfa_notices").select("board_no, title, body_text, tags")
               .order("board_no").range(page * size, page * size + size - 1).execute())
        rows = res.data or []
        for r in rows:
            tags = classify_tags(r["title"], r.get("body_text") or "")
            if tags != (r.get("tags") or []):
                db.table("data_kfa_notices").update({"tags": tags}).eq("board_no", r["board_no"]).execute()
                logger.info(f"  {r['board_no']} {r.get('tags')} → {tags}  {r['title'][:50]}")
                changed += 1
        if len(rows) < size:
            break
        page += 1
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="1-40", help="목록 페이지 범위, 예: 1-10 또는 3,5,7")
    ap.add_argument("--board", nargs="*", type=int, help="특정 boardNo 만 처리")
    ap.add_argument("--refresh", action="store_true", help="이미 저장된 공지도 다시 읽어 갱신")
    ap.add_argument("--reclassify", action="store_true",
                    help="저장된 공지의 tags 만 현재 분류 규칙으로 다시 계산 (네트워크 없음)")
    args = ap.parse_args()

    monitor = KfaNoticeMonitor(notify=False)
    if not monitor.db:
        logger.error("Supabase 연결 실패 (.env 확인)")
        sys.exit(1)

    started = datetime.now()
    if args.reclassify:
        changed = _reclassify(monitor.db)
        logger.info(f"재분류 완료 ({(datetime.now() - started).seconds}s): 태그 변경 {changed}건")
        return
    if args.board:
        stats = asyncio.run(_refresh_boards(monitor, args.board))
    else:
        stats = asyncio.run(monitor.run(pages=_parse_pages(args.pages), refresh=args.refresh))

    logger.info(
        f"백필 완료 ({(datetime.now() - started).seconds}s): 스캔 {stats['scanned']} · 신규 {stats['new']} "
        f"· 갱신 {stats['updated']} · 첨부 {stats['attachments']} (추출 {stats['extracted']}) "
        f"· 오류 {len(stats['errors'])}"
    )
    for e in stats["errors"]:
        logger.warning(f"  오류: {e}")


if __name__ == "__main__":
    main()
