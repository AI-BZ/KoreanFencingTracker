"""국제 결과의 로마자 선수명 ↔ players 테이블 매칭.

FIE·아시안게임 결과는 "OH Sanguk"(성 대문자 + 이름) 로 오고, players 에는
자동 로마자(`translations.en.name` = "Sanguk Oh", 국립국어원 표기)만 있다.
선수 여권 표기는 국립국어원 표기와 자주 다르다 (Sangyoung/Sangyeong,
Heegeun/Huigeun, Jihee/Jihui). 그래서 양쪽을 같은 '음운 키'로 접은 뒤 비교한다.

원칙 (제0원칙 — 추측 금지):
  * 키가 일치하는 활성 선수가 정확히 1명일 때만 player_id 를 채운다.
  * 동명이인이 여럿이면 성인 실업팀·대학 소속이 단 1명일 때만 그 사람으로 본다
    (FIE 시니어 랭킹·아시안게임은 성인 종목). 그래도 여럿이면 이름만 채우고
    player_id 는 NULL — 호출자가 목록으로 보고한다.
  * 수동 확정 표(`data/international_cache/intl_name_overrides.json`)가 있으면
    그것이 자동 매칭보다 우선한다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from loguru import logger

_OVERRIDES_PATH = Path(__file__).resolve().parent.parent / "data" / "international_cache" / "intl_name_overrides.json"

# 성인 실업팀/대학 소속 판정 — 동명이인 후보를 좁힐 때만 쓴다
_ADULT_TEAM_RE = re.compile(r"(시청|도청|구청|군청|공사|공단|국군체육부대|대학교|대학|체육회|연맹)$")

# 로마자 변형을 접는 규칙. 순서가 중요하다 (긴 패턴 먼저).
# 목적은 '같은 한글을 다르게 적은 것'을 같게 만드는 것이지 정확한 발음 복원이 아니다.
_FOLD_RULES: List[Tuple[str, str]] = [
    ("young", "yeong"), ("yung", "yeong"), ("yong", "yeong"),
    ("hyun", "hyeon"), ("kyun", "gyeon"), ("gyun", "gyeon"), ("byun", "byeon"),
    ("jung", "jeong"), ("sung", "seong"), ("chung", "jeong"), ("kyung", "gyeong"),
    ("hee", "hi"), ("hui", "hi"), ("hyee", "hi"),
    ("woo", "u"), ("oo", "u"), ("wu", "u"),
    ("eui", "i"), ("ui", "i"), ("ee", "i"), ("yi", "i"),
    ("ae", "a"), ("ai", "a"),
    ("uh", "eo"), ("eo", "eo"),
    ("ck", "g"), ("kk", "g"), ("k", "g"), ("pp", "b"), ("p", "b"), ("tt", "d"), ("t", "d"),
    ("ch", "j"), ("jj", "j"), ("sh", "s"), ("ss", "s"), ("r", "l"),
    ("wh", "w"),
]
# 'oh'/'ah' 는 위치를 가려 접는다. 무조건 접으면 Taehwan(태환)의 h 가 사라져 Taewan(태완)과
# 섞인다 (2026-09-27 김태환/김태완/김대완이 한 키로 뭉친 사례). 어두 "Oh-min"(오민),
# 어말 "Min-ah"(미나) 처럼 h 가 발음 없이 붙은 자리만 접는다.
_EDGE_H_RULES = [
    (re.compile(r"^oh(?=[^aeiouy])"), "o"), (re.compile(r"^ah(?=[^aeiouy])"), "a"),
    (re.compile(r"oh$"), "o"), (re.compile(r"ah$"), "a"),
]


# 성(姓) 변형표 — 여권 표기가 국립국어원 표기와 가장 자주 갈리는 곳이 성이다
# (IM/LIM/YIM, YOUN/YOON/YUN, ROH/NOH/NO). app.international_data.KOREAN_SURNAMES 를
# 기반으로 하고, 거기 없는 변형을 보탠다. 류/유 처럼 로마자가 겹치는 성은 한 묶음으로 접는다.
def _build_surname_table() -> Dict[str, str]:
    try:
        from app.international_data import KOREAN_SURNAMES
    except Exception:  # 단독 실행 등
        KOREAN_SURNAMES = {}
    extra = {
        "윤": ["Youn", "Yoon", "Yun"], "임": ["Lim", "Im", "Yim", "Rim"], "이": ["Lee", "Yi", "Rhee", "Li"],
        "노": ["No", "Noh", "Roh", "Ro"], "곽": ["Kwak", "Gwak", "Kwag"], "성": ["Sung", "Seong"],
        "정": ["Jung", "Jeong", "Chung", "Cheong"], "조": ["Jo", "Cho", "Joe"], "최": ["Choi", "Choe", "Choy"],
        "권": ["Kwon", "Gwon", "Kweon"], "구": ["Koo", "Ku", "Gu", "Goo"], "우": ["Woo", "Wu", "U"],
        "나": ["Na", "Ra", "La"], "라": ["Ra", "La", "Na"], "육": ["Yook", "Yuk"],
        "유": ["Yoo", "Yu", "You", "Ryu", "Ryoo", "Yoo"], "류": ["Ryu", "Ryoo", "Yoo", "Yu", "You"],
        "박": ["Park", "Pak", "Bak", "Bahk"], "김": ["Kim", "Gim", "Ghim"], "강": ["Kang", "Gang", "Khang"],
        "전": ["Jeon", "Jun", "Chun", "Jeun", "Chon"], "천": ["Cheon", "Chun", "Chon"],
        "신": ["Shin", "Sin", "Shinn"], "서": ["Seo", "Suh", "Su", "Sur"], "송": ["Song"], "황": ["Hwang", "Whang"],
        "안": ["An", "Ahn"], "오": ["Oh", "O"], "한": ["Han", "Hahn"], "홍": ["Hong"], "문": ["Moon", "Mun"],
        "양": ["Yang", "Ryang"], "손": ["Son", "Sohn"], "배": ["Bae", "Pae", "Bai"], "백": ["Baek", "Paek", "Back", "Baik"],
        "허": ["Heo", "Hur", "Huh", "Her"], "남": ["Nam"], "하": ["Ha"], "고": ["Ko", "Go", "Koh", "Goh"],
        "도": ["Do", "Doh", "To"], "모": ["Mo", "Moh"], "심": ["Shim", "Sim"], "장": ["Jang", "Chang"],
        "민": ["Min", "Minn"], "변": ["Byun", "Byeon", "Pyun"], "표": ["Pyo", "Pyoh"], "차": ["Cha"],
        "주": ["Joo", "Ju", "Chu", "Choo"], "지": ["Ji", "Jee", "Chi"], "채": ["Chae", "Chai"], "탁": ["Tak", "Tark"],
    }
    # 류·유, 나·라 처럼 로마자가 겹치는 성은 같은 그룹으로
    group = {"류": "유", "라": "나"}
    table: Dict[str, str] = {}
    for hangul, variants in list(KOREAN_SURNAMES.items()) + list(extra.items()):
        canon = group.get(hangul, hangul)
        for v in variants:
            table.setdefault(v.lower(), canon)
    return table


_SURNAME_TABLE = _build_surname_table()


def fold_surname(text: str) -> str:
    s = re.sub(r"[^a-z]", "", (text or "").lower())
    return _SURNAME_TABLE.get(s) or fold_roman(s)


def fold_roman(text: str) -> str:
    """로마자 이름 한 토막을 비교용 키로 접는다."""
    s = re.sub(r"[^a-z]", "", (text or "").lower())
    if not s:
        return ""
    for pat, dst in _EDGE_H_RULES:
        s = pat.sub(dst, s)
    for src, dst in _FOLD_RULES:
        s = s.replace(src, dst)
    return s


def split_intl_name(name: str) -> Tuple[str, str]:
    """'OH Sanguk' / 'KIRIA Tikanah Abdul Rahman' → (family, given).

    FIE·Bornan 표기는 성이 전부 대문자다. 대문자 토큰이 없으면 첫 토큰을 성으로 본다.
    """
    tokens = (name or "").replace("-", " ").split()
    if not tokens:
        return "", ""
    family = [t for t in tokens if t.isupper() and len(t) > 1]
    given = [t for t in tokens if not (t.isupper() and len(t) > 1)]
    if not family:
        family, given = tokens[:1], tokens[1:]
    return " ".join(family), " ".join(given)


def intl_name_key(name: str) -> str:
    family, given = split_intl_name(name)
    return f"{fold_surname(family)}|{fold_roman(given)}"


def db_name_keys(en_name: str) -> List[str]:
    """players.translations.en.name ('Sanguk Oh', western order) → 후보 키들.

    name_order 를 믿지 않고 두 순서를 모두 낸다. 마지막 토큰을 성으로 보는 서양식과
    첫 토큰을 성으로 보는 동양식 둘 다.
    """
    tokens = (en_name or "").replace("-", " ").split()
    if len(tokens) < 2:
        return []
    western = f"{fold_surname(tokens[-1])}|{fold_roman(''.join(tokens[:-1]))}"
    eastern = f"{fold_surname(tokens[0])}|{fold_roman(''.join(tokens[1:]))}"
    return list(dict.fromkeys([western, eastern]))


def load_overrides() -> Dict[str, Dict[str, Any]]:
    """수동 확정 표: {"OH Sanguk": {"player_name_ko": "오상욱", "player_id": 753}}"""
    try:
        if _OVERRIDES_PATH.exists():
            return json.loads(_OVERRIDES_PATH.read_text(encoding="utf-8"))
    except Exception as e:  # 표가 깨져도 자동 매칭은 계속
        logger.warning(f"intl_name_overrides.json 읽기 실패: {e}")
    return {}


class IntlPlayerMatcher:
    """players 활성 행을 한 번 읽어 키 인덱스를 만든 뒤 반복 조회한다."""

    def __init__(self, db, overrides: Optional[Dict[str, Dict[str, Any]]] = None):
        self.db = db
        self.overrides = overrides if overrides is not None else load_overrides()
        self._index: Dict[str, List[Dict[str, Any]]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        rows: List[Dict[str, Any]] = []
        start = 0
        page = 1000
        while True:
            res = (
                self.db.table("players")
                .select("id,player_name,team_name,translations,name_roman,is_active,merged_into")
                .eq("is_active", True)
                .is_("merged_into", "null")
                .range(start, start + page - 1)
                .execute()
            )
            batch = res.data or []
            rows.extend(batch)
            if len(batch) < page:
                break
            start += page
        for p in rows:
            names: List[str] = []
            tr = p.get("translations") or {}
            if isinstance(tr, str):
                try:
                    tr = json.loads(tr)
                except Exception:
                    tr = {}
            en = (tr.get("en") or {}).get("name") if isinstance(tr, dict) else None
            if en:
                names.append(en)
            if p.get("name_roman"):
                names.append(p["name_roman"])
            for n in names:
                for k in db_name_keys(n):
                    self._index.setdefault(k, []).append(p)
        self._loaded = True
        logger.info(f"IntlPlayerMatcher: 활성 선수 {len(rows)}명, 키 {len(self._index)}개")

    def match(self, intl_name: str, country: str = "KOR") -> Dict[str, Any]:
        """→ {player_name_ko, player_id, method, candidates}

        method: 'override' | 'unique' | 'adult_team' | 'ambiguous' | 'none' | 'skip'
        """
        if (country or "").upper() != "KOR":
            return {"player_name_ko": None, "player_id": None, "method": "skip", "candidates": []}
        ov = self.overrides.get(intl_name)
        if ov and ov.get("player_name_ko"):
            return {
                "player_name_ko": ov["player_name_ko"],
                "player_id": ov.get("player_id"),
                "method": "override",
                "candidates": [],
            }
        self._load()
        cands = self._index.get(intl_name_key(intl_name), [])
        # 같은 사람이 두 키(서양/동양 순서)로 들어갈 수 있으니 id 로 중복 제거
        uniq: Dict[int, Dict[str, Any]] = {c["id"]: c for c in cands}
        cands = list(uniq.values())
        summary = [{"id": c["id"], "name": c["player_name"], "team": c.get("team_name")} for c in cands]
        if not cands:
            return {"player_name_ko": None, "player_id": None, "method": "none", "candidates": []}
        if len(cands) == 1:
            c = cands[0]
            return {"player_name_ko": c["player_name"], "player_id": c["id"], "method": "unique", "candidates": summary}
        ko_names = {c["player_name"] for c in cands}
        adults = [c for c in cands if _ADULT_TEAM_RE.search(c.get("team_name") or "")]
        if len(adults) == 1:
            c = adults[0]
            return {"player_name_ko": c["player_name"], "player_id": c["id"], "method": "adult_team", "candidates": summary}
        # 한글 이름이 하나로 모이면 이름은 확정(프로필 링크 가능), id 만 미정
        name = ko_names.pop() if len(ko_names) == 1 else None
        return {"player_name_ko": name, "player_id": None, "method": "ambiguous", "candidates": summary}


def summarize_matches(results: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in results:
        out[r.get("method", "?")] = out.get(r.get("method", "?"), 0) + 1
    return out
