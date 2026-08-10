"""
BRN (Business Registration Number) Validation

사업자등록번호 검증 유틸리티:
- Check Digit 검증 (오프라인)
- 국세청 API 진위확인
"""
import httpx
from loguru import logger


NTS_BASE = "https://api.odcloud.kr/api/nts-businessman/v1"


def validate_brn_checkdigit(brn: str) -> bool:
    """
    사업자등록번호 체크디짓 검증 (XXX-XX-XXXXX)

    한국 사업자등록번호 10자리의 마지막 자리가 체크디짓.
    가중치 [1, 3, 7, 1, 3, 7, 1, 3, 5]를 적용하여 검증.

    Args:
        brn: 사업자등록번호 ("123-45-67890" 또는 "1234567890" 형식)

    Returns:
        bool: 체크디짓 유효 여부
    """
    brn = brn.replace("-", "").replace(" ", "")
    if len(brn) != 10 or not brn.isdigit():
        return False

    weights = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    digits = [int(d) for d in brn]

    total = sum(d * w for d, w in zip(digits[:9], weights))
    total += (digits[8] * 5) // 10

    check = (10 - (total % 10)) % 10
    return check == digits[9]


async def verify_business_registration_nts(
    brn: str,
    representative_name: str,
    opening_date: str,
    api_key: str,
) -> dict:
    """
    국세청 사업자등록 진위확인 API (무료, data.go.kr 발급)

    Args:
        brn: 사업자등록번호 (하이픈 포함/미포함 모두 가능)
        representative_name: 대표자 성명
        opening_date: 개업년월일 ("YYYYMMDD" 형식)
        api_key: data.go.kr API 키

    Returns:
        dict: {
            "valid": bool,       # 진위확인 결과
            "status": str,       # 사업 상태 텍스트 (계속사업자/휴업/폐업)
            "status_code": str,  # 상태 코드 (01=계속, 02=휴업, 03=폐업)
            "tax_type": str,     # 과세 유형
            "raw": dict,         # 원본 응답
        }
    """
    url = f"{NTS_BASE}/validate?serviceKey={api_key}"
    payload = {
        "businesses": [{
            "b_no": brn.replace("-", "").replace(" ", ""),
            "start_dt": opening_date.replace("-", ""),
            "p_nm": representative_name,
        }]
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)

            if resp.status_code != 200:
                logger.error(f"NTS API error: {resp.status_code} - {resp.text[:200]}")
                return {
                    "valid": False,
                    "status": "api_error",
                    "status_code": None,
                    "tax_type": None,
                    "raw": {"error": f"HTTP {resp.status_code}"},
                }

            result = resp.json()

        if not result.get("data"):
            logger.error(f"NTS API: No data in response: {result}")
            return {
                "valid": False,
                "status": "no_data",
                "status_code": None,
                "tax_type": None,
                "raw": result,
            }

        item = result["data"][0]
        return {
            "valid": item.get("valid") == "01",
            "status": item.get("b_stt"),
            "status_code": item.get("b_stt_cd"),
            "tax_type": item.get("tax_type"),
            "raw": item,
        }

    except httpx.TimeoutException:
        logger.error("NTS API: Request timeout")
        return {
            "valid": False,
            "status": "timeout",
            "status_code": None,
            "tax_type": None,
            "raw": {"error": "timeout"},
        }
    except Exception as e:
        logger.error(f"NTS API unexpected error: {e}")
        return {
            "valid": False,
            "status": "error",
            "status_code": None,
            "tax_type": None,
            "raw": {"error": str(e)},
        }
