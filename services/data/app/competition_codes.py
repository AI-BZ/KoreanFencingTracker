"""
FencingMind Competition Code System
===================================

대회 코드 형식: {Country}{Type}{Level}{Location}{Year}{Month}{Days}
예시: KoNaA1Yg26Ja1422

- Ko = 국가 (Korea)
- Na = 국가대표선발전 (대회 유형)
- A1 = 대회 레벨
- Yg = 양구 (장소)
- 26 = 연도 (2026)
- Ja = 월 (January)
- 1422 = 개최일 (14~22)

총 16자리 코드로 대회를 고유하게 식별 (첫 글자 대문자)
"""

from typing import Dict, Optional, Tuple, List, Union
from dataclasses import dataclass
from datetime import date
from enum import Enum


# =============================================================================
# 1. COUNTRY CODES (국가 코드) - 2자리, ISO 3166-1 기반
# =============================================================================

class CountryCode(str, Enum):
    """국가 코드 - ISO 3166-1 alpha-2 기반 (첫 글자 대문자)"""
    # 아시아
    Ko = "Ko"  # 대한민국 (Korea)
    Jp = "Jp"  # 일본 (Japan)
    Cn = "Cn"  # 중국 (China)
    Tw = "Tw"  # 대만 (Taiwan)
    Hk = "Hk"  # 홍콩 (Hong Kong)
    Sg = "Sg"  # 싱가포르 (Singapore)
    Th = "Th"  # 태국 (Thailand)
    My = "My"  # 말레이시아 (Malaysia)
    Ph = "Ph"  # 필리핀 (Philippines)
    Id = "Id"  # 인도네시아 (Indonesia)
    Vn = "Vn"  # 베트남 (Vietnam)
    In = "In"  # 인도 (India)

    # 유럽
    Fr = "Fr"  # 프랑스 (France)
    It = "It"  # 이탈리아 (Italy)
    De = "De"  # 독일 (Germany)
    Hu = "Hu"  # 헝가리 (Hungary)
    Pl = "Pl"  # 폴란드 (Poland)
    Ru = "Ru"  # 러시아 (Russia)
    Ua = "Ua"  # 우크라이나 (Ukraine)
    Ro = "Ro"  # 루마니아 (Romania)
    Es = "Es"  # 스페인 (Spain)
    Gb = "Gb"  # 영국 (Great Britain)
    At = "At"  # 오스트리아 (Austria)
    Ch = "Ch"  # 스위스 (Switzerland)
    Nl = "Nl"  # 네덜란드 (Netherlands)
    Be = "Be"  # 벨기에 (Belgium)
    Se = "Se"  # 스웨덴 (Sweden)
    Fi = "Fi"  # 핀란드 (Finland)
    Dk = "Dk"  # 덴마크 (Denmark)
    No = "No"  # 노르웨이 (Norway)
    Gr = "Gr"  # 그리스 (Greece)
    Pt = "Pt"  # 포르투갈 (Portugal)
    Cz = "Cz"  # 체코 (Czech Republic)
    Sk = "Sk"  # 슬로바키아 (Slovakia)

    # 아메리카
    Us = "Us"  # 미국 (United States)
    Ca = "Ca"  # 캐나다 (Canada)
    Mx = "Mx"  # 멕시코 (Mexico)
    Br = "Br"  # 브라질 (Brazil)
    Ar = "Ar"  # 아르헨티나 (Argentina)
    Cu = "Cu"  # 쿠바 (Cuba)
    Ve = "Ve"  # 베네수엘라 (Venezuela)
    Co = "Co"  # 콜롬비아 (Colombia)
    Cl = "Cl"  # 칠레 (Chile)
    Pe = "Pe"  # 페루 (Peru)

    # 오세아니아
    Au = "Au"  # 호주 (Australia)
    Nz = "Nz"  # 뉴질랜드 (New Zealand)

    # 아프리카
    Eg = "Eg"  # 이집트 (Egypt)
    Za = "Za"  # 남아프리카공화국 (South Africa)
    Tn = "Tn"  # 튀니지 (Tunisia)
    Ma = "Ma"  # 모로코 (Morocco)

    # 국제대회
    Xx = "Xx"  # 국제/다국적 (International)


COUNTRY_NAMES: Dict[str, str] = {
    "Ko": "대한민국",
    "Jp": "일본",
    "Cn": "중국",
    "Tw": "대만",
    "Hk": "홍콩",
    "Sg": "싱가포르",
    "Th": "태국",
    "My": "말레이시아",
    "Ph": "필리핀",
    "Id": "인도네시아",
    "Vn": "베트남",
    "In": "인도",
    "Fr": "프랑스",
    "It": "이탈리아",
    "De": "독일",
    "Hu": "헝가리",
    "Pl": "폴란드",
    "Ru": "러시아",
    "Ua": "우크라이나",
    "Ro": "루마니아",
    "Es": "스페인",
    "Gb": "영국",
    "At": "오스트리아",
    "Ch": "스위스",
    "Nl": "네덜란드",
    "Be": "벨기에",
    "Se": "스웨덴",
    "Fi": "핀란드",
    "Dk": "덴마크",
    "No": "노르웨이",
    "Gr": "그리스",
    "Pt": "포르투갈",
    "Cz": "체코",
    "Sk": "슬로바키아",
    "Us": "미국",
    "Ca": "캐나다",
    "Mx": "멕시코",
    "Br": "브라질",
    "Ar": "아르헨티나",
    "Cu": "쿠바",
    "Ve": "베네수엘라",
    "Co": "콜롬비아",
    "Cl": "칠레",
    "Pe": "페루",
    "Au": "호주",
    "Nz": "뉴질랜드",
    "Eg": "이집트",
    "Za": "남아프리카공화국",
    "Tn": "튀니지",
    "Ma": "모로코",
    "Xx": "국제대회",
}


# =============================================================================
# 2. COMPETITION TYPE CODES (대회 유형 코드) - 2자리
# =============================================================================

class CompetitionType(str, Enum):
    """대회 유형 코드 (첫 글자 대문자)"""
    # 국내 대회 유형 (한국)
    Na = "Na"  # 국가대표선발전 (National Selection)
    Op = "Op"  # 오픈대회 (Open Tournament)
    Ch = "Ch"  # 전국체전 (National Sports Festival)
    Pr = "Pr"  # 대통령배/회장배 (President/Chairman Cup)
    Rk = "Rk"  # 랭킹대회 (Ranking Tournament)
    Cl = "Cl"  # 클럽대회 (Club Tournament)
    Sc = "Sc"  # 학교대회 (School Tournament)
    Lg = "Lg"  # 리그전 (League)
    Fr = "Fr"  # 친선대회 (Friendly Match)

    # 연령별 대회
    Yo = "Yo"  # 유소년대회 (Youth)
    Ju = "Ju"  # 주니어대회 (Junior)
    Ca = "Ca"  # 카데대회 (Cadet)
    Sr = "Sr"  # 시니어대회 (Senior)
    Vt = "Vt"  # 베테랑대회 (Veteran)

    # 학교급 대회
    El = "El"  # 초등부대회 (Elementary)
    Ms = "Ms"  # 중등부대회 (Middle School)
    Hs = "Hs"  # 고등부대회 (High School)
    Un = "Un"  # 대학대회 (University)

    # 국제대회
    Wc = "Wc"  # 월드컵 (World Cup)
    Gp = "Gp"  # 그랑프리 (Grand Prix)
    Wh = "Wh"  # 세계선수권 (World Championship)
    Og = "Og"  # 올림픽 (Olympics)
    Ag = "Ag"  # 아시안게임 (Asian Games)
    Ac = "Ac"  # 아시아선수권 (Asian Championship)
    Zo = "Zo"  # 존 대회 (Zone Competition)
    Sa = "Sa"  # 새틀라이트 (Satellite)
    In = "In"  # 국제오픈 (International Open)


COMPETITION_TYPE_NAMES: Dict[str, str] = {
    # 국내 대회
    "Na": "국가대표선발전",
    "Op": "오픈대회",
    "Ch": "전국체전",
    "Pr": "회장배/대통령배",
    "Rk": "랭킹대회",
    "Cl": "클럽대회",
    "Sc": "학교대회",
    "Lg": "리그전",
    "Fr": "친선대회",
    # 연령별
    "Yo": "유소년대회",
    "Ju": "주니어대회",
    "Ca": "카데대회",
    "Sr": "시니어대회",
    "Vt": "베테랑대회",
    # 학교급
    "El": "초등부대회",
    "Ms": "중등부대회",
    "Hs": "고등부대회",
    "Un": "대학대회",
    # 국제대회
    "Wc": "월드컵",
    "Gp": "그랑프리",
    "Wh": "세계선수권",
    "Og": "올림픽",
    "Ag": "아시안게임",
    "Ac": "아시아선수권",
    "Zo": "존 대회",
    "Sa": "새틀라이트",
    "In": "국제오픈",
}


# =============================================================================
# 3. COMPETITION LEVEL CODES (대회 레벨 코드) - 2자리
# =============================================================================

class CompetitionLevel(str, Enum):
    """대회 레벨/등급"""
    # A급 (최상위)
    A1 = "A1"  # A급 1티어 (올림픽, 세계선수권)
    A2 = "A2"  # A급 2티어 (월드컵, 그랑프리)
    A3 = "A3"  # A급 3티어 (아시안게임, 대륙선수권)

    # B급 (상위)
    B1 = "B1"  # B급 1티어 (국가대표선발전, 전국체전)
    B2 = "B2"  # B급 2티어 (회장배, 랭킹대회)
    B3 = "B3"  # B급 3티어 (지역 랭킹대회)

    # C급 (중급)
    C1 = "C1"  # C급 1티어 (전국규모 오픈)
    C2 = "C2"  # C급 2티어 (지역규모 오픈)
    C3 = "C3"  # C급 3티어 (소규모 오픈)

    # D급 (초급)
    D1 = "D1"  # D급 1티어 (클럽 대항전)
    D2 = "D2"  # D급 2티어 (친선대회)
    D3 = "D3"  # D급 3티어 (내부 경기)

    # 특수
    X1 = "X1"  # 비공식 대회
    X2 = "X2"  # 연습 경기


LEVEL_DESCRIPTIONS: Dict[str, str] = {
    "A1": "A급 1티어 (올림픽, 세계선수권)",
    "A2": "A급 2티어 (월드컵, 그랑프리)",
    "A3": "A급 3티어 (아시안게임, 대륙선수권)",
    "B1": "B급 1티어 (국가대표선발전, 전국체전)",
    "B2": "B급 2티어 (회장배, 랭킹대회)",
    "B3": "B급 3티어 (지역 랭킹대회)",
    "C1": "C급 1티어 (전국규모 오픈)",
    "C2": "C급 2티어 (지역규모 오픈)",
    "C3": "C급 3티어 (소규모 오픈)",
    "D1": "D급 1티어 (클럽 대항전)",
    "D2": "D급 2티어 (친선대회)",
    "D3": "D급 3티어 (내부 경기)",
    "X1": "비공식 대회",
    "X2": "연습 경기",
}

# 레벨별 포인트 배수 (랭킹 포인트 계산용)
LEVEL_POINT_MULTIPLIER: Dict[str, float] = {
    "A1": 10.0,
    "A2": 8.0,
    "A3": 6.0,
    "B1": 5.0,
    "B2": 4.0,
    "B3": 3.0,
    "C1": 2.5,
    "C2": 2.0,
    "C3": 1.5,
    "D1": 1.0,
    "D2": 0.5,
    "D3": 0.25,
    "X1": 0.0,
    "X2": 0.0,
}


# =============================================================================
# 4. LOCATION CODES (장소 코드) - 2자리
# =============================================================================

class LocationCode(str, Enum):
    """개최 장소 코드 - 한국 주요 도시/지역 (첫 글자 대문자)"""
    # 서울/수도권
    Se = "Se"  # 서울 (Seoul)
    Ic = "Ic"  # 인천 (Incheon)
    Gg = "Gg"  # 경기 (Gyeonggi)
    Sw = "Sw"  # 수원 (Suwon)
    Sn = "Sn"  # 성남 (Seongnam)
    Gy = "Gy"  # 고양 (Goyang)
    Yi = "Yi"  # 용인 (Yongin)
    Hn = "Hn"  # 하남 (Hanam)

    # 강원권
    Gw = "Gw"  # 강원 (Gangwon)
    Cc = "Cc"  # 춘천 (Chuncheon)
    Wj = "Wj"  # 원주 (Wonju)
    Yg = "Yg"  # 양구 (Yanggu)
    Pyc = "Pyc"  # 평창 (Pyeongchang)
    Gn = "Gn"  # 강릉 (Gangneung)

    # 충청권
    Dj = "Dj"  # 대전 (Daejeon)
    Sj = "Sj"  # 세종 (Sejong)
    Cn = "Cn"  # 충남 (Chungnam)
    Cb = "Cb"  # 충북 (Chungbuk)
    Cj = "Cj"  # 청주 (Cheongju)
    Ca = "Ca"  # 천안 (Cheonan)

    # 전라권
    Gwj = "Gwj"  # 광주 (Gwangju)
    Jn = "Jn"  # 전남 (Jeonnam)
    Jb = "Jb"  # 전북 (Jeonbuk)
    Jj = "Jj"  # 전주 (Jeonju)
    Ik = "Ik"  # 익산 (Iksan)
    Ys = "Ys"  # 여수 (Yeosu)
    Mp = "Mp"  # 목포 (Mokpo)

    # 경상권
    Bs = "Bs"  # 부산 (Busan)
    Dg = "Dg"  # 대구 (Daegu)
    Us = "Us"  # 울산 (Ulsan)
    Gns = "Gns"  # 경남 (Gyeongnam)
    Gb = "Gb"  # 경북 (Gyeongbuk)
    Cw = "Cw"  # 창원 (Changwon)
    Ph = "Ph"  # 포항 (Pohang)
    Gh = "Gh"  # 김해 (Gimhae)
    Gc = "Gc"  # 경주 (Gyeongju)

    # 제주
    Jju = "Jju"  # 제주 (Jeju)
    Sgp = "Sgp"  # 서귀포 (Seogwipo)

    # 해외 주요 도시
    Pr = "Pr"  # 파리 (Paris)
    Tk = "Tk"  # 도쿄 (Tokyo)
    Bp = "Bp"  # 부다페스트 (Budapest)
    Ml = "Ml"  # 밀라노 (Milan)
    Ny = "Ny"  # 뉴욕 (New York)
    La = "La"  # 로스앤젤레스 (Los Angeles)
    Ln = "Ln"  # 런던 (London)
    Bj = "Bj"  # 베이징 (Beijing)
    Sh = "Sh"  # 상하이 (Shanghai)
    Db = "Db"  # 두바이 (Dubai)
    Sgs = "Sgs"  # 싱가포르 (Singapore)
    Ts = "Ts"  # 타슈켄트 (Tashkent)

    # 기타
    Xx = "Xx"  # 미정/기타 (Unknown)
    On = "On"  # 온라인 (Online)


LOCATION_NAMES: Dict[str, str] = {
    # 서울/수도권
    "Se": "서울",
    "Ic": "인천",
    "Gg": "경기",
    "Sw": "수원",
    "Sn": "성남",
    "Gy": "고양",
    "Yi": "용인",
    "Hn": "하남",
    # 강원권
    "Gw": "강원",
    "Cc": "춘천",
    "Wj": "원주",
    "Yg": "양구",
    "Pyc": "평창",
    "Gn": "강릉",
    # 충청권
    "Dj": "대전",
    "Sj": "세종",
    "Cn": "충남",
    "Cb": "충북",
    "Cj": "청주",
    "Ca": "천안",
    # 전라권
    "Gwj": "광주",
    "Jn": "전남",
    "Jb": "전북",
    "Jj": "전주",
    "Ik": "익산",
    "Ys": "여수",
    "Mp": "목포",
    # 경상권
    "Bs": "부산",
    "Dg": "대구",
    "Us": "울산",
    "Gns": "경남",
    "Gb": "경북",
    "Cw": "창원",
    "Ph": "포항",
    "Gh": "김해",
    "Gc": "경주",
    # 제주
    "Jju": "제주",
    "Sgp": "서귀포",
    # 해외
    "Pr": "파리",
    "Tk": "도쿄",
    "Bp": "부다페스트",
    "Ml": "밀라노",
    "Ny": "뉴욕",
    "La": "로스앤젤레스",
    "Ln": "런던",
    "Bj": "베이징",
    "Sh": "상하이",
    "Db": "두바이",
    "Sgs": "싱가포르",
    "Ts": "타슈켄트",
    # 기타
    "Xx": "미정",
    "On": "온라인",
}


# =============================================================================
# 5. MONTH CODES (월 코드) - 2자리
# =============================================================================

class MonthCode(str, Enum):
    """월 코드 - 영어 약자 기반 (첫 글자 대문자)"""
    Ja = "Ja"  # January (1월)
    Fe = "Fe"  # February (2월)
    Mr = "Mr"  # March (3월)
    Ap = "Ap"  # April (4월)
    My = "My"  # May (5월)
    Jn = "Jn"  # June (6월)
    Jl = "Jl"  # July (7월)
    Au = "Au"  # August (8월)
    Sp = "Sp"  # September (9월)
    Oc = "Oc"  # October (10월)
    Nv = "Nv"  # November (11월)
    Dc = "Dc"  # December (12월)


MONTH_CODES: Dict[int, str] = {
    1: "Ja",
    2: "Fe",
    3: "Mr",
    4: "Ap",
    5: "My",
    6: "Jn",
    7: "Jl",
    8: "Au",
    9: "Sp",
    10: "Oc",
    11: "Nv",
    12: "Dc",
}

MONTH_NAMES: Dict[str, Tuple[int, str]] = {
    "Ja": (1, "1월"),
    "Fe": (2, "2월"),
    "Mr": (3, "3월"),
    "Ap": (4, "4월"),
    "My": (5, "5월"),
    "Jn": (6, "6월"),
    "Jl": (7, "7월"),
    "Au": (8, "8월"),
    "Sp": (9, "9월"),
    "Oc": (10, "10월"),
    "Nv": (11, "11월"),
    "Dc": (12, "12월"),
}


# =============================================================================
# 6. DATA CLASSES
# =============================================================================

@dataclass
class CompetitionCodeParts:
    """파싱된 대회 코드 구성 요소"""
    country: str           # 국가 코드 (2자리)
    comp_type: str         # 대회 유형 (2자리)
    level: str             # 대회 레벨 (2자리)
    location: str          # 장소 코드 (2자리)
    year: int              # 연도 (2자리 숫자)
    month: str             # 월 코드 (2자리)
    start_day: int         # 시작일 (2자리 숫자)
    end_day: int           # 종료일 (2자리 숫자)

    # 해석된 값
    country_name: str = ""
    comp_type_name: str = ""
    level_description: str = ""
    location_name: str = ""
    month_number: int = 0
    month_name: str = ""
    full_year: int = 0

    def __post_init__(self):
        """초기화 후 해석된 값 설정"""
        self.country_name = COUNTRY_NAMES.get(self.country, "알 수 없음")
        self.comp_type_name = COMPETITION_TYPE_NAMES.get(self.comp_type, "알 수 없음")
        self.level_description = LEVEL_DESCRIPTIONS.get(self.level, "알 수 없음")
        self.location_name = LOCATION_NAMES.get(self.location, "알 수 없음")

        if self.month in MONTH_NAMES:
            self.month_number, self.month_name = MONTH_NAMES[self.month]

        # 2자리 연도를 4자리로 변환 (20xx 또는 19xx)
        if self.year >= 50:
            self.full_year = 1900 + self.year
        else:
            self.full_year = 2000 + self.year

    @property
    def date_range_str(self) -> str:
        """날짜 범위 문자열"""
        if self.start_day == self.end_day:
            return f"{self.full_year}년 {self.month_number}월 {self.start_day}일"
        return f"{self.full_year}년 {self.month_number}월 {self.start_day}~{self.end_day}일"

    @property
    def start_date(self) -> Optional[date]:
        """시작 날짜 객체"""
        try:
            return date(self.full_year, self.month_number, self.start_day)
        except ValueError:
            return None

    @property
    def end_date(self) -> Optional[date]:
        """종료 날짜 객체"""
        try:
            return date(self.full_year, self.month_number, self.end_day)
        except ValueError:
            return None

    @property
    def display_name(self) -> str:
        """표시용 대회명"""
        return f"{self.full_year} {self.location_name} {self.comp_type_name}"

    @property
    def point_multiplier(self) -> float:
        """랭킹 포인트 배수"""
        return LEVEL_POINT_MULTIPLIER.get(self.level, 1.0)

    def to_dict(self) -> Dict:
        """딕셔너리로 변환"""
        return {
            "code": generate_competition_code(
                self.country, self.comp_type, self.level,
                self.location, self.year, self.month,
                self.start_day, self.end_day
            ),
            "country": self.country,
            "country_name": self.country_name,
            "comp_type": self.comp_type,
            "comp_type_name": self.comp_type_name,
            "level": self.level,
            "level_description": self.level_description,
            "location": self.location,
            "location_name": self.location_name,
            "year": self.year,
            "full_year": self.full_year,
            "month": self.month,
            "month_number": self.month_number,
            "month_name": self.month_name,
            "start_day": self.start_day,
            "end_day": self.end_day,
            "date_range": self.date_range_str,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "display_name": self.display_name,
            "point_multiplier": self.point_multiplier,
        }


# =============================================================================
# 7. CODE GENERATION & PARSING FUNCTIONS
# =============================================================================

def generate_competition_code(
    country: str,
    comp_type: str,
    level: str,
    location: str,
    year: int,
    month: Union[str, int],
    start_day: int,
    end_day: int
) -> str:
    """
    대회 코드 생성

    Args:
        country: 국가 코드 (예: "Ko", "Jp")
        comp_type: 대회 유형 코드 (예: "Na", "Op")
        level: 대회 레벨 (예: "A1", "B2")
        location: 장소 코드 (예: "Ya", "Se")
        year: 연도 (2자리 또는 4자리)
        month: 월 코드 (예: "Ja") 또는 월 숫자 (1-12)
        start_day: 시작일 (1-31)
        end_day: 종료일 (1-31)

    Returns:
        16자리 대회 코드 (예: "KoNaA1Ya26Ja1422")
    """
    # 연도 처리 (4자리 -> 2자리)
    if year >= 100:
        year = year % 100

    # 월 처리 (숫자 -> 코드)
    if isinstance(month, int):
        if month not in MONTH_CODES:
            raise ValueError(f"Invalid month: {month}")
        month = MONTH_CODES[month]

    # 유효성 검사
    if country not in COUNTRY_NAMES:
        raise ValueError(f"Invalid country code: {country}")
    if comp_type not in COMPETITION_TYPE_NAMES:
        raise ValueError(f"Invalid competition type: {comp_type}")
    if level not in LEVEL_DESCRIPTIONS:
        raise ValueError(f"Invalid level: {level}")
    if location not in LOCATION_NAMES:
        raise ValueError(f"Invalid location: {location}")
    if month not in MONTH_NAMES:
        raise ValueError(f"Invalid month code: {month}")
    if not (1 <= start_day <= 31):
        raise ValueError(f"Invalid start day: {start_day}")
    if not (1 <= end_day <= 31):
        raise ValueError(f"Invalid end day: {end_day}")
    # Note: start_day > end_day is valid for cross-month competitions
    # e.g., Aug 30 ~ Sep 5 → month=Aug, days="3005"

    # 날짜 4자리 포맷 (DDDD)
    days = f"{start_day:02d}{end_day:02d}"

    return f"{country}{comp_type}{level}{location}{year:02d}{month}{days}"


def parse_competition_code(code: str) -> CompetitionCodeParts:
    """
    대회 코드 파싱

    Args:
        code: 16자리 대회 코드 (예: "KoNaA1Ya26Ja1422")

    Returns:
        CompetitionCodeParts 객체

    Raises:
        ValueError: 잘못된 코드 형식
    """
    if len(code) != 16:
        raise ValueError(f"Invalid code length: {len(code)} (expected 16)")

    try:
        country = code[0:2]    # Ko
        comp_type = code[2:4]  # Na
        level = code[4:6]      # A1
        location = code[6:8]   # Ya
        year = int(code[8:10]) # 26
        month = code[10:12]    # Ja
        start_day = int(code[12:14])  # 14
        end_day = int(code[14:16])    # 22
    except (IndexError, ValueError) as e:
        raise ValueError(f"Failed to parse code '{code}': {e}")

    # 유효성 검사
    if country not in COUNTRY_NAMES:
        raise ValueError(f"Unknown country code: {country}")
    if comp_type not in COMPETITION_TYPE_NAMES:
        raise ValueError(f"Unknown competition type: {comp_type}")
    if level not in LEVEL_DESCRIPTIONS:
        raise ValueError(f"Unknown level: {level}")
    if location not in LOCATION_NAMES:
        raise ValueError(f"Unknown location: {location}")
    if month not in MONTH_NAMES:
        raise ValueError(f"Unknown month code: {month}")

    return CompetitionCodeParts(
        country=country,
        comp_type=comp_type,
        level=level,
        location=location,
        year=year,
        month=month,
        start_day=start_day,
        end_day=end_day
    )


def generate_code_from_date(
    country: str,
    comp_type: str,
    level: str,
    location: str,
    start_date: date,
    end_date: Optional[date] = None
) -> str:
    """
    날짜 객체로부터 대회 코드 생성

    Args:
        country: 국가 코드
        comp_type: 대회 유형 코드
        level: 대회 레벨
        location: 장소 코드
        start_date: 시작 날짜
        end_date: 종료 날짜 (없으면 start_date와 동일)

    Returns:
        16자리 대회 코드
    """
    if end_date is None:
        end_date = start_date

    return generate_competition_code(
        country=country,
        comp_type=comp_type,
        level=level,
        location=location,
        year=start_date.year,
        month=start_date.month,
        start_day=start_date.day,
        end_day=end_date.day
    )


def validate_code(code: str) -> Tuple[bool, Optional[str]]:
    """
    대회 코드 유효성 검사

    Args:
        code: 검사할 대회 코드

    Returns:
        (유효 여부, 오류 메시지 또는 None)
    """
    try:
        parse_competition_code(code)
        return True, None
    except ValueError as e:
        return False, str(e)


def search_codes(
    country: Optional[str] = None,
    comp_type: Optional[str] = None,
    level: Optional[str] = None,
    location: Optional[str] = None,
    year: Optional[int] = None
) -> Dict[str, List[str]]:
    """
    조건에 맞는 코드 옵션 검색

    Args:
        country: 국가 코드 필터
        comp_type: 대회 유형 필터
        level: 레벨 필터
        location: 장소 필터
        year: 연도 필터

    Returns:
        사용 가능한 코드 옵션 딕셔너리
    """
    result = {
        "countries": list(COUNTRY_NAMES.keys()),
        "comp_types": list(COMPETITION_TYPE_NAMES.keys()),
        "levels": list(LEVEL_DESCRIPTIONS.keys()),
        "locations": list(LOCATION_NAMES.keys()),
        "months": list(MONTH_CODES.values()),
    }

    # 필터 적용
    if country:
        result["countries"] = [c for c in result["countries"] if c == country]
    if comp_type:
        result["comp_types"] = [t for t in result["comp_types"] if t == comp_type]
    if level:
        result["levels"] = [l for l in result["levels"] if l == level]
    if location:
        result["locations"] = [l for l in result["locations"] if l == location]

    return result


# =============================================================================
# 8. UTILITY FUNCTIONS
# =============================================================================

def get_all_countries() -> Dict[str, str]:
    """모든 국가 코드와 이름 반환"""
    return COUNTRY_NAMES.copy()


def get_all_competition_types() -> Dict[str, str]:
    """모든 대회 유형 코드와 이름 반환"""
    return COMPETITION_TYPE_NAMES.copy()


def get_all_levels() -> Dict[str, str]:
    """모든 대회 레벨과 설명 반환"""
    return LEVEL_DESCRIPTIONS.copy()


def get_all_locations() -> Dict[str, str]:
    """모든 장소 코드와 이름 반환"""
    return LOCATION_NAMES.copy()


def get_korean_locations() -> Dict[str, str]:
    """한국 내 장소만 반환"""
    korean_prefixes = ["Se", "Ic", "Gg", "Sw", "Sn", "Gy", "Yi", "Hn",
                       "Gw", "Cc", "Wj", "Yg", "Pyc", "Gn",
                       "Dj", "Sj", "Cn", "Cb", "Cj", "Ca",
                       "Gwj", "Jn", "Jb", "Jj", "Ik", "Ys", "Mp",
                       "Bs", "Dg", "Us", "Gns", "Gb", "Cw", "Ph", "Gh", "Gc",
                       "Jju", "Sgp"]
    return {k: v for k, v in LOCATION_NAMES.items() if k in korean_prefixes}


def get_international_locations() -> Dict[str, str]:
    """해외 장소만 반환"""
    intl_prefixes = ["Pr", "Tk", "Bp", "Ml", "Ny", "La", "Ln", "Bj", "Sh", "Db", "Sgs", "Ts"]
    return {k: v for k, v in LOCATION_NAMES.items() if k in intl_prefixes}


def format_code_for_display(code: str) -> str:
    """
    대회 코드를 읽기 쉬운 형식으로 포맷

    Args:
        code: 16자리 대회 코드

    Returns:
        포맷된 문자열 (예: "Ko-Na-A1-Ya-26-Ja-1422")
    """
    if len(code) != 16:
        return code

    return f"{code[0:2]}-{code[2:4]}-{code[4:6]}-{code[6:8]}-{code[8:10]}-{code[10:12]}-{code[12:16]}"


def infer_competition_type(comp_name: str) -> str:
    """
    대회명으로부터 대회 유형 추론

    Args:
        comp_name: 대회명

    Returns:
        추론된 대회 유형 코드 (첫 글자 대문자)
    """
    name_lower = comp_name.lower()

    # 국제대회
    if "올림픽" in comp_name or "olympic" in name_lower:
        return "Og"
    if "세계선수권" in comp_name or "world championship" in name_lower:
        return "Wh"
    if "월드컵" in comp_name or "world cup" in name_lower:
        return "Wc"
    if "그랑프리" in comp_name or "grand prix" in name_lower:
        return "Gp"
    if "아시안게임" in comp_name or "asian game" in name_lower:
        return "Ag"
    if "아시아선수권" in comp_name or "asian championship" in name_lower:
        return "Ac"

    # 국내 대회
    if "국가대표" in comp_name or "국대선발" in comp_name:
        return "Na"
    if "전국체전" in comp_name:
        return "Ch"
    if "회장배" in comp_name or "대통령배" in comp_name:
        return "Pr"
    if "랭킹" in comp_name or "ranking" in name_lower:
        return "Rk"

    # 연령별
    if "유소년" in comp_name or "youth" in name_lower:
        return "Yo"
    if "주니어" in comp_name or "junior" in name_lower:
        return "Ju"
    if "카데" in comp_name or "cadet" in name_lower:
        return "Ca"
    if "시니어" in comp_name or "senior" in name_lower:
        return "Sr"
    if "베테랑" in comp_name or "veteran" in name_lower:
        return "Vt"

    # 학교급
    if "초등" in comp_name or "elementary" in name_lower:
        return "El"
    if "중등" in comp_name or "middle school" in name_lower:
        return "Ms"
    if "고등" in comp_name or "high school" in name_lower:
        return "Hs"
    if "대학" in comp_name or "university" in name_lower or "collegiate" in name_lower:
        return "Un"

    # 기본값
    return "Op"  # 오픈대회


def infer_level_from_type(comp_type: str) -> str:
    """
    대회 유형으로부터 기본 레벨 추론

    Args:
        comp_type: 대회 유형 코드 (첫 글자 대문자)

    Returns:
        추론된 대회 레벨
    """
    level_mapping = {
        # A급
        "Og": "A1",  # 올림픽
        "Wh": "A1",  # 세계선수권
        "Wc": "A2",  # 월드컵
        "Gp": "A2",  # 그랑프리
        "Ag": "A3",  # 아시안게임
        "Ac": "A3",  # 아시아선수권

        # B급
        "Na": "B1",  # 국가대표선발전
        "Ch": "B1",  # 전국체전
        "Pr": "B2",  # 회장배
        "Rk": "B2",  # 랭킹대회

        # C급
        "Op": "C1",  # 오픈
        "In": "C1",  # 국제오픈
        "Ju": "C2",  # 주니어
        "Ca": "C2",  # 카데
        "Yo": "C2",  # 유소년
        "Sr": "C2",  # 시니어
        "Vt": "C3",  # 베테랑

        # D급
        "Cl": "D1",  # 클럽대회
        "Sc": "D2",  # 학교대회
        "Fr": "D2",  # 친선대회
        "Lg": "D1",  # 리그전
    }

    return level_mapping.get(comp_type, "C2")  # 기본값


# =============================================================================
# 9. EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    # 코드 생성 예시 (첫 글자 대문자)
    code = generate_competition_code(
        country="Ko",
        comp_type="Na",
        level="A1",
        location="Yg",
        year=2026,
        month=1,  # 또는 "Ja"
        start_day=14,
        end_day=22
    )
    print(f"Generated code: {code}")  # KoNaA1Yg26Ja1422
    print(f"Formatted: {format_code_for_display(code)}")  # Ko-Na-A1-Yg-26-Ja-1422

    # 코드 파싱 예시
    parsed = parse_competition_code("KoNaA1Yg26Ja1422")
    print(f"\nParsed code:")
    print(f"  Country: {parsed.country_name}")
    print(f"  Type: {parsed.comp_type_name}")
    print(f"  Level: {parsed.level_description}")
    print(f"  Location: {parsed.location_name}")
    print(f"  Date: {parsed.date_range_str}")
    print(f"  Display name: {parsed.display_name}")
    print(f"  Point multiplier: {parsed.point_multiplier}")

    # date 객체로 생성 예시
    from datetime import date
    code2 = generate_code_from_date(
        country="Ko",
        comp_type="Op",
        level="C1",
        location="Ik",
        start_date=date(2025, 3, 15),
        end_date=date(2025, 3, 17)
    )
    print(f"\nFrom date: {code2}")  # KoOpC1Ik25Mr1517

    # 유효성 검사
    is_valid, error = validate_code("KoNaA1Yg26Ja1422")
    print(f"\nValidation: valid={is_valid}, error={error}")

    # 대회명에서 유형 추론
    comp_type = infer_competition_type("2026 국가대표 1차 선발전")
    print(f"\nInferred type: {comp_type} ({COMPETITION_TYPE_NAMES[comp_type]})")

    # 전체 딕셔너리 출력
    print(f"\nTo dict: {parsed.to_dict()}")
