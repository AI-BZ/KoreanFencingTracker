"""
학년 추정 시스템 (Grade Estimator)

KFF API와 DB에 학년/생년월일 정보가 없으므로,
과거 대회 이력(이벤트명의 학교 레벨 + 대회 날짜)을 기반으로 학년을 추정한다.

학년도 정의: Y학년도 = Y년 3월 ~ (Y+1)년 2월

중/고등학교 (3년제):
    학년 = 현재학년도 - 해당 레벨 첫 등장 학년도 + 1  (max 3)

초등학교 (2학년 밴드: 1-2, 3-4, 5-6):
    같은 밴드 2학년도 연속 → 첫해=하위학년, 둘째해=상위학년
    밴드 전환(3-4→5-6) → 전환학년도 = 상위밴드 하위학년
    1학년도만 등장 → 밴드만 표시 (예: "초5-6")
"""
import re
from datetime import date, datetime
from typing import Optional, Dict, List, Any, Tuple

from loguru import logger


class GradeEstimator:
    """선수의 학년을 과거 대회 이력으로 추정"""

    def __init__(self):
        # {(name, team): {level: first_school_year}}
        # level: 'middle', 'high', 'elem_1_2', 'elem_3_4', 'elem_5_6', 'elementary'
        self._cache: Dict[Tuple[str, str], Dict[str, int]] = {}
        # 이적 대응: {name: {level: earliest_school_year}} (팀 무관, 가장 이른 학년도)
        self._name_level_cache: Dict[str, Dict[str, int]] = {}

    @staticmethod
    def get_school_year(d) -> int:
        """날짜에서 학년도 계산. 3월~2월이 한 학년도."""
        if isinstance(d, str):
            try:
                d = datetime.strptime(d[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return 0
        if isinstance(d, datetime):
            d = d.date()
        if not isinstance(d, date):
            return 0
        return d.year if d.month >= 3 else d.year - 1

    @staticmethod
    def parse_school_level(event_name: str) -> Optional[str]:
        """이벤트 이름에서 학교 레벨 파싱

        Returns:
            'middle' - 중학교 (남중/여중/중등부)
            'high' - 고등학교 (남고/여고/고등부)
            'elem_1_2' - 초등 1-2학년
            'elem_3_4' - 초등 3-4학년
            'elem_5_6' - 초등 5-6학년
            'elementary' - 초등 (밴드 불명)
            None - 해당 없음 (일반부/대학부 등)
        """
        if not event_name:
            return None

        # 초등부 밴드 파싱 (구체적 패턴 먼저)
        # "초등부(1-2학년)", "초등부(3-4학년)", "초등부(5-6학년)"
        elem_band = re.search(r'초등.*?(\d)\s*[-~]\s*(\d)\s*학년', event_name)
        if elem_band:
            low = int(elem_band.group(1))
            high = int(elem_band.group(2))
            return f'elem_{low}_{high}'

        # "초등부(1-3학년)" 같은 3학년 밴드도 처리
        elem_band3 = re.search(r'초등.*?(\d)\s*[-~]\s*(\d)\s*학년', event_name)
        if elem_band3:
            low = int(elem_band3.group(1))
            high = int(elem_band3.group(2))
            return f'elem_{low}_{high}'

        # 중학교 패턴
        if re.search(r'남중|여중|중등부|중학', event_name):
            return 'middle'

        # 고등학교 패턴
        if re.search(r'남고|여고|고등부|고등학교', event_name):
            return 'high'

        # 초등 일반 (밴드 불명)
        if re.search(r'남초|여초|초등부|초등학교', event_name):
            return 'elementary'

        return None

    def build_cache(self, competitions_cache: List[Dict], events_data: List[Dict]):
        """서버 데이터 로드 시 호출하여 캐시 구축

        Args:
            competitions_cache: [{competition: {event_cd, start_date, ...}, events: [...]}, ...]
            events_data: competitions_cache에서 모든 이벤트를 플랫하게 전달하거나,
                        competitions_cache 자체를 순회하여 추출
        """
        import time
        start_time = time.time()
        self._cache.clear()

        # competitions_cache에서 comp_id → start_date 매핑
        comp_date_map = {}
        for comp in competitions_cache:
            comp_info = comp.get("competition", {})
            event_cd = comp_info.get("event_cd", "")
            start_date = comp_info.get("start_date", "")
            if event_cd and start_date:
                comp_date_map[event_cd] = start_date

        # 모든 이벤트 순회
        events_processed = 0
        for comp in competitions_cache:
            comp_info = comp.get("competition", {})
            start_date = comp_info.get("start_date", "")
            if not start_date:
                continue

            school_year = self.get_school_year(start_date)
            if school_year == 0:
                continue

            for event in comp.get("events", []):
                event_name = event.get("name", "")
                level = self.parse_school_level(event_name)
                if not level:
                    continue

                events_processed += 1

                # 이벤트에 참여한 선수 수집
                players = set()
                raw = event  # 이미 raw_data가 펼쳐진 구조

                # final_rankings
                for r in raw.get("final_rankings", []):
                    name = (r.get("name") or "").strip()
                    team = (r.get("team") or "").strip()
                    if name and team:
                        players.add((name, team))

                # pool_rounds
                for pool in raw.get("pool_rounds", []):
                    for r in pool.get("results", []):
                        name = (r.get("name") or "").strip()
                        team = (r.get("team") or "").strip()
                        if name and team:
                            players.add((name, team))

                # participants (2026 이후 사전 등록)
                for p in raw.get("participants", []):
                    name = (p.get("name") or "").strip()
                    team = (p.get("team") or "").strip()
                    if name and team:
                        players.add((name, team))

                # pool_total_ranking
                for r in raw.get("pool_total_ranking", []):
                    name = (r.get("name") or "").strip()
                    team = (r.get("team") or "").strip()
                    if name and team:
                        players.add((name, team))

                # 첫 등장 학년도 기록 (min)
                for key in players:
                    entry = self._cache.setdefault(key, {})
                    entry[level] = min(entry.get(level, 9999), school_year)

        # 이적 대응: 이름 기반 크로스-팀 레벨 캐시 구축 (팀 무관, 가장 이른 학년도)
        self._name_level_cache.clear()
        for (name, team), history in self._cache.items():
            if name not in self._name_level_cache:
                self._name_level_cache[name] = {}
            for level, sy in history.items():
                self._name_level_cache[name][level] = min(
                    self._name_level_cache[name].get(level, 9999), sy
                )

        elapsed = time.time() - start_time
        logger.info(f"📊 학년 추정기: {len(self._cache)}명 캐시, "
                     f"{events_processed}개 이벤트 처리 ({elapsed:.2f}초)")

    def _is_homonym_conflict(self, name: str, team: str,
                             level: str, candidate_sy: int) -> bool:
        """크로스-팀 캐시 값이 동명이인에 의한 것인지 검증

        candidate_sy 시점에 현재 선수(name, team)가 하위 레벨에서
        활동한 기록이 있으면 동명이인으로 판단.

        예: 박소윤(최병철) middle candidate_sy=2024 → 2024~2025에 초등부 출전 기록 있음 → 동명이인
        """
        history = self._cache.get((name, team), {})
        if not history:
            return False

        # 레벨 계층: elementary < middle < high
        lower_levels = []
        if level == 'middle':
            lower_levels = [k for k in history if k.startswith('elem')]
        elif level == 'high':
            lower_levels = [k for k in history if k == 'middle' or k.startswith('elem')]

        for lower_level in lower_levels:
            lower_sy = history.get(lower_level)
            if lower_sy is not None and lower_sy != 9999:
                # 하위 레벨 활동이 candidate_sy와 같은 해 이후이면 모순
                # (candidate_sy에 중학생이면 그 해에 초등부 출전 불가)
                if lower_sy >= candidate_sy:
                    logger.debug(
                        f"동명이인 감지: {name}({team}) {level} "
                        f"candidate_sy={candidate_sy}, "
                        f"but {lower_level} in {lower_sy} → 무시"
                    )
                    return True
        return False

    def estimate_grade(self, name: str, team: str, event_name: str,
                       ref_date) -> Dict[str, Any]:
        """선수의 학년 추정

        Args:
            name: 선수 이름
            team: 소속
            event_name: 현재 이벤트 이름 (학교 레벨 파싱용)
            ref_date: 기준 날짜 (대회 start_date)

        Returns:
            {
                "grade": "2학년" | "초5-6" | "미확인",
                "grade_num": 2 | None,
                "confidence": "confirmed" | "estimated" | "unknown"
            }
        """
        current_sy = self.get_school_year(ref_date)
        if current_sy == 0:
            return {"grade": "미확인", "grade_num": None, "confidence": "unknown"}

        current_level = self.parse_school_level(event_name)
        if not current_level:
            return {"grade": "미확인", "grade_num": None, "confidence": "unknown"}

        name = (name or "").strip()
        team = (team or "").strip()
        history = self._cache.get((name, team), {})

        # --- 중/고등학교 (3년제) ---
        if current_level in ('middle', 'high'):
            first_sy = history.get(current_level)

            # 이적 대응: 같은 이름의 다른 팀에서 더 이른 기록 확인
            # 단, 동명이인 모순 감지 시 크로스-팀 캐시 무시
            name_first_sy = self._name_level_cache.get(name, {}).get(current_level)
            if name_first_sy is not None and name_first_sy != 9999:
                if first_sy is None or name_first_sy < first_sy:
                    if not self._is_homonym_conflict(name, team, current_level, name_first_sy):
                        first_sy = name_first_sy

            if first_sy is not None and first_sy != 9999:
                grade = min(current_sy - first_sy + 1, 3)
                if grade < 1:
                    grade = 1
                confidence = "confirmed" if grade >= 2 else "estimated"
                return {
                    "grade": f"{grade}학년",
                    "grade_num": grade,
                    "confidence": confidence
                }

            # 해당 레벨 이력 없음 → 이전 레벨 확인
            if current_level == 'middle':
                has_prev = any(k.startswith('elem') for k in history)
            else:  # high
                has_prev = 'middle' in history

            if has_prev:
                # 이전 레벨 이력 있음 → 전환 확정 → 1학년
                return {
                    "grade": "1학년",
                    "grade_num": 1,
                    "confidence": "confirmed"
                }

            if not history:
                # 아예 이력 없음 → 추정 불가
                return {"grade": "미확인", "grade_num": None, "confidence": "unknown"}

            # 이력은 있지만 관련 없는 레벨 → 미확인
            return {"grade": "미확인", "grade_num": None, "confidence": "unknown"}

        # --- 초등학교 밴드 ---
        if current_level.startswith('elem_'):
            return self._estimate_elementary_grade(
                history, current_level, current_sy
            )

        # elementary (밴드 불명)
        if current_level == 'elementary':
            return {"grade": "미확인", "grade_num": None, "confidence": "unknown"}

        return {"grade": "미확인", "grade_num": None, "confidence": "unknown"}

    def _estimate_elementary_grade(self, history: Dict[str, int],
                                    current_level: str,
                                    current_sy: int) -> Dict[str, Any]:
        """초등학교 학년 추정 (밴드 기반)

        같은 밴드 2학년도 연속 → 첫해=하위학년, 둘째해=상위학년
        밴드 전환(3-4→5-6) → 전환학년도 = 상위밴드 하위학년
        1학년도만 등장 → 밴드만 표시
        """
        # 현재 밴드 파싱
        m = re.match(r'elem_(\d+)_(\d+)', current_level)
        if not m:
            return {"grade": "미확인", "grade_num": None, "confidence": "unknown"}

        band_low = int(m.group(1))
        band_high = int(m.group(2))

        first_sy = history.get(current_level)

        if first_sy is not None and first_sy != 9999:
            years_in_band = current_sy - first_sy + 1

            if years_in_band >= 2:
                # 2학년도 이상 → 상위학년
                grade = band_high
                return {
                    "grade": f"초{grade}",
                    "grade_num": grade,
                    "confidence": "confirmed"
                }
            elif years_in_band == 1:
                # 1학년도만 → 이전 밴드 확인
                prev_band = self._get_prev_band(current_level)
                if prev_band and prev_band in history:
                    # 이전 밴드 이력 있음 → 하위학년 확정
                    grade = band_low
                    return {
                        "grade": f"초{grade}",
                        "grade_num": grade,
                        "confidence": "confirmed"
                    }
                else:
                    # 밴드만 표시
                    return {
                        "grade": f"초{band_low}-{band_high}",
                        "grade_num": None,
                        "confidence": "estimated"
                    }
        else:
            # 이 밴드 이력 없음 → 이전 밴드 확인
            prev_band = self._get_prev_band(current_level)
            if prev_band and prev_band in history:
                # 이전 밴드에서 전환 → 하위학년
                grade = band_low
                return {
                    "grade": f"초{grade}",
                    "grade_num": grade,
                    "confidence": "confirmed"
                }

        # 추정 불가
        return {
            "grade": f"초{band_low}-{band_high}",
            "grade_num": None,
            "confidence": "estimated"
        }

    @staticmethod
    def _get_prev_band(current_level: str) -> Optional[str]:
        """현재 밴드의 이전 밴드 반환"""
        band_order = ['elem_1_2', 'elem_3_4', 'elem_5_6']
        if current_level in band_order:
            idx = band_order.index(current_level)
            if idx > 0:
                return band_order[idx - 1]
        return None

    def estimate_grade_from_history(self, name: str, team: str,
                                     ref_date) -> Dict[str, Any]:
        """이벤트명 없이 선수 히스토리만으로 학년 추정

        청소년 대표 선발 등 일반부 대회에서 선수의 학년을 추정할 때 사용.
        _cache와 _name_level_cache에 있는 중/고 이력을 기반으로 학년 계산.

        Args:
            name: 선수 이름
            team: 소속
            ref_date: 기준 날짜 (대회 start_date)

        Returns:
            {
                "school_level": "middle" | "high" | None,
                "grade": "중2" | "고1" | "미확인",
                "grade_num": 2 | None,
                "confidence": "confirmed" | "estimated" | "unknown"
            }
        """
        current_sy = self.get_school_year(ref_date)
        if current_sy == 0:
            return {"school_level": None, "grade": "미확인",
                    "grade_num": None, "confidence": "unknown"}

        name = (name or "").strip()
        team = (team or "").strip()

        # 1. (name, team) 캐시에서 중/고 이력 확인
        history = self._cache.get((name, team), {})

        # 2. 이적 대응: _name_level_cache에서도 확인
        #    단, 동명이인 모순 감지 시 크로스-팀 캐시 무시
        name_history = self._name_level_cache.get(name, {})

        # 중/고 레벨별 가장 이른 학년도 찾기 (동명이인 검증 포함)
        def _get_first_sy(level: str) -> Optional[int]:
            sy1 = history.get(level)
            sy2 = name_history.get(level)
            candidates = []
            if sy1 is not None and sy1 != 9999:
                candidates.append(sy1)
            if sy2 is not None and sy2 != 9999:
                # 크로스-팀 값이 자체 값보다 이르면 동명이인 검증
                if sy1 is None or sy2 < sy1:
                    if not self._is_homonym_conflict(name, team, level, sy2):
                        candidates.append(sy2)
                else:
                    candidates.append(sy2)
            return min(candidates) if candidates else None

        middle_first = _get_first_sy('middle')
        high_first = _get_first_sy('high')

        # 고등학교 이력이 있으면 → 고등학생 or 졸업
        if high_first is not None:
            raw_grade = current_sy - high_first + 1
            if raw_grade > 3:
                # 고등학교 3년 초과 → 졸업 (대학/실업)
                return {
                    "school_level": "graduated",
                    "grade": "졸업",
                    "grade_num": None,
                    "confidence": "confirmed",
                }
            grade = max(raw_grade, 1)
            return {
                "school_level": "high",
                "grade": f"고{grade}",
                "grade_num": grade,
                "confidence": "confirmed" if grade >= 2 else "estimated",
            }

        # 중학교 이력만 있으면
        if middle_first is not None:
            grade = min(current_sy - middle_first + 1, 3)
            if grade < 1:
                grade = 1

            # 중학교 3년을 초과하면 → 고등학교로 전환 or 졸업
            years_since_middle = current_sy - middle_first + 1
            if years_since_middle > 3:
                high_years = years_since_middle - 3
                if high_years > 3:
                    # 고등학교도 졸업 (대학/실업)
                    return {
                        "school_level": "graduated",
                        "grade": "졸업",
                        "grade_num": None,
                        "confidence": "confirmed",
                    }
                return {
                    "school_level": "high",
                    "grade": f"고{high_years}",
                    "grade_num": high_years,
                    "confidence": "estimated",
                }

            return {
                "school_level": "middle",
                "grade": f"중{grade}",
                "grade_num": grade,
                "confidence": "confirmed" if grade >= 2 else "estimated",
            }

        # 이력 없음
        return {"school_level": None, "grade": "미확인",
                "grade_num": None, "confidence": "unknown"}

    def enrich_participants(self, participants: List[Dict],
                            event_name: str,
                            ref_date) -> List[Dict]:
        """참가자 리스트에 grade/grade_num 필드 일괄 추가

        Args:
            participants: [{"name": "...", "team": "...", ...}, ...]
            event_name: 이벤트 이름
            ref_date: 대회 start_date

        Returns:
            동일 리스트에 grade, grade_num, grade_confidence 필드 추가
        """
        if not participants:
            return participants

        for p in participants:
            name = (p.get("name") or "").strip()
            team = (p.get("team") or "").strip()
            if name and team:
                result = self.estimate_grade(name, team, event_name, ref_date)
                p["grade"] = result.get("grade", "미확인")
                p["grade_num"] = result.get("grade_num")
                p["grade_confidence"] = result.get("confidence", "unknown")
            else:
                p["grade"] = "미확인"
                p["grade_num"] = None
                p["grade_confidence"] = "unknown"

        return participants
