"""
종목 정보 파서
"""
from typing import List, Dict, Any
import re
from loguru import logger

from ..models import Event, Weapon, Gender


class EventParser:
    """종목 정보 파서"""

    @staticmethod
    def parse_json(json_data: List[Dict[str, Any]], event_cd: str) -> List[Event]:
        """JSON 응답에서 종목 정보 파싱"""
        events = []

        for item in json_data:
            try:
                event = EventParser._parse_item(item, event_cd)
                events.append(event)
            except Exception as e:
                logger.error(f"종목 파싱 오류: {e}")

        return events

    @staticmethod
    def _parse_item(item: Dict[str, Any], event_cd: str) -> Event:
        """단일 종목 아이템 파싱"""
        event_name = item.get("subEventNm", "")

        # 종목명에서 무기, 성별, 연령대 추출
        weapon = EventParser._extract_weapon(event_name)
        gender = EventParser._extract_gender(event_name)
        category = EventParser._extract_category(event_name)
        age_group = EventParser._extract_age_group(event_name)

        return Event(
            event_cd=event_cd,
            sub_event_cd=item.get("subEventCd"),
            event_name=event_name,
            weapon=weapon,
            gender=gender,
            category=category,
            age_group=age_group,
            raw_data=item
        )

    @staticmethod
    def _extract_weapon(event_name: str) -> Weapon:
        """종목명에서 무기 추출"""
        weapon_patterns = {
            Weapon.FOIL: ["플뢰레", "플로레", "foil", "FL"],
            Weapon.EPEE: ["에페", "epee", "EP"],
            Weapon.SABRE: ["사브르", "세이버", "sabre", "saber", "SA"],
        }

        for weapon, patterns in weapon_patterns.items():
            for pattern in patterns:
                if pattern.lower() in event_name.lower():
                    return weapon

        return Weapon.UNKNOWN

    @staticmethod
    def _extract_gender(event_name: str) -> Gender:
        """종목명에서 성별 추출"""
        if any(g in event_name for g in ["남자", "남성", "M ", "Men"]):
            return Gender.MALE
        elif any(g in event_name for g in ["여자", "여성", "W ", "Women"]):
            return Gender.FEMALE
        elif any(g in event_name for g in ["혼성", "Mixed"]):
            return Gender.MIXED
        return Gender.UNKNOWN

    @staticmethod
    def _extract_category(event_name: str) -> str:
        """종목명에서 개인/단체 구분 추출"""
        if any(c in event_name for c in ["개인", "Individual"]):
            return "개인"
        elif any(c in event_name for c in ["단체", "Team"]):
            return "단체"
        return ""

    @staticmethod
    def _extract_age_group(event_name: str) -> str:
        """종목명에서 연령대 추출"""
        age_groups = {
            "시니어": ["시니어", "Senior", "성인"],
            "주니어": ["주니어", "Junior", "Jr"],
            "카뎃": ["카뎃", "Cadet"],
            "유소년": ["유소년", "Youth"],
            "베테랑": ["베테랑", "Veteran"],
            "마스터즈": ["마스터즈", "Masters"],
            "초등": ["초등", "Elementary"],
            "중등": ["중등", "Middle"],
            "고등": ["고등", "High"],
            "대학": ["대학", "University", "College"],
        }

        for group, patterns in age_groups.items():
            for pattern in patterns:
                if pattern in event_name:
                    return group

        return ""
