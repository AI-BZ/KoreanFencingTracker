"""
대한펜싱협회 공지사항 파싱·분류·첨부 텍스트 추출 (순수 함수)

네트워크·DB 를 만지지 않는다. 게시판 HTML 과 첨부 바이트를 받아
구조화된 값을 돌려주는 것까지가 이 모듈의 일이고, 가져오기·저장·알림은
scheduler/kfa_notice_monitor.py 가 한다. 그래서 여기 있는 함수는 전부
tests/ 에서 고정 문자열로 검증할 수 있다.

첨부 텍스트 규약:
    - PDF 는 페이지 경계를 \\f(form feed) 로 구분해 하나의 문자열로 만든다.
      합산 랭킹표처럼 페이지마다 머리글("종목 : 여자사브르 …")이 반복되는
      문서는 페이지 단위로 파싱해야 어느 종목의 행인지 알 수 있다.
    - HWP(5.x, OLE) 는 BodyText 레코드 중 HWPTAG_PARA_TEXT(67)만 골라
      UTF-16LE 로 풀고, 인라인 컨트롤 문자를 규격대로 건너뛴다.
      문단 하나가 한 줄이 되므로 표 셀은 각각 한 줄로 나온다.
"""
from __future__ import annotations

import html as _html
import io
import re
import struct
import zlib
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

KFA_BASE_URL = "https://fencing.sports.or.kr"
NOTICE_LIST_PATH = "/board/list?code=notice&pageNum={page}"
NOTICE_VIEW_PATH = "/board/view?code=notice&boardNo={no}&repNo=0&masterNo={no}&pageNum=1"


# =====================================================================
# 태그 분류
# =====================================================================

# 제목에 이 단어가 있으면 해당 태그. 순서는 무관하고 여러 개가 붙을 수 있다.
# (제목은 공백을 전부 지운 뒤 비교하므로 규칙 단어에도 공백을 넣지 않는다)
_TAG_RULES = {
    "candidate_u25": ("후보선수", "25세이하", "미래국가대표", "23세이하"),
    "youth": ("청소년", "유소년", "주니어", "카데트"),
    "kkumnamu": ("꿈나무",),
    "regulation": ("규정", "규칙"),  # "요강"은 대회 요강이 대부분이라 제외
    "procurement": ("견적", "입찰", "채용", "모집", "구매", "계약", "공고", "합격자", "지도자", "트레이너"),
}
# 파견 공지: '파견' 이 있거나, 대회명 + 선수단/명단/선발 조합일 때만.
# ("올림픽 공원 출입 안내", "88 서울올림픽 사진공모전" 같은 것이 걸리면 안 된다)
_DISPATCH_GAMES = ("아시안게임", "아시아경기", "올림픽", "세계선수권", "아시아선수권", "유니버시아드", "그랑프리", "월드컵")
_DISPATCH_WORDS = ("선수단", "명단", "선발", "엔트리", "출전")
# 대회 이름의 일부일 뿐인 '선발대회' 와 일정 공지는 명단 판정에서 제외한다
_SCHEDULE_WORDS = ("경기일정", "일정알림", "일정변경", "마감일", "대진표", "참가신청", "경기장안내")
_REPLACEMENT_WORDS = ("교체", "결원", "차순위", "추가선발", "추가 선발", "보충")
_RANKING_WORDS = ("합산", "랭킹", "포인트현황", "점수현황")

# 알림·명단 파싱 대상. 다른 태그와 달리 '국가대표'만으로는 부족하다 —
# "국가대표 전담팀 채용", "국가대표 후보선수 합숙 견적" 처럼 명단이 아닌 공지가
# 많아 '명단/선발' 이 함께 있어야 한다.
_NT_WORDS = ("국가대표", "대표선수")
_ROSTER_WORDS = ("명단", "선발", "선정")


def classify_tags(title: str, body: str = "") -> List[str]:
    """제목(+본문 앞부분)으로 태그 목록을 만든다. 아무것도 안 맞으면 ['other'].

    본문은 'replacement' 판정에만 쓴다. 2026-08-14 공지처럼 제목은
    "국가대표선수 선발 명단 공지"인데 본문이 "결원이 발생하여 차순위 선수를
    선발" 인 경우가 있어서, 제목만 보면 새 명단으로 오인한다.
    """
    t = _norm_title(title)
    b = re.sub(r"\s+", " ", body or "")[:800]
    tags: List[str] = []

    for tag, words in _TAG_RULES.items():
        if any(w in t for w in words):
            tags.append(tag)

    if "파견" in t or (any(g in t for g in _DISPATCH_GAMES) and any(w in t for w in _DISPATCH_WORDS)):
        tags.append("dispatch")

    t_roster = t.replace("선발대회", "").replace("선발전", "")
    is_nt = any(w in t for w in _NT_WORDS)
    is_roster = any(w in t_roster for w in _ROSTER_WORDS) and not any(w in t for w in _SCHEDULE_WORDS)
    if is_nt and any(w in t for w in _RANKING_WORDS):
        tags.append("ranking_points")
    # 국가대표 맥락에서만. 공백을 지운 제목에서 "학교체육"이 "교체"에 걸리는 식의
    # 부분 일치가 있어서, '국가대표' 없이 교체 단어만으로는 판정하지 않는다.
    if is_nt and (any(w in t for w in _REPLACEMENT_WORDS) or (is_roster and any(w in b for w in _REPLACEMENT_WORDS))):
        tags.append("replacement")
    if is_nt and is_roster and not any(x in tags for x in ("candidate_u25", "youth", "kkumnamu", "procurement", "ranking_points")):
        tags.append("national_team")

    # 규정 개정 공지가 '국가대표 선발 규정' 이라 national_team 이 같이 붙는 것을 막는다
    if "regulation" in tags and "national_team" in tags and "명단" not in t:
        tags.remove("national_team")
    # 교체 공지는 제목이 "선발 명단"이라도 새 명단이 아니다. national_team 은
    # '전체 명단 공지'만 뜻하게 해서, 태그로 거른 결과가 곧 명단 파싱 대상이 되게 한다.
    if "replacement" in tags and "national_team" in tags:
        tags.remove("national_team")

    if not tags:
        tags.append("other")
    # 순서 고정 (테스트·표시 안정성)
    order = ["national_team", "replacement", "candidate_u25", "ranking_points", "dispatch",
             "regulation", "youth", "kkumnamu", "procurement", "other"]
    return [x for x in order if x in tags]


def _norm_title(title: str) -> str:
    t = _html.unescape(title or "")
    # "에  뻬", "국가 대표" 같은 공백 삽입 표기가 흔해 공백을 전부 지우고 비교한다
    return re.sub(r"\s+", "", t)


# =====================================================================
# 게시판 HTML 파싱
# =====================================================================

@dataclass
class NoticeRow:
    board_no: int
    title: str
    posted_at: Optional[date]
    is_pinned: bool = False
    url: str = ""


@dataclass
class Attachment:
    name: str
    url: str


@dataclass
class NoticeDetail:
    board_no: int
    title: str
    posted_at: Optional[date]
    body_text: str
    attachments: List[Attachment] = field(default_factory=list)


def parse_kfa_date(s: str) -> Optional[date]:
    m = re.search(r"(20\d\d)[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})", s or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_notice_list(html: str) -> List[NoticeRow]:
    """목록 페이지 → 행 목록. 고정 공지('공지' 붉은 번호)는 is_pinned=True.

    목록 페이지가 작성일을 갖고 있으므로 날짜만 필요할 때는 상세를 안 열어도 된다.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="list")
    if not table:
        return []
    rows: List[NoticeRow] = []
    seen = set()
    for tr in table.find_all("tr"):
        a = tr.find("a", href=re.compile(r"boardNo=\d+"))
        if not a:
            continue
        m = re.search(r"boardNo=(\d+)", a["href"])
        board_no = int(m.group(1))
        if board_no in seen:
            continue
        seen.add(board_no)
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        tds = tr.find_all("td")
        pinned = bool(tds) and "공지" in tds[0].get_text(strip=True)
        posted = None
        for td in tds:
            d = parse_kfa_date(td.get_text(strip=True))
            if d and re.fullmatch(r"\s*20\d\d[.\-/]\d{1,2}[.\-/]\d{1,2}\s*", td.get_text()):
                posted = d
                break
        rows.append(NoticeRow(
            board_no=board_no, title=title, posted_at=posted, is_pinned=pinned,
            url=KFA_BASE_URL + NOTICE_VIEW_PATH.format(no=board_no),
        ))
    return rows


def parse_notice_detail(html: str, board_no: int) -> NoticeDetail:
    """상세 페이지 → 제목·작성일·본문 평문·첨부 목록."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="view")
    title, posted, body_text = "", None, ""
    attachments: List[Attachment] = []

    if table:
        th = table.find("th")
        if th:
            title = re.sub(r"\s+", " ", th.get_text(" ", strip=True)).strip()
        for td in table.find_all("td"):
            txt = td.get_text(" ", strip=True)
            if txt.startswith("작성일"):
                posted = parse_kfa_date(txt)
                break
        body = table.find("td", class_="the-body")
        if body:
            att_div = body.find("div", class_="attachment")
            if att_div:
                for a in att_div.find_all("a", href=True):
                    name = a.get("data-name") or a.get("title") or a.get_text(strip=True)
                    attachments.append(Attachment(
                        name=_html.unescape(name).strip(),
                        url=urljoin(KFA_BASE_URL, _html.unescape(a["href"])),
                    ))
                att_div.extract()
            for br in body.find_all("br"):
                br.replace_with("\n")
            body_text = body.get_text("\n", strip=True)
            body_text = re.sub(r"[ \t ]+", " ", body_text)
            body_text = re.sub(r"\n{3,}", "\n\n", body_text).strip()

    if not attachments:
        # 마크업이 바뀌어도 업로드 링크만은 살릴 수 있게 정규식 폴백
        for href, name in re.findall(
            r'<a href="(https?://fencing\.sports\.or\.kr/upload_fencing/[^"]+)"[^>]*data-name="([^"]+)"', html
        ):
            attachments.append(Attachment(name=_html.unescape(name).strip(), url=_html.unescape(href)))

    if not posted:
        m = re.search(r"작성일\s*:?\s*(20\d\d\.\d{1,2}\.\d{1,2})", html)
        posted = parse_kfa_date(m.group(1)) if m else None

    return NoticeDetail(board_no=board_no, title=title, posted_at=posted,
                        body_text=body_text, attachments=attachments)


# =====================================================================
# 첨부 텍스트 추출
# =====================================================================

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def detect_kind(data: bytes, name: str = "") -> str:
    """바이트 서명으로 종류 판별. 확장자는 믿지 않는다 — 협회는 HWP 를 .pdf 로 올린 적이 있다."""
    head = data[:8]
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(_OLE_MAGIC):
        # FileHeader 스트림은 OLE 섹터 안에 있어 앞부분 바이트 검색으로는 안 잡힌다
        try:
            import olefile
            return "hwp" if olefile.OleFileIO(io.BytesIO(data)).exists("FileHeader") else "ole"
        except Exception:  # noqa: BLE001
            return "ole"
    if head.startswith(b"PK"):
        return "hwpx" if b"Contents/" in data[:4096] or name.lower().endswith(".hwpx") else "zip"
    if head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8") or head.startswith(b"GIF8"):
        return "image"
    return "other"


def extract_text(data: bytes, name: str = "") -> Dict[str, object]:
    """첨부 바이트 → {kind, text_extracted, text, extract_note}.

    실패해도 예외를 올리지 않는다. 어떤 첨부 하나가 깨졌다고 공지 저장이
    멈추면 안 되기 때문이다. 실패 사유는 extract_note 에 남긴다.
    """
    kind = detect_kind(data, name)
    text, note = "", None
    try:
        if kind == "pdf":
            text = _pdf_text(data)
            if len(text.strip()) < 30:
                note = "PDF 에 텍스트 레이어가 거의 없음 (스캔본 가능성)"
        elif kind == "hwp":
            text = _hwp_text(data)
            note = "HWP 5.x BodyText 문단 텍스트만 추출 — 표 구조·서식은 잃음"
        elif kind == "hwpx":
            text = _hwpx_text(data)
            note = "HWPX section XML 태그 제거 방식 — 표 구조는 잃음"
        else:
            note = f"텍스트 추출 미지원 종류: {kind}"
    except Exception as e:  # noqa: BLE001 — 사유를 남기고 계속 간다
        note = f"추출 실패 ({type(e).__name__}: {str(e)[:120]})"
        text = ""
    # Postgres text 는 NUL 을 받지 않는다 (22P05) — PDF 폰트 매핑 실패분에 섞여 나온다
    text = text.replace("\x00", "")
    return {
        "kind": kind,
        "text_extracted": bool(text.strip()),
        "text": text,
        "extract_note": note,
    }


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for p in reader.pages:
        pages.append(p.extract_text() or "")
    return "\f".join(pages)


def _hwp_text(data: bytes) -> str:
    import olefile
    ole = olefile.OleFileIO(io.BytesIO(data))
    header = ole.openstream("FileHeader").read()
    compressed = bool(header[36] & 0x01)
    if header[36] & 0x02:
        raise ValueError("암호화된 HWP")
    paras: List[str] = []
    sections = sorted(
        (s for s in ole.listdir() if s and s[0] == "BodyText"),
        key=lambda s: int(re.sub(r"\D", "", s[-1]) or 0),
    )
    for s in sections:
        raw = ole.openstream(s).read()
        if compressed:
            raw = zlib.decompress(raw, -15)
        paras.extend(_hwp_para_texts(raw))
    return "\n".join(paras)


# HWP 문단 텍스트의 제어 문자(코드 0~31). 문자 컨트롤(0, 10, 13, 24~31)은 1 워드,
# 확장·인라인 컨트롤(그 외)은 자기 자신을 포함해 8 워드를 차지하므로 함께 건너뛴다.
_HWP_CTRL_1WORD = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}


def _hwp_para_texts(section: bytes) -> List[str]:
    out: List[str] = []
    i, n = 0, len(section)
    while i + 4 <= n:
        (h,) = struct.unpack_from("<I", section, i)
        tag_id, size = h & 0x3FF, (h >> 20) & 0xFFF
        i += 4
        if size == 0xFFF:
            (size,) = struct.unpack_from("<I", section, i)
            i += 4
        if tag_id == 67:  # HWPTAG_PARA_TEXT
            out.append(_hwp_decode_para(section[i:i + size]))
        i += size
    return out


def _hwp_decode_para(buf: bytes) -> str:
    units = struct.unpack("<%dH" % (len(buf) // 2), buf[: len(buf) // 2 * 2])
    chars: List[str] = []
    j = 0
    while j < len(units):
        c = units[j]
        if c < 32:
            if c in _HWP_CTRL_1WORD:
                if c in (10, 13):
                    chars.append("\n")
                j += 1
            else:
                # 확장/인라인 컨트롤: 자기 자신 + 7 워드
                if c == 9:
                    chars.append("\t")
                j += 8
            continue
        chars.append(chr(c))
        j += 1
    text = "".join(chars)
    # 서로게이트 쌍 결합 실패분·잔여 제어문자 제거
    text = text.encode("utf-16", "surrogatepass").decode("utf-16", "ignore")
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text).strip()


def _hwpx_text(data: bytes) -> str:
    import zipfile
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = sorted(n for n in zf.namelist() if re.match(r"Contents/section\d+\.xml$", n))
    parts = []
    for n in names:
        xml = zf.read(n).decode("utf-8", "ignore")
        xml = re.sub(r"</hp:p>", "\n", xml)
        xml = re.sub(r"<[^>]+>", " ", xml)
        parts.append(re.sub(r"[ \t]+", " ", _html.unescape(xml)))
    return "\n".join(parts)


def safe_filename(name: str, limit: int = 120) -> str:
    """보관용 파일명 — 경로 구분자·제어문자 제거, 길이 제한."""
    base = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name or "attachment").strip() or "attachment"
    if len(base) > limit:
        stem, dot, ext = base.rpartition(".")
        base = (stem[: limit - len(ext) - 1] + dot + ext) if dot and len(ext) <= 8 else base[:limit]
    return base


# =====================================================================
# 프로필 배지 — data_kfa_rosters 조회 (이 모듈에서 유일하게 DB 를 읽는 함수)
# =====================================================================

ROSTER_TYPE_LABELS = {
    "national_team": "국가대표",
    "national_team_replacement": "국가대표 교체선발",
    "candidate_u25": "국가대표 후보(25세이하)",
    "u23": "23세이하 대표",
    "youth": "청소년대표",
    "kkumnamu": "꿈나무",
    "asian_games_dispatch": "아시안게임 파견",
}
# roster_type 별 표시 순서 (상위 명단이 앞)
_ROSTER_TYPE_ORDER = ["asian_games_dispatch", "national_team", "national_team_replacement",
                      "candidate_u25", "u23", "youth", "kkumnamu"]
WEAPON_LABELS = {"foil": "플러레", "epee": "에뻬", "sabre": "사브르"}


def _norm_team(name: Optional[str]) -> str:
    from app.player_identity import canonical_team_name
    return re.sub(r"\s+", "", canonical_team_name(name or "") or "")


def match_rosters(rows: List[Dict], player_name: str, teams: Iterable[str]) -> List[Dict]:
    """명단 행 → 이 선수의 배지 목록 (순수 함수, 테스트 대상).

    규칙:
    - (이름, 소속) 둘 다 맞아야 한다. 소속은 공백 제거 + canonical_team_name 후 정확 일치.
      소속이 없는 행(media 에서 소속을 못 채운 경우)은 대조 불가이므로 배지를 달지 않는다
      — 동명이인 오표시가 미표시보다 나쁘다.
    - roster_type 마다 가장 최근 year 하나만.
    - source: kfa 는 공지 링크(boardNo), media 는 반드시 SNS/언론 확인분으로 구분.
    """
    my_teams = {_norm_team(t) for t in teams if t}
    my_teams.discard("")
    best: Dict[str, Dict] = {}
    for r in rows:
        if r.get("player_name") != player_name:
            continue
        team = _norm_team(r.get("team"))
        if not team or team not in my_teams:
            continue
        rt = r.get("roster_type")
        year = r.get("year") or 0
        cur = best.get(rt)
        if cur is None or year > cur["year"] or (year == cur["year"] and r.get("source_type") == "kfa"):
            best[rt] = r
    badges: List[Dict] = []
    for rt in _ROSTER_TYPE_ORDER:
        r = best.get(rt)
        if not r:
            continue
        year = r.get("year")
        label = (f"AG{year} 파견" if rt == "asian_games_dispatch"
                 else f"{year} {ROSTER_TYPE_LABELS.get(rt, rt)}")
        is_media = r.get("source_type") == "media"
        note = r.get("note") or ""
        if is_media:
            source_label = "합동훈련 명단(SNS)" if ("합동훈련" in note or "합숙" in note) else "언론·SNS 확인"
        else:
            source_label = f"협회 공지 #{r.get('source_board_no')}" if r.get("source_board_no") else "협회 공지"
        badges.append({
            "roster_type": rt,
            "year": year,
            "label": label,
            "weapon": r.get("weapon"),
            "weapon_label": WEAPON_LABELS.get(r.get("weapon"), r.get("weapon")),
            "gender": r.get("gender"),
            "team": r.get("team"),
            "seed_rank": r.get("seed_rank"),
            "source_type": r.get("source_type"),
            "source_label": source_label,
            "source_url": None if is_media else r.get("source_url"),
            "source_board_no": r.get("source_board_no"),
            "announced_at": r.get("announced_at"),
        })
    return badges


def rosters_for_player(player_name: str, teams: Iterable[str], db=None) -> List[Dict]:
    """data_kfa_rosters 에서 이 선수(이름+소속 일치)의 배지를 만든다. 실패하면 빈 목록."""
    if not player_name:
        return []
    try:
        if db is None:
            from scheduler.competition_detector import get_supabase_client
            db = get_supabase_client()
        if not db:
            return []
        res = (db.table("data_kfa_rosters")
               .select("roster_type, year, weapon, gender, player_name, team, seed_rank, "
                       "source_board_no, source_url, source_type, announced_at, note")
               .eq("player_name", player_name).execute())
        return match_rosters(res.data or [], player_name, teams)
    except Exception:  # noqa: BLE001 — 배지 조회 실패가 프로필을 막으면 안 된다
        return []
