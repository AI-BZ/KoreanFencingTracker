"""
조직(팀) 식별 시스템 - ID 체계 및 영문 이름 관리

ID 체계:
- 국가코드 (2글자 ISO): KO(한국), JP(일본), CN(중국), TW(대만), HK(홍콩), SG(싱가포르) 등
- 조직유형: C(클럽), M(중학교), H(고등학교), V(대학교), A(실업팀/시청/기업)
- 예: KOC0001 = 한국 클럽 0001, KOH0015 = 한국 고등학교 0015
"""

import re
import hashlib
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
    MIDDLE_SCHOOL = "M"  # 중학교
    HIGH_SCHOOL = "H"    # 고등학교
    UNIVERSITY = "V"     # 대학교 (Varsity)
    PROFESSIONAL = "A"   # 실업팀/시청/기업 (Adult/Professional)
    NATIONAL = "N"       # 국가대표/협회
    UNKNOWN = "X"        # 분류 불가


# 한국 조직 유형 판별 키워드
KOREAN_ORG_TYPE_KEYWORDS = {
    OrganizationType.MIDDLE_SCHOOL: [
        "중학교", "중학", "여중", "남중", "중"
    ],
    OrganizationType.HIGH_SCHOOL: [
        "고등학교", "고등", "여고", "남고", "체육고", "예술고", "과학고",
        "외고", "국제고", "자사고", "특목고", "고"
    ],
    OrganizationType.UNIVERSITY: [
        "대학교", "대학", "대"
    ],
    OrganizationType.PROFESSIONAL: [
        "시청", "군청", "구청", "도청", "체육회",
        "공사", "공단", "은행", "보험", "증권", "카드",
        "전력", "가스", "통신", "철도", "항공",
        "삼성", "현대", "LG", "SK", "롯데", "포스코", "KT", "CJ"
    ],
    OrganizationType.CLUB: [
        "클럽", "펜싱클럽", "펜싱", "스포츠클럽", "FC", "SC",
        "아카데미", "도장", "체육관", "센터", "랩", "LAB"
    ],
    OrganizationType.NATIONAL: [
        "국가대표", "대표팀", "협회", "연맹"
    ]
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
    "클럽": "Club",
    "스포츠클럽": "Sports Club",
    "아카데미": "Academy",
    "센터": "Center",
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

    # 실업팀
    "서울시청": {"name_en": "Seoul City Hall", "type": OrganizationType.PROFESSIONAL},
    "부산시청": {"name_en": "Busan City Hall", "type": OrganizationType.PROFESSIONAL},
    "부산광역시청": {"name_en": "Busan Metropolitan City Hall", "type": OrganizationType.PROFESSIONAL},
    "대전시청": {"name_en": "Daejeon City Hall", "type": OrganizationType.PROFESSIONAL},
    "울산시청": {"name_en": "Ulsan City Hall", "type": OrganizationType.PROFESSIONAL},
    "경기도청": {"name_en": "Gyeonggi Province", "type": OrganizationType.PROFESSIONAL},
    "충남도청": {"name_en": "Chungnam Province", "type": OrganizationType.PROFESSIONAL},

    # 클럽
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

    # 중학교
    "전주호성중학교": {"name_en": "Jeonju Hoseong Middle School", "type": OrganizationType.MIDDLE_SCHOOL},
    "신언중학교": {"name_en": "Sineon Middle School", "type": OrganizationType.MIDDLE_SCHOOL},
    "경덕중학교": {"name_en": "Gyeongdeok Middle School", "type": OrganizationType.MIDDLE_SCHOOL},

    # 고등학교
    "전주제일고등학교": {"name_en": "Jeonju Jeil High School", "type": OrganizationType.HIGH_SCHOOL},
    "울산산업고등학교": {"name_en": "Ulsan Technical High School", "type": OrganizationType.HIGH_SCHOOL},
    "동래원예고등학교": {"name_en": "Dongnae Horticultural High School", "type": OrganizationType.HIGH_SCHOOL},
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
            "M": 0,  # Middle School
            "H": 0,  # High School
            "V": 0,  # University
            "A": 0,  # Professional
            "N": 0,  # National
            "X": 0,  # Unknown
        }

    def _detect_org_type(self, name: str) -> OrganizationType:
        """조직 유형 감지"""
        # 우선순위: 대학 > 고등학교 > 중학교 > 실업팀 > 클럽
        # (더 구체적인 키워드가 먼저 매칭되도록)

        # 대학교 체크 (가장 먼저 - "대학"이 포함되면 대학)
        for keyword in KOREAN_ORG_TYPE_KEYWORDS[OrganizationType.UNIVERSITY]:
            if keyword in name:
                return OrganizationType.UNIVERSITY

        # 고등학교 체크
        for keyword in KOREAN_ORG_TYPE_KEYWORDS[OrganizationType.HIGH_SCHOOL]:
            if keyword in name:
                return OrganizationType.HIGH_SCHOOL

        # 중학교 체크
        for keyword in KOREAN_ORG_TYPE_KEYWORDS[OrganizationType.MIDDLE_SCHOOL]:
            if keyword in name:
                return OrganizationType.MIDDLE_SCHOOL

        # 실업팀/시청 체크
        for keyword in KOREAN_ORG_TYPE_KEYWORDS[OrganizationType.PROFESSIONAL]:
            if keyword in name:
                return OrganizationType.PROFESSIONAL

        # 국가대표/협회 체크
        for keyword in KOREAN_ORG_TYPE_KEYWORDS[OrganizationType.NATIONAL]:
            if keyword in name:
                return OrganizationType.NATIONAL

        # 클럽 체크
        for keyword in KOREAN_ORG_TYPE_KEYWORDS[OrganizationType.CLUB]:
            if keyword in name:
                return OrganizationType.CLUB

        return OrganizationType.UNKNOWN

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
        JONGSUNG = ['', 'k', 'k', 'k', 'n', 'n', 'n', 't', 'l', 'k', 'm', 'p', 't', 't', 'ng', 't', 't', 'k', 't', 'p', 't', 't', 't', 't', 'p', 't', 't', 'p']

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
