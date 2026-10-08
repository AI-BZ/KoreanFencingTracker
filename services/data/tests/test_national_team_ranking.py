"""NT 전체 랭킹 — 대한펜싱협회 「국가대표 선발 규정」(2025.04.23 개정) 제20조·제21조 고정 테스트.

배점(② 1호), 예선 탈락 0점(② 1호 단서), FIE 점수(② 3호), 동점 규칙(③), 달력 연도 창,
4개 대회 분류, calculator 경유 시 best_results 가 4칸 표인지.
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from ranking.national_team import (  # noqa: E402
    NationalTeamRankingCalculator, classify_nt_competition, nt_rank_points,
    fie_rank_points, nt_international_points, nt_selection_quota, normalize_name,
    NT_COMP_ORDER,
)


# ---------- 픽스처 ----------

def event(name, rankings, de_names=None, weapon=None, gender=None):
    """final_rankings + DE 대진표. de_names=None 이면 DE 정보 없음(rank_only)."""
    ev = {"name": name, "weapon": weapon, "gender": gender,
          "final_rankings": [{"name": n, "rank": r, "team": t} for n, r, t in rankings]}
    if de_names is not None:
        ev["de_bracket"] = {"first_de": {"seeding": [{"name": n} for n in de_names]}}
    return ev


def comp(name, start, events):
    return {"competition": {"name": name, "start_date": start, "end_date": start, "event_cd": name},
            "events": events}


PRES, KIM, OPEN, NAT = (
    "제66회 대통령배전국남·녀펜싱선수권대회 겸 국가대표선수 선발대회",
    "제30회 김창환배전국남녀펜싱선수권대회 겸 국가대표선수 선발대회",
    "2026 전국남·녀종목별오픈펜싱선수권대회 겸 국가대표선수 선발대회",
    "2026 펜싱 국가대표선수 선발대회",
)


# ---------- 배점표 ----------

@pytest.mark.parametrize("rank,pts", [
    (1, 32), (2, 26), (3, 20), (4, 20), (5, 14), (8, 14), (9, 8), (16, 8),
    (17, 4), (32, 4), (33, 2), (64, 2), (65, 1), (96, 1), (97, 0.5), (128, 0.5),
    (129, 0), (200, 0), (0, 0),
])
def test_domestic_points_table(rank, pts):
    assert nt_rank_points(rank) == pts


@pytest.mark.parametrize("rank,pts", [(1, 32), (2, 31), (3, 30), (16, 17), (17, 0), (None, 0), (0, 0)])
def test_fie_points_table(rank, pts):
    assert fie_rank_points(rank) == pts


@pytest.mark.parametrize("rank,pts", [(1, 36), (3, 28), (8, 24), (128, 4), (256, 3), (257, 2), (None, 2)])
def test_international_points_table_prepared(rank, pts):
    assert nt_international_points(rank) == pts


# ---------- 대회 분류 ----------

@pytest.mark.parametrize("name,cid", [
    (PRES, "president_cup"), (KIM, "kim_changhwan"), (OPEN, "jongbyul_open"), (NAT, "national_selection"),
    ("2020 펜싱 국가대표선수 선발전", "national_selection"),
    ("2026 대한펜싱협회 유소년 국가대표선수 선발전", None),
    ("2019 대한펜싱협회 청소년, 유소년 국가대표선수 선발전", None),
    ("2025 하계유니버시아드 파견선수 선발전", None),
    ("2026 펜싱 클럽 코리아 오픈대회", None),
    ("제64회 전국남녀종별펜싱선수권대회", None),
])
def test_classify_four_competitions(name, cid):
    assert classify_nt_competition(name) == cid


def test_quota_default_and_override():
    assert nt_selection_quota(2026, "foil") == 8
    assert nt_selection_quota(2025, "sabre") == 12  # 2025.09.11 선발 명단


def test_normalize_name_strips_homonym_marker():
    assert normalize_name("김재원(*)") == "김재원"
    assert normalize_name(" 김재원 ") == "김재원"
    assert normalize_name("김재원(2)") == "김재원"
    assert normalize_name("김주희050513") == "김주희"  # 복구 데이터의 생년월일 접미
    assert normalize_name("김주희") == "김주희"


# ---------- 합산·예선 탈락·연도 창 ----------

def _calc(*comps):
    return NationalTeamRankingCalculator({"competitions": list(comps)})


def test_four_column_sum_and_pool_eliminated_zero():
    # 대통령배: A 1위, B 33위(DE 진출), C 40위인데 DE 대진표에 없음 → 예선 탈락 0점
    data = _calc(
        comp(PRES, "2026-08-12", [event("남자 에뻬(개)", [("A", 1, "t"), ("B", 33, "t"), ("C", 40, "t")],
                                       de_names=["A", "B"], weapon="epee", gender="남")]),
        comp(NAT, "2026-06-06", [event("남자 에뻬(개)", [("B", 1, "t"), ("A", 2, "t"), ("C", 3, "t")],
                                      de_names=["A", "B", "C"], weapon="epee", gender="남")]),
    )
    t = data.calculate("epee", "남", 2026)
    by = {r.player_name: r for r in t.rankings}
    assert by["A"].total_points == 32 + 26
    assert by["B"].total_points == 2 + 32
    assert by["C"].total_points == 0 + 20
    assert by["C"].results["president_cup"].qualified is False
    assert by["C"].results["president_cup"].points == 0
    assert [c.status for c in t.columns] == ["completed", "upcoming", "upcoming", "completed"]
    assert t.completed_count == 2 and len(t.columns) == 4
    assert [c.comp_id for c in t.columns] == NT_COMP_ORDER
    assert t.quota == 8 and t.fie_applied is False


def test_rank_only_when_no_de_data():
    data = _calc(comp(NAT, "2026-06-06", [event("여자 사브르(개)", [("A", 1, "t"), ("B", 130, "t")],
                                              weapon="sabre", gender="여")]))
    t = data.calculate("sabre", "여", 2026)
    assert t.columns[3].qualification_source == "rank_only"
    by = {r.player_name: r for r in t.rankings}
    assert by["A"].total_points == 32 and by["B"].total_points == 0


def test_latest_edition_window_and_carryover():
    """협회 방식: 기준일 시점 각 대회의 최근 결과 회차. 새 회차 없으면 직전 연도 회차 이월."""
    from datetime import date
    data = _calc(
        comp(KIM, "2025-08-30", [event("여자 플러레(개)", [("A", 1, "t")], de_names=["A"], weapon="foil", gender="여")]),
        comp(KIM.replace("제30회", "제31회"), "2026-08-28",
             [event("여자 플러레(개)", [("A", 5, "t")], de_names=["A"], weapon="foil", gender="여")]),
    )
    # 2026.08.26 시점(협회 8/26 표): 2026 김창환배는 아직 안 열림 → 2025 회차 이월
    t = data.calculate("foil", "여", 2026, today=date(2026, 8, 26))
    assert {r.player_name: r.total_points for r in t.rankings} == {"A": 32}
    assert t.columns[1].is_carryover is True and t.columns[1].edition_year == 2025
    assert t.columns[1].status == "completed" and t.meta()["carryover_count"] == 1
    # 2026.09.27 시점: 2026 회차 결과 있음 → 교체
    t = data.calculate("foil", "여", 2026, today=date(2026, 9, 27))
    assert {r.player_name: r.total_points for r in t.rankings} == {"A": 14}
    assert t.columns[1].is_carryover is False and t.columns[1].comp_name.startswith("제31회")
    # 지난해 조회는 그 해 12/31 기준 → 2025 회차만
    t25 = data.calculate("foil", "여", 2025, today=date(2026, 9, 27))
    assert {r.player_name: r.total_points for r in t25.rankings} == {"A": 32}
    assert t25.columns[1].edition_year == 2025 and not t25.columns[1].is_carryover
    # 2년 전 회차는 이월하지 않는다
    t27 = data.calculate("foil", "여", 2027, today=date(2027, 8, 1))
    assert t27.columns[1].status == "completed" and t27.columns[1].edition_year == 2026
    t28 = data.calculate("foil", "여", 2028, today=date(2028, 8, 1))
    assert t28.columns[1].status == "upcoming"
    assert data.available_years() == [2026, 2025]


def test_new_edition_without_results_keeps_previous_and_marks_pending():
    from datetime import date
    data = _calc(
        comp(KIM, "2025-08-30", [event("여자 플러레(개)", [("A", 1, "t")], de_names=["A"], weapon="foil", gender="여")]),
        {"competition": {"name": KIM.replace("제30회", "제31회"), "start_date": "2026-08-28", "end_date": "2026-09-04",
                         "event_cd": "x"},
         "events": [{"name": "여자 플러레(개)", "weapon": "foil", "gender": "여", "final_rankings": []}]},
    )
    t = data.calculate("foil", "여", 2026, today=date(2026, 8, 30))  # 회차 진행 중 → 직전 회차 이월
    col = t.columns[1]
    assert col.is_carryover and col.edition_year == 2025 and col.pending_comp_name.startswith("제31회")
    assert {r.player_name: r.total_points for r in t.rankings} == {"A": 32}


def test_team_event_and_other_weapon_ignored():
    data = _calc(comp(NAT, "2026-06-06", [
        event("남자 에뻬(단)", [("A", 1, "t")], de_names=["A"], weapon="epee", gender="남"),
        event("남자 플러레(개)", [("A", 1, "t")], de_names=["A"], weapon="foil", gender="남"),
    ]))
    assert data.calculate("epee", "남", 2026).rankings == []


# ---------- 동점 규칙 (제20조 ③) ----------

def _tie_data():
    # 순위 목록 사전식 비교 (협회 표 실측):
    # A: 대통령배 1위(32) + 국대선발 33위(2)  = 34 → [1,33]
    # B: 대통령배 2위(26) + 국대선발 9위(8)   = 34 → [2,9]
    # C: 대통령배 3위(20) + 국대선발 5위(14)  = 34 → [3,5]
    # D: 김창환배 1위(32) + 국대선발 33위(2)  = 34 → [1,33] = A 와 동일
    #    → 규정 순서 대통령배 성적 비교: A(1위) 가 D(불참) 앞
    return _calc(
        comp(PRES, "2026-08-12", [event("남자 사브르(개)",
             [("A", 1, "t"), ("B", 2, "t"), ("C", 3, "t")], de_names=["A", "B", "C"], weapon="sabre", gender="남")]),
        comp(KIM, "2026-08-28", [event("남자 사브르(개)", [("D", 1, "t")], de_names=["D"], weapon="sabre", gender="남")]),
        comp(NAT, "2026-06-06", [event("남자 사브르(개)",
             [("C", 5, "t"), ("B", 9, "t"), ("A", 33, "t"), ("D", 33, "t")],
             de_names=["A", "B", "C", "D"], weapon="sabre", gender="남")]),
    )


def test_tie_break_more_first_places_then_competition_order():
    t = _tie_data().calculate("sabre", "남", 2026)
    assert [r.total_points for r in t.rankings] == [34, 34, 34, 34]
    assert [r.player_name for r in t.rankings] == ["A", "D", "B", "C"]
    assert [r.current_rank for r in t.rankings] == [1, 2, 3, 4]


def test_tie_break_lexicographic_on_sorted_finishes():
    """2026 여사브르 실측: 양예솔 [11,2,17,6]=52 가 선은비 [2,19,14,8]=52 보다 앞 (6위 > 8위)."""
    def mk(cid_ranks):
        return cid_ranks
    comps = [
        comp(PRES, "2026-08-12", [event("여자 사브르(개)", [("양예솔", 11, "t"), ("선은비", 2, "t")], de_names=["양예솔", "선은비"], weapon="sabre", gender="여")]),
        comp(KIM, "2026-08-28", [event("여자 사브르(개)", [("양예솔", 2, "t"), ("선은비", 19, "t")], de_names=["양예솔", "선은비"], weapon="sabre", gender="여")]),
        comp(OPEN, "2026-01-14", [event("여자 사브르(개)", [("양예솔", 17, "t"), ("선은비", 14, "t")], de_names=["양예솔", "선은비"], weapon="sabre", gender="여")]),
        comp(NAT, "2026-06-06", [event("여자 사브르(개)", [("양예솔", 6, "t"), ("선은비", 8, "t")], de_names=["양예솔", "선은비"], weapon="sabre", gender="여")]),
    ]
    from datetime import date
    t = _calc(*comps).calculate("sabre", "여", 2026, today=date(2026, 9, 27))
    assert [(r.player_name, r.total_points) for r in t.rankings] == [("양예솔", 52), ("선은비", 52)]


# ---------- FIE 점수 (제20조 ② 3호) ----------

def test_fie_points_added_when_lookup_available():
    def fie(weapon, gender, year):
        return {"B": 5} if (weapon, gender, year) == ("sabre", "남", 2026) else None
    data = NationalTeamRankingCalculator({"competitions": [
        comp(NAT, "2026-06-06", [event("남자 사브르(개)", [("A", 1, "t"), ("B", 2, "t")],
                                      de_names=["A", "B"], weapon="sabre", gender="남")]),
    ]}, fie_lookup=fie)
    t = data.calculate("sabre", "남", 2026)
    assert t.fie_applied is True
    by = {r.player_name: r for r in t.rankings}
    # 표 순위·total_points 는 국내 합산(협회 합산표와 동일), FIE 는 선발 순위에만 합산
    assert by["B"].fie_points == 28 and by["B"].total_points == 26 and by["B"].selection_points == 26 + 28
    assert by["A"].fie_points == 0 and by["A"].total_points == 32 and by["A"].selection_points == 32
    assert t.rankings[0].player_name == "A" and by["A"].current_rank == 1
    assert by["B"].selection_rank == 1 and by["A"].selection_rank == 2


# ---------- 동명이인 ----------

def test_homonyms_split_by_team_when_same_event_has_two():
    data = _calc(
        comp(PRES, "2026-08-12", [event("여자 에뻬(개)", [("X", 1, "서울시청"), ("X", 40, "덕원중학교")],
                                       de_names=["X"], weapon="epee", gender="여")]),
        comp(NAT, "2026-06-06", [event("여자 에뻬(개)", [("X", 2, "서울시청")], de_names=["X"], weapon="epee", gender="여")]),
    )
    t = data.calculate("epee", "여", 2026)
    rows = {(r.player_name, r.team): r.total_points for r in t.rankings}
    assert rows == {("X", "서울시청"): 32 + 26, ("X", "덕원중학교"): 2}


# ---------- calculator.py 경유 ----------

def test_calculator_nt_path_returns_four_cell_breakdown():
    from ranking.calculator import RankingCalculator
    rc = RankingCalculator()
    rc.load_from_data({"competitions": [
        comp(NAT, "2026-06-06", [event("남자 에뻬(개)", [("A", 1, "t"), ("B", 2, "t")],
                                      de_names=["A", "B"], weapon="epee", gender="남")]),
        comp(PRES, "2026-08-12", [event("남자 에뻬(개)", [("B", 1, "t"), ("A", 5, "t")],
                                       de_names=["A", "B"], weapon="epee", gender="남")]),
    ]})
    rows = rc.calculate_rankings(weapon="epee", gender="남", age_group="NT", year=2026, national_team_only=True)
    assert [r.player_name for r in rows] == ["B", "A"]  # B 58 > A 46
    b = rows[0]
    assert b.total_points == 26 + 32
    assert [c["comp_id"] for c in b.best_results] == NT_COMP_ORDER
    assert [c["rank"] for c in b.best_results] == [1, None, None, 2]
    assert b.nt_info["completed_count"] == 2 and b.nt_info["quota"] == 8
    assert b.nt_info["fie_applied"] is False
    assert b.gold_count == 1 and b.silver_count == 1 and b.competitions_count == 2
    # 나이리그 경로는 그대로 (NT 서브랭킹은 'NT' 결과를 만든다)
    assert any(r.age_group == "NT" for r in rc.results)


# ---------- FIE 로더 (data_fie_rankings 실제 스키마) ----------

def test_fie_loader_reads_real_schema_and_maps_season():
    from ranking.national_team import build_fie_lookup_from_rows
    rows = [
        {"season": 2026, "weapon": "S", "gender": "M", "fie_rank": 3, "athlete_name": "OH Sanguk",
         "player_name_ko": "오상욱", "country": "KOR"},
        {"season": 2026, "weapon": "S", "gender": "M", "fie_rank": 9, "athlete_name": "X", "player_name_ko": None,
         "country": "KOR"},                                                  # 한글 미확정 → 건너뜀
        {"season": 2026, "weapon": "S", "gender": "M", "fie_rank": 1, "player_name_ko": "누군가", "country": "ITA"},  # 외국
        {"season": 2027, "weapon": "F", "gender": "F", "fie_rank": 12, "player_name_ko": "홍효진", "country": "KOR"},
        {"year": 2026, "weapon": "epee", "gender": "여", "rank": 5, "player_name": "송세라"},  # 일반형도 허용
    ]
    fie = build_fie_lookup_from_rows(rows)
    assert fie("sabre", "남", 2026) == {"오상욱": 3}
    assert fie("foil", "여", 2027) == {"홍효진": 12}
    assert fie("foil", "여", 2026) is None
    assert fie("epee", "여", 2026) == {"송세라": 5}


def test_finished_edition_without_results_is_missing_data_not_carryover():
    """끝난 회차에 결과가 없으면(우리 결손) 직전 회차를 이월하지 않고 no_results 로 표시."""
    from datetime import date
    data = _calc(
        comp(KIM, "2025-08-30", [event("여자 플러레(개)", [("A", 1, "t")], de_names=["A"], weapon="foil", gender="여")]),
        {"competition": {"name": KIM.replace("제30회", "제31회"), "start_date": "2026-08-28", "end_date": "2026-09-04",
                         "event_cd": "x"},
         "events": [{"name": "여자 플러레(개)", "weapon": "foil", "gender": "여", "final_rankings": []}]},
    )
    t = data.calculate("foil", "여", 2026, today=date(2026, 9, 27))
    col = t.columns[1]
    assert col.status == "no_results" and col.edition_year == 2026 and not col.is_carryover
    assert t.rankings == [] and t.completed_count == 0


def test_rank_within_confirmed_de_range_counts_as_qualified():
    """대진표에서 이름이 빠진 선수도, 확인된 DE 진출자의 최하위 순위 이내면 진출자(데이터 결손 보정)."""
    data = _calc(comp(NAT, "2026-06-06", [event(
        "남자 사브르(개)",
        [("A", 1, "t"), ("B", 33, "t"), ("C", 40, "t"), ("D", 120, "t"), ("E", 125, "t")],
        de_names=["A", "B", "D"], weapon="sabre", gender="남")]))
    by = {r.player_name: r for r in data.calculate("sabre", "남", 2026).rankings}
    assert by["C"].results["national_selection"].qualified is True and by["C"].total_points == 2
    assert by["E"].results["national_selection"].qualified is False and by["E"].total_points == 0


def test_homonym_groups_merge_renamed_team_via_identity_lookup():
    """소속 개명(중구청→영종구청)은 신원 조회가 같은 사람으로 알려 주면 한 행으로 합산."""
    lookup = lambda n: [{"인천광역시중구청", "인천광역시영종구청"}, {"전남체육고등학교"}] if n == "김현진" else []
    data = NationalTeamRankingCalculator({"competitions": [
        comp(PRES, "2026-08-12", [event("여자 플러레(개)", [("김현진", 6, "인천광역시중구청"), ("김현진", 60, "전남체육고등학교")],
                                       de_names=["김현진"], weapon="foil", gender="여")]),
        comp(NAT, "2026-06-06", [event("여자 플러레(개)", [("김현진", 1, "인천광역시영종구청")], de_names=["김현진"], weapon="foil", gender="여")]),
    ]}, team_groups_lookup=lookup)
    rows = {(r.player_name, r.team): r.total_points for r in data.calculate("foil", "여", 2026).rankings}
    # 행의 소속은 가장 최근 대회(대통령배 8월)의 표기 — 개명 전 이름이라도 한 사람으로 합산된다
    assert rows == {("김현진", "인천광역시중구청"): 14 + 32, ("김현진", "전남체육고등학교"): 2}


def test_identity_lookup_wins_when_one_team_belongs_to_two_people():
    """같은 소속을 두 사람이 거쳤으면 소속 집합만으로는 못 가른다 — 레코드 주인을 직접 묻는다.

    실제 사고(2026-10-08, 2026 여자 플뢰레): '김현진'의 '인천광역시중구청'이 두 프로필
    (영종구청으로 개명한 사람 / 독도스포츠단으로 옮긴 다른 사람) 양쪽에 들어 있었다.
    `_team_group_key` 가 '먼저 걸린 집합'을 쓰던 동안에는 집합 순회 순서에 따라 답이
    바뀌어, 서버를 재시작하면 협회 표 2위(74점)가 8위(46점)로 떨어졌다.
    """
    groups = [{"인천광역시중구청", "인천광역시영종구청"},
              {"인천광역시중구청", "경상북도체육회 독도스포츠단"}]
    team_lookup = lambda n: groups if n == "김현진" else []
    # 리졸버는 각 순위 행의 주인을 이미 알고 있다 (comp_cd 로 구분)
    owners = {("김현진", "pres-cd", "여자 플러레(개)", "인천광역시영종구청"): "KOP_A",
              ("김현진", "nat-cd", "여자 플러레(개)", "인천광역시중구청"): "KOP_A"}
    identity = lambda name, comp_cd, event_name, team: owners.get((name, comp_cd, event_name, team))

    def _data(**kw):
        pres = comp(PRES, "2026-08-12", [event(
            "여자 플러레(개)",
            [("김현진", 6, "인천광역시영종구청"), ("김현진", 60, "경상북도체육회 독도스포츠단")],
            de_names=["김현진"], weapon="foil", gender="여")])
        pres["competition"]["event_cd"] = "pres-cd"
        nat = comp(NAT, "2026-06-06", [event(
            "여자 플러레(개)", [("김현진", 1, "인천광역시중구청")],
            de_names=["김현진"], weapon="foil", gender="여")])
        nat["competition"]["event_cd"] = "nat-cd"
        return NationalTeamRankingCalculator({"competitions": [pres, nat]}, **kw)

    rows = {(r.player_name, r.team): r.total_points
            for r in _data(team_groups_lookup=team_lookup, identity_lookup=identity)
            .calculate("foil", "여", 2026).rankings}
    assert rows == {("김현진", "인천광역시영종구청"): 14 + 32,
                    ("김현진", "경상북도체육회 독도스포츠단"): 2}

    # 신원 조회가 없으면 애매한 소속은 **아무 집합도 고르지 않는다** (소속명 그대로 → 분리).
    # 틀린 쪽으로 합치는 것보다 갈라 두는 쪽이 낫다 — 제0원칙 1(모르면 추측하지 않는다).
    rows_no_identity = {(r.player_name, r.team): r.total_points
                        for r in _data(team_groups_lookup=team_lookup)
                        .calculate("foil", "여", 2026).rankings}
    assert rows_no_identity == {("김현진", "인천광역시영종구청"): 14,
                                ("김현진", "경상북도체육회 독도스포츠단"): 2,
                                ("김현진", "인천광역시중구청"): 32}
