"""
Translation Service for Multi-Language Database Content

Provides unified translation interface for:
- Player names (Korean -> English romanization)
- Organization names (Korean -> English)
- Competition names (Korean -> English)

Usage:
    from app.translation_service import TranslationService

    ts = TranslationService()

    # Player name
    result = ts.translate_player_name("박소윤")
    # {"en": {"name": "Soyun Park", "verified": False, "source": "romanization"}}

    # Organization name
    result = ts.translate_organization_name("최병철펜싱클럽")
    # {"en": {"name": "Choi Byeongcheol Fencing Club", "verified": True, "source": "verified"}}
"""

import re
from datetime import datetime
from typing import Dict, Any, Optional, List

from app.international_data import (
    InternationalDataManager,
    VERIFIED_NAME_MAPPINGS,
    KOREAN_SURNAMES,
    romanize_syllable,
    is_korean_char,
    generate_english_name_candidates,
)
from app.organization_identity import (
    OrganizationIdentityResolver,
    VERIFIED_ORG_MAPPINGS,
    KOREAN_REGIONS,
)


# Competition name translation patterns
COMPETITION_NAME_PATTERNS = {
    # 대회 종류 (긴 패턴 우선)
    "회장배": "President's Cup",
    "협회장배": "Association President's Cup",
    "전국선수권대회": "National Championship",
    "전국선수권": "National Championship",
    "선수권대회": "Championship",
    "선수권": "Championship",
    "전국체육대회": "National Sports Festival",
    "전국대회": "National Championship",
    "종별선수권대회": "Category Championship",
    "종별선수권": "Category Championship",
    "종합선수권대회": "General Championship",
    "종합선수권": "General Championship",
    "선발대회": "Selection",
    "선발전": "Selection",

    # 연령별 대회
    "꿈나무대회": "Youth Championship",
    "꿈나무": "Youth",
    "초등부대회": "Elementary Championship",
    "중등부대회": "Middle School Championship",
    "고등부대회": "High School Championship",
    "대학부대회": "University Championship",
    "동호인대회": "Club Championship",
    "동호인": "Club",
    "생활체육대회": "Community Sports Championship",
    "유소년": "Youth",

    # 국제대회
    "국제대회": "International Championship",
    "국제펜싱대회": "International Fencing Championship",
    "아시아선수권대회": "Asian Championship",
    "아시아선수권": "Asian Championship",
    "세계선수권대회": "World Championship",
    "세계선수권": "World Championship",
    "올림픽": "Olympic",

    # 기타
    "펜싱선수권대회": "Fencing Championship",
    "펜싱대회": "Fencing Championship",
    "펜싱": "Fencing",
    "종별펜싱": "Category Fencing",
    "대회": "Championship",
    "리그": "League",
    "컵": "Cup",
    "오픈": "Open",
    "페스티벌": "Festival",
    "챔피언십": "Championship",

    # 조직/주최
    "대한펜싱협회": "Korea Fencing Association",
    "한국중고펜싱연맹": "Korea Middle/High School Fencing Federation",
    "한국실업": "Korea Professional",
    "KFA": "KFA",
    "국가대표선수": "National Team",
    "국가대표": "National Team",

    # 주최/지역
    "전국": "National",
    "남녀": "",
    "남·녀": "",
    "종목별": "Category",
    "겸": "&",

    # 한자어 (제X회)
    "제": "",
    "회": "",

    # 지역명
    "서울시": "Seoul",
    "부산시": "Busan",
    "대구시": "Daegu",
    "인천시": "Incheon",
    "광주시": "Gwangju",
    "대전시": "Daejeon",
    "울산시": "Ulsan",
    "세종시": "Sejong",
    "경기도": "Gyeonggi",
    "강원도": "Gangwon",
    "충청북도": "Chungbuk",
    "충청남도": "Chungnam",
    "전라북도": "Jeonbuk",
    "전라남도": "Jeonnam",
    "경상북도": "Gyeongbuk",
    "경상남도": "Gyeongnam",
    "제주도": "Jeju",
    "제주특별자치도": "Jeju",
    "익산": "Iksan",
    "서울": "Seoul",
    "부산": "Busan",
    "대구": "Daegu",
    "인천": "Incheon",
}

# Verified competition name mappings (exact matches, highest priority)
# All competition names from the database with verified English translations
VERIFIED_COMPETITION_MAPPINGS = {
    # === 전국남녀종목별오픈펜싱선수권대회 겸 국가대표선수 선발대회 ===
    "2019 전국남·녀종목별오픈펜싱선수권대회 겸 국가대표선수 선발대회": "2019 National Open Fencing Championship & National Team Selection",
    "2019 전국남녀종목별오픈펜싱선수권대회 겸 국가대표 선수 선발대회": "2019 National Open Fencing Championship & National Team Selection",
    "2020 전국남녀종목별오픈펜싱선수권대회": "2020 National Open Fencing Championship",
    "2021 전국남·녀종목별오픈펜싱선수권대회 겸 국가대표선수 선발대회": "2021 National Open Fencing Championship & National Team Selection",
    "2022 전국남·녀종목별오픈펜싱선수권대회 겸 국가대표선수 선발대회": "2022 National Open Fencing Championship & National Team Selection",
    "2023 전국남·녀종목별오픈펜싱선수권대회 겸 국가대표선수 선발대회": "2023 National Open Fencing Championship & National Team Selection",
    "2024 전국남·녀종목별오픈펜싱선수권대회 겸 국가대표선수 선발대회": "2024 National Open Fencing Championship & National Team Selection",
    "2025 전국남·녀종목별오픈펜싱선수권대회 겸 국가대표선수 선발대회": "2025 National Open Fencing Championship & National Team Selection",
    "2026 전국남·녀종목별오픈펜싱선수권대회 겸 국가대표선수 선발대회": "2026 National Open Fencing Championship & National Team Selection",

    # === 대한펜싱협회 유소년 국가대표선수 선발전 ===
    "2019 대한펜싱협회 청소년, 유소년 국가대표선수 선발전": "2019 KFA Youth National Team Selection",
    "2020 대한펜싱협회 유소년 국가대표선수 선발전": "2020 KFA Youth National Team Selection",
    "2021 대한펜싱협회 유소년 국가대표선수 선발전": "2021 KFA Youth National Team Selection",
    "2022 대한펜싱협회 유소년 국가대표선수 선발전": "2022 KFA Youth National Team Selection",
    "2023 대한펜싱협회 유소년 국가대표선수 선발전": "2023 KFA Youth National Team Selection",
    "2024 대한펜싱협회 유소년 국가대표선수 선발전": "2024 KFA Youth National Team Selection",
    "2025 대한펜싱협회 유소년 국가대표선수 선발전": "2025 KFA Youth National Team Selection",
    "2026 대한펜싱협회 유소년 국가대표선수 선발전": "2026 KFA Youth National Team Selection",

    # === 펜싱 국가대표선수 선발대회 ===
    "2019 펜싱 국가대표선수 선발대회": "2019 Fencing National Team Selection",
    "2020 펜싱 국가대표선수 선발전": "2020 Fencing National Team Selection",
    "2021 펜싱 국가대표선수 선발대회": "2021 Fencing National Team Selection",
    "2022 펜싱 국가대표선수 선발대회": "2022 Fencing National Team Selection",
    "2023 펜싱 국가대표선수 선발대회": "2023 Fencing National Team Selection",
    "2024 펜싱 국가대표선수 선발대회": "2024 Fencing National Team Selection",
    "2025 펜싱 국가대표선수 선발대회": "2025 Fencing National Team Selection",

    # === 한국실업종별펜싱선수권대회 ===
    "2023 한국실업종별펜싱선수권대회": "2023 Korea Professional Category Fencing Championship",
    "2024 한국실업종별펜싱선수권대회": "2024 Korea Professional Category Fencing Championship",
    "2025 한국실업종별펜싱선수권대회": "2025 Korea Professional Category Fencing Championship",

    # === 펜싱 클럽 코리아 오픈대회 ===
    "2019 펜싱클럽 코리아 오픈대회": "2019 Fencing Club Korea Open",
    "2021 펜싱 클럽 코리아  오픈대회": "2021 Fencing Club Korea Open",
    "2022 펜싱 클럽 코리아 오픈대회": "2022 Fencing Club Korea Open",
    "2023 펜싱 클럽 코리아 오픈대회": "2023 Fencing Club Korea Open",
    "2024 펜싱 클럽 코리아 오픈대회": "2024 Fencing Club Korea Open",
    "2025 펜싱 클럽 코리아 오픈대회": "2025 Fencing Club Korea Open",

    # === 대한펜싱협회장배 전국클럽동호인펜싱선수권대회 ===
    "2019 제7회 대한펜싱협회장배 전국 클럽·동호인 펜싱선수권대회": "2019 7th KFA President's Cup National Club Championship",
    "2020 제8회 대한펜싱협회장배 전국남녀클럽동호인펜싱선수권대회": "2020 8th KFA President's Cup National Club Championship",
    "2021 제9회 대한펜싱협회장배 전국클럽·동호인펜싱선수권대회": "2021 9th KFA President's Cup National Club Championship",
    "2022 제10회 대한펜싱협회장배 전국클럽‧동호인펜싱선수권대회": "2022 10th KFA President's Cup National Club Championship",
    "2023 제11회 대한펜싱협회장배 전국클럽·동호인펜싱선수권대회": "2023 11th KFA President's Cup National Club Championship",
    "2024 제12회 대한펜싱협회장배 전국클럽·동호인펜싱선수권대회": "2024 12th KFA President's Cup National Club Championship",
    "2025 제13회 대한펜싱협회장배 전국클럽·동호인펜싱선수권대회": "2025 13th KFA President's Cup National Club Championship",

    # === 생활체육(클럽, 동호인) 전국펜싱대회 ===
    "2019 생활체육(클럽·동호인) 전국펜싱대회": "2019 Community Sports (Club) National Fencing Championship",
    "2022 생활체육(클럽, 동호인) 전국펜싱대회": "2022 Community Sports (Club) National Fencing Championship",
    "2023 생활체육(클럽, 동호인) 전국펜싱대회": "2023 Community Sports (Club) National Fencing Championship",
    "2024 생활체육(클럽, 동호인) 전국펜싱대회": "2024 Community Sports (Club) National Fencing Championship",
    "2025 생활체육(클럽, 동호인) 전국펜싱대회": "2025 Community Sports (Club) National Fencing Championship",

    # === FILA배 전국생활체육 동호인클럽펜싱선수권대회 ===
    "2019 FILA배 전국생활체육 동호인·클럽펜싱선수권대회": "2019 FILA Cup National Community Sports Club Fencing Championship",
    "2022 FILA배 전국생활체육 동호인·클럽펜싱선수권대회": "2022 FILA Cup National Community Sports Club Fencing Championship",
    "2023 FILA배 전국생활체육 동호인·클럽펜싱선수권대회": "2023 FILA Cup National Community Sports Club Fencing Championship",
    "2024 FILA배 전국생활체육 동호인·클럽펜싱선수권대회": "2024 FILA Cup National Community Sports Club Fencing Championship",
    "2025 FILA배 전국생활체육 동호인·클럽펜싱선수권대회": "2025 FILA Cup National Community Sports Club Fencing Championship",

    # === 하계유니버시아드 ===
    "2019 하계유니버시아드대회 파견선수 선발전": "2019 Summer Universiade Team Selection",
    "2019 하계유니버시아드대회 파견선수 선발전(1차)": "2019 Summer Universiade Team Selection (1st Round)",
    "2019 하계유니버시아드대회 파견선수 선발전(2차)": "2019 Summer Universiade Team Selection (2nd Round)",

    # === 익산 국제 ===
    "2025 코리아 익산 인터내셔널 펜싱선수권대회(U13,U11,U9)": "2025 Korea Iksan International Fencing Championship (U13, U11, U9)",
    "2025 코리아 익산 인터내셔널 펜싱선수권대회(U17,U20)": "2025 Korea Iksan International Fencing Championship (U17, U20)",

    # === 전국체육대회 ===
    "제100회 전국체육대회": "100th National Sports Festival",
    "제102회 전국체육대회": "102nd National Sports Festival",
    "제103회 전국체육대회": "103rd National Sports Festival",
    "제104회 전국체육대회": "104th National Sports Festival",
    "제105회 전국체육대회": "105th National Sports Festival",
    "제106회 전국체육대회": "106th National Sports Festival",

    # === 전국소년체육대회 ===
    "제48회 전국소년체육대회": "48th National Youth Sports Festival",
    "제51회 전국소년체육대회": "51st National Youth Sports Festival",
    "제52회 전국소년체육대회": "52nd National Youth Sports Festival",
    "제53회 전국소년체육대회": "53rd National Youth Sports Festival",
    "제54회 전국소년체육대회": "54th National Youth Sports Festival",

    # === 한국중고펜싱연맹전국남녀종별펜싱선수권대회 ===
    "제16회 한국중고펜싱연맹전국남녀종별펜싱선수권대회": "16th Korea Middle/High School Fencing Federation National Category Championship",
    "제17회 한국중고펜싱연맹전국남녀종별펜싱선수권대회": "17th Korea Middle/High School Fencing Federation National Category Championship",
    "제18회 한국중고펜싱연맹전국남녀종별펜싱선수권대회": "18th Korea Middle/High School Fencing Federation National Category Championship",
    "제19회 한국중고펜싱연맹전국남녀종별펜싱선수권대회": "19th Korea Middle/High School Fencing Federation National Category Championship",
    "제20회 한국중고펜싱연맹전국남녀종별펜싱선수권대회": "20th Korea Middle/High School Fencing Federation National Category Championship",
    "제21회 한국중고펜싱연맹전국남녀종별펜싱선수권대회": "21st Korea Middle/High School Fencing Federation National Category Championship",
    "제22회 한국중고펜싱연맹전국남녀종별펜싱선수권대회": "22nd Korea Middle/High School Fencing Federation National Category Championship",

    # === 한국중고펜싱연맹회장배전국남녀중고펜싱선수권대회 ===
    "제32회 한국중고펜싱연맹회장배전국남녀중고펜싱선수권대회": "32nd Korea Middle/High School Fencing Federation President's Cup Championship",
    "제33회 한국중고펜싱연맹회장배전국남녀중고펜싱선수권대회": "33rd Korea Middle/High School Fencing Federation President's Cup Championship",
    "제34회 한국중고펜싱연맹회장배전국남녀중고펜싱선수권대회": "34th Korea Middle/High School Fencing Federation President's Cup Championship",
    "제35회 한국중고펜싱연맹회장배전국남녀중고펜싱선수권대회": "35th Korea Middle/High School Fencing Federation President's Cup Championship",
    "제36회 한국중고펜싱연맹회장배전국남녀중고펜싱선수권대회": "36th Korea Middle/High School Fencing Federation President's Cup Championship",
    "제37회 한국중고펜싱연맹회장배전국남녀중고펜싱선수권대회": "37th Korea Middle/High School Fencing Federation President's Cup Championship",

    # === 전국남녀대학펜싱선수권대회 ===
    "제21회 전국남녀대학펜싱선수권대회": "21st National University Fencing Championship",
    "제22회 전국남녀대학펜싱선수권대회": "22nd National University Fencing Championship",
    "제23회 전국남녀대학펜싱선수권대회": "23rd National University Fencing Championship",
    "제24회 전국남녀대학펜싱선수권대회": "24th National University Fencing Championship",
    "제25회 전국남녀대학펜싱선수권대회": "25th National University Fencing Championship",
    "제26회 전국남녀대학펜싱선수권대회": "26th National University Fencing Championship",

    # === 한국실업펜싱연맹회장배전국남녀펜싱선수권대회 ===
    "제22회 한국실업펜싱연맹회장배전국남녀펜싱선수권대회": "22nd Korea Professional Fencing Federation President's Cup Championship",
    "제23회 한국실업펜싱연맹회장배전국남녀펜싱선수권대회": "23rd Korea Professional Fencing Federation President's Cup Championship",
    "제24회 한국실업펜싱연맹회장배전국남녀펜싱선수권대회": "24th Korea Professional Fencing Federation President's Cup Championship",
    "제25회 한국실업펜싱연맹회장배전국남녀펜싱선수권대회": "25th Korea Professional Fencing Federation President's Cup Championship",
    "제26회 한국실업펜싱연맹회장배전국남녀펜싱선수권대회": "26th Korea Professional Fencing Federation President's Cup Championship",
    "제27회 한국실업펜싱연맹회장배전국남녀펜싱선수권대회": "27th Korea Professional Fencing Federation President's Cup Championship",

    # === 김창환배전국남녀펜싱선수권대회 ===
    "제24회 김창환배전국남·녀펜싱선수권대회 겸 국가대표선수 선발대회": "24th Kim Chang-hwan Cup National Fencing Championship & National Team Selection",
    "제25회 김창환배 전국남녀펜싱선수권대회": "25th Kim Chang-hwan Cup National Fencing Championship",
    "제26회 김창환배전국남녀펜싱선수권대회 겸 국가대표선수 선발대회": "26th Kim Chang-hwan Cup National Fencing Championship & National Team Selection",
    "제27회 김창환배전국남녀펜싱선수권대회 겸 국가대표선수 선발대회": "27th Kim Chang-hwan Cup National Fencing Championship & National Team Selection",
    "제28회 김창환배전국남녀펜싱선수권대회 겸 국가대표선수 선발대회": "28th Kim Chang-hwan Cup National Fencing Championship & National Team Selection",
    "제29회 김창환배전국남녀펜싱선수권대회 겸 국가대표선수 선발대회": "29th Kim Chang-hwan Cup National Fencing Championship & National Team Selection",
    "제30회 김창환배전국남녀펜싱선수권대회 겸 국가대표선수 선발대회": "30th Kim Chang-hwan Cup National Fencing Championship & National Team Selection",

    # === 대통령배전국남녀펜싱선수권대회 ===
    "제59회 대통령배 전국남·녀펜싱선수권대회 겸 국가대표 선수 선발대회": "59th President's Cup National Fencing Championship & National Team Selection",
    "제60회 대통령배전국남녀펜싱선수권대회": "60th President's Cup National Fencing Championship",
    "제61회 대통령배전국남녀펜싱선수권대회 겸 국가대표선수 선발대회": "61st President's Cup National Fencing Championship & National Team Selection",
    "제62회 대통령배전국남·녀펜싱선수권대회 겸 국가대표선수 선발대회": "62nd President's Cup National Fencing Championship & National Team Selection",
    "제63회 대통령배전국남녀펜싱선수권대회 겸 국가대표선수 선발대회": "63rd President's Cup National Fencing Championship & National Team Selection",
    "제64회 대통령배전국남·녀펜싱선수권대회 겸 국가대표선수 선발대회": "64th President's Cup National Fencing Championship & National Team Selection",
    "제65회 대통령배전국남·녀펜싱선수권대회 겸 국가대표선수 선발대회": "65th President's Cup National Fencing Championship & National Team Selection",

    # === 문화체육관광부장관기전국남녀중고펜싱선수권대회 ===
    "제47회 문화체육관광부장관기전국남녀중고펜싱선수권대회": "47th Minister of Culture Cup National Middle/High School Fencing Championship",
    "제48회 문화체육관광부장관기전국남녀중고펜싱선수권대회": "48th Minister of Culture Cup National Middle/High School Fencing Championship",
    "제49회 문화체육관광부장관기전국남녀중고펜싱선수권대회": "49th Minister of Culture Cup National Middle/High School Fencing Championship",
    "제50회 문화체육관광부장관기전국남녀중고펜싱선수권대회": "50th Minister of Culture Cup National Middle/High School Fencing Championship",
    "제51회 문화체육관광부장관기전국남녀중고펜싱선수권대회": "51st Minister of Culture Cup National Middle/High School Fencing Championship",
    "제52회 문화체육관광부장관기전국남녀중고펜싱선수권대회": "52nd Minister of Culture Cup National Middle/High School Fencing Championship",
    "제53회 문화체육관광부장관기전국남녀중고펜싱선수권대회": "53rd Minister of Culture Cup National Middle/High School Fencing Championship",

    # === 회장배전국남녀종별펜싱선수권대회 ===
    "제48회 회장배전국남·녀종별펭신선수권대회": "48th President's Cup National Category Fencing Championship",
    "제49회 회장배전국남녀종별펜싱선수권대회": "49th President's Cup National Category Fencing Championship",
    "제50회 회장배전국남녀종별펜싱선수권대회": "50th President's Cup National Category Fencing Championship",
    "제51회 회장배전국남·녀종별펜싱선수권대회": "51st President's Cup National Category Fencing Championship",
    "제52회 회장배전국남녀종별펜싱선수권대회": "52nd President's Cup National Category Fencing Championship",
    "제53회 회장배전국남녀종별펜싱선수권대회": "53rd President's Cup National Category Fencing Championship",
    "제54회 회장배전국남녀종별펜싱선수권대회": "54th President's Cup National Category Fencing Championship",

    # === 전국남녀종별펜싱선수권대회 ===
    "제57회 전국남녀종별펜싱선수권대회": "57th National Category Fencing Championship",
    "제58회 전국남녀종별펜싱선수권대회(고등부)": "58th National Category Fencing Championship (High School)",
    "제58회 전국남녀종별펜싱선수권대회(초·중·대·일반부 개최)": "58th National Category Fencing Championship (Elementary/Middle/University/Senior)",
    "제59회 전국남녀종별펜싱선수권대회": "59th National Category Fencing Championship",
    "제60회 전국남녀종별펜싱선수권대회": "60th National Category Fencing Championship",
    "제61회 전국남녀종별펜싱선수권대회": "61st National Category Fencing Championship",
    "제62회 전국남녀종별펜싱선수권대회": "62nd National Category Fencing Championship",
    "제63회 전국남녀종별펜싱선수권대회": "63rd National Category Fencing Championship",

    # === 한국대학펜싱연맹회장기전국남녀펜싱선수권대회 ===
    "제38회 한국대학펜싱연맹회장기 전국남녀대학펜싱선수권대회": "38th Korea University Fencing Federation President's Trophy Championship",
    "제39회 한국대학펜싱연맹회장기전국남녀펜싱선수권대회": "39th Korea University Fencing Federation President's Trophy Championship",
    "제40회 한국대학펜싱연맹회장기전국남녀펜싱선수권대회": "40th Korea University Fencing Federation President's Trophy Championship",
    "제41회 한국대학연맹회장기전국남녀펜싱선수권대회": "41st Korea University Fencing Federation President's Trophy Championship",
    "제42회 한국대학연맹회장기전국남녀펜싱선수권대회": "42nd Korea University Fencing Federation President's Trophy Championship",
    "제43회 한국대학연맹회장기전국남녀펜싱선수권대회": "43rd Korea University Fencing Federation President's Trophy Championship",

    # === 테스트 대회 (무시) ===
    "테스트_2019 대한펜싱협회 유소년 국가대표선수 선발전(여자 플러레)": "[TEST] 2019 KFA Youth National Team Selection (Women's Foil)",
}

# Additional pattern components (for fallback translation)
ADDITIONAL_PATTERNS = {
    "종별": "Category",
    "전국남녀": "National",
    "남녀": "",
    "남·녀": "",
}

# Event name component translations (종목명 구성요소)
EVENT_NAME_COMPONENTS = {
    # Gender
    "남자": "Men's",
    "여자": "Women's",
    "남녀": "Mixed",
    "혼성": "Mixed",

    # Weapons (Korean variants + English codes)
    "플뢰레": "Foil",
    "플러레": "Foil",
    "에뻬": "Epee",
    "에페": "Epee",
    "사브르": "Sabre",
    "foil": "Foil",
    "epee": "Epee",
    "sabre": "Sabre",

    # Age groups - Elementary
    "초등부": "Elementary",
    "초등1-2학년": "Y8 (Elem 1-2)",
    "초등3-4학년": "Y10 (Elem 3-4)",
    "초등5-6학년": "Y12 (Elem 5-6)",
    "1-2학년": "Grade 1-2",
    "3-4학년": "Grade 3-4",
    "5-6학년": "Grade 5-6",

    # Age groups - Secondary
    "중등부": "Middle School",
    "중학부": "Middle School",
    "고등부": "High School",
    "고교부": "High School",

    # Age groups - Adult
    "대학부": "University",
    "일반부": "Senior",
    "실업부": "Professional",

    # International age codes
    "U9": "U9",
    "U11": "U11",
    "U13": "U13",
    "U15": "U15",
    "U17": "U17",
    "U20": "U20",
    "9세이하": "Under 9",
    "11세이하": "Under 11",
    "13세이하": "Under 13",
    "15세이하": "Under 15",
    "17세이하": "Under 17",
    "20세이하": "Under 20",

    # Event types
    "개인": "Individual",
    "단체": "Team",
    "개인전": "Individual",
    "단체전": "Team",
}


class TranslationService:
    """
    Unified translation service for database content.

    Provides consistent interface for translating:
    - Player names (Korean -> English, Western order: Given Surname)
    - Organization names (Korean -> English)
    - Competition names (Korean -> English)
    """

    def __init__(self):
        self.intl_manager = InternationalDataManager()
        self.org_resolver = OrganizationIdentityResolver()

    def translate_player_name(self, korean_name: str) -> Dict[str, Any]:
        """
        Convert Korean player name to English romanization.

        Format: Western order (Given name + Surname)
        Example: 박소윤 -> Soyun Park

        Args:
            korean_name: Korean name (e.g., "박소윤")

        Returns:
            Translation dict for JSONB storage:
            {
                "en": {
                    "name": "Soyun Park",
                    "name_order": "western",
                    "verified": False,
                    "source": "romanization",
                    "updated_at": "2025-01-09T..."
                }
            }
        """
        if not korean_name:
            return {}

        korean_name = korean_name.strip()
        now = datetime.utcnow().isoformat() + "Z"

        # Check verified mappings first
        if korean_name in VERIFIED_NAME_MAPPINGS:
            verified = VERIFIED_NAME_MAPPINGS[korean_name]
            return {
                "en": {
                    "name": self._format_western_name(verified['en_given'], verified['en_surname']),
                    "name_order": "western",
                    "verified": True,
                    "source": "verified",
                    "fie_id": verified.get('fie_id'),
                    "fencingtracker_id": verified.get('fencingtracker_id'),
                    "updated_at": now,
                }
            }

        # Generate romanization
        candidates = generate_english_name_candidates(korean_name)
        if not candidates:
            # Fallback: simple romanization
            return self._fallback_romanization(korean_name)

        # Get the best Western-order candidate
        western_candidates = [c for c in candidates if c.name_order == 'western']
        if western_candidates:
            best = max(western_candidates, key=lambda c: c.confidence)
        else:
            best = max(candidates, key=lambda c: c.confidence)

        return {
            "en": {
                "name": best.full_name,
                "name_order": best.name_order,
                "verified": False,
                "source": best.source,
                "confidence": best.confidence,
                "updated_at": now,
            }
        }

    def _format_western_name(self, given: str, surname: str) -> str:
        """Format name in Western order (Given Surname)."""
        return f"{given} {surname}"

    def _fallback_romanization(self, korean_name: str) -> Dict[str, Any]:
        """Fallback romanization for names not matching standard patterns."""
        now = datetime.utcnow().isoformat() + "Z"

        # Assume first character is surname
        surname_kr = korean_name[0] if korean_name else ''
        given_kr = korean_name[1:] if len(korean_name) > 1 else ''

        # Get surname romanization
        surname_variants = KOREAN_SURNAMES.get(surname_kr, [])
        surname_en = surname_variants[0] if surname_variants else self._romanize_text(surname_kr).capitalize()

        # Romanize given name
        given_en = self._romanize_text(given_kr).capitalize()

        return {
            "en": {
                "name": f"{given_en} {surname_en}",
                "name_order": "western",
                "verified": False,
                "source": "fallback_romanization",
                "updated_at": now,
            }
        }

    def _romanize_text(self, text: str) -> str:
        """Romanize Korean text character by character."""
        result = ''
        for char in text:
            if is_korean_char(char):
                result += romanize_syllable(char)
            else:
                result += char
        return result

    def translate_organization_name(self, korean_name: str) -> Dict[str, Any]:
        """
        Convert Korean organization name to English.

        Example: 최병철펜싱클럽 -> Choi Byeongcheol Fencing Club

        Args:
            korean_name: Korean organization name

        Returns:
            Translation dict for JSONB storage
        """
        if not korean_name:
            return {}

        korean_name = korean_name.strip()
        now = datetime.utcnow().isoformat() + "Z"

        # Check verified mappings first
        if korean_name in VERIFIED_ORG_MAPPINGS:
            verified = VERIFIED_ORG_MAPPINGS[korean_name]
            return {
                "en": {
                    "name": verified["name_en"],
                    "verified": True,
                    "source": "verified",
                    "updated_at": now,
                }
            }

        # Use OrganizationIdentityResolver
        profile = self.org_resolver.get_or_create_organization(korean_name)

        return {
            "en": {
                "name": profile.name_en,
                "verified": profile.name_en_verified,
                "source": "auto_translation",
                "org_type": profile.org_type.value,
                "updated_at": now,
            }
        }

    def translate_competition_name(self, korean_name: str) -> Dict[str, Any]:
        """
        Convert Korean competition name to English.

        Example: 회장배 전국펜싱선수권대회 -> President's Cup National Fencing Championship

        Args:
            korean_name: Korean competition name

        Returns:
            Translation dict for JSONB storage
        """
        if not korean_name:
            return {}

        korean_name = korean_name.strip()
        now = datetime.utcnow().isoformat() + "Z"

        # Check verified mappings first
        if korean_name in VERIFIED_COMPETITION_MAPPINGS:
            return {
                "en": {
                    "name": VERIFIED_COMPETITION_MAPPINGS[korean_name],
                    "verified": True,
                    "source": "verified",
                    "updated_at": now,
                }
            }

        # Pattern-based translation
        english_name = self._translate_competition_pattern(korean_name)

        return {
            "en": {
                "name": english_name,
                "verified": False,
                "source": "pattern_translation",
                "updated_at": now,
            }
        }

    def _translate_competition_pattern(self, korean_name: str) -> str:
        """
        Translate competition name using pattern matching.

        Applies translations from longest to shortest patterns to avoid
        partial matches (e.g., "전국대회" before "대회").
        """
        result = korean_name

        # Sort patterns by length (longest first) to avoid partial matches
        sorted_patterns = sorted(
            COMPETITION_NAME_PATTERNS.items(),
            key=lambda x: len(x[0]),
            reverse=True
        )

        for korean, english in sorted_patterns:
            if korean in result:
                result = result.replace(korean, english + " ")

        # Also apply region translations
        for korean, english in sorted(
            KOREAN_REGIONS.items(),
            key=lambda x: len(x[0]),
            reverse=True
        ):
            if korean in result:
                result = result.replace(korean, english + " ")

        # Clean up: remove duplicate spaces and trim
        result = re.sub(r'\s+', ' ', result).strip()

        # Romanize any remaining Korean characters
        if re.search(r'[가-힣]', result):
            parts = []
            current = ""
            for char in result:
                if is_korean_char(char):
                    if current:
                        parts.append(current)
                        current = ""
                    parts.append(romanize_syllable(char))
                else:
                    current += char
            if current:
                parts.append(current)
            result = ''.join(parts).title()

        return result

    def get_localized_name(
        self,
        record: Dict[str, Any],
        lang: str,
        fallback_field: str = "name"
    ) -> str:
        """
        Get name in specified language with fallback to original.

        Args:
            record: Database record with 'translations' field
            lang: Target language code (e.g., 'en', 'ko')
            fallback_field: Field name to use as fallback

        Returns:
            Localized name or fallback value
        """
        # If requesting Korean, return original
        if lang == 'ko':
            return record.get(fallback_field, '')

        # Check translations
        translations = record.get('translations', {})
        if isinstance(translations, dict):
            lang_data = translations.get(lang, {})
            if isinstance(lang_data, dict) and lang_data.get('name'):
                return lang_data['name']

        # Fallback to original
        return record.get(fallback_field, '')

    def translate_event_name(self, korean_name: str) -> str:
        """
        Translate event name (종목명) to English.

        Example: "남자 플뢰레 고등부 개인" -> "Men's Foil High School Individual"

        Args:
            korean_name: Korean event name

        Returns:
            English event name
        """
        if not korean_name:
            return ""

        result = korean_name.strip()

        # Apply component translations (longest first to avoid partial matches)
        sorted_components = sorted(
            EVENT_NAME_COMPONENTS.items(),
            key=lambda x: len(x[0]),
            reverse=True
        )

        for korean, english in sorted_components:
            if korean in result:
                result = result.replace(korean, english)

        # Clean up spaces
        result = re.sub(r'\s+', ' ', result).strip()

        return result

    def get_localized_event_name(self, event: Dict[str, Any], lang: str) -> str:
        """
        Get event name in specified language.

        Args:
            event: Event data dict with 'name' field
            lang: Target language code

        Returns:
            Localized event name
        """
        if lang == 'ko':
            return event.get('name', '')

        korean_name = event.get('name', '')
        return self.translate_event_name(korean_name)

    def get_localized_competition_name(
        self,
        comp_info: Dict[str, Any],
        lang: str
    ) -> str:
        """
        Get competition name in specified language.

        Checks translations field first, then generates translation if needed.

        Args:
            comp_info: Competition data dict (with comp_name or name, and translations)
            lang: Target language code

        Returns:
            Localized competition name
        """
        korean_name = comp_info.get('comp_name', '') or comp_info.get('name', '')

        if lang == 'ko':
            return korean_name

        # Check existing translations in record
        translations = comp_info.get('translations', {})
        if isinstance(translations, dict):
            lang_data = translations.get(lang, {})
            if isinstance(lang_data, dict) and lang_data.get('name'):
                return lang_data['name']

        # Generate translation on-the-fly
        result = self.translate_competition_name(korean_name)
        return result.get('en', {}).get('name', korean_name)

    def batch_translate_players(
        self,
        players: List[Dict[str, Any]],
        name_field: str = "name"
    ) -> List[Dict[str, Any]]:
        """
        Batch translate player names.

        Args:
            players: List of player records
            name_field: Field containing Korean name

        Returns:
            List of translation dicts ready for DB update
        """
        results = []
        for player in players:
            korean_name = player.get(name_field, "")
            player_id = player.get("id")

            translation = self.translate_player_name(korean_name)

            results.append({
                "id": player_id,
                "translations": translation,
            })

        return results

    def batch_translate_organizations(
        self,
        organizations: List[Dict[str, Any]],
        name_field: str = "name"
    ) -> List[Dict[str, Any]]:
        """
        Batch translate organization names.

        Args:
            organizations: List of organization records
            name_field: Field containing Korean name

        Returns:
            List of translation dicts ready for DB update
        """
        results = []
        for org in organizations:
            korean_name = org.get(name_field, "")
            org_id = org.get("id")

            translation = self.translate_organization_name(korean_name)

            results.append({
                "id": org_id,
                "translations": translation,
            })

        return results

    def batch_translate_competitions(
        self,
        competitions: List[Dict[str, Any]],
        name_field: str = "name"
    ) -> List[Dict[str, Any]]:
        """
        Batch translate competition names.

        Args:
            competitions: List of competition records
            name_field: Field containing Korean name

        Returns:
            List of translation dicts ready for DB update
        """
        results = []
        for comp in competitions:
            korean_name = comp.get(name_field, "")
            comp_id = comp.get("id")

            translation = self.translate_competition_name(korean_name)

            results.append({
                "id": comp_id,
                "translations": translation,
            })

        return results


# Singleton instance
_translation_service: Optional[TranslationService] = None


def get_translation_service() -> TranslationService:
    """Get or create singleton TranslationService instance."""
    global _translation_service
    if _translation_service is None:
        _translation_service = TranslationService()
    return _translation_service


# Quick test
if __name__ == "__main__":
    ts = TranslationService()

    print("=== Player Name Tests ===")
    test_names = ["박소윤", "김철수", "공하이", "송세라", "이민지"]
    for name in test_names:
        result = ts.translate_player_name(name)
        print(f"{name} -> {result.get('en', {}).get('name', 'N/A')}")

    print("\n=== Organization Name Tests ===")
    test_orgs = ["최병철펜싱클럽", "서울체육고등학교", "한국체육대학교", "부산시청", "송도펜싱클럽"]
    for org in test_orgs:
        result = ts.translate_organization_name(org)
        print(f"{org} -> {result.get('en', {}).get('name', 'N/A')}")

    print("\n=== Competition Name Tests ===")
    test_comps = ["회장배 전국펜싱선수권대회", "전국체육대회", "전국종별펜싱선수권대회", "꿈나무 전국펜싱대회"]
    for comp in test_comps:
        result = ts.translate_competition_name(comp)
        print(f"{comp} -> {result.get('en', {}).get('name', 'N/A')}")
