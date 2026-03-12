"""
Claims Router - 선수 데이터 Claim 및 조직 소유권 Claim 엔드포인트

/account/verification 접두사 하위에 등록됨.
최종 경로:
  - /account/verification/player-search
  - /account/verification/player-claim
  - /account/verification/player-claim/status
  - /account/verification/org-claim
  - /account/verification/org-claim/status
"""
import json
from datetime import datetime
from typing import Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from loguru import logger
from pydantic import BaseModel

from shared_core.auth.jwt import get_current_member
from shared_core.db.client import get_supabase_client

from ..config import get_account_settings, VERIFICATION_PROMPTS
from .processor import GeminiVerifier
from .brn import validate_brn_checkdigit, verify_business_registration_nts

router = APIRouter(tags=["claims"])


# =============================================
# Pydantic Models
# =============================================

class PlayerClaimRequest(BaseModel):
    """선수 Claim 요청"""
    player_id: int
    evidence_text: Optional[str] = None


class OrgClaimRequest(BaseModel):
    """조직 Claim 요청"""
    organization_id: int
    claim_type: str = "director"  # director, head_coach, representative


# =============================================
# Player Claim Confidence Scoring
# =============================================

def calculate_claim_confidence(member: dict, player: dict) -> float:
    """
    선수 Claim 매칭 점수 계산

    가중치:
    - 이름 일치: 0.35
    - 생년 일치: 0.25
    - 소속팀 일치: 0.25
    - 무기 일치: 0.10
    - 최근 대회 참가: 0.05
    """
    score = 0.0

    # Name match (0.35)
    member_name = (member.get("full_name") or "").strip()
    player_name = (player.get("name") or "").strip()
    if member_name and player_name:
        # Exact match
        if member_name == player_name:
            score += 0.35
        # Partial match (contained in each other)
        elif member_name in player_name or player_name in member_name:
            score += 0.25
        else:
            # Character overlap similarity
            common = set(member_name) & set(player_name)
            if common:
                similarity = len(common) / max(len(member_name), len(player_name))
                if similarity >= 0.7:
                    score += 0.20

    # Birth year match (0.25)
    member_birth = member.get("birth_date")
    player_birth_year = player.get("birth_year")
    if member_birth and player_birth_year:
        member_year = str(member_birth)[:4]
        if member_year == str(player_birth_year):
            score += 0.25

    # Team match (0.25)
    member_org_id = member.get("organization_id")
    player_team = (player.get("team_name") or "").strip()
    if member_org_id and player_team:
        try:
            supabase = get_supabase_client()
            org_result = supabase.table("organizations").select("name").eq(
                "id", member_org_id
            ).single().execute()
            if org_result.data:
                org_name = (org_result.data.get("name") or "").strip()
                if org_name and player_team:
                    if org_name == player_team:
                        score += 0.25
                    elif org_name in player_team or player_team in org_name:
                        score += 0.15
        except Exception as e:
            logger.debug(f"Team match lookup failed: {e}")

    # Weapon match (0.10) - check from player's event history
    # This would require joining events table; for now check if player has weapon info
    player_weapon = player.get("weapon")
    if player_weapon:
        score += 0.05  # Partial credit for having weapon data available

    # Recent competition (0.05) - check if player has recent data
    player_last_comp = player.get("last_competition_date")
    if player_last_comp:
        score += 0.05

    return round(min(score, 1.0), 2)


# =============================================
# Player Claim Endpoints
# =============================================

@router.get("/player-search")
async def search_players_for_claim(
    request: Request,
    name: str,
    birth_year: Optional[int] = None,
    team: Optional[str] = None,
    weapon: Optional[str] = None,
):
    """
    선수 데이터 검색 (Claim용)

    GET /account/verification/player-search?name=홍길동&birth_year=2005
    """
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    if not name or len(name.strip()) < 2:
        raise HTTPException(status_code=400, detail="이름은 2자 이상이어야 합니다")

    supabase = get_supabase_client()

    # Build query - search players table
    query = supabase.table("players").select(
        "id, name, team_name, birth_year, gender, weapon, "
        "competition_count, last_competition_date"
    ).ilike("name", f"%{name.strip()}%")

    if birth_year:
        query = query.eq("birth_year", birth_year)

    if team:
        query = query.ilike("team_name", f"%{team.strip()}%")

    if weapon:
        query = query.eq("weapon", weapon)

    query = query.limit(20)

    try:
        result = query.execute()
    except Exception as e:
        logger.error(f"Player search error: {e}")
        raise HTTPException(status_code=500, detail="선수 검색 중 오류가 발생했습니다")

    candidates = []
    for player in (result.data or []):
        # Calculate confidence for each candidate
        confidence = calculate_claim_confidence(member, player)
        candidates.append({
            "player_id": player["id"],
            "name": player.get("name"),
            "team_name": player.get("team_name"),
            "birth_year": player.get("birth_year"),
            "gender": player.get("gender"),
            "weapon": player.get("weapon"),
            "competition_count": player.get("competition_count"),
            "last_competition_date": player.get("last_competition_date"),
            "confidence": confidence,
        })

    # Sort by confidence descending
    candidates.sort(key=lambda x: x["confidence"], reverse=True)

    return {"candidates": candidates, "total": len(candidates)}


@router.post("/player-claim")
async def submit_player_claim(
    request: Request,
    claim: PlayerClaimRequest,
):
    """
    선수 데이터 Claim 제출

    POST /account/verification/player-claim
    Body: { "player_id": 123, "evidence_text": "..." }

    Auto-approve: confidence >= 0.85
    Manual review: 0.50 <= confidence < 0.85
    Reject: confidence < 0.50
    """
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    settings = get_account_settings()
    supabase = get_supabase_client()

    # Check if member already has an approved claim
    existing_claim = supabase.table("player_claims").select("id, status").eq(
        "member_id", member["id"]
    ).eq("status", "approved").execute()

    if existing_claim.data:
        raise HTTPException(
            status_code=409,
            detail="이미 승인된 선수 Claim이 있습니다. 기존 Claim을 취소한 후 다시 시도하세요."
        )

    # Check if this player is already claimed by someone else
    player_claimed = supabase.table("player_claims").select("id").eq(
        "player_id", claim.player_id
    ).eq("status", "approved").execute()

    if player_claimed.data:
        raise HTTPException(
            status_code=409,
            detail="이 선수는 이미 다른 회원에 의해 Claim되었습니다."
        )

    # Get the player data
    try:
        player_result = supabase.table("players").select("*").eq(
            "id", claim.player_id
        ).single().execute()
    except Exception:
        raise HTTPException(status_code=404, detail="선수 정보를 찾을 수 없습니다")

    if not player_result.data:
        raise HTTPException(status_code=404, detail="선수 정보를 찾을 수 없습니다")

    player = player_result.data

    # Calculate confidence
    confidence = calculate_claim_confidence(member, player)

    # Build evidence
    evidence = {
        "member_name": member.get("full_name"),
        "player_name": player.get("name"),
        "confidence_breakdown": {
            "name_match": member.get("full_name") == player.get("name"),
            "birth_year_match": (
                str(member.get("birth_date", ""))[:4] == str(player.get("birth_year", ""))
                if member.get("birth_date") and player.get("birth_year") else False
            ),
        },
    }
    if claim.evidence_text:
        evidence["user_provided"] = claim.evidence_text

    # Determine status based on confidence
    auto_approve = confidence >= settings.CLAIM_AUTO_APPROVE_THRESHOLD
    auto_reject = confidence < settings.CLAIM_MANUAL_REVIEW_THRESHOLD

    if auto_approve:
        status = "approved"
    elif auto_reject:
        status = "rejected"
    else:
        status = "pending"

    # Create claim record
    claim_data = {
        "member_id": member["id"],
        "player_id": claim.player_id,
        "confidence_score": confidence,
        "evidence": json.dumps(evidence),
        "status": status,
    }

    if status == "approved":
        claim_data["reviewed_at"] = datetime.utcnow().isoformat()

    try:
        result = supabase.table("player_claims").insert(claim_data).execute()
    except Exception as e:
        logger.error(f"Player claim insert error: {e}")
        # Check if it's a unique constraint violation
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail="이미 이 선수에 대한 Claim이 존재합니다."
            )
        raise HTTPException(status_code=500, detail="Claim 생성 중 오류가 발생했습니다")

    if not result.data:
        raise HTTPException(status_code=500, detail="Claim 생성 중 오류가 발생했습니다")

    claim_record = result.data[0]

    # If auto-approved, update members.player_id and verification_tier
    if status == "approved":
        await _link_player_to_member(supabase, member["id"], claim.player_id)

    return {
        "claim_id": claim_record["id"],
        "status": status,
        "confidence": confidence,
        "message": _get_claim_status_message(status, confidence),
    }


@router.get("/player-claim/status")
async def get_player_claim_status(request: Request):
    """현재 회원의 선수 Claim 상태 조회"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    supabase = get_supabase_client()

    claims = supabase.table("player_claims").select("*").eq(
        "member_id", member["id"]
    ).order("created_at", desc=True).limit(5).execute()

    return {"claims": claims.data or []}


# =============================================
# Organization Claim Endpoints
# =============================================

@router.post("/org-claim")
async def submit_org_claim(
    request: Request,
    organization_id: int = Form(...),
    claim_type: str = Form("director"),
    file: Optional[UploadFile] = File(None),
):
    """
    조직 소유권 Claim 제출

    POST /account/verification/org-claim
    Form: organization_id, claim_type, file (사업자등록증 이미지)

    사업자등록증 제출 시 3-Layer 자동 검증 파이프라인:
    1. Gemini OCR → 사업자번호/상호/대표자명/개업일 추출
    2. Check Digit → 사업자번호 형식 유효성 검증
    3. NTS API → 국세청 진위확인
    """
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    if claim_type not in ("director", "head_coach", "representative"):
        raise HTTPException(status_code=400, detail="유효하지 않은 claim_type입니다")

    supabase = get_supabase_client()
    settings = get_account_settings()

    # Check if org exists
    try:
        org_result = supabase.table("organizations").select("id, name").eq(
            "id", organization_id
        ).single().execute()
    except Exception:
        raise HTTPException(status_code=404, detail="조직 정보를 찾을 수 없습니다")

    if not org_result.data:
        raise HTTPException(status_code=404, detail="조직 정보를 찾을 수 없습니다")

    # Check for existing claim
    existing = supabase.table("organization_claims").select("id, status").eq(
        "member_id", member["id"]
    ).eq("organization_id", organization_id).execute()

    if existing.data:
        existing_claim = existing.data[0]
        if existing_claim["status"] in ("pending", "auto_verified", "approved"):
            raise HTTPException(
                status_code=409,
                detail="이미 이 조직에 대한 Claim이 존재합니다."
            )

    # Create initial claim record
    claim_data = {
        "member_id": member["id"],
        "organization_id": organization_id,
        "claim_type": claim_type,
        "status": "pending",
    }

    document_url = None

    # Upload document if provided
    if file and file.content_type and file.content_type.startswith("image/"):
        content = await file.read()
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="파일 크기는 10MB 이하여야 합니다")

        import uuid
        file_ext = file.filename.split(".")[-1] if file.filename else "jpg"
        storage_path = f"org-claims/{member['id']}/{uuid.uuid4()}.{file_ext}"

        try:
            supabase.storage.from_("verification-images").upload(
                storage_path, content, {"content-type": file.content_type}
            )
            document_url = supabase.storage.from_("verification-images").get_public_url(storage_path)
        except Exception as e:
            logger.error(f"Document upload error: {e}")
            document_url = None

        claim_data["document_url"] = document_url

        # ===== 3-Layer BRN Verification Pipeline =====
        brn_result = await _run_brn_verification_pipeline(
            content, member, settings
        )

        if brn_result:
            claim_data.update(brn_result)

            # If all 3 layers pass and name matches, auto-verify
            if brn_result.get("brn_auto_verified"):
                claim_data["status"] = "auto_verified"

    # Insert the claim
    try:
        result = supabase.table("organization_claims").insert(claim_data).execute()
    except Exception as e:
        logger.error(f"Organization claim insert error: {e}")
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail="이미 이 조직에 대한 Claim이 존재합니다."
            )
        raise HTTPException(status_code=500, detail="Claim 생성 중 오류가 발생했습니다")

    if not result.data:
        raise HTTPException(status_code=500, detail="Claim 생성 중 오류가 발생했습니다")

    claim_record = result.data[0]

    # If auto-verified AND claim_type is director, run auto-registration
    if claim_record["status"] == "auto_verified" and claim_type == "director":
        await _approve_director_claim(
            supabase, claim_record["id"], member["id"], organization_id
        )

    return {
        "claim_id": claim_record["id"],
        "status": claim_record["status"],
        "brn_auto_verified": claim_data.get("brn_auto_verified", False),
        "message": _get_org_claim_message(claim_record["status"]),
    }


@router.get("/org-claim/status")
async def get_org_claim_status(request: Request):
    """현재 회원의 조직 Claim 상태 조회"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    supabase = get_supabase_client()

    claims = supabase.table("organization_claims").select("*").eq(
        "member_id", member["id"]
    ).order("created_at", desc=True).limit(5).execute()

    return {"claims": claims.data or []}


# =============================================
# Internal Helper Functions
# =============================================

async def _run_brn_verification_pipeline(
    image_data: bytes,
    member: dict,
    settings,
) -> Optional[dict]:
    """
    사업자등록증 3-Layer 자동 검증 파이프라인

    Layer 1: Gemini OCR - 사업자등록증 이미지에서 정보 추출
    Layer 2: Check Digit - 사업자번호 형식 유효성 검증
    Layer 3: NTS API - 국세청 진위확인
    """
    result = {}

    # Layer 1: Gemini OCR
    logger.info("BRN Pipeline Layer 1: Gemini OCR")
    verifier = GeminiVerifier()
    try:
        ocr_result = await verifier.verify_brn_image(image_data)
    except Exception as e:
        logger.error(f"BRN OCR failed: {e}")
        return None

    if not ocr_result:
        logger.warning("BRN OCR returned no result")
        return None

    brn_number = ocr_result.get("business_registration_number", "")
    business_name = ocr_result.get("business_name")
    representative_name = ocr_result.get("representative_name")
    opening_date = ocr_result.get("opening_date")
    ocr_confidence = ocr_result.get("confidence", 0.0)

    result["brn_number"] = brn_number
    result["brn_business_name"] = business_name
    result["brn_representative_name"] = representative_name
    result["brn_opening_date"] = opening_date
    result["brn_ocr_confidence"] = ocr_confidence

    if not brn_number:
        logger.warning("BRN OCR: No BRN number extracted")
        return result

    # Layer 2: Check Digit validation
    logger.info("BRN Pipeline Layer 2: Check Digit")
    checkdigit_valid = validate_brn_checkdigit(brn_number)
    result["brn_checkdigit_valid"] = checkdigit_valid

    if not checkdigit_valid:
        logger.warning(f"BRN Check Digit failed: {brn_number}")
        return result

    # Layer 3: NTS API verification
    logger.info("BRN Pipeline Layer 3: NTS API")
    if settings.NTS_API_KEY and representative_name and opening_date:
        try:
            nts_result = await verify_business_registration_nts(
                brn=brn_number,
                representative_name=representative_name,
                opening_date=opening_date,
                api_key=settings.NTS_API_KEY,
            )
            result["brn_nts_valid"] = nts_result.get("valid", False)
            result["brn_nts_status"] = nts_result.get("status")

            # Determine auto-verification
            if (
                nts_result.get("valid")
                and nts_result.get("status_code") == "01"  # 계속사업자
            ):
                # Check if representative name matches member name
                member_name = (member.get("full_name") or "").strip()
                rep_name = (representative_name or "").strip()
                if member_name and rep_name and member_name == rep_name:
                    result["brn_auto_verified"] = True
                    logger.info("BRN Pipeline: All 3 layers passed + name match → auto_verified")
                else:
                    logger.info(
                        f"BRN Pipeline: 3 layers passed but name mismatch "
                        f"(member={member_name}, rep={rep_name}) → manual review"
                    )
            else:
                logger.info(
                    f"BRN Pipeline: NTS result not fully valid "
                    f"(valid={nts_result.get('valid')}, status={nts_result.get('status_code')})"
                )
        except Exception as e:
            logger.error(f"NTS API call failed: {e}")
            result["brn_nts_valid"] = None
            result["brn_nts_status"] = "api_error"
    else:
        logger.warning("BRN Pipeline: Skipping NTS (missing API key or OCR fields)")
        result["brn_nts_valid"] = None

    return result


async def _link_player_to_member(supabase, member_id: str, player_id: int):
    """선수 Claim 승인 시 members.player_id 설정 및 verification_tier 업데이트"""
    try:
        supabase.table("members").update({
            "player_id": player_id,
            "data_linked_at": datetime.utcnow().isoformat(),
            "verification_tier": 3,
        }).eq("id", member_id).execute()
        logger.info(f"Player {player_id} linked to member {member_id}")
    except Exception as e:
        logger.error(f"Failed to link player to member: {e}")


async def _approve_director_claim(
    supabase, claim_id: str, member_id: str, organization_id: int
):
    """
    감독 Claim 승인 시 자동 등록:
    1. member_organizations (role='owner')
    2. club_settings (자동 생성)
    3. organizations.owner_member_id 설정
    """
    try:
        # 1. member_organizations 생성
        supabase.table("member_organizations").upsert({
            "member_id": member_id,
            "organization_id": organization_id,
            "role": "owner",
            "status": "active",
        }).execute()
        logger.info(f"member_organizations created: member={member_id}, org={organization_id}")

        # 2. club_settings 자동 생성 (테이블 존재 여부 확인 후)
        try:
            supabase.table("club_settings").upsert(
                {
                    "organization_id": organization_id,
                    "status": "active",
                    "onboarding_completed": False,
                    "created_by": member_id,
                },
                on_conflict="organization_id"
            ).execute()
            logger.info(f"club_settings created for org={organization_id}")
        except Exception as e:
            # club_settings 테이블이 없을 수 있음 (아직 club 서비스 미구현)
            logger.warning(f"club_settings upsert skipped (table may not exist): {e}")

        # 3. organizations 테이블에 owner 기록
        supabase.table("organizations").update({
            "owner_member_id": member_id,
        }).eq("id", organization_id).execute()
        logger.info(f"organizations.owner_member_id updated for org={organization_id}")

        # 4. Claim 상태 업데이트 → approved
        supabase.table("organization_claims").update({
            "status": "approved",
            "reviewed_at": datetime.utcnow().isoformat(),
        }).eq("id", claim_id).execute()

        # 5. 회원 verification_tier 업데이트
        supabase.table("members").update({
            "verification_tier": 3,
            "data_linked_at": datetime.utcnow().isoformat(),
        }).eq("id", member_id).execute()

    except Exception as e:
        logger.error(f"Director claim auto-registration failed: {e}")


def _get_claim_status_message(status: str, confidence: float) -> str:
    """Claim 상태별 메시지"""
    if status == "approved":
        return "선수 데이터가 성공적으로 연결되었습니다!"
    elif status == "rejected":
        return f"매칭 점수가 낮아 자동 승인되지 않았습니다 (점수: {confidence}). 관리자 검토가 필요합니다."
    else:
        return f"Claim이 제출되었습니다 (매칭 점수: {confidence}). 관리자 검토 후 승인됩니다."


def _get_org_claim_message(status: str) -> str:
    """조직 Claim 상태별 메시지"""
    messages = {
        "auto_verified": "사업자등록증 자동 검증이 완료되었습니다! 클럽 관리 기능이 활성화됩니다.",
        "pending": "Claim이 제출되었습니다. 관리자 검토 후 승인됩니다.",
        "approved": "조직 소유권이 확인되었습니다.",
        "rejected": "조직 소유권 인증이 거부되었습니다.",
    }
    return messages.get(status, "처리 중입니다.")
