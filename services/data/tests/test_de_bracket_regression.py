"""저장 직전 회귀 가드 (`_de_bracket_regression`) 테스트.

이 가드는 두 방향으로 틀릴 수 있고, 둘 다 실제로 데이터를 망가뜨렸다.

  ① 너무 느슨하면 → 부분 유실이 완전 데이터를 덮어쓴다
     (2026-08-17, 2026-08-18: 예선 64강 32경기가 사라져 159→127경기)
  ② 너무 빡빡하면 → 올바른 교정본이 영구히 거부된다
     (2026-08-19: 구 파서의 팬텀 부전승·오라벨 때문에 단체전 2종목 SKIP)

그래서 양쪽을 모두 고정한다. 한쪽만 테스트하면 다음 사람이 반대쪽으로 넘어간다.
"""
import importlib.util
import os

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# scheduler/__init__.py 가 apscheduler 를 끌고 오므로 모듈 파일만 직접 로드한다.
_spec = importlib.util.spec_from_file_location(
    "_competition_detector_for_test",
    os.path.join(BASE, "scheduler", "competition_detector.py"))
_cd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cd)

regression = _cd._de_bracket_regression


def bout(p1, p2, round_name, phase=None, **kw):
    b = {"player1_name": p1, "player2_name": p2, "round_name": round_name,
         "bout_id": f"{round_name}_01"}
    if phase:
        b["de_phase"] = phase
    b.update(kw)
    return b


def single(bouts, **kw):
    return {"format": "single_de", "full_bouts": bouts, **kw}


def dual(first, second):
    return {"format": "dual_de",
            "first_de": {"full_bouts": first},
            "second_de": {"full_bouts": second}}


# ── ① 느슨하면 안 되는 쪽: 진짜 유실은 반드시 막는다 ────────────────────────

def test_실제_대결이_사라지면_거부한다():
    old = single([bout("A", "B", "8강"), bout("C", "D", "8강")])
    new = single([bout("A", "B", "8강")])
    assert regression(new, old) is not None


def test_dual_de_예선_위상이_통째로_사라지면_거부한다():
    """2026-08-18 재현 — 예선/본선이 같은 '64강' 이름을 쓰기 때문에
    위상을 신원에 넣지 않으면 32경기 유실이 눈에 띄지 않는다."""
    old = dual(
        first=[bout(f"예선{i}A", f"예선{i}B", "64강", "qualifying") for i in range(8)],
        second=[bout(f"본선{i}A", f"본선{i}B", "64강", "main") for i in range(8)])
    new = dual(first=[], second=old["second_de"]["full_bouts"])
    reason = regression(new, old)
    assert reason is not None
    assert "qualifying" in reason


def test_format_강등은_거부한다():
    old = dual(first=[bout("A", "B", "64강", "qualifying")],
               second=[bout("C", "D", "64강", "main")])
    assert regression(single([]), old) is not None


# ── ② 빡빡하면 안 되는 쪽: 정당한 교정은 통과시킨다 ─────────────────────────

def test_라운드명_재라벨만으로는_유실이_아니다():
    """구 파서가 8팀 브래킷의 첫 라운드를 '32강'으로 적어 뒀다.
    재수집이 '8강'으로 고치는 것은 교정이지 유실이 아니다."""
    old = single([bout("A", "B", "32강"), bout("C", "D", "32강")], starting_round="32강")
    new = single([bout("A", "B", "8강"), bout("C", "D", "8강")], starting_round="8강")
    assert regression(new, old) is None


def test_팬텀_부전승이_사라지는_것은_유실이_아니다():
    """구 파서는 브래킷의 참가자 표시 컬럼을 부전승 경기로 오파싱해
    참가 팀 수만큼 팬텀 항목(`..._bye_NN`, 한쪽 이름만)을 남겼다.
    부전승은 경기가 아니므로 제거돼도 유실이 아니다."""
    old = single([
        bout("A", "B", "8강"),
        {"player1_name": "A", "player2_name": None, "round_name": "8강",
         "bout_id": "8강_bye_01", "is_bye": True},
        {"player1_name": "B", "player2_name": None, "round_name": "8강",
         "bout_id": "8강_bye_02", "is_bye": True},
    ])
    new = single([bout("A", "B", "8강")])
    assert regression(new, old) is None


def test_is_bye_플래그가_없어도_한쪽이_비면_부전승으로_본다():
    """스크래퍼 경로에 따라 플래그 없이 슬롯만 비는 형태가 있다."""
    old = single([
        bout("A", "B", "8강"),
        {"player1_name": "C", "player2_name": "", "round_name": "8강", "bout_id": "8강_02"},
    ])
    new = single([bout("A", "B", "8강")])
    assert regression(new, old) is None


def test_선수쌍_순서가_바뀌어도_같은_경기다():
    old = single([bout("A", "B", "8강")])
    new = single([bout("B", "A", "8강")])
    assert regression(new, old) is None


def test_match_number_재부여는_유실이_아니다():
    """스크래퍼는 병합 후 match_number 를 브래킷 전역 연속번호로 재부여한다."""
    old = single([bout("A", "B", "8강", match_number=1)])
    new = single([bout("A", "B", "8강", match_number=17)])
    assert regression(new, old) is None


def test_기존_중복본은_새_데이터를_붙잡지_않는다():
    """풀 2배 저장 사고(2026-08-15) 계열 — 사본이 섞여도 집합은 같은 원소로 접힌다."""
    old = single([bout("A", "B", "8강"), bout("A", "B", "8강")])
    new = single([bout("A", "B", "8강")])
    assert regression(new, old) is None


def test_기존_데이터가_없으면_통과시킨다():
    assert regression(single([bout("A", "B", "8강")]), {}) is None
    assert regression(single([bout("A", "B", "8강")]), single([])) is None


@pytest.mark.parametrize("phase", ["qualifying", "main"])
def test_같은_위상_안에서는_라운드가_달라도_같은_선수쌍이면_같은_경기(phase):
    """단일 제거 토너먼트에서 한 위상 안에 같은 선수쌍이 두 번 편성되는 일은 없다."""
    old = dual(first=[bout("A", "B", "64강", phase)] if phase == "qualifying" else [],
               second=[bout("A", "B", "64강", phase)] if phase == "main" else [])
    new = dual(first=[bout("A", "B", "32강", phase)] if phase == "qualifying" else [],
               second=[bout("A", "B", "32강", phase)] if phase == "main" else [])
    assert regression(new, old) is None
