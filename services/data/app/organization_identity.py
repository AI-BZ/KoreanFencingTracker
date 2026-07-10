"""
조직(팀) 식별 시스템 - ID 체계 및 영문 이름 관리

ID 체계:
- 국가코드 (2글자 ISO): KO(한국), JP(일본), CN(중국), TW(대만), HK(홍콩), SG(싱가포르) 등
- 조직유형: C(클럽), M(중학교), H(고등학교), V(대학교), A(실업팀/시청/기업)
- 예: KOC0001 = 한국 클럽 0001, KOH0015 = 한국 고등학교 0015
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from enum import Enum


class CountryCode(Enum):
    """국가 코드 (2글자 ISO 스타일)"""
    KOREA = "KO"
    JAPAN = "JP"
    CHINA = "CN"
    TAIWAN = "TW"
    HONGKONG = "HK"
    SINGAPORE = "SG"
    THAILAND = "TH"
    VIETNAM = "VN"
    PHILIPPINES = "PH"
    MALAYSIA = "MY"
    INDONESIA = "ID"
    # 추가 국가는 여기에


class OrganizationType(Enum):
    """조직 유형"""
    CLUB = "C"           # 클럽/동호회
    ELEMENTARY = "E"     # 초등학교
    MIDDLE_SCHOOL = "M"  # 중학교
    HIGH_SCHOOL = "H"    # 고등학교
    UNIVERSITY = "V"     # 대학교 (Varsity)
    PROFESSIONAL = "A"   # 실업팀/시청/기업 (Adult/Professional)
    NATIONAL = "N"       # 국가대표/협회
    UNKNOWN = "X"        # 분류 불가


# 한국 조직 유형 판별 패턴 (순서 중요! 긴 패턴/구체적 패턴 우선)
# 각 항목: (regex_pattern, OrganizationType)
# _detect_org_type()이 이 리스트를 순서대로 매칭하여 첫 히트 반환
ORG_TYPE_PATTERNS: list = [
    # --- 0단계: OB(졸업생/동문) — 대학교 패턴보다 먼저 매칭 ---
    (r'OB$|OB\b', OrganizationType.CLUB),  # "고려대학교OB" → club (졸업생 팀)

    # --- 1단계: 부속학교 (대학교+고등학교 조합) ---
    (r'부속고등학교|부속중학교|부속초등학교|부속고|부속중|부설고|부설중', None),  # 아래에서 세분화

    # --- 2단계: 전체 단어 학교 (substring 안전) ---
    (r'초등학교|초교', OrganizationType.ELEMENTARY),
    (r'중학교|중학', OrganizationType.MIDDLE_SCHOOL),
    (r'고등학교|고등|체육고|예술고|과학고|외고|국제고|자사고|특목고|국제학교', OrganizationType.HIGH_SCHOOL),
    (r'대학교|대학', OrganizationType.UNIVERSITY),

    # --- 3단계: 행정기관/실업팀 (클럽보다 먼저, 단 체육회+클럽은 클럽 우선) ---
    (r'체육회.*클럽|체육회.*아카데미|체육회.*도장', OrganizationType.CLUB),  # "안산시체육회 상록펜싱클럽" → club
    (r'시청|군청|구청|도청|체육회|체육부대', OrganizationType.PROFESSIONAL),
    (r'공사|공단|은행|보험|증권|카드|전력|가스|통신|철도|항공', OrganizationType.PROFESSIONAL),
    (r'삼성|현대|LG|SK|롯데|포스코|KT|CJ', OrganizationType.PROFESSIONAL),

    # --- 4단계: 국가대표/협회 (단, 협회클럽은 클럽 우선) ---
    (r'협회클럽', OrganizationType.CLUB),  # "수원시펜싱협회클럽" → club
    (r'국가대표|대표팀|협회|연맹', OrganizationType.NATIONAL),

    # --- 5단계: 클럽 키워드 (한글 + 영문) ---
    (r'클럽|스포츠클럽|스포츠단|스포츠스쿨|아카데미|도장|체육관|센터|랩|LAB|FC|SC|가르드', OrganizationType.CLUB),
    (r'(?i)CLUB|FENCING\s*CLUB', OrganizationType.CLUB),  # 영문 클럽명
    (r'(?i)INTERNATIONAL\s*SCHOOL|SCHOOL', OrganizationType.HIGH_SCHOOL),  # 국제학교

    # --- 6단계 (최후 fallback): 단일글자 + $ anchor ---
    # "중원대학교"가 "중$"에 매칭되지 않도록 끝글자만 검사
    (r'여중$|남중$', OrganizationType.MIDDLE_SCHOOL),
    (r'여고$|남고$', OrganizationType.HIGH_SCHOOL),
    (r'중$', OrganizationType.MIDDLE_SCHOOL),
    (r'고$', OrganizationType.HIGH_SCHOOL),
    (r'대$', OrganizationType.UNIVERSITY),
]

# 부속학교 세분화 매핑
_BUSOK_TYPE_MAP = {
    '부속고등학교': OrganizationType.HIGH_SCHOOL,
    '부속고': OrganizationType.HIGH_SCHOOL,
    '부설고': OrganizationType.HIGH_SCHOOL,
    '부속중학교': OrganizationType.MIDDLE_SCHOOL,
    '부속중': OrganizationType.MIDDLE_SCHOOL,
    '부설중': OrganizationType.MIDDLE_SCHOOL,
    '부속초등학교': OrganizationType.ELEMENTARY,
}


def detect_org_type(name: str) -> OrganizationType:
    """조직 유형 감지 (공용 함수 — player_identity.py에서도 사용 가능)

    우선순위: 부속학교 → 전체단어 학교 → 행정기관 → 클럽 → 단일글자 fallback
    """
    if not name:
        return OrganizationType.UNKNOWN

    # 검증된 매핑 우선
    if name in VERIFIED_ORG_MAPPINGS:
        return VERIFIED_ORG_MAPPINGS[name]["type"]

    for pattern, org_type in ORG_TYPE_PATTERNS:
        m = re.search(pattern, name)
        if m:
            if org_type is None:
                # 부속학교: 매칭된 텍스트로 세분화
                matched = m.group(0)
                for key, busok_type in _BUSOK_TYPE_MAP.items():
                    if key in matched:
                        return busok_type
                return OrganizationType.HIGH_SCHOOL  # default busok
            return org_type

    return OrganizationType.UNKNOWN


# 하위 호환: 기존 dict도 유지 (외부 코드에서 참조할 수 있음)
KOREAN_ORG_TYPE_KEYWORDS = {
    OrganizationType.MIDDLE_SCHOOL: ["중학교", "중학", "여중", "남중"],
    OrganizationType.HIGH_SCHOOL: ["고등학교", "고등", "여고", "남고", "체육고", "예술고", "과학고", "외고", "국제고", "자사고", "특목고"],
    OrganizationType.UNIVERSITY: ["대학교", "대학"],
    OrganizationType.PROFESSIONAL: ["시청", "군청", "구청", "도청", "체육회", "공사", "공단", "은행", "보험", "증권", "카드", "전력", "가스", "통신", "철도", "항공", "삼성", "현대", "LG", "SK", "롯데", "포스코", "KT", "CJ"],
    OrganizationType.CLUB: ["클럽", "펜싱클럽", "펜싱", "스포츠클럽", "FC", "SC", "아카데미", "도장", "체육관", "센터", "랩", "LAB", "가르드"],
    OrganizationType.NATIONAL: ["국가대표", "대표팀", "협회", "연맹"],
}

# 영문 변환용 학교/조직 키워드
KOREAN_TO_ENGLISH_ORG = {
    # 학교 유형
    "중학교": "Middle School",
    "여자중학교": "Girls' Middle School",
    "남자중학교": "Boys' Middle School",
    "고등학교": "High School",
    "여자고등학교": "Girls' High School",
    "남자고등학교": "Boys' High School",
    "체육고등학교": "Sports High School",
    "예술고등학교": "Arts High School",
    "과학고등학교": "Science High School",
    "외국어고등학교": "Foreign Language High School",
    "산업고등학교": "Technical High School",
    "원예고등학교": "Horticultural High School",
    "대학교": "University",
    "대학": "University",

    # 행정구역
    "광역시청": "Metropolitan City Hall",
    "광역시": "Metropolitan City",
    "특별시청": "Special City Hall",
    "특별시": "Special City",

    # 조직 유형
    "시청": "City Hall",
    "군청": "County Office",
    "구청": "District Office",
    "도청": "Provincial Office",
    "체육회": "Sports Council",
    "펜싱클럽": "Fencing Club",
    "펜싱아카데미": "Fencing Academy",
    "펜싱코리아클럽": "Fencing Korea Club",
    "펜싱코리아": "Fencing Korea",
    "펜싱협회": "Fencing Association",
    "펜싱부": "Fencing Team",
    "펜싱": "Fencing",
    "클럽": "Club",
    "스포츠클럽": "Sports Club",
    "스포츠과학고등학교": "Sports Science High School",
    "스포츠단": "Sports Team",
    "스포츠": "Sports",
    "아카데미": "Academy",
    "센터": "Center",
    "인터내셔널": "International",
    "국제": "International",
    "트레이닝센터": "Training Center",
    "협회": "Association",
    "연맹": "Federation",
    "주니어펜싱클럽": "Junior Fencing Club",
    "거점스포츠클럽": "Regional Sports Club",
}

# 지역명 영문 변환
KOREAN_REGIONS = {
    # 특별시/광역시
    "서울": "Seoul",
    "부산": "Busan",
    "대구": "Daegu",
    "인천": "Incheon",
    "광주": "Gwangju",
    "대전": "Daejeon",
    "울산": "Ulsan",
    "세종": "Sejong",

    # 도
    "경기": "Gyeonggi",
    "강원": "Gangwon",
    "충북": "Chungbuk",
    "충남": "Chungnam",
    "전북": "Jeonbuk",
    "전남": "Jeonnam",
    "경북": "Gyeongbuk",
    "경남": "Gyeongnam",
    "제주": "Jeju",

    # 주요 도시
    "수원": "Suwon",
    "성남": "Seongnam",
    "용인": "Yongin",
    "고양": "Goyang",
    "안양": "Anyang",
    "안산": "Ansan",
    "청주": "Cheongju",
    "천안": "Cheonan",
    "전주": "Jeonju",
    "포항": "Pohang",
    "창원": "Changwon",
    "김해": "Gimhae",
    "진주": "Jinju",
    "양산": "Yangsan",
    "구미": "Gumi",
    "경주": "Gyeongju",
    "거제": "Geoje",
    "통영": "Tongyeong",
    "사천": "Sacheon",
    "밀양": "Miryang",
    "함안": "Haman",
    "거창": "Geochang",
    "합천": "Hapcheon",
    "의령": "Uiryeong",
    "하동": "Hadong",
    "산청": "Sancheong",
    "남해": "Namhae",
    "함양": "Hamyang",
    "목포": "Mokpo",
    "여수": "Yeosu",
    "순천": "Suncheon",
    "나주": "Naju",
    "광양": "Gwangyang",
    "군산": "Gunsan",
    "익산": "Iksan",
    "정읍": "Jeongeup",
    "남원": "Namwon",
    "김제": "Gimje",
    "완주": "Wanju",
    "안동": "Andong",
    "영주": "Yeongju",
    "영천": "Yeongcheon",
    "상주": "Sangju",
    "문경": "Mungyeong",
    "경산": "Gyeongsan",
    "칠곡": "Chilgok",
    "예천": "Yecheon",
    "봉화": "Bonghwa",
    "울진": "Uljin",
    "영덕": "Yeongdeok",
    "청도": "Cheongdo",
    "고령": "Goryeong",
    "성주": "Seongju",
    "원주": "Wonju",
    "춘천": "Chuncheon",
    "강릉": "Gangneung",
    "동해": "Donghae",
    "태백": "Taebaek",
    "속초": "Sokcho",
    "삼척": "Samcheok",
    "홍천": "Hongcheon",
    "횡성": "Hoengseong",
    "영월": "Yeongwol",
    "평창": "Pyeongchang",
    "정선": "Jeongseon",
    "철원": "Cheorwon",
    "화천": "Hwacheon",
    "양구": "Yanggu",
    "인제": "Inje",
    "고성": "Goseong",
    "양양": "Yangyang",
    "충주": "Chungju",
    "제천": "Jecheon",
    "보은": "Boeun",
    "옥천": "Okcheon",
    "영동": "Yeongdong",
    "증평": "Jeungpyeong",
    "진천": "Jincheon",
    "괴산": "Goesan",
    "음성": "Eumseong",
    "단양": "Danyang",
    "공주": "Gongju",
    "보령": "Boryeong",
    "아산": "Asan",
    "서산": "Seosan",
    "논산": "Nonsan",
    "계룡": "Gyeryong",
    "당진": "Dangjin",
    "금산": "Geumsan",
    "부여": "Buyeo",
    "서천": "Seocheon",
    "청양": "Cheongyang",
    "홍성": "Hongseong",
    "예산": "Yesan",
    "태안": "Taean",
    "서귀포": "Seogwipo",

    # 서울 구
    "강남": "Gangnam",
    "강동": "Gangdong",
    "강북": "Gangbuk",
    "강서": "Gangseo",
    "관악": "Gwanak",
    "광진": "Gwangjin",
    "구로": "Guro",
    "금천": "Geumcheon",
    "노원": "Nowon",
    "도봉": "Dobong",
    "동대문": "Dongdaemun",
    "동작": "Dongjak",
    "마포": "Mapo",
    "서대문": "Seodaemun",
    "서초": "Seocho",
    "성동": "Seongdong",
    "성북": "Seongbuk",
    "송파": "Songpa",
    "양천": "Yangcheon",
    "영등포": "Yeongdeungpo",
    "용산": "Yongsan",
    "은평": "Eunpyeong",
    "종로": "Jongno",
    "중구": "Jung-gu",
    "중랑": "Jungnang",

    # 학교 이름에 자주 사용되는 한글 단어
    "호성": "Hoseong",
    "제일": "Jeil",
    "동래": "Dongnae",
    "원예": "Wonye",
    "신언": "Sineon",
    "경덕": "Gyeongdeok",
    "목동": "Mokdong",
    "압구정": "Apgujeong",
    "송도": "Songdo",
    "최병철": "Choibyeongcheol",
}

# 검증된 조직 영문명 (수동 매핑)
VERIFIED_ORG_MAPPINGS: Dict[str, dict] = {
    # 대학교
    "서울대학교": {"name_en": "Seoul National University", "type": OrganizationType.UNIVERSITY},
    "연세대학교": {"name_en": "Yonsei University", "type": OrganizationType.UNIVERSITY},
    "고려대학교": {"name_en": "Korea University", "type": OrganizationType.UNIVERSITY},
    "한국체육대학교": {"name_en": "Korea National Sport University", "type": OrganizationType.UNIVERSITY},
    "중앙대학교": {"name_en": "Chung-Ang University", "type": OrganizationType.UNIVERSITY},
    "성균관대학교": {"name_en": "Sungkyunkwan University", "type": OrganizationType.UNIVERSITY},
    "단국대학교": {"name_en": "Dankook University", "type": OrganizationType.UNIVERSITY},
    "원광대학교": {"name_en": "Wonkwang University", "type": OrganizationType.UNIVERSITY},
    "호원대학교": {"name_en": "Howon University", "type": OrganizationType.UNIVERSITY},
    "용인대학교": {"name_en": "Yongin University", "type": OrganizationType.UNIVERSITY},
    "경희대학교": {"name_en": "Kyung Hee University", "type": OrganizationType.UNIVERSITY},
    "한양대학교": {"name_en": "Hanyang University", "type": OrganizationType.UNIVERSITY},
    "동국대학교": {"name_en": "Dongguk University", "type": OrganizationType.UNIVERSITY},
    "건국대학교": {"name_en": "Konkuk University", "type": OrganizationType.UNIVERSITY},
    "인하대학교": {"name_en": "Inha University", "type": OrganizationType.UNIVERSITY},
    "부산대학교": {"name_en": "Pusan National University", "type": OrganizationType.UNIVERSITY},
    "경북대학교": {"name_en": "Kyungpook National University", "type": OrganizationType.UNIVERSITY},
    "전남대학교": {"name_en": "Chonnam National University", "type": OrganizationType.UNIVERSITY},
    "충남대학교": {"name_en": "Chungnam National University", "type": OrganizationType.UNIVERSITY},
    "전북대학교": {"name_en": "Jeonbuk National University", "type": OrganizationType.UNIVERSITY},
    "강원대학교": {"name_en": "Kangwon National University", "type": OrganizationType.UNIVERSITY},
    "제주대학교": {"name_en": "Jeju National University", "type": OrganizationType.UNIVERSITY},
    "경남대학교": {"name_en": "Kyungnam University", "type": OrganizationType.UNIVERSITY},
    "부산외국어대학교": {"name_en": "Busan University of Foreign Studies", "type": OrganizationType.UNIVERSITY},
    "동의대학교": {"name_en": "Dong-Eui University", "type": OrganizationType.UNIVERSITY},
    "영남대학교": {"name_en": "Yeungnam University", "type": OrganizationType.UNIVERSITY},
    "조선대학교": {"name_en": "Chosun University", "type": OrganizationType.UNIVERSITY},
    "울산대학교": {"name_en": "University of Ulsan", "type": OrganizationType.UNIVERSITY},
    "명지대학교": {"name_en": "Myongji University", "type": OrganizationType.UNIVERSITY},
    "홍익대학교": {"name_en": "Hongik University", "type": OrganizationType.UNIVERSITY},

    # 체육고등학교
    "서울체육고등학교": {"name_en": "Seoul Sports High School", "type": OrganizationType.HIGH_SCHOOL},
    "부산체육고등학교": {"name_en": "Busan Sports High School", "type": OrganizationType.HIGH_SCHOOL},
    "대구체육고등학교": {"name_en": "Daegu Sports High School", "type": OrganizationType.HIGH_SCHOOL},
    "인천체육고등학교": {"name_en": "Incheon Sports High School", "type": OrganizationType.HIGH_SCHOOL},
    "광주체육고등학교": {"name_en": "Gwangju Sports High School", "type": OrganizationType.HIGH_SCHOOL},
    "대전체육고등학교": {"name_en": "Daejeon Sports High School", "type": OrganizationType.HIGH_SCHOOL},
    "울산체육고등학교": {"name_en": "Ulsan Sports High School", "type": OrganizationType.HIGH_SCHOOL},
    "경기체육고등학교": {"name_en": "Gyeonggi Sports High School", "type": OrganizationType.HIGH_SCHOOL},
    "강원체육고등학교": {"name_en": "Gangwon Sports High School", "type": OrganizationType.HIGH_SCHOOL},
    "충북체육고등학교": {"name_en": "Chungbuk Sports High School", "type": OrganizationType.HIGH_SCHOOL},
    "충남체육고등학교": {"name_en": "Chungnam Sports High School", "type": OrganizationType.HIGH_SCHOOL},
    "전북체육고등학교": {"name_en": "Jeonbuk Sports High School", "type": OrganizationType.HIGH_SCHOOL},
    "전남체육고등학교": {"name_en": "Jeonnam Sports High School", "type": OrganizationType.HIGH_SCHOOL},
    "경북체육고등학교": {"name_en": "Gyeongbuk Sports High School", "type": OrganizationType.HIGH_SCHOOL},
    "경남체육고등학교": {"name_en": "Gyeongnam Sports High School", "type": OrganizationType.HIGH_SCHOOL},
    "제주체육고등학교": {"name_en": "Jeju Sports High School", "type": OrganizationType.HIGH_SCHOOL},

    # 실업팀/공공기관
    "서울시청": {"name_en": "Seoul City Hall", "type": OrganizationType.PROFESSIONAL},
    "부산시청": {"name_en": "Busan City Hall", "type": OrganizationType.PROFESSIONAL},
    "부산광역시청": {"name_en": "Busan Metropolitan City Hall", "type": OrganizationType.PROFESSIONAL},
    "대전시청": {"name_en": "Daejeon City Hall", "type": OrganizationType.PROFESSIONAL},
    "대구시청": {"name_en": "Daegu City Hall", "type": OrganizationType.PROFESSIONAL},
    "인천시청": {"name_en": "Incheon City Hall", "type": OrganizationType.PROFESSIONAL},
    "광주시청": {"name_en": "Gwangju City Hall", "type": OrganizationType.PROFESSIONAL},
    "울산시청": {"name_en": "Ulsan City Hall", "type": OrganizationType.PROFESSIONAL},
    "화성시청": {"name_en": "Hwaseong City Hall", "type": OrganizationType.PROFESSIONAL},
    "안산시청": {"name_en": "Ansan City Hall", "type": OrganizationType.PROFESSIONAL},
    "계룡시청": {"name_en": "Gyeryong City Hall", "type": OrganizationType.PROFESSIONAL},
    "성북구청": {"name_en": "Seongbuk-gu Office", "type": OrganizationType.PROFESSIONAL},
    "경기도청": {"name_en": "Gyeonggi Province", "type": OrganizationType.PROFESSIONAL},
    "충남도청": {"name_en": "Chungnam Province", "type": OrganizationType.PROFESSIONAL},

    # 체육회
    "국군체육부대": {"name_en": "Korea Armed Forces Athletic Corps", "type": OrganizationType.PROFESSIONAL},
    "상무": {"name_en": "Korea Armed Forces Athletic Corps", "type": OrganizationType.PROFESSIONAL},
    "충청남도체육회": {"name_en": "Chungnam Sports Council", "type": OrganizationType.PROFESSIONAL},
    "경기도체육회": {"name_en": "Gyeonggi-do Sports Council", "type": OrganizationType.PROFESSIONAL},
    "서울시체육회": {"name_en": "Seoul Sports Council", "type": OrganizationType.PROFESSIONAL},
    "부산시체육회": {"name_en": "Busan Sports Council", "type": OrganizationType.PROFESSIONAL},
    "대구시체육회": {"name_en": "Daegu Sports Council", "type": OrganizationType.PROFESSIONAL},
    "인천시체육회": {"name_en": "Incheon Sports Council", "type": OrganizationType.PROFESSIONAL},
    "광주시체육회": {"name_en": "Gwangju Sports Council", "type": OrganizationType.PROFESSIONAL},
    "대전시체육회": {"name_en": "Daejeon Sports Council", "type": OrganizationType.PROFESSIONAL},
    "울산시체육회": {"name_en": "Ulsan Sports Council", "type": OrganizationType.PROFESSIONAL},
    "강원도체육회": {"name_en": "Gangwon-do Sports Council", "type": OrganizationType.PROFESSIONAL},
    "충청북도체육회": {"name_en": "Chungbuk Sports Council", "type": OrganizationType.PROFESSIONAL},
    "전라북도체육회": {"name_en": "Jeonbuk Sports Council", "type": OrganizationType.PROFESSIONAL},
    "전라남도체육회": {"name_en": "Jeonnam Sports Council", "type": OrganizationType.PROFESSIONAL},
    "경상북도체육회": {"name_en": "Gyeongbuk Sports Council", "type": OrganizationType.PROFESSIONAL},
    "경상남도체육회": {"name_en": "Gyeongnam Sports Council", "type": OrganizationType.PROFESSIONAL},
    "제주도체육회": {"name_en": "Jeju Sports Council", "type": OrganizationType.PROFESSIONAL},

    # 공사/공단
    "대전도시공사": {"name_en": "Daejeon City Corporation", "type": OrganizationType.PROFESSIONAL},
    "화성도시공사": {"name_en": "Hwaseong City Corporation", "type": OrganizationType.PROFESSIONAL},

    # 클럽 (검증된 이름)
    "최병철펜싱클럽": {"name_en": "Choi Byeongcheol Fencing Club", "type": OrganizationType.CLUB},
    "송도펜싱클럽": {"name_en": "Songdo Fencing Club", "type": OrganizationType.CLUB},
    "서울시주니어펜싱클럽": {"name_en": "Seoul Junior Fencing Club", "type": OrganizationType.CLUB},
    "목동펜싱클럽": {"name_en": "Mokdong Fencing Club", "type": OrganizationType.CLUB},
    "압구정펜싱클럽": {"name_en": "Apgujeong Fencing Club", "type": OrganizationType.CLUB},
    "AXIOM 펜싱 랩": {"name_en": "AXIOM Fencing Lab", "type": OrganizationType.CLUB},
    "FENCINGLAB(펜싱랩)": {"name_en": "Fencing Lab", "type": OrganizationType.CLUB},
    "양구군청펜싱클럽": {"name_en": "Yanggu County Fencing Club", "type": OrganizationType.CLUB},
    "(사)부산펜싱클럽": {"name_en": "Busan Fencing Club", "type": OrganizationType.CLUB},
    "비앤케이펜싱클럽": {"name_en": "B&K Fencing Club", "type": OrganizationType.CLUB},
    "부산광역시거점스포츠클럽": {"name_en": "Busan Regional Sports Club", "type": OrganizationType.CLUB},

    # 외래어 클럽 (Loanword-based clubs — 한글로 표기된 영어/프랑스어 이름)
    # 펜싱 용어
    "투셰펜싱클럽": {"name_en": "Touché Fencing Club", "type": OrganizationType.CLUB},
    "알레펜싱클럽": {"name_en": "Allez Fencing Club", "type": OrganizationType.CLUB},
    "알레펜싱코리아": {"name_en": "Allez Fencing Korea", "type": OrganizationType.CLUB},
    "라팡트 펜싱클럽": {"name_en": "La Fente Fencing Club", "type": OrganizationType.CLUB},
    # 영어 일반 단어
    "몬스터펜싱클럽": {"name_en": "Monster Fencing Club", "type": OrganizationType.CLUB},
    "마스터펜싱클럽": {"name_en": "Master Fencing Club", "type": OrganizationType.CLUB},
    "포스펜싱클럽": {"name_en": "Force Fencing Club", "type": OrganizationType.CLUB},
    "포스 펜싱클럽": {"name_en": "Force Fencing Club", "type": OrganizationType.CLUB},
    "월드펜싱클럽": {"name_en": "World Fencing Club", "type": OrganizationType.CLUB},
    "드림펜싱클럽": {"name_en": "Dream Fencing Club", "type": OrganizationType.CLUB},
    "이글펜싱클럽": {"name_en": "Eagle Fencing Club", "type": OrganizationType.CLUB},
    "이글펜싱클럽 송파점": {"name_en": "Eagle Fencing Club Songpa", "type": OrganizationType.CLUB},
    "이글펜싱클럽 잠실본점": {"name_en": "Eagle Fencing Club Jamsil", "type": OrganizationType.CLUB},
    "이글펜싱클럽 남양주점": {"name_en": "Eagle Fencing Club Namyangju", "type": OrganizationType.CLUB},
    "이글펜싱클럽-송파점": {"name_en": "Eagle Fencing Club Songpa", "type": OrganizationType.CLUB},
    "이글펜싱클럽 전문트레이닝센터 올림픽점": {"name_en": "Eagle Fencing Club Training Center Olympic", "type": OrganizationType.CLUB},
    "스타펜싱아카데미": {"name_en": "Star Fencing Academy", "type": OrganizationType.CLUB},
    "스타펜싱클럽": {"name_en": "Star Fencing Club", "type": OrganizationType.CLUB},
    "센텀펜싱클럽": {"name_en": "Centum Fencing Club", "type": OrganizationType.CLUB},
    "센트럴펜싱클럽": {"name_en": "Central Fencing Club", "type": OrganizationType.CLUB},
    "위너펜싱클럽": {"name_en": "Winner Fencing Club", "type": OrganizationType.CLUB},
    "위즈펜싱클럽": {"name_en": "Wiz Fencing Club", "type": OrganizationType.CLUB},
    "윈펜싱클럽": {"name_en": "Win Fencing Club", "type": OrganizationType.CLUB},
    "로얄펜싱클럽": {"name_en": "Royal Fencing Club", "type": OrganizationType.CLUB},
    "프라임펜싱클럽": {"name_en": "Prime Fencing Club", "type": OrganizationType.CLUB},
    "베스트펜싱클럽": {"name_en": "Best Fencing Club", "type": OrganizationType.CLUB},
    "베스트 펜싱 클럽": {"name_en": "Best Fencing Club", "type": OrganizationType.CLUB},
    "에코펜싱클럽": {"name_en": "Eco Fencing Club", "type": OrganizationType.CLUB},
    "퍼스트펜싱클럽": {"name_en": "First Fencing Club", "type": OrganizationType.CLUB},
    "원탑펜싱클럽": {"name_en": "One Top Fencing Club", "type": OrganizationType.CLUB},
    "노블레스펜싱클럽": {"name_en": "Noblesse Fencing Club", "type": OrganizationType.CLUB},
    "앱솔루트펜싱클럽": {"name_en": "Absolute Fencing Club", "type": OrganizationType.CLUB},
    "어썸코리아펜싱클럽": {"name_en": "Awesome Korea Fencing Club", "type": OrganizationType.CLUB},
    "스킬펜싱클럽": {"name_en": "Skill Fencing Club", "type": OrganizationType.CLUB},
    "포인트펜싱클럽": {"name_en": "Point Fencing Club", "type": OrganizationType.CLUB},
    "코리아펜싱클럽": {"name_en": "Korea Fencing Club", "type": OrganizationType.CLUB},
    "사비오펜싱클럽": {"name_en": "Savio Fencing Club", "type": OrganizationType.CLUB},
    "아레스 펜싱클럽": {"name_en": "Ares Fencing Club", "type": OrganizationType.CLUB},
    "로러스펜싱클럽": {"name_en": "Laurus Fencing Club", "type": OrganizationType.CLUB},
    "부산로러스펜싱클럽": {"name_en": "Busan Laurus Fencing Club", "type": OrganizationType.CLUB},
    "레이스펜싱클럽": {"name_en": "Lace Fencing Club", "type": OrganizationType.CLUB},
    "루이펜싱클럽": {"name_en": "Louis Fencing Club", "type": OrganizationType.CLUB},
    "올림픽펜싱아카데미": {"name_en": "Olympic Fencing Academy", "type": OrganizationType.CLUB},
    "하이브 펜싱클럽": {"name_en": "Hive Fencing Club", "type": OrganizationType.CLUB},
    "하이브 펜싱클럽 강남": {"name_en": "Hive Fencing Club Gangnam", "type": OrganizationType.CLUB},
    "하이브 펜싱클럽 목동": {"name_en": "Hive Fencing Club Mokdong", "type": OrganizationType.CLUB},
    "라피네킴스펜싱클럽": {"name_en": "Raffine Kim's Fencing Club", "type": OrganizationType.CLUB},
    "라피크엔시스펜싱클럽": {"name_en": "Rapique N Sis Fencing Club", "type": OrganizationType.CLUB},
    "더 펜싱 [The Fencing]": {"name_en": "The Fencing", "type": OrganizationType.CLUB},
    "펜싱 290 (Fencing 290)": {"name_en": "Fencing 290", "type": OrganizationType.CLUB},
    "펜싱레이블": {"name_en": "Fencing Label", "type": OrganizationType.CLUB},
    "펜싱의 계절": {"name_en": "Season of Fencing", "type": OrganizationType.CLUB},
    "펜싱의계절": {"name_en": "Season of Fencing", "type": OrganizationType.CLUB},
    "펜싱_아레나": {"name_en": "Fencing Arena", "type": OrganizationType.CLUB},
    "펜싱아카데미 더원": {"name_en": "Fencing Academy The One", "type": OrganizationType.CLUB},
    "펜싱랩": {"name_en": "Fencing Lab", "type": OrganizationType.CLUB},
    "더블유펜싱클럽": {"name_en": "W Fencing Club", "type": OrganizationType.CLUB},
    "비에이블펜싱클럽": {"name_en": "B-Able Fencing Club", "type": OrganizationType.CLUB},
    "이지펜싱클럽": {"name_en": "Easy Fencing Club", "type": OrganizationType.CLUB},
    "동탄펜싱클럽": {"name_en": "Dongtan Fencing Club", "type": OrganizationType.CLUB},
    "운정펜싱클럽": {"name_en": "Unjeong Fencing Club", "type": OrganizationType.CLUB},
    "청라펜싱클럽": {"name_en": "Cheongna Fencing Club", "type": OrganizationType.CLUB},
    "부천트윈펜싱클럽": {"name_en": "Bucheon Twin Fencing Club", "type": OrganizationType.CLUB},
    "잠실펜싱클럽": {"name_en": "Jamsil Fencing Club", "type": OrganizationType.CLUB},
    "해운대펜싱클럽": {"name_en": "Haeundae Fencing Club", "type": OrganizationType.CLUB},
    "향남펜싱클럽": {"name_en": "Hyangnam Fencing Club", "type": OrganizationType.CLUB},
    "평창동펜싱클럽": {"name_en": "Pyeongchangdong Fencing Club", "type": OrganizationType.CLUB},
    "성북펜싱클럽": {"name_en": "Seongbuk Fencing Club", "type": OrganizationType.CLUB},
    "고양펜싱클럽": {"name_en": "Goyang Fencing Club", "type": OrganizationType.CLUB},
    "광교펜싱클럽": {"name_en": "Gwanggyo Fencing Club", "type": OrganizationType.CLUB},
    "남양주펜싱클럽": {"name_en": "Namyangju Fencing Club", "type": OrganizationType.CLUB},
    "강남펜싱클럽": {"name_en": "Gangnam Fencing Club", "type": OrganizationType.CLUB},
    "서울펜싱클럽": {"name_en": "Seoul Fencing Club", "type": OrganizationType.CLUB},

    # 약자 클럽 (Abbreviation-based clubs — 한글로 풀어쓴 영문 약자)
    "엔에스펜싱클럽": {"name_en": "NS Fencing Club", "type": OrganizationType.CLUB},
    "엔에프에이펜싱아카데미": {"name_en": "NFA Fencing Academy", "type": OrganizationType.CLUB},
    "제이펜싱아카데미": {"name_en": "J Fencing Academy", "type": OrganizationType.CLUB},
    "케이펜싱클럽": {"name_en": "K Fencing Club", "type": OrganizationType.CLUB},
    "에이치펜싱클럽": {"name_en": "H Fencing Club", "type": OrganizationType.CLUB},
    "에이치펜싱클럽(H FENCING CLUB)": {"name_en": "H Fencing Club", "type": OrganizationType.CLUB},
    "에스씨펜싱클럽": {"name_en": "SC Fencing Club", "type": OrganizationType.CLUB},
    "엠디비펜싱클럽": {"name_en": "MDB Fencing Club", "type": OrganizationType.CLUB},
    "제이에스펜싱클럽": {"name_en": "JS Fencing Club", "type": OrganizationType.CLUB},
    "제이제이펜싱아카데미JJFA": {"name_en": "JJFA Fencing Academy", "type": OrganizationType.CLUB},
    "제이제이펜싱클럽": {"name_en": "JJ Fencing Club", "type": OrganizationType.CLUB},
    "제이케이펜싱클럽": {"name_en": "JK Fencing Club", "type": OrganizationType.CLUB},
    "제이콩펜싱클럽": {"name_en": "J Kong Fencing Club", "type": OrganizationType.CLUB},
    "엔티언 펜싱클럽 김포": {"name_en": "NTion Fencing Club Gimpo", "type": OrganizationType.CLUB},
    "엔티언 펜싱클럽 배곧": {"name_en": "NTion Fencing Club Baegot", "type": OrganizationType.CLUB},
    "엔티언펜싱클럽 김포": {"name_en": "NTion Fencing Club Gimpo", "type": OrganizationType.CLUB},
    "엔티언펜싱클럽 배곧": {"name_en": "NTion Fencing Club Baegot", "type": OrganizationType.CLUB},
    "엔티언펜싱클럽 위례": {"name_en": "NTion Fencing Club Wirye", "type": OrganizationType.CLUB},
    "엔티언펜싱클럽_위례": {"name_en": "NTion Fencing Club Wirye", "type": OrganizationType.CLUB},

    "블레이드나인 펜싱클럽 삼산점": {"name_en": "Blade Nine Fencing Club Samsan", "type": OrganizationType.CLUB},

    # 특수 이름/혼합형 클럽
    "올즈윈스포츠": {"name_en": "Olds Win Sports", "type": OrganizationType.CLUB},
    "올즈윈스포츠펜싱클럽": {"name_en": "Olds Win Sports Fencing Club", "type": OrganizationType.CLUB},
    "진주펜싱코리아클럽": {"name_en": "Jinju Fencing Korea Club", "type": OrganizationType.CLUB},
    "고덕국제펜싱클럽": {"name_en": "Godeok International Fencing Club", "type": OrganizationType.CLUB},
    "분당국제펜싱클럽": {"name_en": "Bundang International Fencing Club", "type": OrganizationType.CLUB},
    "분당국제펜싱클럽 서판교": {"name_en": "Bundang International Fencing Club Seopangyo", "type": OrganizationType.CLUB},
    "분당국제펜싱클럽(서판교)": {"name_en": "Bundang International Fencing Club Seopangyo", "type": OrganizationType.CLUB},
    "인천국제펜싱클럽": {"name_en": "Incheon International Fencing Club", "type": OrganizationType.CLUB},
    "부산국제펜싱아카데미": {"name_en": "Busan International Fencing Academy", "type": OrganizationType.CLUB},
    "부산국제펜싱클럽": {"name_en": "Busan International Fencing Club", "type": OrganizationType.CLUB},
    "국제펜싱클럽": {"name_en": "International Fencing Club", "type": OrganizationType.CLUB},
    "국대펜싱클럽": {"name_en": "Gukdae Fencing Club", "type": OrganizationType.CLUB},
    "국대스포츠클럽": {"name_en": "Gukdae Sports Club", "type": OrganizationType.CLUB},
    "안산시 G-스포츠클럽": {"name_en": "Ansan City G-Sports Club", "type": OrganizationType.CLUB},
    "안산시G-스포츠클럽": {"name_en": "Ansan City G-Sports Club", "type": OrganizationType.CLUB},
    "안산시스포츠클럽": {"name_en": "Ansan City Sports Club", "type": OrganizationType.CLUB},
    "안산시체육회 상록펜싱클럽": {"name_en": "Ansan Sports Council Sangnok Fencing Club", "type": OrganizationType.CLUB},
    "광주시G-스포츠클럽": {"name_en": "Gwangju City G-Sports Club", "type": OrganizationType.CLUB},
    "남현희 인터내셔널펜싱아카데미": {"name_en": "Nam Hyunhee International Fencing Academy", "type": OrganizationType.CLUB},
    "남현희인터내셔널펜싱아카데미": {"name_en": "Nam Hyunhee International Fencing Academy", "type": OrganizationType.CLUB},
    "서미정펜싱아카데미": {"name_en": "Seo Mijeong Fencing Academy", "type": OrganizationType.CLUB},
    "서미정펜싱클럽": {"name_en": "Seo Mijeong Fencing Club", "type": OrganizationType.CLUB},
    "구본길펜싱클럽": {"name_en": "Gu Bongil Fencing Club", "type": OrganizationType.CLUB},
    "대구프라임펜싱클럽": {"name_en": "Daegu Prime Fencing Club", "type": OrganizationType.CLUB},
    "대전GD펜싱클럽": {"name_en": "Daejeon GD Fencing Club", "type": OrganizationType.CLUB},
    "대전문정펜싱클럽": {"name_en": "Daejeon Munjeong Fencing Club", "type": OrganizationType.CLUB},
    "대전펜싱클럽": {"name_en": "Daejeon Fencing Club", "type": OrganizationType.CLUB},
    "vip펜싱클럽": {"name_en": "VIP Fencing Club", "type": OrganizationType.CLUB},
    "JK펜싱클럽": {"name_en": "JK Fencing Club", "type": OrganizationType.CLUB},
    "JS펜싱클럽": {"name_en": "JS Fencing Club", "type": OrganizationType.CLUB},
    "제주TOP펜싱아카데미": {"name_en": "Jeju TOP Fencing Academy", "type": OrganizationType.CLUB},
    "APEX FENCING CLUB(에이펙스 펜싱클럽)": {"name_en": "Apex Fencing Club", "type": OrganizationType.CLUB},
    "청라국제스포츠스쿨": {"name_en": "Cheongna International Sports School", "type": OrganizationType.CLUB},
    "경남펜싱아카데미": {"name_en": "Gyeongnam Fencing Academy", "type": OrganizationType.CLUB},
    "성남펜싱아카데미": {"name_en": "Seongnam Fencing Academy", "type": OrganizationType.CLUB},
    "울산펜싱아카데미": {"name_en": "Ulsan Fencing Academy", "type": OrganizationType.CLUB},
    "신수펜싱아카데미": {"name_en": "Sinsu Fencing Academy", "type": OrganizationType.CLUB},
    "달구벌스포츠클럽": {"name_en": "Dalgubeol Sports Club", "type": OrganizationType.CLUB},
    "나주스포츠클럽": {"name_en": "Naju Sports Club", "type": OrganizationType.CLUB},
    "진주스포츠클럽": {"name_en": "Jinju Sports Club", "type": OrganizationType.CLUB},
    "춘천스포츠클럽": {"name_en": "Chuncheon Sports Club", "type": OrganizationType.CLUB},
    "강원스포츠클럽": {"name_en": "Gangwon Sports Club", "type": OrganizationType.CLUB},
    "석정마크써밋스포츠단": {"name_en": "Seokjeong Mark Summit Sports Team", "type": OrganizationType.CLUB},
    "경상북도체육회 독도스포츠단": {"name_en": "Gyeongbuk Sports Council Dokdo Sports Team", "type": OrganizationType.PROFESSIONAL},
    "인천광역시체육회 스포츠클럽육성팀": {"name_en": "Incheon Sports Council Sports Club Development Team", "type": OrganizationType.PROFESSIONAL},
    "땅끝해남스포츠클럽": {"name_en": "Haenam Sports Club", "type": OrganizationType.CLUB},

    # 학교 (스포츠과학고 등 특수)
    "울산스포츠과학고등학교": {"name_en": "Ulsan Sports Science High School", "type": OrganizationType.HIGH_SCHOOL},

    # 중학교
    "전주호성중학교": {"name_en": "Jeonju Hoseong Middle School", "type": OrganizationType.MIDDLE_SCHOOL},
    "신언중학교": {"name_en": "Sineon Middle School", "type": OrganizationType.MIDDLE_SCHOOL},
    "경덕중학교": {"name_en": "Gyeongdeok Middle School", "type": OrganizationType.MIDDLE_SCHOOL},

    # 일반 고등학교
    "전주제일고등학교": {"name_en": "Jeonju Jeil High School", "type": OrganizationType.HIGH_SCHOOL},
    "울산산업고등학교": {"name_en": "Ulsan Technical High School", "type": OrganizationType.HIGH_SCHOOL},
    "동래원예고등학교": {"name_en": "Dongnae Horticultural High School", "type": OrganizationType.HIGH_SCHOOL},
    "홍익대학교사범대학부속고등학교": {"name_en": "Hongik University High School", "type": OrganizationType.HIGH_SCHOOL},
    "곤지암고등학교": {"name_en": "Gonjiam High School", "type": OrganizationType.HIGH_SCHOOL},
    "푸른고등학교": {"name_en": "Pureun High School", "type": OrganizationType.HIGH_SCHOOL},
    "가릿고등학교": {"name_en": "Garit High School", "type": OrganizationType.HIGH_SCHOOL},
    "진주기계공업고등학교": {"name_en": "Jinju Technical High School", "type": OrganizationType.HIGH_SCHOOL},

    # 일반 중학교
    "곤지암중학교": {"name_en": "Gonjiam Middle School", "type": OrganizationType.MIDDLE_SCHOOL},
    "신수중학교": {"name_en": "Sinsu Middle School", "type": OrganizationType.MIDDLE_SCHOOL},
    "신도중학교": {"name_en": "Sindo Middle School", "type": OrganizationType.MIDDLE_SCHOOL},
    "가좌중학교": {"name_en": "Gajwa Middle School", "type": OrganizationType.MIDDLE_SCHOOL},
    "부산연수중학교": {"name_en": "Busan Yeonsoo Middle School", "type": OrganizationType.MIDDLE_SCHOOL},

    # 클럽 추가 (legacy - overridden by loanword section above)

    # 자동 분류 불가 (창작 이름 — 수동 지정)
    "검속그대": {"name_en": "Geomsok Geudae", "type": OrganizationType.CLUB},
    "광주국대펜싱": {"name_en": "Gwangju Gukdae Fencing", "type": OrganizationType.CLUB},
    "대전대펜싱학교": {"name_en": "Daejeon Fencing School", "type": OrganizationType.CLUB},

    # 국제학교
    "CSIS국제학교": {"name_en": "CSIS International School", "type": OrganizationType.HIGH_SCHOOL},
    "KIS 한국외국인학교(판교)": {"name_en": "Korea International School Pangyo", "type": OrganizationType.HIGH_SCHOOL},
    "US International School 펜싱팀": {"name_en": "US International School Fencing Team", "type": OrganizationType.CLUB},
}


@dataclass
class OrganizationProfile:
    """조직 프로필"""
    org_id: str                          # 조직 ID (예: KC001, KH015)
    name: str                            # 한글 이름
    name_en: Optional[str] = None        # 영문 이름
    name_en_verified: bool = False       # 영문 이름 검증 여부
    country: str = "KO"                  # 국가 코드 (2글자 ISO)
    org_type: OrganizationType = OrganizationType.UNKNOWN
    region: Optional[str] = None         # 지역
    region_en: Optional[str] = None      # 지역 영문
    player_ids: Set[str] = field(default_factory=set)  # 소속 선수 ID들
    first_seen: Optional[str] = None     # 첫 등장 날짜
    last_seen: Optional[str] = None      # 마지막 등장 날짜
    competition_count: int = 0           # 대회 출전 횟수

    def to_dict(self) -> dict:
        return {
            "org_id": self.org_id,
            "name": self.name,
            "name_en": self.name_en,
            "name_en_verified": self.name_en_verified,
            "country": self.country,
            "org_type": self.org_type.value,
            "org_type_name": self.org_type.name,
            "region": self.region,
            "region_en": self.region_en,
            "player_count": len(self.player_ids),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "competition_count": self.competition_count,
        }


class OrganizationIdentityResolver:
    """조직 식별 시스템"""

    def __init__(self, country: str = "KO"):
        self.country = country
        self.organizations: Dict[str, OrganizationProfile] = {}  # org_id -> profile
        self.name_to_org: Dict[str, str] = {}  # name -> org_id
        self._id_counters: Dict[str, int] = {
            "C": 0,  # Club
            "E": 0,  # Elementary School
            "M": 0,  # Middle School
            "H": 0,  # High School
            "V": 0,  # University
            "A": 0,  # Professional
            "N": 0,  # National
            "X": 0,  # Unknown
        }

    def _detect_org_type(self, name: str) -> OrganizationType:
        """조직 유형 감지 — 모듈 레벨 detect_org_type() 위임"""
        return detect_org_type(name)

    def _extract_region(self, name: str) -> Tuple[Optional[str], Optional[str]]:
        """지역명 추출"""
        for korean, english in KOREAN_REGIONS.items():
            if name.startswith(korean) or korean in name:
                return korean, english
        return None, None

    def _generate_org_id(self, org_type: OrganizationType) -> str:
        """조직 ID 생성"""
        type_code = org_type.value
        self._id_counters[type_code] += 1
        return f"{self.country}{type_code}{self._id_counters[type_code]:04d}"

    def _convert_to_english(self, name: str) -> str:
        """한글 조직명을 영문으로 변환"""
        # 1. 검증된 매핑 확인
        if name in VERIFIED_ORG_MAPPINGS:
            return VERIFIED_ORG_MAPPINGS[name]["name_en"]

        result = name

        # 2. 지역명 변환
        for korean, english in sorted(KOREAN_REGIONS.items(), key=lambda x: -len(x[0])):
            if korean in result:
                result = result.replace(korean, english + " ")
                break

        # 3. 조직 유형 변환
        for korean, english in sorted(KOREAN_TO_ENGLISH_ORG.items(), key=lambda x: -len(x[0])):
            if korean in result:
                result = result.replace(korean, " " + english)

        # 4. 정리 (중복 공백 제거, 앞뒤 공백 제거)
        result = re.sub(r'\s+', ' ', result).strip()

        # 5. 한글이 남아있으면 로마자 변환 시도
        if re.search(r'[가-힣]', result):
            # 간단한 로마자 변환 (international_data.py의 로직 재사용 가능)
            result = self._romanize_korean(result)

        return result

    def _romanize_korean(self, text: str) -> str:
        """한글 텍스트를 로마자로 변환 (간단 버전)"""
        # 초성, 중성, 종성 로마자 매핑
        CHOSUNG = ['g', 'kk', 'n', 'd', 'tt', 'r', 'm', 'b', 'pp', 's', 'ss', '', 'j', 'jj', 'ch', 'k', 't', 'p', 'h']
        JUNGSUNG = ['a', 'ae', 'ya', 'yae', 'eo', 'e', 'yeo', 'ye', 'o', 'wa', 'wae', 'oe', 'yo', 'u', 'wo', 'we', 'wi', 'yu', 'eu', 'ui', 'i']
        # 종성 (받침) 로마자 매핑 - Unicode 종성 인덱스 순서 (0~27)
        # 0:없음 1:ㄱ 2:ㄲ 3:ㄳ 4:ㄴ 5:ㄵ 6:ㄶ 7:ㄷ 8:ㄹ 9:ㄺ 10:ㄻ
        # 11:ㄼ 12:ㄽ 13:ㄾ 14:ㄿ 15:ㅀ 16:ㅁ 17:ㅂ 18:ㅄ 19:ㅅ 20:ㅆ
        # 21:ㅇ 22:ㅈ 23:ㅊ 24:ㅋ 25:ㅌ 26:ㅍ 27:ㅎ
        JONGSUNG = ['', 'k', 'k', 'k', 'n', 'n', 'n', 't', 'l', 'k', 'm', 'l', 'l', 'l', 'l', 'l', 'm', 'p', 'p', 't', 't', 'ng', 't', 't', 'k', 't', 'p', 't']

        result = []
        for char in text:
            if '가' <= char <= '힣':
                code = ord(char) - ord('가')
                cho = code // 588
                jung = (code % 588) // 28
                jong = code % 28
                result.append(CHOSUNG[cho])
                result.append(JUNGSUNG[jung])
                result.append(JONGSUNG[jong])
            else:
                result.append(char)

        return ''.join(result).title()

    def get_or_create_organization(self, name: str) -> OrganizationProfile:
        """조직 프로필 조회 또는 생성"""
        # 정규화된 이름으로 조회
        normalized_name = name.strip()

        if normalized_name in self.name_to_org:
            org_id = self.name_to_org[normalized_name]
            return self.organizations[org_id]

        # 새 조직 생성
        org_type = self._detect_org_type(normalized_name)
        org_id = self._generate_org_id(org_type)
        region, region_en = self._extract_region(normalized_name)

        # 영문 이름 생성
        name_en = self._convert_to_english(normalized_name)
        name_en_verified = normalized_name in VERIFIED_ORG_MAPPINGS

        profile = OrganizationProfile(
            org_id=org_id,
            name=normalized_name,
            name_en=name_en,
            name_en_verified=name_en_verified,
            country=self.country,
            org_type=org_type,
            region=region,
            region_en=region_en,
        )

        self.organizations[org_id] = profile
        self.name_to_org[normalized_name] = org_id

        return profile

    def update_organization_stats(self, name: str, date: str, player_id: Optional[str] = None):
        """조직 통계 업데이트"""
        profile = self.get_or_create_organization(name)

        if not profile.first_seen or date < profile.first_seen:
            profile.first_seen = date
        if not profile.last_seen or date > profile.last_seen:
            profile.last_seen = date

        profile.competition_count += 1

        if player_id:
            profile.player_ids.add(player_id)

    def get_organization_by_id(self, org_id: str) -> Optional[OrganizationProfile]:
        """ID로 조직 조회"""
        return self.organizations.get(org_id)

    def get_organization_by_name(self, name: str) -> Optional[OrganizationProfile]:
        """이름으로 조직 조회"""
        org_id = self.name_to_org.get(name.strip())
        if org_id:
            return self.organizations.get(org_id)
        return None

    def search_organizations(self, query: str, limit: int = 20) -> List[OrganizationProfile]:
        """조직 검색"""
        query_lower = query.lower()
        results = []

        for org in self.organizations.values():
            if query_lower in org.name.lower():
                results.append(org)
            elif org.name_en and query_lower in org.name_en.lower():
                results.append(org)

        # 선수 수 기준 정렬
        results.sort(key=lambda x: len(x.player_ids), reverse=True)
        return results[:limit]

    def get_stats(self) -> dict:
        """통계 정보"""
        type_counts = {}
        for org in self.organizations.values():
            type_name = org.org_type.name
            type_counts[type_name] = type_counts.get(type_name, 0) + 1

        return {
            "total": len(self.organizations),
            "by_type": type_counts,
            "verified_count": len([o for o in self.organizations.values() if o.name_en_verified]),
        }


# 글로벌 인스턴스
_org_resolver: Optional[OrganizationIdentityResolver] = None


def get_org_resolver() -> OrganizationIdentityResolver:
    """조직 식별자 가져오기"""
    global _org_resolver
    if _org_resolver is None:
        _org_resolver = OrganizationIdentityResolver(country="KO")
    return _org_resolver


def init_org_resolver(country: str = "KO") -> OrganizationIdentityResolver:
    """조직 식별자 초기화"""
    global _org_resolver
    _org_resolver = OrganizationIdentityResolver(country=country)
    return _org_resolver
