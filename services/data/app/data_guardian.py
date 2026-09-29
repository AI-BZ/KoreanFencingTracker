"""
Data Guardian — 자동 데이터 무결성 관리 시스템

스케줄러에 의해 자동 실행되며, 데이터 품질을 모니터링하고
문제 발견 시 Discord로 보고한다.

주요 기능:
1. post_scrape_validation — 스크래핑 후 자동 검증 → Discord 알림
2. daily_health_check — 매일 시스템 건강 상태 점검 → 보고
3. weekly_report — 주간 누적 통계 + LLM 분석 요약 → 리포트

사용법:
    guardian = DataGuardian()
    await guardian.post_scrape_validation(comp_name, events)
    await guardian.daily_health_check()
    await guardian.weekly_report()
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from loguru import logger


# 🔴 Guardian 은 전수 검증기가 아니다.
#
# `_load_competitions()` 는 **최근 N개 대회만** 읽는다 (일일 점검 20, 그 외 기본 50).
# DB 에는 대회가 148개 있으므로 기본값으로도 전체의 1/3 만 본다. 그런데 리포트 문구는
# "전체 데이터 검증" 이라 적혀 있어서, 2026-09-28 에 이 숫자를 전수 배치 결과(6,489건)와
# 나란히 놓고 읽다가 한 번 오해가 났다. 그래서 범위를 결과·로그·Discord 문구에 실어 낸다.
#
# 전 연도 전수 검증 경로는 `scripts/run_validation.py` 다 (약 14분 소요 — 운영 서버의
# 이벤트 루프에서 돌리지 말고 배치로 돌린다).
FULL_SCAN_SCRIPT = "scripts/run_validation.py"
DEFAULT_SCAN_LIMIT = 50
DAILY_SCAN_LIMIT = 20


class DataGuardian:
    """데이터 무결성 자동 관리 봇"""

    def __init__(self, db_client=None):
        self.db = db_client
        # 주간 누적 통계
        self._weekly_stats = {
            "validation_runs": 0,
            "total_errors": 0,
            "total_warnings": 0,
            "scrape_events": 0,
            "scrape_competitions": 0,
            "changes_detected": 0,
            "week_start": datetime.now().isoformat(),
        }

    # =====================================================================
    # 1. Post-Scrape Validation (스크래핑 후 자동 검증)
    # =====================================================================

    async def post_scrape_validation(
        self,
        comp_name: str = "",
        events_count: int = 0,
        competition_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """스크래핑 완료 후 데이터 검증 실행 + Discord 알림

        Args:
            comp_name: 대회명 (알림용)
            events_count: 수집된 종목 수
            competition_id: 특정 대회만 검증 (None이면 전체)

        Returns:
            검증 결과 요약
        """
        logger.info(f"🛡️ Data Guardian: 스크래핑 후 검증 시작 — {comp_name or '전체'}")

        try:
            # 검증 대상 데이터 로드
            competitions = self._load_competitions(competition_id)
            if not competitions:
                logger.warning("🛡️ 검증할 데이터 없음")
                return {"status": "no_data"}

            # DataValidator 실행 — 별도 스레드에서 CPU를 양보하며 돈다.
            # 예전에는 여기서 동기로 실행해 이벤트 루프를 통째로 막았고, 대회 데이터가
            # 바뀔 때마다 서버가 십수 분간 응답하지 못했다 (2026-08-15).
            from app.data_validator import run_validation_async
            result = await run_validation_async(competitions)

            errors = result.get("errors", 0)
            warnings = result.get("warnings", 0)
            issues = result.get("issues", [])

            # 주간 통계 누적
            self._weekly_stats["validation_runs"] += 1
            self._weekly_stats["total_errors"] += errors
            self._weekly_stats["total_warnings"] += warnings
            self._weekly_stats["scrape_events"] += events_count
            self._weekly_stats["scrape_competitions"] += 1 if comp_name else 0

            # Discord 알림: 에러가 있거나 수동 트리거일 때
            if errors > 0 or (warnings > 0 and events_count > 0):
                from app.discord_notify import send_validation_report
                await send_validation_report(
                    summary=result,
                    issues=issues[:10],
                    trigger="post_scrape",
                )
                logger.info(f"🛡️ 검증 결과 Discord 발송 — ERROR: {errors}, WARNING: {warnings}")
            elif events_count > 0:
                # 에러 없으면 스크래핑 완료 알림만
                from app.discord_notify import send_scrape_complete
                await send_scrape_complete(
                    comp_name=comp_name,
                    events_count=events_count,
                    validation_result=result,
                )

            logger.info(
                f"🛡️ 검증 완료 — {comp_name} [{self._scope_label(competitions)}]: "
                f"이슈 {result.get('total_issues', 0)}건 "
                f"(ERROR: {errors}, WARNING: {warnings})"
            )

            return {
                "status": "completed",
                "comp_name": comp_name,
                "scope": self._scope_label(competitions),
                "total_issues": result.get("total_issues", 0),
                "errors": errors,
                "warnings": warnings,
                "by_rule": result.get("by_rule", {}),
            }

        except Exception as e:
            logger.error(f"🛡️ 검증 오류: {e}")
            # 오류도 Discord로 알림
            try:
                from app.discord_notify import send_alert
                await send_alert(
                    severity="error",
                    title="Data Guardian 검증 오류",
                    message=f"스크래핑 후 검증 중 오류 발생: {str(e)[:500]}",
                    fields=[{"name": "대회", "value": comp_name or "전체"}],
                )
            except Exception:
                pass
            return {"status": "error", "error": str(e)}

    # =====================================================================
    # 2. Daily Health Check (매일 건강 상태 점검)
    # =====================================================================

    async def daily_health_check(self) -> Dict[str, Any]:
        """시스템 건강 상태 전체 점검 + Discord 보고"""
        logger.info("🛡️ Data Guardian: 일일 건강 상태 점검 시작")

        results = {
            "timestamp": datetime.now().isoformat(),
            "checks": {},
        }

        try:
            # 1. 데이터 검증 — ⚠️ 최근 20개 대회만 (전수 아님, 성능 때문)
            competitions = self._load_competitions(limit=self.DAILY_SCAN_LIMIT)
            validation_issues = []
            if competitions:
                from app.data_validator import run_validation_async
                validation = await run_validation_async(competitions)
                results["checks"]["validation"] = {
                    "scope": self._scope_label(competitions),
                    "total_issues": validation.get("total_issues", 0),
                    "errors": validation.get("errors", 0),
                    "warnings": validation.get("warnings", 0),
                    "by_rule": validation.get("by_rule", {}),
                }
                validation_issues = validation.get("issues", [])

            # 2. 데이터 신선도 점검
            freshness = await self._check_data_freshness()
            results["checks"]["freshness"] = freshness

            # 3. 중복 데이터 점검
            duplicates = await self._check_duplicates()
            results["checks"]["duplicates"] = duplicates

            # 4. 동명이인 미등록 점검 (검증 결과에서 R13 추출 — 재검증 안 함)
            r13_names = list({
                issue.player_name for issue in validation_issues
                if hasattr(issue, "rule_id") and issue.rule_id == "R13"
            })
            results["checks"]["homonyms"] = {
                "unregistered_count": len(r13_names),
                "names": r13_names[:10],
            }

            # 건강도 판정
            errors = results["checks"].get("validation", {}).get("errors", 0)
            stale_tables = freshness.get("stale_count", 0)

            if errors > 5 or stale_tables > 2:
                health_status = "unhealthy"
            elif errors > 0 or stale_tables > 0:
                health_status = "degraded"
            else:
                health_status = "healthy"

            results["health_status"] = health_status

            # Discord 보고
            from app.discord_notify import send_alert
            severity = {"healthy": "success", "degraded": "warning", "unhealthy": "error"}[health_status]

            check_summary = []
            if competitions:
                v = results["checks"]["validation"]
                check_summary.append(
                    f"검증({v['scope']}): ERROR {v['errors']}건, WARNING {v['warnings']}건"
                )
            check_summary.append(f"신선도: {freshness.get('stale_count', 0)}개 테이블 오래됨")
            check_summary.append(f"동명이인 미등록: {len(r13_names)}건")

            await send_alert(
                severity=severity,
                title=f"일일 건강 점검 — {health_status.upper()}",
                message="\n".join(check_summary),
                fields=[
                    {"name": "상태", "value": health_status.upper(), "inline": True},
                    {"name": "검증 ERROR", "value": str(errors), "inline": True},
                    {"name": "스테일 테이블", "value": str(stale_tables), "inline": True},
                ],
            )

            logger.info(f"🛡️ 건강 점검 완료 — {health_status}")
            return results

        except Exception as e:
            logger.error(f"🛡️ 건강 점검 오류: {e}")
            try:
                from app.discord_notify import send_alert
                await send_alert(
                    severity="error",
                    title="Data Guardian 건강 점검 오류",
                    message=str(e)[:500],
                )
            except Exception:
                pass
            return {"status": "error", "error": str(e)}

    # =====================================================================
    # 3. Weekly Report (주간 리포트)
    # =====================================================================

    async def weekly_report(self) -> Dict[str, Any]:
        """주간 누적 통계 + LLM 분석 요약 → Discord 리포트"""
        logger.info("🛡️ Data Guardian: 주간 리포트 생성 시작")

        validation_summary = {
            "total_runs": self._weekly_stats["validation_runs"],
            "total_errors": self._weekly_stats["total_errors"],
            "total_warnings": self._weekly_stats["total_warnings"],
        }
        scrape_stats = {
            "competitions_scraped": self._weekly_stats["scrape_competitions"],
            "events_scraped": self._weekly_stats["scrape_events"],
            "changes_detected": self._weekly_stats["changes_detected"],
        }

        # LLM 분석 (qwen3:32b, think:false) — 선택적
        analysis_text = await self._generate_llm_analysis(validation_summary, scrape_stats)

        # Discord 발송
        try:
            from app.discord_notify import send_weekly_summary
            await send_weekly_summary(
                validation_summary=validation_summary,
                scrape_stats=scrape_stats,
                analysis_text=analysis_text,
            )
        except Exception as e:
            logger.error(f"🛡️ 주간 리포트 Discord 전송 실패: {e}")

        # 주간 통계 리셋
        result = dict(self._weekly_stats)
        self._weekly_stats = {
            "validation_runs": 0,
            "total_errors": 0,
            "total_warnings": 0,
            "scrape_events": 0,
            "scrape_competitions": 0,
            "changes_detected": 0,
            "week_start": datetime.now().isoformat(),
        }

        logger.info("🛡️ 주간 리포트 완료, 통계 리셋")
        return result

    # =====================================================================
    # 4. 수동 전체 검증 (CLI용)
    # =====================================================================

    async def run_full_validation(self, limit: int = DEFAULT_SCAN_LIMIT) -> Dict[str, Any]:
        """최근 `limit` 개 대회 검증 + Discord 보고.

        ⚠️ 이름과 달리 **전 연도 전수가 아니다.** 기본 50개 대회(전체 148개 중)만 본다.
        전수는 `scripts/run_validation.py` 로 돌린다 — 이벤트 루프를 14분간 점유하므로
        운영 서버 안에서 돌리지 않는다.
        """
        competitions = self._load_competitions(limit=limit)
        if not competitions:
            return {"status": "no_data", "message": "검증할 데이터 없음"}

        from app.data_validator import run_validation_async
        result = await run_validation_async(competitions)

        from app.discord_notify import send_validation_report
        await send_validation_report(
            summary=result,
            issues=result.get("issues", [])[:10],
            trigger="manual",
        )

        return {
            "status": "completed",
            "scope": self._scope_label(competitions),
            "full_scan_command": f"PYTHONPATH='.:../../packages' python {self.FULL_SCAN_SCRIPT}",
            "total_issues": result.get("total_issues", 0),
            "errors": result.get("errors", 0),
            "warnings": result.get("warnings", 0),
            "by_rule": result.get("by_rule", {}),
        }

    # =====================================================================
    # 내부 헬퍼
    # =====================================================================

    # 모듈 상수의 별칭 (외부에서 guardian.DAILY_SCAN_LIMIT 로도 읽을 수 있게)
    FULL_SCAN_SCRIPT = FULL_SCAN_SCRIPT
    DEFAULT_SCAN_LIMIT = DEFAULT_SCAN_LIMIT
    DAILY_SCAN_LIMIT = DAILY_SCAN_LIMIT

    def _load_competitions(
        self, competition_id: Optional[int] = None, limit: int = DEFAULT_SCAN_LIMIT
    ) -> List[Dict]:
        """Supabase에서 대회 + 이벤트 데이터 로드 (검증용 형식).

        ⚠️ `limit` 개 **최근 대회만** 읽는다. 전수가 아니다 (위 주석 참조).
        """
        try:
            db = self._get_db()
            if not db:
                return []

            # 대회 조회
            query = db.table("competitions").select("*")
            if competition_id:
                query = query.eq("id", competition_id)
            comps = query.order("start_date", desc=True).limit(limit).execute()

            if not comps.data:
                return []

            result = []
            for comp in comps.data:
                # 해당 대회 이벤트 조회
                events = db.table("events").select(
                    "sub_event_cd, event_name, raw_data"
                ).eq("competition_id", comp["id"]).execute()

                comp_events = []
                for ev in (events.data or []):
                    raw = ev.get("raw_data") or {}
                    comp_events.append({
                        "sub_event_cd": ev.get("sub_event_cd", ""),
                        "event_name": ev.get("event_name", ""),
                        "pool_rounds": raw.get("pool_rounds", []),
                        "pool_total_ranking": raw.get("pool_total_ranking", []),
                        "de_bracket": raw.get("de_bracket", {}),
                        "final_rankings": raw.get("final_rankings", []),
                        # R27 이 로스터를 모을 때 쓴다. 없으면 로스터가 얇아져
                        # 규칙이 스스로 판정을 포기한다(오탐 방지 가드).
                        "participants": raw.get("participants", []),
                    })

                result.append({
                    "competition": {
                        "id": comp["id"],
                        # 🔴 competitions 테이블의 컬럼명은 `comp_name` 이다. `name` 컬럼은
                        # 존재하지 않는다 — `comp.get("name", "")` 은 **항상 빈 문자열**을
                        # 돌려주므로 Guardian 이 만든 모든 이슈의 competition_name 이 빈칸이었다
                        # (Discord 알림에서 어느 대회인지 알 수 없었다). 2026-09-28 수정.
                        "name": comp.get("comp_name") or comp.get("name", ""),
                        "event_cd": comp.get("comp_idx", ""),
                        "start_date": comp.get("start_date", ""),
                    },
                    "events": comp_events,
                })

            return result

        except Exception as e:
            logger.error(f"🛡️ 데이터 로드 오류: {e}")
            return []

    @staticmethod
    def _scope_label(competitions: List[Dict]) -> str:
        """검사 범위를 사람이 읽을 문구로. 리포트에 반드시 실어 보낸다 —
        범위를 안 적으면 전수 배치 숫자와 나란히 놓였을 때 오해를 부른다."""
        n_comp = len(competitions)
        n_ev = sum(len(c.get("events") or []) for c in competitions)
        return f"최근 대회 {n_comp}개 / 종목 {n_ev}개"

    def _get_db(self):
        """Supabase DB 클라이언트"""
        if self.db:
            return self.db
        try:
            from database.supabase_client import get_supabase_client
            return get_supabase_client()
        except ImportError:
            try:
                from supabase import create_client
                url = os.getenv("SUPABASE_URL", "")
                key = os.getenv("SUPABASE_KEY", "")
                if url and key:
                    return create_client(url, key)
            except Exception:
                pass
        return None

    async def _check_data_freshness(self) -> Dict[str, Any]:
        """데이터 신선도 점검: 각 테이블의 마지막 업데이트 시각"""
        db = self._get_db()
        if not db:
            return {"status": "no_db"}

        tables = ["competitions", "events", "players"]
        stale_count = 0
        details = {}

        for table in tables:
            try:
                result = db.table(table).select("updated_at").order(
                    "updated_at", desc=True
                ).limit(1).execute()

                if result.data:
                    last_update = result.data[0].get("updated_at", "")
                    if last_update:
                        # updated_at이 48시간 이상 전이면 stale
                        from datetime import timezone
                        update_dt = datetime.fromisoformat(
                            last_update.replace("Z", "+00:00")
                        )
                        hours_ago = (
                            datetime.now(timezone.utc) - update_dt
                        ).total_seconds() / 3600
                        is_stale = hours_ago > 48
                        if is_stale:
                            stale_count += 1
                        details[table] = {
                            "last_update": last_update,
                            "hours_ago": round(hours_ago, 1),
                            "is_stale": is_stale,
                        }
                    else:
                        details[table] = {"last_update": None, "is_stale": True}
                        stale_count += 1
                else:
                    details[table] = {"last_update": None, "is_stale": True}
                    stale_count += 1
            except Exception as e:
                details[table] = {"error": str(e)}

        return {"stale_count": stale_count, "details": details}

    async def _check_duplicates(self) -> Dict[str, Any]:
        """중복 데이터 점검"""
        db = self._get_db()
        if not db:
            return {"status": "no_db"}

        try:
            # 이벤트 중복: 같은 competition_id + sub_event_cd
            result = db.rpc("check_duplicate_events", {}).execute()
            dup_count = len(result.data) if result.data else 0
            return {"duplicate_events": dup_count}
        except Exception:
            # RPC가 없으면 간단한 체크
            return {"duplicate_events": "unchecked"}

    def _check_unregistered_homonyms(self, competitions: List[Dict]) -> List[str]:
        """동명이인 미등록 감지 (R13 기반)"""
        from app.data_validator import DataValidator

        # 동명이인 판정을 '실제 분리 결과' 기준으로 하려면 리졸버가 필요하다.
        # 서버 프로세스 안에서 돌 때만 있으므로, 없으면 예전 기준(수동 등록)으로 내려간다.
        resolver = None
        try:
            from app import server as _srv
            resolver = getattr(_srv, "_identity_resolver", None)
        except Exception:
            resolver = None
        validator = DataValidator(competitions, identity_resolver=resolver)
        issues = validator.validate_all()

        # R13 이슈만 필터
        r13_names = set()
        for issue in issues:
            if issue.rule_id == "R13":
                r13_names.add(issue.player_name)

        return list(r13_names)

    async def _generate_llm_analysis(
        self,
        validation_summary: Dict[str, Any],
        scrape_stats: Dict[str, Any],
    ) -> str:
        """qwen3:32b로 주간 데이터 분석 요약 생성"""
        try:
            import subprocess

            prompt = (
                f"FencingMind 데이터 플랫폼 주간 요약을 한국어 3줄로 작성해줘.\n"
                f"검증: {validation_summary['total_runs']}회 실행, "
                f"ERROR {validation_summary['total_errors']}건, "
                f"WARNING {validation_summary['total_warnings']}건\n"
                f"스크래핑: {scrape_stats['competitions_scraped']}개 대회, "
                f"{scrape_stats['events_scraped']}개 종목 수집, "
                f"{scrape_stats['changes_detected']}건 변경 감지\n"
                f"핵심 상태와 개선 필요 사항을 간결하게 요약해줘."
            )

            # qwen3:32b think:false (CLAUDE.md 규칙 준수)
            cmd = [
                "curl", "-s", "http://localhost:11434/api/chat",
                "-d", json.dumps({
                    "model": "qwen3:32b",
                    "stream": False,
                    "think": False,
                    "messages": [{"role": "user", "content": prompt}],
                    "options": {"temperature": 0.3, "num_predict": 256},
                }),
            ]

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )

            if result.returncode == 0:
                response = json.loads(result.stdout)
                content = response.get("message", {}).get("content", "")
                if content:
                    return content.strip()[:500]

        except Exception as e:
            logger.debug(f"🛡️ LLM 분석 생략 (ollama 미실행 또는 오류): {e}")

        return ""


# 전역 Guardian 인스턴스
_guardian_instance: Optional[DataGuardian] = None


def get_guardian(db_client=None) -> DataGuardian:
    """Guardian 싱글톤 인스턴스"""
    global _guardian_instance
    if _guardian_instance is None:
        _guardian_instance = DataGuardian(db_client=db_client)
    return _guardian_instance
