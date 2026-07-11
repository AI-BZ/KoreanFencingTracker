"""
OAuth 프로바이더 설정

Kakao, Google, X(Twitter) OAuth 프로바이더 목록 및 필터 함수
"""
from typing import Optional, List


# OAuth Provider 설정
OAUTH_PROVIDERS = {
    "kakao": {
        "enabled": True,
        "region_restriction": "KR",
        "authorize_url": "https://kauth.kakao.com/oauth/authorize",
        "token_url": "https://kauth.kakao.com/oauth/token",
        "userinfo_url": "https://kapi.kakao.com/v2/user/me",
        "scopes": ["profile_nickname"],
    },
    "google": {
        "enabled": True,
        "region_restriction": None,
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v2/userinfo",
        "scopes": ["openid", "email", "profile"],
    },
    "x": {
        "enabled": True,
        "region_restriction": None,
        "promotional_only": True,
        "authorize_url": "https://twitter.com/i/oauth2/authorize",
        "token_url": "https://api.twitter.com/2/oauth2/token",
        "userinfo_url": "https://api.twitter.com/2/users/me",
        "scopes": ["tweet.read", "users.read"],
    },
    "line": {
        "enabled": False,
        "region_restriction": None,
        "authorize_url": "https://access.line.me/oauth2/v2.1/authorize",
        "token_url": "https://api.line.me/oauth2/v2.1/token",
        "userinfo_url": "https://api.line.me/v2/profile",
        "scopes": ["profile", "openid"],
    },
}


def get_available_providers(country_code: Optional[str] = None) -> List[str]:
    """국가 코드에 따라 사용 가능한 OAuth 제공자 목록 반환"""
    providers = []
    for provider, config in OAUTH_PROVIDERS.items():
        if not config.get("enabled", False):
            continue
        if config.get("promotional_only", False):
            continue
        region = config.get("region_restriction")
        if region and country_code and country_code != region:
            continue
        providers.append(provider)
    if country_code == "KR" and "kakao" in providers:
        providers.remove("kakao")
        providers.insert(0, "kakao")
    return providers


def get_promotional_providers() -> List[str]:
    """홍보용 연동 가능한 OAuth 제공자 목록 반환"""
    return [
        provider for provider, config in OAUTH_PROVIDERS.items()
        if config.get("enabled", False) and config.get("promotional_only", False)
    ]
