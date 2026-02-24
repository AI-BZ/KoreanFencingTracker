"""
서비스 타입 정의

FencingMind의 6개 서브도메인 서비스 Enum
"""
from enum import Enum


class ServiceType(str, Enum):
    """FencingMind 서비스 유형"""
    DATA = "data"              # data.fencingmind.ai
    CLUB = "club"              # club.fencingmind.ai
    COMMUNITY = "community"    # community.fencingmind.ai
    SHOP = "shop"              # shop.fencingmind.ai
    BLOG = "blog"              # blog.fencingmind.ai
    ANALYTICS = "analytics"    # analytics.fencingmind.ai


class SubscriptionTier(str, Enum):
    """구독 등급"""
    FREE = "free"
    BASIC = "basic"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(str, Enum):
    """구독 상태"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
