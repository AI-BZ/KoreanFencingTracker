"""저장 직전 유령 브래킷 가드(`_de_phantom_bracket_issues`)와
종목 스크래핑 재시도 헬퍼(`_fetch_event_results_with_retry`) 테스트.

배경 (2026-09-28 DB 감사): 88종목의 full_bouts에 player1_name == player2_name 인
'유령 경기'가 저장돼 있었다 (예: event_id=1440, '정효정' 대 '정효정'이 8강~32강에
match_number 1~16으로 반복, 실제로는 8명이 뛴 브래킷이 46경기로 부풀어 있었다).
_de_bracket_regression() 은 '있었는데 없어졌다'만 보므로 첫 스크랩/신규 오염은
못 잡는다 — 이 가드는 새 데이터 자체의 구조적 모순만 본다.

이 테스트는 두 방향을 모두 고정한다 (test_de_bracket_regression.py 와 같은 원칙):
  ① 너무 느슨하면 → 유령 경기가 그대로 저장된다
  ② 너무 빡빡하면 → 정상적인 Dual DE(예선/본선이 같은 라운드명을 공유)를 오탐한다
"""
import asyncio
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

phantom_issues = _cd._de_phantom_bracket_issues
fetch_with_retry = _cd._fetch_event_results_with_retry


def bout(p1, p2, round_name, match_number=1, s1=None, s2=None, is_bye=False, **kw):
    b = {
        "player1_name": p1,
        "player2_name": p2,
        "round_name": round_name,
        "match_number": match_number,
        "player1_score": s1,
        "player2_score": s2,
        "is_bye": is_bye,
    }
    b.update(kw)
    return b


def seed(name, n=1):
    return {"seed": n, "name": name}


def single(bouts, seeding=None):
    d = {"format": "single_de", "full_bouts": bouts}
    if seeding is not None:
        d["seeding"] = seeding
    return d


def dual(first_bouts, second_bouts, first_seeding=None, second_seeding=None):
    first = {"full_bouts": first_bouts}
    if first_seeding is not None:
        first["seeding"] = first_seeding
    second = {"full_bouts": second_bouts}
    if second_seeding is not None:
        second["seeding"] = second_seeding
    return {"format": "dual_de", "first_de": first, "second_de": second}


# ── ① 느슨하면 안 되는 쪽: 진짜 오염은 반드시 막는다 ────────────────────────

def test_자기경기가_있으면_거부한다():
    de = single([
        bout("고윤신", "이태린", "32강", match_number=2, s1=8, s2=15),
        bout("정효정", "정효정", "16강", match_number=1),  # 유령 경기
    ], seeding=[seed("고윤신", 1), seed("이태린", 2)])
    issues = phantom_issues(de)
    assert issues
    assert any("자기경기" in i for i in issues)


def test_실제_사고_재현_event_1440_46경기_중_38건이_정효정_유령():
    """실제 DB(event_id=1440)에서 관측된 패턴의 축약 재현.

    실제로는 8명(부전승 1명 포함 32강 진출자 기준)이 뛴 8강제 브래킷인데,
    '정효정' 자기경기가 여러 라운드에 match_number를 늘려가며 반복 저장돼
    46경기로 부풀어 있었다. 여기서는 실제 대결 7개 + 유령 10개로 축약한다.
    """
    real = [
        bout("GAO YIFEI", None, "32강", match_number=1, is_bye=True),
        bout("고윤신", "이태린", "32강", match_number=2, s1=8, s2=15),
        bout("황즈친", "장은지", "32강", match_number=3, s1=15, s2=4),
        bout("최주연", "김나율", "32강", match_number=4, s1=1, s2=15),
        bout("GAO YIFEI", "이태린", "준결승", match_number=1, s1=15, s2=4),
        bout("황즈친", "김나율", "준결승", match_number=2, s1=3, s2=15),
        bout("GAO YIFEI", "김나율", "결승", match_number=1, s1=15, s2=11),
    ]
    ghosts = [
        bout("정효정", "정효정", "16강", match_number=n, s1=(15 if n > 4 else None), s2=(1 if n > 4 else None))
        for n in range(1, 11)
    ]
    de = single(real + ghosts, seeding=[seed(n, i) for i, n in enumerate(
        ["GAO YIFEI", "고윤신", "이태린", "황즈친", "장은지", "최주연", "김나율"], start=1)])
    issues = phantom_issues(de)
    assert issues
    assert any("자기경기" in i and "10건" in i for i in issues)


def test_경기수_과다는_차단하지_않고_경고로만_남긴다():
    """경기 수 과다는 advisory 다 — 저장을 막지 않는다 (2026-09-28 결정).

    기존 DB 2,070종목에 차단 규칙으로 돌려보니 자기경기가 전혀 없는 정상 종목
    122건(5.9%)이 걸렸다. 3-4위전이 있는 대회(경기 수 = n)와 seeding 불완전 종목이
    섞여 있어, 차단하면 진행 중 대회의 정상 갱신이 조용히 멈춘다. 확실한 오염 신호
    (자기경기)만 차단하고 경기 수는 사람이 볼 경고로 남긴다.
    """
    # seeding 3명 → 허용치 3건(n−1 + 3-4위전 1). 초과는 +3건 이상일 때만 경고.
    de = single([
        bout(f"P{i}", f"Q{i}", "8강", match_number=i, s1=15, s2=1) for i in range(10)
    ], seeding=[seed("A", 1), seed("B", 2), seed("C", 3)])
    issues = phantom_issues(de)
    assert list(issues) == []                      # 저장은 허용
    assert any("경기 수 과다" in a for a in issues.advisories)


def test_3_4위전이_있는_대회는_경기수_경고도_내지_않는다():
    """n−1 + 1경기(3-4위전)는 정상이다. 2020 국가대표 선발전이 그 형태였다."""
    bouts = [bout(f"P{i}", f"Q{i}", "8강", match_number=i, s1=15, s2=1) for i in range(8)]
    de = single(bouts, seeding=[seed(f"S{i}", i) for i in range(1, 9)])
    issues = phantom_issues(de)
    assert list(issues) == []
    assert issues.advisories == []


# ── ② 빡빡하면 안 되는 쪽: 정상 Dual DE는 절대 오탐하지 않는다 ──────────────

def test_정상_단일_DE는_통과한다():
    de = single([
        bout("A", "B", "준결승", match_number=1, s1=15, s2=10),
        bout("C", "D", "준결승", match_number=2, s1=15, s2=10),
        bout("A", "C", "결승", match_number=1, s1=15, s2=13),
    ], seeding=[seed(n, i) for i, n in enumerate(["A", "B", "C", "D"], start=1)])
    assert phantom_issues(de) == []


def test_예선_64강과_본선_64강이_같은_이름이어도_오탐하지_않는다():
    """Dual DE는 예선/본선이 둘 다 '64강'을 갖는다 — 위상별 독립 검사가 핵심."""
    # 예선: 32명 시드, 64강(32경기) + 32강(16경기) = 48건, 상한 31 이내
    first_bouts = [bout(f"Q{i}A", f"Q{i}B", "64강", match_number=i, s1=15, s2=10) for i in range(20)]
    first_seeding = [seed(f"S{i}", i) for i in range(1, 33)]
    # 본선: 32명 시드, 64강(다른 선수들) + 이후 라운드, 상한 31 이내
    second_bouts = [bout(f"M{i}A", f"M{i}B", "64강", match_number=i, s1=15, s2=10) for i in range(20)]
    second_seeding = [seed(f"T{i}", i) for i in range(1, 33)]
    de = dual(first_bouts, second_bouts, first_seeding, second_seeding)
    assert phantom_issues(de) == []


def test_한쪽_위상만_오염돼도_잡아내고_라벨을_구분한다():
    first_bouts = [
        bout("정효정", "정효정", "64강", match_number=1),
        bout("A", "B", "64강", match_number=2, s1=15, s2=10),
    ]
    second_bouts = [bout("C", "D", "결승", match_number=1, s1=15, s2=10)]
    de = dual(first_bouts, second_bouts,
              first_seeding=[seed("A", 1), seed("B", 2)],
              second_seeding=[seed("C", 1), seed("D", 2)])
    issues = phantom_issues(de)
    assert any("예선" in i for i in issues)
    assert not any("본선" in i for i in issues)


def test_부전승은_경기_수에_포함되지_않는다():
    # 부전승 다수 + 실제 대결 소수 — is_bye 로 표시된 것은 상한 계산에서 빠져야 한다
    bouts = [bout(f"P{i}", None, "16강", match_number=i, is_bye=True) for i in range(10)]
    bouts.append(bout("A", "B", "16강", match_number=99, s1=15, s2=10))
    de = single(bouts, seeding=[seed("A", 1), seed("B", 2)])
    # seeding 2명 기준 상한 1건인데 실제 대결은 1건 → 통과해야 한다
    assert phantom_issues(de) == []


def test_빈_브래킷은_통과한다():
    assert phantom_issues({}) == []
    assert phantom_issues(None) == []
    assert phantom_issues(single([])) == []


# ── 재시도 헬퍼 ──────────────────────────────────────────────────────────

class _FakeScraper:
    def __init__(self, outcomes):
        # outcomes: 호출마다 반환할 값 또는 raise할 예외의 리스트
        self._outcomes = list(outcomes)
        self.calls = 0

    async def get_full_results(self, comp_idx, sub_event_cd, page_num=1):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_재시도_첫시도_성공하면_바로_반환():
    scraper = _FakeScraper([{"pool_rounds": []}])

    async def _run():
        return await fetch_with_retry(scraper, "c1", "e1", "종목1", max_retries=2, base_delay=0)

    result = asyncio.run(_run())
    assert result == {"pool_rounds": []}
    assert scraper.calls == 1


def test_재시도_두번_실패후_성공():
    scraper = _FakeScraper([
        TimeoutError("timeout 1"),
        TimeoutError("timeout 2"),
        {"pool_rounds": ["ok"]},
    ])

    async def _run():
        return await fetch_with_retry(scraper, "c1", "e1", "종목1", max_retries=2, base_delay=0)

    result = asyncio.run(_run())
    assert result == {"pool_rounds": ["ok"]}
    assert scraper.calls == 3


def test_재시도_상한_넘으면_예외_전파():
    scraper = _FakeScraper([
        TimeoutError("timeout 1"),
        TimeoutError("timeout 2"),
        TimeoutError("timeout 3"),
    ])

    async def _run():
        return await fetch_with_retry(scraper, "c1", "e1", "종목1", max_retries=2, base_delay=0)

    with pytest.raises(TimeoutError):
        asyncio.run(_run())
    assert scraper.calls == 3  # 최초 1회 + 재시도 2회
