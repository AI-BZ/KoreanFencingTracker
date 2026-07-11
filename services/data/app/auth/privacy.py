"""
Privacy Module - Shim (호환성 유지)

실제 구현은 shared_core.privacy에 위치.
기존 import 경로를 유지하기 위한 re-export 파일.
"""
from shared_core.privacy.masking import (
    mask_korean_name,
    mask_email,
    mask_phone,
    CHOSUNG_LIST,
    CHOSUNG_EN,
)
from shared_core.privacy.anonymize import (
    anonymize_team,
    is_minor,
    get_age,
)
from shared_core.types.organization import ORG_TYPE_LABELS

__all__ = [
    "mask_korean_name",
    "mask_email",
    "mask_phone",
    "anonymize_team",
    "is_minor",
    "get_age",
    "CHOSUNG_LIST",
    "CHOSUNG_EN",
    "ORG_TYPE_LABELS",
]
