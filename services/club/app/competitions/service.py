"""
Competitions Service - 대회 참가 관리 비즈니스 로직
"""

from datetime import datetime
from typing import Optional, List, Tuple
from loguru import logger

from ..database import get_supabase_client


class CompetitionService:
    """대회 참가 관리 서비스"""

    @property
    def supabase(self):
        return get_supabase_client()

    # -----------------------------------------
    # 회원 이름 매핑 헬퍼
    # -----------------------------------------

    def _get_members_map(self, org_id: int) -> dict:
        """회원 ID -> {name, role} 매핑"""
        result = self.supabase.table("members").select(
            "id, full_name, club_role"
        ).eq("organization_id", org_id).execute()
        return {
            str(m["id"]): {"name": m["full_name"], "role": m.get("club_role")}
            for m in (result.data or [])
        }

    # -----------------------------------------
    # 대회 이벤트 CRUD
    # -----------------------------------------

    def create_event(
        self,
        org_id: int,
        data: dict,
        created_by: str,
    ) -> dict:
        """대회 이벤트 생성"""
        insert_data = {
            "organization_id": org_id,
            "name": data["name"],
            "start_date": data["start_date"].isoformat() if hasattr(data["start_date"], "isoformat") else data["start_date"],
            "end_date": data.get("end_date").isoformat() if data.get("end_date") and hasattr(data["end_date"], "isoformat") else data.get("end_date"),
            "location": data.get("location"),
            "weapon": data.get("weapon"),
            "age_group": data.get("age_group"),
            "entry_fee": data.get("entry_fee", 0),
            "coach_travel_fee": data.get("coach_travel_fee", 0),
            "transportation_fee": data.get("transportation_fee", 0),
            "rsvp_deadline": data.get("rsvp_deadline").isoformat() if data.get("rsvp_deadline") and hasattr(data["rsvp_deadline"], "isoformat") else data.get("rsvp_deadline"),
            "competition_id": data.get("competition_id"),
            "source": "manual",
            "is_auto_synced": False,
            "status": "upcoming",
            "created_by": created_by,
        }

        result = self.supabase.table("app_competition_events").insert(insert_data).execute()
        event = result.data[0]

        logger.info(
            "대회 이벤트 생성: name={}, org={}, date={}",
            data["name"], org_id, data["start_date"],
        )
        return event

    def list_events(
        self,
        org_id: int,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[dict], int]:
        """대회 이벤트 목록 조회 (RSVP 카운트 포함)"""
        query = self.supabase.table("app_competition_events").select(
            "*", count="exact"
        ).eq("organization_id", org_id)

        if status:
            query = query.eq("status", status)

        result = query.order("start_date", desc=True).range(
            offset, offset + limit - 1
        ).execute()

        events = result.data or []

        # RSVP 카운트 조회
        if events:
            event_ids = [e["id"] for e in events]
            rsvps = self.supabase.table("app_competition_rsvps").select(
                "event_id, status"
            ).in_("event_id", event_ids).execute()

            # 이벤트별 RSVP 카운트 집계
            rsvp_counts = {}
            for r in (rsvps.data or []):
                eid = r["event_id"]
                if eid not in rsvp_counts:
                    rsvp_counts[eid] = {"attending": 0, "not_attending": 0, "maybe": 0}
                s = r["status"]
                if s in rsvp_counts[eid]:
                    rsvp_counts[eid][s] += 1

            for event in events:
                counts = rsvp_counts.get(event["id"], {})
                event["rsvp_summary"] = {
                    "attending_count": counts.get("attending", 0),
                    "not_attending_count": counts.get("not_attending", 0),
                    "maybe_count": counts.get("maybe", 0),
                }

        return events, result.count or 0

    def get_event(self, org_id: int, event_id: str) -> Optional[dict]:
        """대회 이벤트 상세 조회 (RSVP 카운트 포함)"""
        result = self.supabase.table("app_competition_events").select(
            "*"
        ).eq("id", event_id).eq("organization_id", org_id).execute()

        if not result.data:
            return None

        event = result.data[0]

        # RSVP 카운트 조회
        rsvps = self.supabase.table("app_competition_rsvps").select(
            "status"
        ).eq("event_id", event_id).execute()

        counts = {"attending": 0, "not_attending": 0, "maybe": 0}
        for r in (rsvps.data or []):
            s = r["status"]
            if s in counts:
                counts[s] += 1

        event["rsvp_summary"] = {
            "attending_count": counts["attending"],
            "not_attending_count": counts["not_attending"],
            "maybe_count": counts["maybe"],
        }

        return event

    def update_event(
        self,
        org_id: int,
        event_id: str,
        data: dict,
    ) -> Optional[dict]:
        """대회 이벤트 수정"""
        update_data = {}
        for key, value in data.items():
            if value is not None:
                if hasattr(value, "isoformat"):
                    update_data[key] = value.isoformat()
                elif hasattr(value, "value"):
                    # Enum
                    update_data[key] = value.value
                else:
                    update_data[key] = value

        if not update_data:
            return None

        result = self.supabase.table("app_competition_events").update(
            update_data
        ).eq("id", event_id).eq("organization_id", org_id).execute()

        if not result.data:
            return None

        logger.info("대회 이벤트 수정: event_id={}", event_id)
        return result.data[0]

    def delete_event(self, org_id: int, event_id: str) -> bool:
        """대회 이벤트 삭제"""
        # 연관 RSVP 먼저 삭제
        self.supabase.table("app_competition_rsvps").delete().eq(
            "event_id", event_id
        ).execute()

        result = self.supabase.table("app_competition_events").delete().eq(
            "id", event_id
        ).eq("organization_id", org_id).execute()

        if result.data:
            logger.info("대회 이벤트 삭제: event_id={}", event_id)
            return True
        return False

    # -----------------------------------------
    # RSVP 관리
    # -----------------------------------------

    def submit_rsvp(
        self,
        org_id: int,
        event_id: str,
        member_id: str,
        responded_by: str,
        data: dict,
    ) -> dict:
        """RSVP 응답 제출 (upsert)"""
        # 이벤트 존재 확인
        event = self.supabase.table("app_competition_events").select(
            "id"
        ).eq("id", event_id).eq("organization_id", org_id).execute()

        if not event.data:
            raise ValueError("대회 이벤트를 찾을 수 없습니다")

        rsvp_data = {
            "event_id": event_id,
            "member_id": member_id,
            "responded_by": responded_by,
            "status": data["status"].value if hasattr(data["status"], "value") else data["status"],
            "reason": data.get("reason"),
            "responded_at": datetime.now().isoformat(),
        }

        result = self.supabase.table("app_competition_rsvps").upsert(
            rsvp_data, on_conflict="event_id,member_id"
        ).execute()

        rsvp = result.data[0] if result.data else rsvp_data

        logger.info(
            "RSVP 제출: event={}, member={}, status={}",
            event_id, member_id, rsvp_data["status"],
        )
        return rsvp

    def get_rsvps(self, org_id: int, event_id: str) -> List[dict]:
        """대회 이벤트 RSVP 목록 (회원 이름 포함)"""
        # 이벤트 존재 확인
        event = self.supabase.table("app_competition_events").select(
            "id"
        ).eq("id", event_id).eq("organization_id", org_id).execute()

        if not event.data:
            return []

        result = self.supabase.table("app_competition_rsvps").select(
            "*"
        ).eq("event_id", event_id).order("responded_at", desc=True).execute()

        return result.data or []

    # -----------------------------------------
    # 대회 마감 & 비용 정산
    # -----------------------------------------

    def finalize_event(
        self,
        org_id: int,
        event_id: str,
        created_by: str,
    ) -> Optional[dict]:
        """대회 이벤트 마감 및 1인당 비용 계산

        - status -> 'closed'
        - 참석 인원 기준으로 코치 교통비, 교통비를 1/N 정산
        """
        event = self.get_event(org_id, event_id)
        if not event:
            return None

        # status를 closed로 변경
        self.supabase.table("app_competition_events").update({
            "status": "closed",
        }).eq("id", event_id).eq("organization_id", org_id).execute()

        # 참석 인원 수
        attending_count = event.get("rsvp_summary", {}).get("attending_count", 0)

        entry_fee = event.get("entry_fee", 0)
        coach_travel_fee = event.get("coach_travel_fee", 0)
        transportation_fee = event.get("transportation_fee", 0)

        if attending_count > 0:
            coach_travel_per_person = coach_travel_fee // attending_count
            transport_per_person = transportation_fee // attending_count
        else:
            coach_travel_per_person = 0
            transport_per_person = 0

        total_per_person = entry_fee + coach_travel_per_person + transport_per_person

        cost_summary = {
            "entry_fee_per_person": entry_fee,
            "coach_travel_per_person": coach_travel_per_person,
            "transport_per_person": transport_per_person,
            "total_per_person": total_per_person,
            "attending_count": attending_count,
        }

        logger.info(
            "대회 마감: event={}, attending={}, total_per_person={}",
            event_id, attending_count, total_per_person,
        )

        return {
            "event": event,
            "cost_summary": cost_summary,
        }

    # -----------------------------------------
    # data 서비스 동기화
    # -----------------------------------------

    def sync_from_data_service(
        self,
        org_id: int,
        competition_data: dict,
    ) -> dict:
        """data 서비스 webhook으로부터 대회 이벤트 자동 생성

        competition_data: {
            competition_id: int,
            name: str,
            start_date: str,
            end_date: str (optional),
            location: str (optional),
            weapon: str (optional),
            age_group: str (optional),
        }
        """
        # 이미 동기화된 이벤트가 있는지 확인
        competition_id = competition_data.get("competition_id")
        if competition_id:
            existing = self.supabase.table("app_competition_events").select(
                "id"
            ).eq("organization_id", org_id).eq(
                "competition_id", competition_id
            ).execute()

            if existing.data:
                # 이미 존재 -> 업데이트
                event_id = existing.data[0]["id"]
                update_data = {
                    "name": competition_data.get("name"),
                    "start_date": competition_data.get("start_date"),
                    "end_date": competition_data.get("end_date"),
                    "location": competition_data.get("location"),
                    "weapon": competition_data.get("weapon"),
                    "age_group": competition_data.get("age_group"),
                }
                # None 값 제거
                update_data = {k: v for k, v in update_data.items() if v is not None}

                result = self.supabase.table("app_competition_events").update(
                    update_data
                ).eq("id", event_id).execute()

                logger.info(
                    "대회 동기화 업데이트: competition_id={}, event_id={}",
                    competition_id, event_id,
                )
                return result.data[0] if result.data else existing.data[0]

        # 새로 생성
        insert_data = {
            "organization_id": org_id,
            "competition_id": competition_data.get("competition_id"),
            "name": competition_data.get("name", "Unknown Competition"),
            "start_date": competition_data.get("start_date"),
            "end_date": competition_data.get("end_date"),
            "location": competition_data.get("location"),
            "weapon": competition_data.get("weapon"),
            "age_group": competition_data.get("age_group"),
            "source": "data_sync",
            "is_auto_synced": True,
            "status": "upcoming",
        }

        result = self.supabase.table("app_competition_events").insert(insert_data).execute()
        event = result.data[0]

        logger.info(
            "대회 동기화 생성: competition_id={}, name={}",
            competition_id, competition_data.get("name"),
        )
        return event


# 싱글톤
competition_service = CompetitionService()
