"""
협회 공지 첨부(명단·교체·합산표)에서 선수 명단을 구조화하는 파서 (순수 함수)

입력은 data_kfa_notices.attachments[].text 에 저장된 평문이다. 파일을 읽지 않는다.

다루는 문서 네 종류:
  1. 명단표 (국가대표 PDF 2024·2025, 후보/23세이하/청소년 HWP 2025, 후보 PDF 2024)
     "남자사브르 / (12명) / 이름 소속 …" 이 종목별로 반복된다. PDF 는 한 줄에
     "이름 소속", HWP 는 셀마다 한 줄이라 "이름" "소속" 이 따로 온다.
  2. 교체 공문 PDF — "- 남자 사브르 2명 : 박준성(한국체육대학교), 원태영(호남대학교)"
  3. 합산 랭킹표 PDF — 페이지마다 "종목 : 여자사브르 - 2026년 …" 머리글이 있고
     행은 "순위 총점 이름 생년월일 소속 …". 페이지(\\f) 단위로 종목을 붙인다.
  4. 협회 공지가 아닌 언론·SNS 확인 명단 (MEDIA_ROSTERS 상수)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

WEAPON_MAP = {
    "사브르": "sabre", "샤브르": "sabre",
    "에뻬": "epee", "에페": "epee",
    "플러레": "foil", "플뢰레": "foil", "후로레": "foil", "플뢰레": "foil",
}
GENDER_MAP = {"남자": "남", "여자": "여", "남": "남", "여": "여"}

# 문서 제목 → roster_type. 먼저 맞는 것이 이긴다 (후보선수 문서 제목에도 '국가대표'가 들어간다)
_DOC_TYPE_RULES = [
    ("candidate_u25", ("후보선수", "25세이하")),
    ("u23", ("23세이하",)),
    ("youth", ("청소년",)),
    ("kkumnamu", ("꿈나무",)),
    ("asian_games_dispatch", ("아시안게임", "아시아경기")),
    ("national_team", ("국가대표선수명단", "국가대표선수선발명단", "국가대표명단")),
]
_HEADER_WORDS = {"직위", "종목", "성명", "소속", "비고", "선수", "이름", "연번", "번호", "No", "no"}
_TEAM_HINTS = ("청", "협회", "대학", "학교", "클럽", "공단", "부대", "체육회", "공사", "연맹", "센터", "아카데미", "펜싱")


@dataclass
class RosterEntry:
    roster_type: str
    year: Optional[int]
    weapon: str
    gender: str
    player_name: str
    team: Optional[str] = None
    seed_rank: Optional[int] = None
    note: Optional[str] = None


@dataclass
class RosterDocument:
    roster_type: Optional[str]
    year: Optional[int]
    title: str
    entries: List[RosterEntry] = field(default_factory=list)
    declared_counts: Dict[Tuple[str, str], int] = field(default_factory=dict)  # (gender, weapon) → (N명)
    declared_total: Optional[int] = None
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------

def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def parse_gender_weapon(s: str) -> Optional[Tuple[str, str]]:
    """'남자사브르', '남자 에  뻬', '여자 플러레', '남사' 같은 표기 → ('남', 'sabre')."""
    z = _squash(s)
    m = re.fullmatch(r"(남자|여자|남|여)(사브르|샤브르|에뻬|에페|플러레|플뢰레|후로레)(?:\(.*\))?", z)
    if not m:
        return None
    return GENDER_MAP[m.group(1)], WEAPON_MAP[m.group(2)]


def parse_year(s: str) -> Optional[int]:
    m = re.search(r"(20\d\d)\s*년?", s or "")
    return int(m.group(1)) if m else None


def detect_roster_type(doc_title: str) -> Optional[str]:
    z = _squash(doc_title)
    for rtype, words in _DOC_TYPE_RULES:
        if any(w in z for w in words):
            return rtype
    return None


def looks_like_name(tok: str) -> bool:
    """한글 2~6자, 숫자·괄호 없음, 소속 힌트 없음."""
    if not re.fullmatch(r"[가-힣]{2,6}", tok):
        return False
    return not any(h in tok for h in _TEAM_HINTS)


# ---------------------------------------------------------------------
# 1. 명단표 (PDF / HWP 공통)
# ---------------------------------------------------------------------

def parse_roster_document(text: str, roster_type: Optional[str] = None,
                          year: Optional[int] = None) -> RosterDocument:
    """종목 머리글로 구분된 명단표 → RosterDocument.

    roster_type / year 를 주지 않으면 첫 줄(문서 제목)에서 추정한다.
    머리글이 하나도 없으면 entries 가 비고 warnings 에 사유가 남는다 — 공문처럼
    명단이 아닌 첨부를 이 함수에 넣어도 예외는 나지 않는다.
    """
    lines = [ln.strip() for ln in (text or "").replace("\f", "\n").splitlines()]
    lines = [ln for ln in lines if ln]
    title = lines[0] if lines else ""
    doc = RosterDocument(
        roster_type=roster_type or detect_roster_type(title),
        year=year or parse_year(title),
        title=title,
    )
    if not lines:
        doc.warnings.append("빈 텍스트")
        return doc

    current: Optional[Tuple[str, str]] = None
    pending_name: Optional[str] = None
    seen_in_section: set = set()

    for ln in lines[1:]:
        z = _squash(ln)
        # 종목 머리글
        gw = parse_gender_weapon(ln)
        if gw:
            current = gw
            pending_name = None
            seen_in_section = set()
            continue
        # 머리글 뒤 "(12명)" / 총원 "선수 (48명)" / "(48명)"
        m = re.fullmatch(r"(?:선수)?\((\d+)\s*명\)", z)
        if m:
            n = int(m.group(1))
            if current and current not in doc.declared_counts:
                doc.declared_counts[current] = n
            elif not current:
                doc.declared_total = n
            continue
        if z == "선수" or z in _HEADER_WORDS:
            continue
        if re.fullmatch(r"[\s직위종목성명소속비고]+", z):
            continue
        if current is None:
            continue

        toks = ln.split()
        name, team = None, None
        if len(toks) >= 2 and looks_like_name(toks[0]):
            name, team = toks[0], " ".join(toks[1:])
            pending_name = None
        elif len(toks) == 1:
            if pending_name is None and looks_like_name(toks[0]):
                pending_name = toks[0]
                continue
            if pending_name is not None:
                name, team = pending_name, toks[0]
                pending_name = None
            else:
                continue  # 소속·비고 같은 단독 토큰
        else:
            continue

        if name in seen_in_section:
            doc.warnings.append(f"중복 이름 {name} ({current[0]} {current[1]})")
            continue
        seen_in_section.add(name)
        doc.entries.append(RosterEntry(
            roster_type=doc.roster_type or "unknown", year=doc.year,
            weapon=current[1], gender=current[0], player_name=name, team=team or None,
        ))

    # 선언 인원과 대조
    for gw, n in doc.declared_counts.items():
        got = sum(1 for e in doc.entries if (e.gender, e.weapon) == gw)
        if got != n:
            doc.warnings.append(f"{gw[0]} {gw[1]}: 선언 {n}명, 파싱 {got}명")
    if doc.declared_total is not None and doc.declared_total != len(doc.entries):
        doc.warnings.append(f"총원: 선언 {doc.declared_total}명, 파싱 {len(doc.entries)}명")
    if not doc.declared_counts and not doc.entries:
        doc.warnings.append("종목 머리글 없음 — 명단표가 아님")
    return doc


# ---------------------------------------------------------------------
# 2. 교체 공문
# ---------------------------------------------------------------------

_REPL_LINE = re.compile(
    r"[-·•]?\s*(남자|여자)\s*(사\s*브\s*르|에\s*[뻬페]|플\s*[러뢰]\s*레)\s*(?:\d+\s*명)?\s*[:：]\s*([^\n]+)"
)
_REPL_ITEM = re.compile(r"([가-힣]{2,6})\s*\(([^)]+)\)")


def parse_replacement_notice(text: str) -> List[RosterEntry]:
    """교체 선발 공문 → 교체 선발자 목록 (year 는 호출자가 채운다)."""
    out: List[RosterEntry] = []
    declared = None
    m = re.search(r"교체\s*선발\s*인원\s*[:：]\s*(\d+)\s*명", text or "")
    if m:
        declared = int(m.group(1))
    for gm in _REPL_LINE.finditer(text or ""):
        gw = parse_gender_weapon(gm.group(1) + gm.group(2))
        if not gw:
            continue
        for name, team in _REPL_ITEM.findall(gm.group(3)):
            out.append(RosterEntry(
                roster_type="national_team_replacement", year=None,
                weapon=gw[1], gender=gw[0], player_name=name, team=team.strip(),
            ))
    if declared is not None and declared != len(out):
        for e in out:
            e.note = f"공문 선언 {declared}명 ≠ 파싱 {len(out)}명"
    return out


# ---------------------------------------------------------------------
# 3. 합산 랭킹표
# ---------------------------------------------------------------------

@dataclass
class RankingRow:
    year: int
    gender: str
    weapon: str
    rank: int
    total: float
    player_name: str
    birth: Optional[str]      # 2026-10-06 표부터 협회가 생년월일을 빼고 게시한다
    team: Optional[str]


# "종목 : 여자사브르 - 2026년 …" / "종목 : 여자 사브르 - 2024년 …" (공백 유무 둘 다)
_RANK_HEADER = re.compile(
    r"종목\s*[:：]\s*(남자|여자)\s*(사\s*브\s*르|에\s*[뻬페]|플\s*[러뢰]\s*레)\s*-\s*(20\d\d)\s*년"
)
# 생년월일 칸은 **있을 때도 있고 없을 때도 있다.**
#   2026-08-26 표(10916): "1 86 최세빈 00.08.11대전광역시청 3 20 1 32 33 2 1 32"
#   2026-10-06 표(10963): "1 110 전하영 서울특별시청 1 32 1 32 2 26 3 20"   ← 생년월일 없음
# 생년월일을 필수로 두면 새 표가 **조용히 0행으로 파싱된다**(2026-10-08 실측:
# 첨부가 교체되자 합산표 자동 대조가 "표 파싱 결과 없음"으로 건너뛰었다).
_RANK_ROW = re.compile(
    r"^\s*(\d+)\s+(\d+(?:\.\d+)?)\s+([가-힣A-Za-z]{2,12})\s*(\d{2}\.\d{2}\.\d{2})?\s*(\S*)"
)


def parse_ranking_points(text: str) -> List[RankingRow]:
    """합산 랭킹표 전체 텍스트(페이지 구분 \\f) → 행 목록.

    같은 (종목, 순위, 이름, 생년월일)이 두 페이지에 걸쳐 중복되면 앞의 것을 남긴다.
    생년월일은 협회 표에 있을 때만 채운다(2026-10-06 표부터 빠졌다).
    """
    rows: List[RankingRow] = []
    seen = set()
    gw: Optional[Tuple[str, str]] = None
    year: Optional[int] = None
    for page in (text or "").split("\f"):
        hm = _RANK_HEADER.search(page)
        if hm:
            gw = parse_gender_weapon(hm.group(1) + hm.group(2))
            year = int(hm.group(3))
        # 머리글이 빠진 페이지(2024 표에 있음)는 직전 페이지의 종목을 잇는다
        if not gw or not year:
            continue
        for ln in page.splitlines():
            rm = _RANK_ROW.match(ln)
            if not rm:
                continue
            team = rm.group(5)
            if not team or team == "-" or re.fullmatch(r"[\d.]+", team):
                team = None
            # 생년월일이 없는 표에서는 (이름, 생년월일)만으로는 동명이인이 한 행으로
            # 합쳐진다 — 순위를 키에 넣어 가른다. 페이지가 겹쳐 같은 행이 두 번
            # 나오는 경우(원래 이 dedup 의 목적)는 순위도 같으므로 그대로 걸러진다.
            key = (gw, year, int(rm.group(1)), rm.group(3), rm.group(4))
            if key in seen:
                continue
            seen.add(key)
            rows.append(RankingRow(
                year=year, gender=gw[0], weapon=gw[1], rank=int(rm.group(1)),
                total=float(rm.group(2)), player_name=rm.group(3), birth=rm.group(4), team=team,
            ))
    return rows


def ranking_lookup(rows: List[RankingRow]) -> Dict[Tuple[int, str, str, str], int]:
    """(year, gender, weapon, name) → rank. 동명이인이 같은 종목에 있으면 앞선 순위."""
    out: Dict[Tuple[int, str, str, str], int] = {}
    for r in rows:
        k = (r.year, r.gender, r.weapon, r.player_name)
        if k not in out or r.rank < out[k]:
            out[k] = r.rank
    return out


# ---------------------------------------------------------------------
# 4. 협회 공지 없이 언론·SNS 로 확인한 명단
# ---------------------------------------------------------------------

_AG_NOTE = "2026 아이치·나고야 아시안게임 파견 선수단 — 협회 공지사항 미게시, 언론·SNS 확인 (2026-09-27 적재)"
_MFOIL_NOTE = "2026 국가대표 후보선수 하계합동훈련 남자 플러레 — 협회 공지 미게시, 인스타그램 @untouche_fencing 게시 기준 (2026-09-27 적재)"

MEDIA_ROSTERS: List[Dict] = [
    {"roster_type": "asian_games_dispatch", "year": 2026, "note": _AG_NOTE, "players": {
        ("남", "sabre"): ["오상욱", "도경동", "박상원", "황희근"],
        ("남", "epee"): ["박상영", "권오민", "남연호", "장효민"],
        ("남", "foil"): ["이광현", "윤정현", "임철우", "김태환"],
        ("여", "sabre"): ["전하영", "김정미", "서지연", "최세빈"],
        ("여", "epee"): ["송세라", "임태희", "이혜인", "양승혜"],
        ("여", "foil"): ["모별이", "박지희", "심소은", "이세주"],
    }},
    {"roster_type": "candidate_u25", "year": 2026, "note": _MFOIL_NOTE, "players": {
        ("남", "foil"): ["유채운", "최혁준", "임혜성", "김종식", "김시우", "최동윤", "신한빈", "김민서"],
    }},
]


def media_roster_entries() -> List[RosterEntry]:
    out: List[RosterEntry] = []
    for block in MEDIA_ROSTERS:
        for (g, w), names in block["players"].items():
            for n in names:
                out.append(RosterEntry(
                    roster_type=block["roster_type"], year=block["year"], weapon=w, gender=g,
                    player_name=n, note=block["note"],
                ))
    return out
