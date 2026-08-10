"""
AI Verification Reporter - 통합 AI 인증 리포트 생성기

모든 인증 요청(이미지 인증, 선수 Claim, 학부모 Claim, 조직 Claim)에 대해
표준 포맷의 AI 리포트를 생성하고 verification_ai_reports 테이블에 저장.

리포트 포맷:
{
    "confidence": 0.78,
    "recommendation": "manual_review",
    "evidence": [
        {"signal": "surname_match", "description": "...", "weight": 0.25, "score": 0.25}
    ],
    "flags": [{"type": "warning", "message": "..."}],
    "reasoning": "한국어 요약"
}
"""
import json
import re
from datetime import datetime
from typing import Optional

import httpx
from loguru import logger

from ..config import get_account_settings, VERIFICATION_PROMPTS
from shared_core.db.client import get_supabase_client


class AIVerificationReporter:
    """통합 AI 인증 리포트 생성기"""

    def __init__(self):
        self.settings = get_account_settings()
        self.api_key = self.settings.GEMINI_API_KEY
        self.model = self.settings.GEMINI_MODEL
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    async def generate_parent_claim_report(
        self,
        parent_member: dict,
        child_name: str,
        child_birth_year: Optional[int],
        child_team_name: Optional[str],
        child_gender: Optional[str],
        relationship_type: str,
        matched_candidates: list,
    ) -> dict:
        """
        학부모 Claim AI 분석 리포트 생성

        1. 결정적(deterministic) 신호 분석
        2. Gemini 종합 추론
        3. 표준 리포트 포맷 반환
        """
        # Step 1: Deterministic signal scoring
        signals = self._calculate_parent_signals(
            parent_member=parent_member,
            child_name=child_name,
            child_birth_year=child_birth_year,
            child_team_name=child_team_name,
            matched_candidates=matched_candidates,
            relationship_type=relationship_type,
        )

        # Calculate deterministic confidence
        det_confidence = sum(s["score"] for s in signals)

        # Step 2: Gemini AI reasoning
        ai_result = await self._call_gemini_parent_analysis(
            parent_member=parent_member,
            child_name=child_name,
            child_birth_year=child_birth_year,
            child_team_name=child_team_name,
            child_gender=child_gender,
            relationship_type=relationship_type,
            matched_candidates=matched_candidates,
            signals=signals,
        )

        # Step 3: Combine results
        if ai_result:
            ai_confidence = ai_result.get("confidence", det_confidence)
            # Weight: 60% deterministic + 40% AI
            final_confidence = round(det_confidence * 0.6 + ai_confidence * 0.4, 2)
            recommendation = ai_result.get("recommendation", "manual_review")
            reasoning = ai_result.get("reasoning", "")
            flags = ai_result.get("flags", [])
        else:
            final_confidence = round(det_confidence, 2)
            recommendation = "manual_review"
            reasoning = "AI 분석을 수행할 수 없어 결정적 신호만으로 판단합니다."
            flags = [{"type": "warning", "message": "Gemini API 호출 실패, 수동 검토 필요"}]

        # Parent claims: never auto-approve (child safety)
        if recommendation == "approve":
            recommendation = "manual_review"

        report = {
            "confidence": min(final_confidence, 1.0),
            "recommendation": recommendation,
            "evidence": signals,
            "flags": flags,
            "reasoning": reasoning,
        }

        return report

    def _calculate_parent_signals(
        self,
        parent_member: dict,
        child_name: str,
        child_birth_year: Optional[int],
        child_team_name: Optional[str],
        matched_candidates: list,
        relationship_type: str,
    ) -> list:
        """학부모 Claim 결정적 신호 분석"""
        signals = []

        parent_name = (parent_member.get("full_name") or "").strip()

        # Signal 1: surname_match (0.25)
        surname_score = 0.0
        surname_desc = "성씨 비교 불가"
        if parent_name and child_name:
            parent_surname = parent_name[0] if parent_name else ""
            child_surname = child_name[0] if child_name else ""
            if parent_surname and child_surname and parent_surname == child_surname:
                surname_score = 0.25
                surname_desc = f"부모 성 '{parent_surname}' == 선수 성 '{child_surname}'"
            elif parent_surname and child_surname:
                surname_desc = f"부모 성 '{parent_surname}' != 선수 성 '{child_surname}'"

        signals.append({
            "signal": "surname_match",
            "description": surname_desc,
            "weight": 0.25,
            "score": surname_score,
        })

        # Signal 2: age_gap (0.20)
        age_score = 0.0
        age_desc = "나이 차이 계산 불가"
        parent_birth = parent_member.get("birth_date")
        if parent_birth and child_birth_year:
            try:
                parent_year = int(str(parent_birth)[:4])
                gap = parent_year - child_birth_year
                # gap is negative because parent is older
                age_diff = abs(gap)
                if 25 <= age_diff <= 40:
                    age_score = 0.20
                    age_desc = f"{age_diff}세 차이 (최적 범위)"
                elif 20 <= age_diff <= 50:
                    age_score = 0.15
                    age_desc = f"{age_diff}세 차이 (정상 범위)"
                elif age_diff < 15 or age_diff > 60:
                    age_score = 0.0
                    age_desc = f"{age_diff}세 차이 (비정상 범위)"
                else:
                    age_score = 0.10
                    age_desc = f"{age_diff}세 차이 (경계 범위)"
            except (ValueError, TypeError):
                pass

        signals.append({
            "signal": "age_gap",
            "description": age_desc,
            "weight": 0.20,
            "score": age_score,
        })

        # Signal 3: team_match (0.20)
        team_score = 0.0
        team_desc = "소속팀 비교 불가"
        parent_org_id = parent_member.get("organization_id")
        if parent_org_id and child_team_name:
            try:
                supabase = get_supabase_client()
                org_result = supabase.table("organizations").select("name").eq(
                    "id", parent_org_id
                ).single().execute()
                if org_result.data:
                    org_name = (org_result.data.get("name") or "").strip()
                    if org_name and child_team_name:
                        if org_name == child_team_name.strip():
                            team_score = 0.20
                            team_desc = f"소속팀 일치: {org_name}"
                        elif org_name in child_team_name or child_team_name.strip() in org_name:
                            team_score = 0.15
                            team_desc = f"소속팀 부분 일치: {org_name} ~ {child_team_name}"
                        else:
                            team_desc = f"소속팀 불일치: {org_name} != {child_team_name}"
            except Exception as e:
                logger.debug(f"Team match lookup failed: {e}")

        signals.append({
            "signal": "team_match",
            "description": team_desc,
            "weight": 0.20,
            "score": team_score,
        })

        # Signal 4: child_found (0.15)
        child_score = 0.0
        child_desc = "선수 데이터 매칭 없음"
        if matched_candidates:
            best = matched_candidates[0]
            child_score = 0.15
            child_desc = f"선수 매칭: {best.get('name', '')} (ID: {best.get('id', '')})"

        signals.append({
            "signal": "child_found",
            "description": child_desc,
            "weight": 0.15,
            "score": child_score,
        })

        # Signal 5: no_duplicate_parent (0.10)
        dup_score = 0.10  # Default: no duplicate
        dup_desc = "기존 학부모 claim 없음"
        if matched_candidates:
            best_player_id = matched_candidates[0].get("id")
            if best_player_id:
                try:
                    supabase = get_supabase_client()
                    existing = supabase.table("parent_claims").select("id").eq(
                        "matched_player_id", best_player_id
                    ).eq("status", "approved").execute()
                    if existing.data:
                        dup_score = 0.0
                        dup_desc = "이미 승인된 학부모 claim 존재"
                except Exception:
                    pass

        signals.append({
            "signal": "no_duplicate_parent",
            "description": dup_desc,
            "weight": 0.10,
            "score": dup_score,
        })

        # Signal 6: registration_context (0.05)
        reg_score = 0.0
        reg_desc = "member_type 확인 불가"
        member_type = parent_member.get("member_type", "")
        if member_type == "player_parent":
            reg_score = 0.05
            reg_desc = "member_type이 player_parent"
        elif member_type:
            reg_desc = f"member_type: {member_type} (player_parent 아님)"

        signals.append({
            "signal": "registration_context",
            "description": reg_desc,
            "weight": 0.05,
            "score": reg_score,
        })

        # Signal 7: additional_children (0.05)
        add_score = 0.0
        add_desc = "추가 자녀 정보 없음"
        try:
            supabase = get_supabase_client()
            other_claims = supabase.table("parent_claims").select("id").eq(
                "member_id", parent_member["id"]
            ).in_("status", ["approved", "ai_reviewed"]).execute()
            if other_claims.data:
                add_score = 0.05
                add_desc = f"같은 부모의 다른 자녀 claim {len(other_claims.data)}건 존재"
        except Exception:
            pass

        signals.append({
            "signal": "additional_children",
            "description": add_desc,
            "weight": 0.05,
            "score": add_score,
        })

        return signals

    async def _call_gemini_parent_analysis(
        self,
        parent_member: dict,
        child_name: str,
        child_birth_year: Optional[int],
        child_team_name: Optional[str],
        child_gender: Optional[str],
        relationship_type: str,
        matched_candidates: list,
        signals: list,
    ) -> Optional[dict]:
        """Gemini API로 학부모 Claim 종합 분석"""
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not set, skipping AI analysis")
            return None

        prompt_template = VERIFICATION_PROMPTS.get("parent_claim", "")
        if not prompt_template:
            return None

        # Build context
        parent_info = {
            "name": parent_member.get("full_name"),
            "birth_date": parent_member.get("birth_date"),
            "member_type": parent_member.get("member_type"),
            "organization_id": parent_member.get("organization_id"),
            "relationship_type": relationship_type,
        }

        child_info = []
        for c in matched_candidates[:5]:
            child_info.append({
                "player_id": c.get("id"),
                "name": c.get("name"),
                "team_name": c.get("team_name"),
                "birth_year": c.get("birth_year"),
                "gender": c.get("gender"),
            })

        prompt = prompt_template.format(
            parent_info=json.dumps(parent_info, ensure_ascii=False),
            child_candidates=json.dumps(child_info, ensure_ascii=False),
            signals=json.dumps(signals, ensure_ascii=False),
        )

        try:
            url = f"{self.base_url}/models/{self.model}:generateContent"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "topK": 1,
                    "topP": 1,
                    "maxOutputTokens": 1024,
                }
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url, json=payload, params={"key": self.api_key}
                )

                if response.status_code != 200:
                    logger.error(f"Gemini parent analysis error: {response.status_code}")
                    return None

                data = response.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]

                # Parse JSON from response
                json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
                if json_match:
                    json_str = json_match.group(1).strip()
                else:
                    json_str = text.strip()

                return json.loads(json_str)

        except Exception as e:
            logger.error(f"Gemini parent analysis failed: {e}")
            return None

    async def save_report(
        self,
        target_type: str,
        target_id: str,
        report: dict,
    ) -> Optional[str]:
        """AI 리포트를 verification_ai_reports 테이블에 저장"""
        try:
            supabase = get_supabase_client()
            result = supabase.table("verification_ai_reports").insert({
                "target_type": target_type,
                "target_id": target_id,
                "ai_model": self.model,
                "confidence": report.get("confidence", 0.0),
                "recommendation": report.get("recommendation", "manual_review"),
                "evidence": json.dumps(report.get("evidence", []), ensure_ascii=False),
                "flags": json.dumps(report.get("flags", []), ensure_ascii=False),
                "reasoning": report.get("reasoning"),
                "raw_response": json.dumps(report, ensure_ascii=False),
            }).execute()

            if result.data:
                return result.data[0]["id"]
        except Exception as e:
            logger.error(f"AI report save failed: {e}")

        return None
