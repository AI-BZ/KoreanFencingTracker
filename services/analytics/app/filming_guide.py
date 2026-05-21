"""
Filming guide for fencing match recording.

Provides camera positioning, settings, and composition
recommendations per video source type and weapon.
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class FilmingGuide:
    """Structured filming recommendations."""
    source_type: str
    weapon: Optional[str]
    language: str
    camera_position: str
    camera_height: str
    frame_composition: str
    resolution_recommendation: str
    lighting_tips: List[str] = field(default_factory=list)
    common_mistakes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source_type": self.source_type,
            "weapon": self.weapon,
            "language": self.language,
            "camera_position": self.camera_position,
            "camera_height": self.camera_height,
            "frame_composition": self.frame_composition,
            "resolution_recommendation": self.resolution_recommendation,
            "lighting_tips": self.lighting_tips,
            "common_mistakes": self.common_mistakes,
        }


_GUIDES = {
    "coach": {
        "ko": {
            "camera_position": "피스트 측면 중앙, 3-4m 거리",
            "camera_height": "삼각대, 1m 높이 (허리 높이)",
            "frame_composition": "양 선수 전신 + 점수판이 프레임 안에 보이도록",
            "resolution_recommendation": "1080p 30fps 이상, 가로 모드",
            "lighting_tips": [
                "자동 노출(AE) 끄기 — LED 점수판이 노출을 방해함",
                "역광 피하기 — 창문이나 조명이 뒤에 오지 않게 배치",
                "실내 조명이 균일한지 확인",
            ],
            "common_mistakes": [
                "세로 모드로 촬영 (가로 모드 필수)",
                "점수판이 프레임 밖에 있음",
                "한 선수만 클로즈업 (양 선수 전체 보여야 함)",
                "촬영 중 핸드폰 이동 (삼각대 고정 권장)",
            ],
        },
        "en": {
            "camera_position": "Piste side, center, 3-4m distance",
            "camera_height": "Tripod at 1m height (waist level)",
            "frame_composition": "Both fencers' full body + scoreboard visible",
            "resolution_recommendation": "1080p 30fps minimum, landscape mode",
            "lighting_tips": [
                "Disable auto-exposure — LED scoreboard disrupts metering",
                "Avoid backlighting — no windows or lights behind fencers",
                "Ensure uniform indoor lighting",
            ],
            "common_mistakes": [
                "Portrait mode recording (use landscape)",
                "Scoreboard out of frame",
                "Close-up of one fencer only (show both)",
                "Moving phone during recording (use tripod)",
            ],
        },
    },
    "parent": {
        "ko": {
            "camera_position": "관중석에서 피스트 중앙을 향해",
            "camera_height": "가능하면 눈높이, 높은 위치가 좋음",
            "frame_composition": "피스트 전체가 보이도록, 가로 모드",
            "resolution_recommendation": "1080p 30fps, 가로 모드",
            "lighting_tips": [
                "줌 사용 자제 — 흔들림 증가",
                "가능하면 손목 안정 또는 난간에 기대기",
            ],
            "common_mistakes": [
                "과도한 줌으로 시야 좁아짐",
                "세로 모드 촬영",
                "특정 선수만 따라가기 (전체 피스트 유지)",
            ],
        },
        "en": {
            "camera_position": "From spectator stand facing piste center",
            "camera_height": "Eye level or higher if possible",
            "frame_composition": "Full piste visible, landscape mode",
            "resolution_recommendation": "1080p 30fps, landscape mode",
            "lighting_tips": [
                "Avoid excessive zoom — increases shake",
                "Stabilize wrist or lean on railing if possible",
            ],
            "common_mistakes": [
                "Too much zoom narrows field of view",
                "Portrait mode recording",
                "Following one fencer only (keep full piste)",
            ],
        },
    },
    "player": {
        "ko": {
            "camera_position": "피스트 끝에서 정면 또는 측면",
            "camera_height": "삼각대 1m, 또는 벽/펜스에 고정",
            "frame_composition": "자신의 전신이 보이도록",
            "resolution_recommendation": "720p 이상, 가로 모드",
            "lighting_tips": [
                "자신 뒤에 강한 조명이 없도록",
                "거울 앞 연습 시 반사 주의",
            ],
            "common_mistakes": [
                "너무 가까이 촬영 (발까지 보여야 함)",
                "세로 모드 촬영",
            ],
        },
        "en": {
            "camera_position": "End of piste, front or side view",
            "camera_height": "Tripod at 1m, or fixed on wall/fence",
            "frame_composition": "Full body visible",
            "resolution_recommendation": "720p minimum, landscape mode",
            "lighting_tips": [
                "No strong light behind you",
                "Watch for reflections when practicing with mirrors",
            ],
            "common_mistakes": [
                "Too close — feet must be visible",
                "Portrait mode recording",
            ],
        },
    },
}


def get_filming_guide(
    source_type: str = "coach",
    weapon: Optional[str] = None,
    language: str = "ko",
) -> FilmingGuide:
    """
    Get filming recommendations for a video source type.

    Args:
        source_type: "coach", "parent", or "player"
        weapon: Optional weapon type (foil/epee/sabre) for specific tips
        language: "ko" or "en"

    Returns:
        FilmingGuide with structured recommendations.
    """
    type_guides = _GUIDES.get(source_type, _GUIDES["coach"])
    guide_data = type_guides.get(language, type_guides.get("ko", {}))

    return FilmingGuide(
        source_type=source_type,
        weapon=weapon,
        language=language,
        camera_position=guide_data.get("camera_position", ""),
        camera_height=guide_data.get("camera_height", ""),
        frame_composition=guide_data.get("frame_composition", ""),
        resolution_recommendation=guide_data.get("resolution_recommendation", ""),
        lighting_tips=guide_data.get("lighting_tips", []),
        common_mistakes=guide_data.get("common_mistakes", []),
    )
