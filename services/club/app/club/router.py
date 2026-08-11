"""
Club Management Router

펜싱 클럽/학교 회원 관리 SaaS 메인 라우터
각 도메인별 하위 모듈을 include합니다.

도메인 구조:
- dashboard/  : 대시보드 API + HTML 페이지 라우팅
- members/    : 회원 CRUD, 내 정보, 공지사항
- attendance/ : 출석 체크인/체크아웃
- accounting/ : 회계관리 (비용 조회/납부 확인)
- lessons/    : 레슨 CRUD + 참가자 관리
- players/    : 선수 데이터 연동 (핵심!)
- parent/     : 학부모 전용 API
"""

from fastapi import APIRouter

from .dashboard import dashboard_router
from .members import members_router
from .attendance import attendance_router
from .accounting import accounting_router
from .lessons import lessons_router
from .players import players_router
from .parent import parent_router

router = APIRouter(prefix="/club", tags=["Club Management"])

# 도메인별 하위 라우터 등록
router.include_router(dashboard_router)
router.include_router(members_router)
router.include_router(attendance_router)
router.include_router(accounting_router)
router.include_router(lessons_router)

# 기존 분리된 라우터 (변경 없음)
router.include_router(players_router)
router.include_router(parent_router)
