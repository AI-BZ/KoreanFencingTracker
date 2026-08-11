"""
카카오 로컬 API를 사용한 조직 주소 수집 스크립트

사용법:
    PYTHONPATH="." python scripts/collect_addresses_kakao.py
    PYTHONPATH="." python scripts/collect_addresses_kakao.py --type club
    PYTHONPATH="." python scripts/collect_addresses_kakao.py --type club,middle,high
    PYTHONPATH="." python scripts/collect_addresses_kakao.py --dry-run  # DB 저장 안 함
"""
import argparse
import os
import re
import sys
import time
from typing import Dict, List, Optional

import httpx
from dotenv import load_dotenv
from loguru import logger
from supabase import create_client

load_dotenv()

logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}")

KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# 시도 정규화 매핑
PROVINCE_MAP = {
    "서울특별시": "서울", "서울시": "서울", "서울": "서울",
    "부산광역시": "부산", "부산시": "부산", "부산": "부산",
    "대구광역시": "대구", "대구시": "대구", "대구": "대구",
    "인천광역시": "인천", "인천시": "인천", "인천": "인천",
    "광주광역시": "광주", "광주시": "광주", "광주": "광주",
    "대전광역시": "대전", "대전시": "대전", "대전": "대전",
    "울산광역시": "울산", "울산시": "울산", "울산": "울산",
    "세종특별자치시": "세종", "세종시": "세종", "세종": "세종",
    "경기도": "경기", "경기": "경기",
    "강원특별자치도": "강원", "강원도": "강원", "강원": "강원",
    "충청북도": "충북", "충북": "충북",
    "충청남도": "충남", "충남": "충남",
    "전북특별자치도": "전북", "전라북도": "전북", "전북": "전북",
    "전라남도": "전남", "전남": "전남",
    "경상북도": "경북", "경북": "경북",
    "경상남도": "경남", "경남": "경남",
    "제주특별자치도": "제주", "제주도": "제주", "제주": "제주",
}


def normalize_province(addr: str) -> str:
    """주소에서 시도를 추출하여 정규화"""
    for full, short in PROVINCE_MAP.items():
        if addr.startswith(full):
            return short
    return ""


def extract_city(addr: str, province: str) -> str:
    """주소에서 시/군/구 추출"""
    # 시도 부분 제거 후 시/군/구 추출
    rest = addr
    for full in PROVINCE_MAP:
        if rest.startswith(full):
            rest = rest[len(full):].strip()
            break

    # 시/군/구 추출
    m = re.match(r'([가-힣]+(?:시|군|구))', rest)
    if m:
        token = m.group(1)
        # "시" 제거 (예: 성남시 → 성남), 단 "시"만 있는 경우 유지
        for suffix in ("시", "군"):
            if token.endswith(suffix) and len(token) > 1:
                return token[:-1]
        return token
    return ""


def search_kakao_local(query: str, client: httpx.Client) -> Optional[Dict]:
    """카카오 로컬 API 키워드 검색

    Returns: {place_name, road_address, address, phone, x, y} or None
    """
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}

    resp = client.get(url, headers=headers, params={"query": query, "size": 1})
    if resp.status_code != 200:
        logger.error(f"API 오류 {resp.status_code}: {resp.text[:200]}")
        return None

    data = resp.json()
    documents = data.get("documents", [])
    if not documents:
        return None

    doc = documents[0]
    return {
        "place_name": doc.get("place_name", ""),
        "road_address": doc.get("road_address_name", ""),
        "address": doc.get("address_name", ""),
        "phone": doc.get("phone", ""),
        "x": doc.get("x", ""),
        "y": doc.get("y", ""),
        "category": doc.get("category_name", ""),
    }


def build_search_queries(name: str, org_type: str) -> List[str]:
    """검색어 후보 리스트 생성 (순서대로 시도)"""
    queries = [name]  # 원래 이름 그대로

    # 펜싱 키워드 추가
    if "펜싱" not in name:
        queries.append(f"{name} 펜싱")

    # 학교의 경우 약어 확장
    if org_type in ("middle", "high"):
        expanded = name
        if name.endswith("중") and not name.endswith("중학교"):
            expanded = name + "학교"
        elif name.endswith("고") and not name.endswith("고등학교"):
            expanded = name + "등학교"
        if expanded != name:
            queries.insert(0, expanded)  # 확장형 우선

    return queries


def is_relevant_result(result: Dict, name: str, org_type: str) -> bool:
    """검색 결과가 해당 조직과 관련 있는지 판단"""
    place = result.get("place_name", "")
    category = result.get("category", "")

    # 학교: 카테고리에 "학교"가 포함되어야 함
    if org_type in ("middle", "high"):
        if "학교" in category or "학원" in category or "교육" in category:
            return True
        if "학교" in place:
            return True
        return False

    # 클럽: 스포츠/펜싱 관련 카테고리
    if org_type == "club":
        sport_keywords = ["스포츠", "체육", "펜싱", "학원", "교육", "레저"]
        if any(kw in category for kw in sport_keywords):
            return True
        # 이름이 충분히 겹치면 OK
        if place and (name[:3] in place or place[:3] in name):
            return True
        return False

    return True


def main():
    parser = argparse.ArgumentParser(description="카카오 로컬 API로 조직 주소 수집")
    parser.add_argument("--type", default="club,middle,high",
                        help="수집 대상 org_type (쉼표 구분)")
    parser.add_argument("--dry-run", action="store_true",
                        help="DB 저장 안 하고 결과만 출력")
    parser.add_argument("--force", action="store_true",
                        help="이미 주소가 있어도 재수집")
    args = parser.parse_args()

    if not KAKAO_REST_API_KEY:
        logger.error("KAKAO_REST_API_KEY가 .env에 설정되지 않았습니다")
        sys.exit(1)

    org_types = [t.strip() for t in args.type.split(",")]
    logger.info(f"수집 대상: {org_types}")

    # DB 연결
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # 주소 없는 조직 조회
    query = supabase.table("organizations").select("id, name, org_type, road_address, province")
    query = query.in_("org_type", org_types)
    if not args.force:
        query = query.or_("road_address.is.null,road_address.eq.,province.is.null,province.eq.")
    result = query.execute()

    orgs = result.data or []
    logger.info(f"수집 대상 조직: {len(orgs)}개")

    if not orgs:
        logger.info("수집할 조직이 없습니다")
        return

    # 카카오 API 호출
    collected = 0
    failed = 0
    skipped = 0

    with httpx.Client(timeout=10) as client:
        for i, org in enumerate(orgs):
            name = org["name"]
            org_type = org["org_type"]
            org_id = org["id"]

            queries = build_search_queries(name, org_type)
            found = False

            for q in queries:
                result = search_kakao_local(q, client)
                if not result:
                    continue

                if not is_relevant_result(result, name, org_type):
                    logger.debug(f"  관련 없는 결과 건너뜀: {result['place_name']} ({result['category']})")
                    continue

                road_addr = result["road_address"] or result["address"]
                if not road_addr:
                    continue

                province = normalize_province(road_addr)
                city = extract_city(road_addr, province)

                if not province:
                    logger.warning(f"  시도 추출 실패: {road_addr}")
                    continue

                logger.success(
                    f"[{i+1}/{len(orgs)}] ✅ {name} → {road_addr} ({province} {city})"
                )

                if not args.dry_run:
                    update_data = {
                        "road_address": result["road_address"],
                        "province": province,
                        "address_source": "kakao_api",
                        "address_status": "collected",
                        "address_error": "",
                    }
                    if city:
                        # city는 organizations 테이블에 없을 수 있으므로 road_address에서 유추
                        pass
                    if result.get("phone"):
                        update_data["phone"] = result["phone"]
                    if result.get("x") and result.get("y"):
                        update_data["longitude"] = float(result["x"])
                        update_data["latitude"] = float(result["y"])

                    try:
                        supabase.table("organizations").update(update_data).eq("id", org_id).execute()
                    except Exception as e:
                        logger.error(f"  DB 저장 실패: {e}")

                collected += 1
                found = True
                break

            if not found:
                failed += 1
                logger.warning(f"[{i+1}/{len(orgs)}] ❌ {name} → 검색 실패")

                if not args.dry_run:
                    try:
                        supabase.table("organizations").update({
                            "address_source": "kakao_api",
                            "address_status": "manual_required",
                            "address_error": "카카오 로컬 API 검색 결과 없음",
                        }).eq("id", org_id).execute()
                    except Exception:
                        pass

            # Rate limiting (초당 약 5건)
            time.sleep(0.2)

    logger.info("=" * 60)
    logger.info(f"수집 완료: 성공 {collected}, 실패 {failed}, 총 {len(orgs)}")
    logger.info(f"성공률: {collected / max(len(orgs), 1) * 100:.1f}%")
    if args.dry_run:
        logger.info("(dry-run 모드: DB 저장 안 함)")


if __name__ == "__main__":
    main()
