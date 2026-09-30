"""검증 규칙 단위 테스트 — 2026-09-28 에 추가/수정한 규칙의 회귀 방지.

여기서 지키려는 것은 두 가지다.
  ① 오염을 **실제로 잡는가** (R1a 는 규칙이 있었는데도 입력 단계에서 증거가 지워져
     한 번도 발동하지 못했다 — 그 종류의 실패를 테스트로 고정한다)
  ② 정상 데이터를 **잡지 않는가** (R8 은 정상 선수를 3,488건 잡고 있었다)

실행:
    cd services/data
    PYTHONPATH=".:../../packages" python -m pytest tests/test_data_validator_rules.py -q
"""
import pytest

from app.data_validator import DataValidator, canon_player_name


# ---------------------------------------------------------------------------
# 픽스처 헬퍼
# ---------------------------------------------------------------------------

def bout(rnd, num, p1, p2, s1=None, s2=None, winner=None, phase=None, is_bye=False):
    b = {
        "round_name": rnd,
        "match_number": num,
        "player1_name": p1,
        "player2_name": p2,
        "player1_score": s1,
        "player2_score": s2,
    }
    if winner is not None:
        b["winner_name"] = winner
    if phase is not None:
        b["de_phase"] = phase
    if is_bye:
        b["is_bye"] = True
    return b


def make_comp(events, comp_name="테스트대회", start_date="2026-01-01"):
    return [{
        "competition": {"id": 1, "name": comp_name, "start_date": start_date},
        "events": events,
    }]


def event(name="여자 에뻬(개)", cd="EV1", de=None, final=None,
          pool_rounds=None, pool_total=None, participants=None):
    return {
        "sub_event_cd": cd,
        "event_name": name,
        "de_bracket": de if de is not None else {},
        "final_rankings": final,
        "pool_rounds": pool_rounds,
        "pool_total_ranking": pool_total or [],
        "participants": participants or [],
    }


def rule_ids(issues, rule):
    return [i for i in issues if i.rule_id == rule]


def run_events(events, **kw):
    v = DataValidator(make_comp(events, **kw))
    v.issues = []
    v._validate_all_events()
    return v.issues


def run_all(events, **kw):
    return DataValidator(make_comp(events, **kw)).validate_all()


# ---------------------------------------------------------------------------
# R1a — self-bout
# ---------------------------------------------------------------------------

class TestR1aSelfBout:
    """R1a 는 2026-09-28 까지 구조적으로 발동 불가였다.

    `_get_full_bouts_from_bracket()` 이 p1 == p2 를 먼저 버렸기 때문에, R1a 가 세려던
    증거가 입력에서 사라졌다. 전수 리포트의 R1a 는 0건이었으나 DB 에는 1,218경기가 있었다.
    이 테스트가 그 회귀를 막는다.
    """

    def test_detects_self_bout(self):
        de = {"bracket_size": 32, "full_bouts": [
            bout("32강", 1, "김하나", "이두리", 15, 10),
            bout("32강", 5, "정효정", "정효정", 15, 1),
            bout("32강", 6, "정효정", "정효정", 15, 1),
        ]}
        found = rule_ids(run_events([event(de=de)]), "R1a")
        assert len(found) == 1, "self-bout 이 있는데 R1a 가 침묵했다"
        assert found[0].severity == "ERROR"
        assert found[0].player_name == "정효정"
        assert found[0].data["bout_count"] == 2

    def test_flags_identical_scores_as_replicated_phantom(self):
        """점수까지 같으면 '복제된 팬텀'으로 표시해야 한다 (실측 오염의 지문)."""
        de = {"bracket_size": 32, "full_bouts": [
            bout("32강", 5, "정효정", "정효정", 15, 1),
            bout("32강", 6, "정효정", "정효정", 15, 1),
            bout("32강", 7, "정효정", "정효정", 15, 1),
        ]}
        found = rule_ids(run_events([event(de=de)]), "R1a")
        assert found[0].data["identical_score"] is True
        assert "복제" in found[0].message

    def test_clean_bracket_has_no_r1a(self):
        de = {"bracket_size": 4, "full_bouts": [
            bout("준결승", 1, "김하나", "이두리", 15, 10),
            bout("준결승", 2, "박세찌", "최네찌", 15, 12),
            bout("결승", 3, "김하나", "박세찌", 15, 14),
        ]}
        assert rule_ids(run_events([event(de=de)]), "R1a") == []

    def test_homonym_pair_is_not_a_self_bout(self):
        """동명이인 두 명이 맞붙는 것은 self-bout 이 아니다 — 이름이 같아도
        협회 순위표가 `(*)` 로 갈라 놓고 대진표에는 별표가 없으므로, 대진표에서
        같은 문자열이 양쪽에 오는 것은 실제로 구분이 불가능하다. 그래서 R1a 는
        점수 동일성으로 팬텀을 가르고, 이름만으로 단죄하지 않는다."""
        de = {"bracket_size": 8, "full_bouts": [
            bout("8강", 1, "김민서", "김민서", 15, 13),  # 서로 다른 두 사람일 수 있다
        ]}
        found = rule_ids(run_events([event(de=de)]), "R1a")
        assert len(found) == 1
        # 1경기뿐이므로 '복제' 판정은 붙지 않는다
        assert found[0].data["identical_score"] is False


# ---------------------------------------------------------------------------
# R1c — 라운드 정원 초과 (팬텀)
# ---------------------------------------------------------------------------

class TestR1cPhantomCapacity:

    def test_detects_capacity_overflow(self):
        """16강은 최대 8경기. 12경기면 4개가 팬텀이다."""
        bouts = [bout("16강", i, f"선수{i}", f"상대{i}", 15, 10) for i in range(1, 13)]
        found = rule_ids(run_events([event(de={"bracket_size": 16, "full_bouts": bouts})]), "R1c")
        assert len(found) == 1
        assert found[0].severity == "ERROR"
        assert found[0].data["capacity"] == 8
        assert found[0].data["excess"] == 4

    def test_full_round_at_capacity_is_clean(self):
        bouts = [bout("16강", i, f"선수{i}", f"상대{i}", 15, 10) for i in range(1, 9)]
        assert rule_ids(run_events([event(de={"bracket_size": 16, "full_bouts": bouts})]), "R1c") == []

    def test_byes_do_not_count_toward_capacity(self):
        """부전승은 경기가 아니다 (CLAUDE.md '슬롯 수 ≠ 경기 수').
        정원을 슬롯으로 세면 부전승이 많은 브래킷이 통째로 오탐이 된다."""
        bouts = [bout("16강", i, f"선수{i}", f"상대{i}", 15, 10) for i in range(1, 9)]
        bouts += [bout("16강", i, f"부전{i}", "", is_bye=True) for i in range(9, 13)]
        assert rule_ids(run_events([event(de={"bracket_size": 16, "full_bouts": bouts})]), "R1c") == []

    def test_dual_de_without_phase_is_skipped(self):
        """예선 64강 32경기 + 본선 64강 32경기가 위상 없이 한 칸에 쌓이면 64 > 32 로
        보이지만 정원 초과가 아니다 — 위상 누락이고 R25 담당이다. 여기서 또 세면
        같은 사실이 두 규칙에서 중복 계상된다."""
        bouts = [bout("64강", i, f"a{i}", f"b{i}", 15, 10) for i in range(1, 65)]
        de = {"format": "dual_de", "bracket_size": 128,
              "first_de": {}, "second_de": {}, "full_bouts": bouts}
        issues = run_events([event(de=de)])
        assert rule_ids(issues, "R1c") == []
        assert rule_ids(issues, "R25"), "위상 누락은 R25 가 잡아야 한다"

    def test_dual_de_with_phase_counts_each_phase_separately(self):
        """위상이 붙어 있으면 예선 64강 32 + 본선 64강 32 는 각각 정원 내라 정상이다."""
        bouts = [bout("64강", i, f"q{i}", f"qq{i}", 15, 10, phase="qualifying")
                 for i in range(1, 33)]
        bouts += [bout("64강", i, f"m{i}", f"mm{i}", 15, 10, phase="main")
                  for i in range(1, 33)]
        de = {"format": "dual_de", "bracket_size": 128,
              "first_de": {}, "second_de": {}, "full_bouts": bouts}
        assert rule_ids(run_events([event(de=de)]), "R1c") == []


# ---------------------------------------------------------------------------
# R28 — 이름 뭉개짐
# ---------------------------------------------------------------------------

class TestR28NameCollapse:

    def test_replicated_name_is_error(self):
        bouts = [bout("32강", i, "정효정", "정효정", 15, 1) for i in range(1, 13)]
        found = rule_ids(run_events([event(de={"bracket_size": 32, "full_bouts": bouts})]), "R28")
        assert found and found[0].severity == "ERROR"
        assert found[0].data["phantom"] is True

    def test_nine_slots_is_the_structural_maximum(self):
        """단일 DE 8라운드 + dual DE 예선 3 + 본선 6 = 최대 9. 실측으로도 오염되지 않은
        종목의 최대 점유는 9슬롯(정유준)이었다. 9는 잡지 않아야 한다."""
        rounds = ["256강", "128강", "64강", "32강", "16강", "8강", "4강", "결승"]
        bouts = [bout(r, i + 1, "정유준", f"상대{i}", 15, 10) for i, r in enumerate(rounds)]
        assert rule_ids(run_events([event(de={"bracket_size": 256, "full_bouts": bouts})]), "R28") == []

    def test_many_slots_without_duplication_is_warning_not_error(self):
        """동명이인 두 명이 각각 깊게 올라가면 한 이름이 10슬롯을 넘을 수 있다.
        중복 증거가 없으면 단죄하지 않고 사람에게 넘긴다."""
        rounds = ["256강", "128강", "64강", "32강", "16강", "8강", "4강", "결승"]
        bouts = [bout(r, i + 1, "김민서", f"상대{i}", 15, 10) for i, r in enumerate(rounds)]
        bouts += [bout(r, 20 + i, "김민서", f"타상대{i}", 15, 9) for i, r in enumerate(rounds[:3])]
        found = rule_ids(run_events([event(de={"bracket_size": 256, "full_bouts": bouts})]), "R28")
        assert found and found[0].severity == "WARNING"
        assert found[0].data["phantom"] is False


# ---------------------------------------------------------------------------
# R26 / R27 — final_rankings
# ---------------------------------------------------------------------------

class TestR26FinalRankingStructure:

    def test_missing_champion(self):
        final = [{"name": "가", "rank": 3}, {"name": "나", "rank": 3},
                 {"name": "다", "rank": 5}]
        found = rule_ids(run_events([event(final=final)]), "R26")
        places = {i.data["place"] for i in found}
        assert places == {1, 2}
        assert all(i.severity == "ERROR" for i in found)

    def test_duplicate_champion(self):
        final = [{"name": "가", "rank": 1}, {"name": "나", "rank": 1},
                 {"name": "다", "rank": 2}]
        found = rule_ids(run_events([event(final=final)]), "R26")
        assert [i.data["place"] for i in found] == [1]
        assert found[0].data["count"] == 2

    def test_tied_third_is_allowed(self):
        """FIE 규정상 동률은 3위(3T)만 존재한다 — 3위 2명은 정상이다."""
        final = [{"name": "가", "rank": 1}, {"name": "나", "rank": 2},
                 {"name": "다", "rank": 3}, {"name": "라", "rank": 3}]
        assert rule_ids(run_events([event(final=final)]), "R26") == []

    def test_single_entry_needs_no_runner_up(self):
        assert rule_ids(run_events([event(final=[{"name": "가", "rank": 1}])]), "R26") == []

    def test_empty_final_is_not_flagged(self):
        """최종순위가 아직 없는 것은 R26 문제가 아니다 (감사 F10 영역)."""
        assert rule_ids(run_events([event(final=[])]), "R26") == []


class TestR27FinalRankingRoster:

    def test_detects_name_absent_from_roster(self):
        de = {"bracket_size": 4, "full_bouts": [
            bout("준결승", 1, "김하나", "이두리", 15, 10),
            bout("준결승", 2, "박세찌", "최네찌", 15, 12),
            bout("결승", 3, "김하나", "박세찌", 15, 14),
        ]}
        final = [{"name": "김하나", "rank": 1}, {"name": "박세찌", "rank": 2},
                 {"name": "이두리", "rank": 3}, {"name": "정효정", "rank": 4}]
        found = rule_ids(run_events([event(de=de, final=final)]), "R27")
        assert len(found) == 1
        assert found[0].severity == "WARNING"
        assert found[0].data["missing_names"] == ["정효정"]

    def test_homonym_star_marker_is_stripped(self):
        """🔴 이 정규화가 없으면 217종목이 걸린다(실측). 협회 순위표는 동명이인에
        `(*)` 를 붙이지만 대진표에는 없다."""
        de = {"bracket_size": 4, "full_bouts": [
            bout("준결승", 1, "김재원", "이두리", 15, 10),
            bout("준결승", 2, "김재원", "최네찌", 15, 12),
            bout("결승", 3, "김재원", "김재원", 15, 14),
        ]}
        final = [{"name": "김재원(*)", "rank": 1}, {"name": "김재원", "rank": 2},
                 {"name": "이두리", "rank": 3}, {"name": "최네찌", "rank": 4}]
        assert rule_ids(run_events([event(de=de, final=final)]), "R27") == []

    def test_thin_roster_is_not_judged(self):
        """로스터가 순위표의 80% 미만이면 판정하지 않는다 — 그건 순위표 문제가 아니라
        풀·DE 결손이고 R22·감사 F07/F10 담당이다. 실측: 2025 전국체육대회 남일 에뻬는
        로스터 2명 / 순위표 17명이어서 15명이 '없는 이름'으로 잡혔다."""
        de = {"bracket_size": 4, "full_bouts": [bout("결승", 1, "가", "나", 15, 10)]}
        final = [{"name": f"선수{i}", "rank": i} for i in range(1, 18)]
        assert rule_ids(run_events([event(de=de, final=final)]), "R27") == []

    def test_team_event_is_skipped(self):
        de = {"bracket_size": 4, "full_bouts": [bout("결승", 1, "A팀", "B팀", 45, 40)]}
        final = [{"name": "C팀", "rank": 1}, {"name": "D팀", "rank": 2}]
        assert rule_ids(run_events([event(name="여자 에뻬(단)", de=de, final=final)]), "R27") == []


def test_canon_player_name_strips_repeated_markers():
    assert canon_player_name("김재원(*)") == "김재원"
    assert canon_player_name("김재원(*)(*)") == "김재원"
    assert canon_player_name("  박소윤 ") == "박소윤"
    assert canon_player_name(None) == ""
    # 이름 안쪽의 괄호는 건드리지 않는다
    assert canon_player_name("GAO YIFEI") == "GAO YIFEI"


# ---------------------------------------------------------------------------
# R8 — 라운드 진행 보존법칙 (오탐 수정)
# ---------------------------------------------------------------------------

class TestR8RoundProgression:
    """🔴 2026-09-28 이전 구현은 라운드를 5칸으로 뭉쳐 비교했다.

    `get_round_category()` 가 256/128/64/32강을 모두 `t32_and_below` 에 넣으므로,
    64강과 32강을 연달아 이기고 16강을 치른 **정상 선수**가
    "~32강 승리 2회 → 16강 출전 1회 (1경기 유실)" 로 걸렸다. 전수 ERROR 3,488건이
    전부 이 형태였고, 실제 라운드 단위 비교로 바꾸자 같은 데이터에서 2건이 됐다.
    """

    def _winner_bracket(self):
        """64강 → 32강 → 16강 을 연달아 이기고 8강에서 진 선수. 완전히 정상이다."""
        return {"bracket_size": 64, "starting_round": "64강", "full_bouts": [
            bout("64강", 1, "우리선수", "상대A", 15, 10, winner="우리선수"),
            bout("32강", 2, "우리선수", "상대B", 15, 12, winner="우리선수"),
            bout("16강", 3, "우리선수", "상대C", 15, 8, winner="우리선수"),
            bout("8강", 4, "우리선수", "상대D", 11, 15, winner="상대D"),
        ]}

    def test_consecutive_wins_in_collapsed_bucket_are_not_flagged(self):
        ev = event(de=self._winner_bracket(),
                   pool_total=[{"name": "우리선수", "team": "우리클럽", "rank": 1}],
                   final=[{"name": "우리선수", "rank": 5}])
        ev2 = event(cd="EV2", de=self._winner_bracket(),
                    pool_total=[{"name": "우리선수", "team": "우리클럽", "rank": 1}],
                    final=[{"name": "우리선수", "rank": 5}])
        assert rule_ids(run_all([ev, ev2]), "R8") == []

    def test_real_gap_is_flagged(self):
        """8강을 이겼는데 4강에 없으면 실제로 경기가 유실된 것이다."""
        de = {"bracket_size": 8, "starting_round": "8강", "full_bouts": [
            bout("8강", 1, "우리선수", "상대A", 15, 10, winner="우리선수"),
            bout("8강", 2, "다른선수", "상대B", 15, 9, winner="다른선수"),
            bout("4강", 3, "다른선수", "또다른", 15, 7, winner="다른선수"),
            bout("결승", 4, "다른선수", "최종", 15, 5, winner="다른선수"),
        ]}
        ev = event(de=de, pool_total=[{"name": "우리선수", "team": "T", "rank": 1}],
                   final=[{"name": "우리선수", "rank": 5}])
        ev2 = event(cd="EV2", de=de,
                    pool_total=[{"name": "우리선수", "team": "T", "rank": 1}],
                    final=[{"name": "우리선수", "rank": 5}])
        found = [i for i in rule_ids(run_all([ev, ev2]), "R8")
                 if i.player_name == "우리선수"]
        assert found, "실제 유실을 놓쳤다"
        assert found[0].data["won_round"] == "8강"
        assert found[0].data["missing_round"] == "4강"

    def test_bye_in_next_round_counts_as_present(self):
        """부전승은 경기가 아니지만 그 라운드에 있었다는 증거다.
        빼고 세면 부전승으로 올라간 선수가 유실로 잡힌다."""
        de = {"bracket_size": 16, "starting_round": "16강", "full_bouts": [
            bout("16강", 1, "우리선수", "상대A", 15, 10, winner="우리선수"),
            bout("8강", 2, "우리선수", "", is_bye=True),
            bout("4강", 3, "우리선수", "상대C", 10, 15, winner="상대C"),
        ]}
        ev = event(de=de, pool_total=[{"name": "우리선수", "team": "T", "rank": 1}],
                   final=[{"name": "우리선수", "rank": 3}])
        ev2 = event(cd="EV2", de=de,
                    pool_total=[{"name": "우리선수", "team": "T", "rank": 1}],
                    final=[{"name": "우리선수", "rank": 3}])
        assert [i for i in rule_ids(run_all([ev, ev2]), "R8")
                if i.player_name == "우리선수"] == []

    def test_skipped_round_in_bracket_is_not_a_violation(self):
        """그 브래킷에 32강이 아예 없으면 64강 승자는 16강에 나타난다.
        라운드 이름표 순서로 +1 하면 오탐이 난다."""
        de = {"bracket_size": 64, "starting_round": "64강", "full_bouts": [
            bout("64강", 1, "우리선수", "상대A", 15, 10, winner="우리선수"),
            bout("16강", 2, "우리선수", "상대B", 12, 15, winner="상대B"),
        ]}
        ev = event(de=de, pool_total=[{"name": "우리선수", "team": "T", "rank": 1}],
                   final=[{"name": "우리선수", "rank": 9}])
        ev2 = event(cd="EV2", de=de,
                    pool_total=[{"name": "우리선수", "team": "T", "rank": 1}],
                    final=[{"name": "우리선수", "rank": 9}])
        assert [i for i in rule_ids(run_all([ev, ev2]), "R8")
                if i.player_name == "우리선수"] == []

    def test_winner_inferred_from_score_when_winner_name_absent(self):
        """winner_name 은 자주 비어 있다(실측: 한 종목 32경기 중 절반 미만만 채워짐).
        점수로 보완하지 않으면 규칙이 조용히 눈을 감는다."""
        de = {"bracket_size": 8, "starting_round": "8강", "full_bouts": [
            bout("8강", 1, "우리선수", "상대A", 15, 10),   # winner_name 없음
            bout("8강", 2, "다른선수", "상대B", 15, 9),
            bout("4강", 3, "다른선수", "또다른", 15, 7),
            bout("결승", 4, "다른선수", "최종", 15, 5),
        ]}
        ev = event(de=de, pool_total=[{"name": "우리선수", "team": "T", "rank": 1}],
                   final=[{"name": "우리선수", "rank": 5}])
        ev2 = event(cd="EV2", de=de,
                    pool_total=[{"name": "우리선수", "team": "T", "rank": 1}],
                    final=[{"name": "우리선수", "rank": 5}])
        found = [i for i in rule_ids(run_all([ev, ev2]), "R8")
                 if i.player_name == "우리선수"]
        assert found, "점수만 있고 winner_name 이 없는 경기에서 R8 이 침묵했다"


# ---------------------------------------------------------------------------
# R7 — 같은 라운드 2경기 (등급 분리)
# ---------------------------------------------------------------------------

class TestR7SeveritySplit:

    def _two_bouts_same_round(self, s2a=13, s2b=11):
        """한 라운드에 같은 이름이 2경기. 결승·준결승을 함께 둬서 **라운드 이름이 실제
        단계와 맞는 정상 브래킷**임을 분명히 한다 — 이름표가 단계를 구분하지 못하는
        소규모 브래킷(결승 라운드가 아예 없는 경우)은 `_round_labels_unreliable()` 이
        따로 걸러내므로, 그 경로와 섞이면 이 테스트의 의도가 흐려진다."""
        return {"bracket_size": 8, "starting_round": "8강", "full_bouts": [
            bout("8강", 1, "김민서", "상대A", 15, s2a, winner="김민서"),
            bout("8강", 2, "김민서", "상대B", 15, s2b, winner="김민서"),
            bout("준결승", 3, "김민서", "상대C", 15, 9, winner="김민서"),
            bout("결승", 4, "김민서", "상대D", 15, 10, winner="김민서"),
        ]}

    def test_single_team_is_error(self):
        """순위표상 소속이 하나면 동명이인으로 설명되지 않는다 → ERROR."""
        ev = event(de=self._two_bouts_same_round(),
                   pool_total=[{"name": "김민서", "team": "한클럽", "rank": 1}],
                   final=[{"name": "김민서", "rank": 1}])
        ev2 = event(cd="EV2", de=self._two_bouts_same_round(),
                    pool_total=[{"name": "김민서", "team": "한클럽", "rank": 1}],
                    final=[{"name": "김민서", "rank": 1}])
        found = rule_ids(run_all([ev, ev2]), "R7")
        assert found and all(i.severity == "ERROR" for i in found)

    def test_two_teams_is_warning(self):
        """같은 종목 순위표에 같은 이름이 서로 다른 소속으로 있으면 동명이인 2명이
        함께 출전한 것이다 — 한 라운드에 그 이름의 경기가 2개인 것은 정상이다."""
        final = [{"name": "김민서(*)", "rank": 1, "team": "가클럽"},
                 {"name": "김민서", "rank": 5, "team": "나클럽"}]
        ev = event(de=self._two_bouts_same_round(), final=final)
        ev2 = event(cd="EV2", de=self._two_bouts_same_round(), final=final)
        found = rule_ids(run_all([ev, ev2]), "R7")
        assert found and all(i.severity == "WARNING" for i in found)
        assert found[0].data["homonym_team_count"] == 2

    def test_identical_content_stays_error_even_with_homonyms(self):
        """두 경기의 선수쌍·점수가 같으면 복제된 팬텀이다 — 동명이인이 있어도 ERROR."""
        de = {"bracket_size": 8, "starting_round": "8강", "full_bouts": [
            bout("8강", 1, "김민서", "상대A", 15, 13, winner="김민서"),
            bout("8강", 2, "김민서", "상대A", 15, 13, winner="김민서"),
        ]}
        final = [{"name": "김민서(*)", "rank": 1, "team": "가클럽"},
                 {"name": "김민서", "rank": 5, "team": "나클럽"}]
        ev = event(de=de, final=final)
        ev2 = event(cd="EV2", de=de, final=final)
        found = rule_ids(run_all([ev, ev2]), "R7")
        # 내용이 동일한 두 bout 은 (라운드, 상대) 키로 합쳐지므로 R7 이 아니라
        # R1b/R1c 영역이다. R7 이 남긴다면 반드시 ERROR 여야 한다.
        assert all(i.severity == "ERROR" for i in found)


# ---------------------------------------------------------------------------
# R15 — bracket_size vs bout 수 (오탐 수정)
# ---------------------------------------------------------------------------

class TestR15BracketSize:

    def test_alias_round_name_duplicate_is_not_flagged(self):
        """🔴 실측 오탐: 4슬롯 브래킷에 '준결승 #1' 과 '4강 #1' 이 같은 경기로 두 번
        저장돼 bout 4개로 세어졌다. 부전승이라 한쪽 이름이 공란이어서 선수쌍 dedup 이
        먹지 않았다. 라운드명 정규화 후 (라운드, 번호, 선수) 로 합치면 3개다."""
        de = {"bracket_size": 4, "full_bouts": [
            bout("준결승", 1, "최정민", "", 0, 0, winner="최정민"),
            bout("준결승", 2, "윤태우", "오세훈", 9, 15),
            bout("결승", 3, "최정민", "오세훈", 15, 3),
            bout("4강", 1, "최정민", "", None, None),   # 같은 경기, 이표기
        ]}
        found = [i for i in rule_ids(run_events([event(de=de)]), "R15")
                 if i.severity == "ERROR"]
        assert found == [], f"alias 중복을 실제 경기로 셌다: {[i.message for i in found]}"

    def test_genuine_overflow_still_flagged(self):
        """정규화해도 슬롯 수를 넘으면 진짜 문제다."""
        bouts = [bout("8강", i, f"가{i}", f"나{i}", 15, 10) for i in range(1, 6)]
        found = [i for i in rule_ids(run_events([event(de={"bracket_size": 4,
                                                          "full_bouts": bouts})]), "R15")
                 if i.severity == "ERROR"]
        assert found, "실제 정원 초과를 놓쳤다"


# ---------------------------------------------------------------------------
# R19 — 이벤트 레벨 vs org_type (오탐 수정)
# ---------------------------------------------------------------------------

class TestR19OrgType:

    ORG_CACHE = {
        "채드윅송도국제학교": {"org_type": "international_school", "province": "인천"},
        "대구광역시펜싱협회": {"org_type": "association", "province": "대구"},
        "부산광역시청": {"org_type": "professional", "province": "부산"},
    }

    def _run(self, team):
        events = [event(name="중등부 여자 플러레(개)",
                        final=[{"name": "홍길동", "rank": 1, "team": team}])]
        v = DataValidator(make_comp(events), org_cache=self.ORG_CACHE)
        v.issues = []
        v._validate_all_events()
        return rule_ids(v.issues, "R19")

    def test_international_school_is_not_flagged(self):
        """국제학교는 한 학교에 K-12 가 다 있어 org_type 으로 학교급을 특정할 수 없다.
        실측 R19 WARNING 271건 중 221건이 이것이었다."""
        assert self._run("채드윅송도국제학교") == []

    def test_association_is_not_flagged(self):
        assert self._run("대구광역시펜싱협회") == []

    def test_professional_in_middle_school_event_is_still_flagged(self):
        """실업팀 소속이 중등부에 나오는 것은 실제로 의심스럽다 — 남겨 둔다."""
        found = self._run("부산광역시청")
        assert found and found[0].severity == "WARNING"


# ---------------------------------------------------------------------------
# 통합: 실측 오염 형태를 한 종목에 모아 넣고 전 규칙이 반응하는지
# ---------------------------------------------------------------------------

def test_real_world_phantom_event_triggers_the_whole_family():
    """2022 제10회 대한펜싱협회장배 고등부 여자 플러레(개) (event id 1440) 재현.

    참가자는 7명인데 bracket_size 32 이고, 빈 슬롯 12개에 '정효정' 이 양쪽으로
    복제되고 점수까지 15-1 로 똑같이 들어가 있었다.
    """
    real = [
        bout("32강", 1, "GAO YIFEI", "", is_bye=True),
        bout("32강", 2, "고윤신", "이태린"),
        bout("32강", 3, "황즈친", "장은지"),
        bout("32강", 4, "최주연", "김나율"),
    ]
    phantom = [bout("32강", i, "정효정", "정효정", 15, 1) for i in range(5, 17)]
    phantom += [bout("16강", i, "정효정", "정효정", 15, 1) for i in range(17, 29)]
    de = {"bracket_size": 32, "starting_round": "32강", "full_bouts": real + phantom}
    final = [{"name": "GAO YIFEI", "rank": 1}, {"name": "김나율", "rank": 2},
             {"name": "황즈친", "rank": 3}, {"name": "이태린", "rank": 4},
             {"name": "고윤신", "rank": 5}, {"name": "장은지", "rank": 6},
             {"name": "최주연", "rank": 7}]

    issues = run_events([event(de=de, final=final)])
    fired = {i.rule_id for i in issues if i.severity == "ERROR"}
    assert "R1a" in fired, "self-bout 미탐"
    assert "R1c" in fired, "정원 초과 미탐"
    assert "R28" in fired, "이름 뭉개짐 미탐"
    # 순위표 자체는 정상이므로 R26/R27 은 조용해야 한다
    assert rule_ids(issues, "R26") == []
    assert rule_ids(issues, "R27") == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
