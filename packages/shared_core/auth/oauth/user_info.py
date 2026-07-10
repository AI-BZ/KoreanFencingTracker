"""
OAuth 사용자 정보 정규화

각 프로바이더별 사용자 정보를 통일된 형식으로 변환
"""
import httpx
from fastapi import HTTPException

from .providers import OAUTH_PROVIDERS


async def get_oauth_user_info(provider: str, access_token: str) -> dict:
    """
    OAuth 사용자 정보 가져오기

    Args:
        provider: OAuth 프로바이더 이름
        access_token: OAuth 액세스 토큰

    Returns:
        정규화된 사용자 정보 {"id": str, "email": Optional[str], "name": Optional[str]}
    """
    config = OAUTH_PROVIDERS[provider]

    async with httpx.AsyncClient() as client:
        if provider == "kakao":
            response = await client.get(
                config["userinfo_url"],
                headers={"Authorization": f"Bearer {access_token}"}
            )
            data = response.json()
            return {
                "id": str(data["id"]),
                "email": data.get("kakao_account", {}).get("email"),
                "name": data.get("properties", {}).get("nickname"),
            }

        elif provider == "google":
            response = await client.get(
                config["userinfo_url"],
                headers={"Authorization": f"Bearer {access_token}"}
            )
            data = response.json()
            return {
                "id": data["id"],
                "email": data.get("email"),
                "name": data.get("name"),
            }

        elif provider == "x":
            response = await client.get(
                config["userinfo_url"],
                headers={"Authorization": f"Bearer {access_token}"},
                params={"user.fields": "id,name,username"}
            )
            data = response.json()
            user_data = data.get("data", {})
            return {
                "id": user_data.get("id"),
                "email": None,
                "name": user_data.get("name"),
            }

        else:
            raise HTTPException(status_code=400, detail=f"지원하지 않는 제공자: {provider}")
