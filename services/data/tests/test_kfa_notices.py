"""
협회 공지 모니터 · 명단 파서 테스트

네트워크·DB 없이 고정 문자열로만 검증한다. 실제 첨부 원본은 세션 스크래치패드에
있을 때만 추가로 돌린다 (없으면 skip).
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.kfa_notices import (  # noqa: E402
    classify_tags,
    detect_kind,
    extract_text,
    parse_kfa_date,
    parse_notice_detail,
    parse_notice_list,
    safe_filename,
)
from app.kfa_roster_parser import (  # noqa: E402
    detect_roster_type,
    media_roster_entries,
    parse_gender_weapon,
    parse_ranking_points,
    parse_replacement_notice,
    parse_roster_document,
    ranking_lookup,
)
from scheduler.kfa_notice_monitor import should_alert  # noqa: E402


# =============================================================================
# 태그 분류
# =============================================================================

@pytest.mark.parametrize("title, body, expected", [
    ("2025 대한펜싱협회 국가대표선수 선발 명단 공지 및 이의 신청 안내", "", ["national_team"]),
    ("2024 대한펜싱협회 국가대표선수 명단 공지", "", ["national_team"]),
    ("(펜싱)국가대표선수 교체 선발 명단 공지 및 이의신청 안내", "", ["replacement"]),
    # 제목은 '선발 명단'인데 본문이 결원 교체 — 본문으로 replacement 판정 (2026-08-14 실사례)
    ("2026 대한펜싱협회 국가대표선수 선발 명단 공지 및 이의 신청 안내",
     "국가대표 선수가 포기함에 따라 결원이 발생하여 차순위 선수를 선발하였기에", ["replacement"]),
    ("2026년 국가대표 선발을 위한 4개 대회 합산 점수 및 랭킹 현황 공지", "", ["ranking_points"]),
    ("2025 국가대표 후보선수(25세이하대표_미래국가대표) 명단", "", ["candidate_u25"]),
    ("2024 대한펜싱협회 25세이하 대표선수(국가대표 후보선수) 명단 공지", "", ["candidate_u25"]),
    ("대한펜싱협회 국가대표 선발 규정 개정 알림", "", ["regulation"]),
    ("2026 아시안게임 펜싱 선수단 파견 명단", "", ["dispatch"]),
    # 견적·채용은 procurement 가 붙어 알림에서 빠진다
    ("펜싱 장비 구입 견적 의뢰 요청 공지_2026 국가대표 후보선수 하계합숙훈련 용구 구입의 건", "",
     ["candidate_u25", "procurement"]),
    ("2026 대한펜싱협회 국가대표 전담팀 (비디오 전력분석 담당자) 채용 5차 공고", "", ["procurement"]),
    # 대회명 속 '선발대회'·경기일정 공지는 명단이 아니다
    ("경기일정 변경알림(제31회 김창환배전국남녀펜싱선수권대회 겸 국가대표선수 선발대회_에뻬종목)", "", ["other"]),
    ("2026 펜싱 국가대표선수선발대회 참가신청 마감일 안내", "", ["other"]),
    # '올림픽공원', '학교체육' 같은 부분 일치 함정
    ("올림픽 공원 내 시위로 인한 업무 및 출입 안내", "", ["other"]),
    ("2024 학교체육진흥포럼 개최 안내", "", ["other"]),
    ("2026 청소년 국가대표 선발전 안내", "", ["youth"]),
])
def test_classify_tags(title, body, expected):
    assert classify_tags(title, body) == expected


def test_should_alert_allowlist_and_suppress():
    assert should_alert(["national_team"])
    assert should_alert(["replacement"])
    assert should_alert(["ranking_points"])
    assert not should_alert(["other"])
    assert not should_alert(["youth"])
    assert not should_alert(["candidate_u25", "procurement"])


# =============================================================================
# 게시판 HTML 파싱
# =============================================================================

LIST_HTML = """
<table class="list"><tbody>
<tr><th>번호</th><th>제목</th><th>첨부파일</th><th>작성일</th><th>조회수</th></tr>
<tr><td class="font-red">공지</td>
    <td class="al-left"><a href="/board/view?code=notice&pageNum=1&boardNo=10935&masterNo=10935" class="pdl14">
      <strong class="font-red"> 2026 대한펜싱협회 국가대표 전담팀 (비디오 전력분석 담당자 ... </strong></a></td>
    <td><a href="http://fencing.sports.or.kr/upload_fencing/x.hwp" title="x.hwp"></a></td>
    <td>2026.09.23</td><td>12</td></tr>
<tr><td>1234</td>
    <td class="al-left"><a href="/board/view?code=notice&pageNum=1&boardNo=10905&masterNo=10905">2026 대한펜싱협회 국가대표선수 선발 명단 공지 및 이의 신청 안내</a></td>
    <td></td><td>2026.08.14</td><td>814</td></tr>
<tr><td>1233</td>
    <td class="al-left"><a href="/board/view?code=notice&pageNum=1&boardNo=10905&masterNo=10905">중복 행</a></td>
    <td></td><td>2026.08.14</td><td>814</td></tr>
</tbody></table>
"""


def test_parse_notice_list():
    rows = parse_notice_list(LIST_HTML)
    assert [r.board_no for r in rows] == [10935, 10905]  # 중복 boardNo 는 한 번
    assert rows[0].is_pinned and not rows[1].is_pinned
    assert rows[0].posted_at == date(2026, 9, 23)
    assert rows[1].posted_at == date(2026, 8, 14)
    assert rows[1].title.startswith("2026 대한펜싱협회 국가대표선수 선발 명단")
    assert "boardNo=10905" in rows[1].url


DETAIL_HTML = """
<table class="view"><tbody>
<tr class="lh19"><th colspan="3">2026 대한펜싱협회 국가대표선수 선발 명단 공지 및 이의 신청 안내</th></tr>
<tr class="lh19"><td>작성자 : 관리자</td><td>작성일 : 2026.08.14</td><td><span>조회수 : 814</span></td></tr>
<tr><td colspan="3" class="the-body pdb border-right">
  <p>본 협회에서는 결원이 발생하여 차순위 선수를 선발하였기에 안내합니다.</p>
  <p>1. 2026 국가대표선수 명단 : 붙임파일 참조</p><br />
  <div class="attachment"><span class="attach">
    <a href="http://fencing.sports.or.kr/upload_fencing/%28%ED%8E%9C%EC%8B%B1%29_b562.pdf" target="_blank"
       data-name="(펜싱)국가대표선수 교체 선발 명단 공지 및 이의신청 안내.pdf">(펜싱)국가대표선수 교체.pdf</a>
  </span></div>
</td></tr>
</tbody></table>
"""


def test_parse_notice_detail():
    d = parse_notice_detail(DETAIL_HTML, 10905)
    assert d.board_no == 10905
    assert d.title == "2026 대한펜싱협회 국가대표선수 선발 명단 공지 및 이의 신청 안내"
    assert d.posted_at == date(2026, 8, 14)
    assert len(d.attachments) == 1
    assert d.attachments[0].name.endswith("이의신청 안내.pdf")
    assert d.attachments[0].url.startswith("http://fencing.sports.or.kr/upload_fencing/")
    assert "차순위 선수를 선발" in d.body_text
    assert "붙임파일 참조" in d.body_text
    assert "교체.pdf" not in d.body_text  # 첨부 링크 텍스트는 본문에서 뺀다


def test_parse_kfa_date_variants():
    assert parse_kfa_date("작성일 : 2026.08.14") == date(2026, 8, 14)
    assert parse_kfa_date("2025-9-11") == date(2025, 9, 11)
    assert parse_kfa_date("없음") is None


def test_detect_kind_by_magic_not_extension():
    assert detect_kind(b"%PDF-1.4 ....", "x.hwp") == "pdf"
    assert detect_kind(b"Handysoft Approval", "x.pdf") == "other"
    assert detect_kind(b"\x89PNG\r\n", "a") == "image"


def test_extract_text_never_raises_and_strips_nul():
    r = extract_text(b"garbage bytes", "x.pdf")
    assert r["kind"] == "other" and r["text_extracted"] is False and r["extract_note"]
    r = extract_text(b"%PDF-1.4 broken", "x.pdf")
    assert r["text_extracted"] is False and "추출 실패" in r["extract_note"]


def test_safe_filename():
    assert "/" not in safe_filename("a/b:c*.pdf")
    assert len(safe_filename("x" * 300 + ".pdf")) <= 120


# =============================================================================
# 명단 파서 — 명단표 (PDF 한 줄형 / HWP 셀 분리형)
# =============================================================================

NT_PDF_TEXT = """2025년 국가대표선수 선발 명단
종목 성명 소속 비고
남자사브르
(3명)
구본길 부산광역시청
도경동 대구광역시청
오상욱 대전광역시청
남자에  뻬
(2명)
장효민 울산광역시청
박상영 울산광역시청
여자플러레
(2명)
심소은 서울특별시청
박지희 서울특별시청
"""


def test_parse_roster_document_pdf_layout():
    doc = parse_roster_document(NT_PDF_TEXT)
    assert doc.roster_type == "national_team" and doc.year == 2025
    assert len(doc.entries) == 7
    assert doc.declared_counts == {("남", "sabre"): 3, ("남", "epee"): 2, ("여", "foil"): 2}
    assert doc.warnings == []
    e = doc.entries[3]
    assert (e.gender, e.weapon, e.player_name, e.team) == ("남", "epee", "장효민", "울산광역시청")


CAND_HWP_TEXT = """
2025년 국가대표 후보선수(25세이하대표, 미래국가대표 후보선수) 명단

직위
종목
성명
소속
비고
선수
(4명)
남자 사브르
(2명)
박준성
한국체육대학교
원태영
호남대학교
여자 에  뻬
(2명)
박하빈
충청북도청
김나경
계룡시청
"""


def test_parse_roster_document_hwp_cell_layout():
    doc = parse_roster_document(CAND_HWP_TEXT)
    assert doc.roster_type == "candidate_u25" and doc.year == 2025
    assert doc.declared_total == 4
    assert [(e.player_name, e.team) for e in doc.entries] == [
        ("박준성", "한국체육대학교"), ("원태영", "호남대학교"), ("박하빈", "충청북도청"), ("김나경", "계룡시청"),
    ]
    assert doc.warnings == []


def test_parse_roster_document_reports_count_mismatch_and_non_roster():
    doc = parse_roster_document(NT_PDF_TEXT.replace("(3명)", "(4명)"))
    assert any("선언 4명, 파싱 3명" in w for w in doc.warnings)
    doc = parse_roster_document("대 한 펜 싱 협 회\n제 목 2025 국가대표선수 선발 명단 공지\n1. 관련근거 : …")
    assert doc.entries == [] and any("명단표가 아님" in w for w in doc.warnings)


def test_detect_roster_type_priority():
    assert detect_roster_type("2025년 국가대표 후보선수(25세이하대표, 미래국가대표 후보선수) 명단") == "candidate_u25"
    assert detect_roster_type("2025년 대한펜싱협회 23세이하 대표선수 명단") == "u23"
    assert detect_roster_type("2025년 대한펜싱협회 청소년 대표선수 명단") == "youth"
    assert detect_roster_type("2024년도 펜싱 국가대표선수 명단") == "national_team"
    assert detect_roster_type("공문") is None


def test_parse_gender_weapon():
    assert parse_gender_weapon("남자사브르") == ("남", "sabre")
    assert parse_gender_weapon("여자 에  뻬") == ("여", "epee")
    assert parse_gender_weapon("남자 플러레 (8명)") == ("남", "foil")
    assert parse_gender_weapon("성명 소속") is None


# =============================================================================
# 명단 파서 — 교체 공문
# =============================================================================

REPL_TEXT = """
    가. 일부 종목 국가대표선수 교체 선발 명단 공지
      1) 교체 선발인원 : 5명
      2) 교체 선발자 명단
      - 남자 사브르 2명 : 박준성(한국체육대학교), 원태영(호남대학교)
      - 남자 플러레 1명 : 서예찬(충청남도체육회)
      - 여자 플러레 1명 : 김기연(성남시청)
      - 여자 에  뻬 1명 : 한다현(전라남도청)
      3) 교체 사유 : 일부 국가대표선수 국가대표 포기에 따른 교체 선발
"""


def test_parse_replacement_notice():
    rows = parse_replacement_notice(REPL_TEXT)
    assert [(r.gender, r.weapon, r.player_name, r.team) for r in rows] == [
        ("남", "sabre", "박준성", "한국체육대학교"),
        ("남", "sabre", "원태영", "호남대학교"),
        ("남", "foil", "서예찬", "충청남도체육회"),
        ("여", "foil", "김기연", "성남시청"),
        ("여", "epee", "한다현", "전라남도청"),
    ]
    assert all(r.roster_type == "national_team_replacement" and r.note is None for r in rows)


def test_parse_replacement_notice_single_without_count():
    rows = parse_replacement_notice("      2) 교체 선발자 명단\n      - 남자 에  뻬 : 곽수인(국군체육부대)\n")
    assert [(r.weapon, r.player_name) for r in rows] == [("epee", "곽수인")]


# =============================================================================
# 명단 파서 — 합산 랭킹표 (페이지 \f 구분, 소속이 생년월일에 붙는 경우, 머리글 없는 페이지)
# =============================================================================

RANK_TEXT = (
    "순위 점수 순위 점수\n"
    "1 86 최세빈 00.08.11대전광역시청 3 20 1 32\n"
    "2 80 전하영 01.08.18서울특별시청 1 32 33 2\n"
    "비고\n종목 : 여자사브르 - 2026년 국가대표 선발을 위한 4개 대회 결과 합산 점수 랭킹 현황\n"
    "\f"
    "3 62 윤소연 98.05.14 대전광역시청 9 8 5 14\n"          # 머리글 없는 페이지 → 직전 종목 유지
    "216 0 이민주 08.02.07 - 158 0\n"                        # 소속 '-'
    "\f"
    "1 70 도경동 99.08.19 대구광역시청 17 4 6 14\n"
    "종목 : 남자 사브르 - 2026년 국가대표 선발을 위한 4개 대회 결과 합산 점수 랭킹 현황\n"
)


def test_parse_ranking_points():
    rows = parse_ranking_points(RANK_TEXT)
    got = [(r.year, r.gender, r.weapon, r.rank, r.player_name, r.team) for r in rows]
    assert got == [
        (2026, "여", "sabre", 1, "최세빈", "대전광역시청"),
        (2026, "여", "sabre", 2, "전하영", "서울특별시청"),
        (2026, "여", "sabre", 3, "윤소연", "대전광역시청"),
        (2026, "여", "sabre", 216, "이민주", None),
        (2026, "남", "sabre", 1, "도경동", "대구광역시청"),
    ]
    lk = ranking_lookup(rows)
    assert lk[(2026, "여", "sabre", "최세빈")] == 1
    assert lk[(2026, "남", "sabre", "도경동")] == 1


def test_media_rosters_shape():
    rows = media_roster_entries()
    ag = [r for r in rows if r.roster_type == "asian_games_dispatch"]
    assert len(ag) == 24 and len({(r.gender, r.weapon) for r in ag}) == 6
    mf = [r for r in rows if r.roster_type == "candidate_u25"]
    assert len(mf) == 8 and all((r.gender, r.weapon, r.year) == ("남", "foil", 2026) for r in mf)


# =============================================================================
# 실제 첨부 원본 (세션 스크래치패드에 있을 때만)
# =============================================================================

SCRATCH = ("/private/tmp/claude-501/-Users-gyejinpark-Documents-GitHub-FencingMind-data/"
           "48d3ff8c-1c03-4623-ae33-b6714784c37f/scratchpad")


@pytest.mark.skipif(not os.path.exists(os.path.join(SCRATCH, "kfa_10576_0.pdf")), reason="원본 없음")
def test_real_national_team_pdf_2025():
    with open(os.path.join(SCRATCH, "kfa_10576_0.pdf"), "rb") as f:
        r = extract_text(f.read(), "x.pdf")
    doc = parse_roster_document(r["text"])
    assert doc.roster_type == "national_team" and doc.year == 2025
    assert len(doc.entries) == 56 and doc.warnings == []
    by = {}
    for e in doc.entries:
        by[(e.gender, e.weapon)] = by.get((e.gender, e.weapon), 0) + 1
    assert by[("남", "sabre")] == 12 and by[("여", "sabre")] == 12 and by[("남", "epee")] == 8


@pytest.mark.skipif(not os.path.exists(os.path.join(SCRATCH, "kfa_10582_0.pdf")), reason="원본 없음")
def test_real_candidate_hwp_2025():
    with open(os.path.join(SCRATCH, "kfa_10582_0.pdf"), "rb") as f:  # 확장자만 pdf 인 HWP
        r = extract_text(f.read(), "x.pdf")
    assert r["kind"] == "hwp" and r["text_extracted"]
    doc = parse_roster_document(r["text"])
    assert doc.roster_type == "candidate_u25" and len(doc.entries) == 48 and doc.warnings == []


@pytest.mark.skipif(not os.path.exists(os.path.join(SCRATCH, "kfa_10835_0.pdf")), reason="원본 없음")
def test_real_replacement_pdf_2026_07():
    with open(os.path.join(SCRATCH, "kfa_10835_0.pdf"), "rb") as f:
        r = extract_text(f.read(), "x.pdf")
    rows = parse_replacement_notice(r["text"])
    assert sorted(x.player_name for x in rows) == ["김기연", "박준성", "서예찬", "원태영", "한다현"]


# =============================================================================
# 프로필 배지 매칭 — (이름, 소속) 둘 다 맞아야 하고 roster_type 별 최신 연도 하나만
# =============================================================================

from app.kfa_notices import match_rosters  # noqa: E402

ROSTER_ROWS = [
    {"roster_type": "national_team", "year": 2024, "weapon": "sabre", "gender": "남", "player_name": "도경동",
     "team": "대구광역시청", "source_type": "kfa", "source_board_no": 10310, "source_url": "https://x/10310"},
    {"roster_type": "national_team", "year": 2025, "weapon": "sabre", "gender": "남", "player_name": "도경동",
     "team": "대구광역시청", "source_type": "kfa", "source_board_no": 10576, "source_url": "https://x/10576"},
    {"roster_type": "asian_games_dispatch", "year": 2026, "weapon": "sabre", "gender": "남", "player_name": "도경동",
     "team": "대구 광역시청", "source_type": "media", "source_url": None, "note": "언론·SNS 확인"},
    {"roster_type": "youth", "year": 2025, "weapon": "foil", "gender": "남", "player_name": "정유준",
     "team": "신수중학교", "source_type": "media", "note": "합동훈련 게시물 전사"},
    {"roster_type": "youth", "year": 2025, "weapon": "sabre", "gender": "여", "player_name": "김민서",
     "team": None, "source_type": "media", "note": "합동훈련"},
]


def test_match_rosters_latest_year_per_type_and_source_labels():
    badges = match_rosters(ROSTER_ROWS, "도경동", ["대구광역시청"])
    assert [(b["label"], b["source_type"]) for b in badges] == [
        ("AG2026 파견", "media"), ("2025 국가대표", "kfa"),
    ]
    assert badges[1]["source_url"] == "https://x/10576" and "#10576" in badges[1]["source_label"]
    assert badges[0]["source_url"] is None and badges[0]["source_label"] == "언론·SNS 확인"


def test_match_rosters_requires_team_match():
    assert match_rosters(ROSTER_ROWS, "도경동", ["성남시청"]) == []          # 소속 불일치 → 미표시
    assert match_rosters(ROSTER_ROWS, "김민서", ["은성중학교"]) == []        # 명단에 소속 없음 → 대조 불가 → 미표시
    b = match_rosters(ROSTER_ROWS, "정유준", ["경덕중학교", "신수중학교"])  # 소속 이력 중 하나면 충분
    assert len(b) == 1 and b[0]["source_label"] == "합동훈련 명단(SNS)"
