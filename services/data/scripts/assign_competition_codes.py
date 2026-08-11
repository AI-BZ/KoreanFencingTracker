"""
국가대표 관련 대회에 새 대회 코드 부여 스크립트

대회 코드 형식: {Country}{Type}{Level}{Location}{Year}{Month}{Days}
예시: KoNaB1Yg26Ja1422 (첫글자 대문자)

사용법:
    # Dry-run (실제 변경 없이 확인만)
    python scripts/assign_competition_codes.py --dry-run

    # 실제 업데이트 실행
    python scripts/assign_competition_codes.py --execute

    # 특정 대회만 처리
    python scripts/assign_competition_codes.py --comp-idx COMPM00680 --execute
"""

import os
import sys
import argparse
from datetime import datetime, date
from typing import Optional, Dict, Tuple
from dotenv import load_dotenv

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client, Client
from app.competition_codes import (
    generate_code_from_date,
    infer_competition_type,
    infer_level_from_type,
    LOCATION_NAMES,
    COMPETITION_TYPE_NAMES,
    LEVEL_DESCRIPTIONS,
)

load_dotenv()


# =============================================================================
# 장소 추론 규칙
# =============================================================================

LOCATION_KEYWORDS: Dict[str, str] = {
    # 강원권 (첫글자 대문자 - location_codes.py와 일치)
    "양구": "Yg",
    "춘천": "Cc",
    "원주": "Wj",
    "강릉": "Gn",
    "평창": "Pyc",

    # 전라권
    "익산": "Ik",
    "전주": "Jj",
    "광주": "Gw",
    "여수": "Ys",
    "목포": "Mp",

    # 충청권
    "대전": "Dj",
    "세종": "Sj",
    "청주": "Cj",
    "천안": "Ca",

    # 경상권
    "부산": "Bs",
    "대구": "Dg",
    "울산": "Us",
    "창원": "Cw",
    "포항": "Ph",
    "김해": "Gh",
    "경주": "Gc",

    # 수도권
    "서울": "Se",
    "인천": "Ic",
    "수원": "Sw",
    "성남": "Sn",
    "고양": "Gy",
    "용인": "Yi",
    "하남": "Hn",

    # 제주
    "제주": "Jj",
    "서귀포": "Sgp",
}


def infer_location(comp_name: str, venue: Optional[str]) -> str:
    """
    대회명이나 장소 필드에서 장소 코드 추론

    Args:
        comp_name: 대회명
        venue: 장소 필드

    Returns:
        장소 코드 (첫글자 대문자), 없으면 "Xx" (미정)
    """
    # 먼저 venue에서 찾기
    if venue:
        for keyword, code in LOCATION_KEYWORDS.items():
            if keyword in venue:
                return code

    # 대회명에서 찾기
    for keyword, code in LOCATION_KEYWORDS.items():
        if keyword in comp_name:
            return code

    # 기본값: 양구 (국가대표 선발전은 보통 양구에서 개최)
    # 하지만 확실하지 않으면 미정으로 표시
    return "Xx"


# =============================================================================
# 대회 유형 상세 추론 (국가대표 대회 전용)
# =============================================================================

def infer_national_team_comp_type(comp_name: str) -> Tuple[str, str]:
    """
    국가대표 관련 대회의 유형과 레벨 추론

    Args:
        comp_name: 대회명

    Returns:
        (대회 유형 코드, 레벨 코드) 튜플 (첫글자 대문자)
    """
    name = comp_name.lower()

    # 1. 유소년 국가대표 선발전
    if "유소년" in comp_name and "국가대표" in comp_name:
        return "Yo", "B1"  # 유소년, B급 1티어

    # 2. 청소년 국가대표 선발전
    if "청소년" in comp_name and "국가대표" in comp_name:
        return "Ju", "B1"  # 주니어, B급 1티어

    # 3. 대통령배 겸 국가대표 선발
    if "대통령배" in comp_name:
        return "Pr", "B1"  # 회장배/대통령배, B급 1티어

    # 4. 김창환배 겸 국가대표 선발
    if "김창환배" in comp_name:
        return "Pr", "B1"  # 회장배, B급 1티어

    # 5. 종목별 오픈 겸 국가대표 선발
    if "종목별" in comp_name and "오픈" in comp_name:
        return "Na", "B1"  # 국가대표선발전, B급 1티어

    # 6. 순수 국가대표 선발대회
    if "국가대표" in comp_name and ("선발" in comp_name or "선발전" in comp_name):
        return "Na", "B1"  # 국가대표선발전, B급 1티어

    # 기본값 - infer_competition_type은 이미 대문자 반환
    comp_type = infer_competition_type(comp_name)
    level = infer_level_from_type(comp_type)
    return comp_type, level


def parse_dates(start_date_str: str, end_date_str: str) -> Tuple[date, date]:
    """
    날짜 문자열을 date 객체로 파싱

    Args:
        start_date_str: 시작 날짜 문자열 (YYYY-MM-DD)
        end_date_str: 종료 날짜 문자열 (YYYY-MM-DD)

    Returns:
        (시작 date, 종료 date) 튜플
    """
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    return start_date, end_date


# =============================================================================
# 메인 클래스
# =============================================================================

class CompetitionCodeAssigner:
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.supabase: Client = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_KEY")
        )
        self.success_count = 0
        self.skip_count = 0
        self.error_count = 0

    def fetch_national_team_competitions(self, comp_idx: Optional[str] = None) -> list:
        """
        국가대표 관련 대회 조회

        Args:
            comp_idx: 특정 대회 ID (없으면 전체 조회)

        Returns:
            대회 목록
        """
        query = self.supabase.table('competitions').select(
            'id, comp_idx, comp_name, start_date, end_date, venue'
        )

        if comp_idx:
            query = query.eq('comp_idx', comp_idx)
        else:
            query = query.like('comp_name', '%국가대표%')

        result = query.order('start_date', desc=True).execute()
        return result.data

    def generate_code_for_competition(self, comp: Dict) -> Optional[str]:
        """
        대회 정보로부터 대회 코드 생성

        Args:
            comp: 대회 딕셔너리

        Returns:
            생성된 대회 코드, 실패 시 None
        """
        comp_name = comp.get('comp_name', '')
        start_date_str = comp.get('start_date')
        end_date_str = comp.get('end_date')
        venue = comp.get('venue')

        if not start_date_str or not end_date_str:
            return None

        try:
            start_date, end_date = parse_dates(start_date_str, end_date_str)
        except ValueError as e:
            print(f"  [오류] 날짜 파싱 실패: {e}")
            return None

        # 대회 유형 및 레벨 추론
        comp_type, level = infer_national_team_comp_type(comp_name)

        # 장소 추론
        location = infer_location(comp_name, venue)

        # 코드 생성 (첫글자 대문자)
        try:
            code = generate_code_from_date(
                country="Ko",
                comp_type=comp_type,
                level=level,
                location=location,
                start_date=start_date,
                end_date=end_date
            )
            return code
        except ValueError as e:
            print(f"  [오류] 코드 생성 실패: {e}")
            return None

    def check_column_exists(self) -> bool:
        """
        competitions 테이블에 competition_code 컬럼이 있는지 확인
        """
        try:
            result = self.supabase.rpc('check_column_exists', {
                'table_name': 'competitions',
                'column_name': 'competition_code'
            }).execute()
            return result.data
        except Exception:
            # RPC가 없으면 직접 조회 시도
            try:
                result = self.supabase.table('competitions').select('competition_code').limit(1).execute()
                return True
            except Exception:
                return False

    def process_competitions(self, comp_idx: Optional[str] = None):
        """
        대회 코드 부여 메인 처리

        Args:
            comp_idx: 특정 대회만 처리 (없으면 전체)
        """
        print("=" * 70)
        print("국가대표 관련 대회 코드 부여 스크립트")
        print("=" * 70)
        print(f"모드: {'DRY-RUN (실제 변경 없음)' if self.dry_run else '실제 실행'}")
        print()

        # 대회 조회
        competitions = self.fetch_national_team_competitions(comp_idx)
        print(f"조회된 대회 수: {len(competitions)}개")
        print()

        if not competitions:
            print("처리할 대회가 없습니다.")
            return

        # 결과 저장용
        results = []

        for comp in competitions:
            comp_idx_val = comp.get('comp_idx')
            comp_name = comp.get('comp_name')
            start_date = comp.get('start_date')
            end_date = comp.get('end_date')

            print(f"[{comp_idx_val}] {comp_name}")
            print(f"  기간: {start_date} ~ {end_date}")

            # 코드 생성
            code = self.generate_code_for_competition(comp)

            if code:
                # 대회 유형과 레벨 추론 (출력용)
                comp_type, level = infer_national_team_comp_type(comp_name)
                location = infer_location(comp_name, comp.get('venue'))

                type_name = COMPETITION_TYPE_NAMES.get(comp_type, comp_type)
                level_desc = LEVEL_DESCRIPTIONS.get(level, level)
                location_name = LOCATION_NAMES.get(location, location)

                print(f"  유형: {type_name} ({comp_type})")
                print(f"  레벨: {level_desc} ({level})")
                print(f"  장소: {location_name} ({location})")
                print(f"  → 생성 코드: {code}")

                results.append({
                    'id': comp.get('id'),
                    'comp_idx': comp_idx_val,
                    'comp_name': comp_name,
                    'code': code,
                    'comp_type': comp_type,
                    'level': level,
                    'location': location
                })
                self.success_count += 1
            else:
                print("  → 코드 생성 실패")
                self.error_count += 1

            print()

        # 요약
        print("=" * 70)
        print("처리 결과 요약")
        print("=" * 70)
        print(f"성공: {self.success_count}개")
        print(f"실패: {self.error_count}개")
        print()

        # 생성된 코드 목록 출력
        if results:
            print("생성된 코드 목록:")
            print("-" * 70)
            for r in results:
                print(f"{r['comp_idx']}: {r['comp_name'][:40]}...")
                print(f"    → {r['code']}")
            print()

        # 실제 업데이트 (dry_run이 아닐 때만)
        if not self.dry_run and results:
            print("=" * 70)
            print("DB 업데이트 시작...")
            print("=" * 70)

            # 먼저 컬럼 존재 여부 확인
            # 참고: competition_code 컬럼이 없으면 마이그레이션 필요
            print("주의: competition_code 컬럼이 없으면 아래 마이그레이션을 먼저 실행하세요:")
            print()
            print("  ALTER TABLE competitions ADD COLUMN competition_code VARCHAR(20);")
            print("  CREATE INDEX idx_competitions_code ON competitions(competition_code);")
            print()

            update_count = 0
            for r in results:
                try:
                    self.supabase.table('competitions').update({
                        'competition_code': r['code']
                    }).eq('id', r['id']).execute()
                    update_count += 1
                    print(f"  ✓ {r['comp_idx']} 업데이트 완료")
                except Exception as e:
                    print(f"  ✗ {r['comp_idx']} 업데이트 실패: {e}")

            print()
            print(f"DB 업데이트 완료: {update_count}개")


# =============================================================================
# CLI 진입점
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='국가대표 관련 대회에 새 대회 코드 부여'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=True,
        help='실제 변경 없이 결과만 확인 (기본값)'
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='실제 DB 업데이트 실행'
    )
    parser.add_argument(
        '--comp-idx',
        type=str,
        help='특정 대회 ID만 처리'
    )

    args = parser.parse_args()

    # --execute가 있으면 dry_run=False
    dry_run = not args.execute

    assigner = CompetitionCodeAssigner(dry_run=dry_run)
    assigner.process_competitions(comp_idx=args.comp_idx)


if __name__ == "__main__":
    main()
