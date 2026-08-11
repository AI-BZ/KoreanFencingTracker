"""
Schedule Service - 일정 관리 비즈니스 로직
"""

import uuid
from datetime import datetime, timedelta, date
from typing import Optional, List, Tuple
from loguru import logger

from ..database import get_supabase_client
from .models import (
    EventType,
    EventVisibility,
    EventStatus,
    RecurrenceFreq,
    EVENT_COLORS,
    ScheduleResponse,
)


class ScheduleService:
    """일정 관리 서비스"""

    @property
    def supabase(self):
        return get_supabase_client()

    # ─────────────────────────────────────────
    # 일정 조회
    # ─────────────────────────────────────────

    def get_events(
        self,
        org_id: int,
        start_date: str,
        end_date: str,
        member_id: Optional[str] = None,
        member_role: Optional[str] = None,
        event_type: Optional[str] = None,
        visibility: Optional[str] = None,
        coach_id: Optional[str] = None,
    ) -> List[dict]:
        """
        날짜 범위 내 일정 조회 (FullCalendar용)

        visibility 필터링:
        - club: 모든 사용자 볼 수 있음
        - coaches: 코치 이상만
        - personal: 본인만
        """
        query = (
            self.supabase.table("app_schedules")
            .select("*")
            .eq("organization_id", org_id)
            .gte("start_at", start_date)
            .lte("start_at", end_date)
            .neq("status", "cancelled")
            .order("start_at")
        )

        if event_type:
            query = query.eq("event_type", event_type)

        if coach_id:
            query = query.eq("assigned_coach_id", coach_id)

        result = query.execute()
        events = result.data or []

        # visibility 필터링 (DB 레벨이 아닌 앱 레벨)
        filtered = []
        for ev in events:
            vis = ev.get("visibility", "club")

            # club 이벤트: 모두 볼 수 있음
            if vis == "club":
                filtered.append(ev)
            # coaches 이벤트: 코치 이상만
            elif vis == "coaches":
                if member_role in ("owner", "head_coach", "coach", "assistant"):
                    filtered.append(ev)
            # personal 이벤트: 생성자 또는 참가자만
            elif vis == "personal":
                if member_id and (
                    ev.get("created_by") == member_id
                    or member_id in (ev.get("participant_ids") or [])
                    or ev.get("assigned_coach_id") == member_id
                ):
                    filtered.append(ev)

        # visibility 파라미터로 추가 필터
        if visibility:
            filtered = [e for e in filtered if e.get("visibility") == visibility]

        return filtered

    def get_event(self, event_id: str, org_id: int) -> Optional[dict]:
        """일정 단건 조회"""
        result = (
            self.supabase.table("app_schedules")
            .select("*")
            .eq("id", event_id)
            .eq("organization_id", org_id)
            .execute()
        )
        data = result.data
        if data:
            return data[0]
        return None

    # ─────────────────────────────────────────
    # 일정 생성
    # ─────────────────────────────────────────

    def create_event(
        self,
        org_id: int,
        created_by: str,
        title: str,
        event_type: str,
        start_at: datetime,
        end_at: datetime,
        all_day: bool = False,
        description: Optional[str] = None,
        color: Optional[str] = None,
        is_recurring: bool = False,
        recurrence_rule: Optional[dict] = None,
        visibility: str = "club",
        assigned_coach_id: Optional[str] = None,
        participant_ids: Optional[List[str]] = None,
        max_participants: Optional[int] = None,
        lesson_id: Optional[str] = None,
        competition_id: Optional[int] = None,
        location: Optional[str] = None,
    ) -> dict:
        """일정 생성"""
        if not color:
            color = EVENT_COLORS.get(event_type, "#667eea")

        event_data = {
            "organization_id": org_id,
            "title": title,
            "description": description,
            "event_type": event_type,
            "color": color,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "all_day": all_day,
            "is_recurring": is_recurring,
            "recurrence_rule": recurrence_rule,
            "created_by": created_by,
            "visibility": visibility,
            "assigned_coach_id": assigned_coach_id,
            "participant_ids": participant_ids or [],
            "max_participants": max_participants,
            "lesson_id": lesson_id,
            "competition_id": competition_id,
            "location": location,
            "status": "scheduled",
        }

        result = self.supabase.table("app_schedules").insert(event_data).execute()
        event = result.data[0]

        # 반복 일정이면 자식 이벤트 생성
        if is_recurring and recurrence_rule:
            self._generate_recurring_events(event, recurrence_rule)

        logger.info(f"Schedule created: {title} ({event_type}) by {created_by}")
        return event

    def _generate_recurring_events(self, parent: dict, rule: dict) -> List[dict]:
        """반복 일정의 자식 이벤트 생성 (최대 90일)"""
        freq = rule.get("freq", "weekly")
        days = rule.get("days", [])  # 0=Mon, 6=Sun
        until_str = rule.get("until")

        parent_start = datetime.fromisoformat(parent["start_at"].replace("Z", "+00:00"))
        parent_end = datetime.fromisoformat(parent["end_at"].replace("Z", "+00:00"))
        duration = parent_end - parent_start

        if until_str:
            until_date = date.fromisoformat(until_str) if isinstance(until_str, str) else until_str
        else:
            until_date = (parent_start + timedelta(days=90)).date()

        # 최대 90일치만 생성
        max_until = (parent_start + timedelta(days=90)).date()
        if until_date > max_until:
            until_date = max_until

        children = []
        current = parent_start + timedelta(days=1)

        while current.date() <= until_date:
            should_create = False

            if freq == "daily":
                should_create = True
            elif freq == "weekly":
                if days:
                    should_create = current.weekday() in days
                else:
                    should_create = current.weekday() == parent_start.weekday()
            elif freq == "monthly":
                should_create = current.day == parent_start.day

            if should_create:
                child_data = {
                    "organization_id": parent["organization_id"],
                    "title": parent["title"],
                    "description": parent.get("description"),
                    "event_type": parent["event_type"],
                    "color": parent.get("color"),
                    "start_at": current.isoformat(),
                    "end_at": (current + duration).isoformat(),
                    "all_day": parent.get("all_day", False),
                    "is_recurring": False,
                    "recurrence_parent_id": parent["id"],
                    "created_by": parent["created_by"],
                    "visibility": parent.get("visibility", "club"),
                    "assigned_coach_id": parent.get("assigned_coach_id"),
                    "participant_ids": parent.get("participant_ids", []),
                    "max_participants": parent.get("max_participants"),
                    "location": parent.get("location"),
                    "status": "scheduled",
                }
                children.append(child_data)

            current += timedelta(days=1)

        if children:
            # batch insert (Supabase는 한번에 여러 행 insert 가능)
            batch_size = 50
            for i in range(0, len(children), batch_size):
                batch = children[i:i + batch_size]
                self.supabase.table("app_schedules").insert(batch).execute()
            logger.info(f"Generated {len(children)} recurring events for '{parent['title']}'")

        return children

    # ─────────────────────────────────────────
    # 일정 수정/삭제
    # ─────────────────────────────────────────

    def update_event(
        self,
        event_id: str,
        org_id: int,
        **kwargs,
    ) -> Optional[dict]:
        """일정 수정"""
        update_data = {k: v for k, v in kwargs.items() if v is not None}

        if not update_data:
            return self.get_event(event_id, org_id)

        # datetime → isoformat
        for field in ("start_at", "end_at"):
            if field in update_data and isinstance(update_data[field], datetime):
                update_data[field] = update_data[field].isoformat()

        # enum → value
        for field in ("event_type", "visibility", "status"):
            if field in update_data and hasattr(update_data[field], "value"):
                update_data[field] = update_data[field].value

        result = (
            self.supabase.table("app_schedules")
            .update(update_data)
            .eq("id", event_id)
            .eq("organization_id", org_id)
            .execute()
        )

        if result.data:
            logger.info(f"Schedule updated: {event_id}")
            return result.data[0]
        return None

    def delete_event(
        self,
        event_id: str,
        org_id: int,
        delete_children: bool = False,
    ) -> bool:
        """일정 삭제 (실제 삭제가 아닌 cancelled 처리)"""
        event = self.get_event(event_id, org_id)
        if not event:
            return False

        # 부모 이벤트 삭제 시 자식도 함께 삭제
        if delete_children and event.get("is_recurring"):
            self.supabase.table("app_schedules").update(
                {"status": "cancelled"}
            ).eq("recurrence_parent_id", event_id).execute()

        self.supabase.table("app_schedules").update(
            {"status": "cancelled"}
        ).eq("id", event_id).eq("organization_id", org_id).execute()

        logger.info(f"Schedule deleted: {event_id} (delete_children={delete_children})")
        return True

    # ─────────────────────────────────────────
    # 드래그&드롭 (시간 변경)
    # ─────────────────────────────────────────

    def move_event(
        self,
        event_id: str,
        org_id: int,
        new_start: datetime,
        new_end: datetime,
        all_day: Optional[bool] = None,
    ) -> Optional[dict]:
        """일정 시간 변경 (드래그&드롭)"""
        update = {
            "start_at": new_start.isoformat(),
            "end_at": new_end.isoformat(),
        }
        if all_day is not None:
            update["all_day"] = all_day

        result = (
            self.supabase.table("app_schedules")
            .update(update)
            .eq("id", event_id)
            .eq("organization_id", org_id)
            .execute()
        )

        if result.data:
            return result.data[0]
        return None

    # ─────────────────────────────────────────
    # 코치/회원 목록 (일정 생성용)
    # ─────────────────────────────────────────

    def get_coaches(self, org_id: int) -> List[dict]:
        """코치 목록"""
        result = (
            self.supabase.table("members")
            .select("id, full_name, club_role")
            .eq("organization_id", org_id)
            .in_("club_role", ["owner", "head_coach", "coach", "assistant"])
            .eq("member_status", "active")
            .execute()
        )
        return [
            {"id": str(m["id"]), "name": m["full_name"], "role": m["club_role"]}
            for m in (result.data or [])
        ]

    def get_members(self, org_id: int) -> List[dict]:
        """전체 활성 회원 목록"""
        result = (
            self.supabase.table("members")
            .select("id, full_name, club_role")
            .eq("organization_id", org_id)
            .eq("member_status", "active")
            .execute()
        )
        return [
            {"id": str(m["id"]), "name": m["full_name"], "role": m["club_role"]}
            for m in (result.data or [])
        ]

    # ─────────────────────────────────────────
    # FullCalendar 응답 변환
    # ─────────────────────────────────────────

    def to_fullcalendar_event(self, ev: dict, members_map: Optional[dict] = None) -> dict:
        """DB 레코드 → FullCalendar 이벤트 형식"""
        creator_name = None
        coach_name = None

        if members_map:
            creator_name = members_map.get(ev.get("created_by"), {}).get("name")
            coach_name = members_map.get(ev.get("assigned_coach_id"), {}).get("name")

        return {
            "id": ev["id"],
            "title": ev["title"],
            "description": ev.get("description"),
            "event_type": ev.get("event_type", "training"),
            "color": ev.get("color", "#667eea"),
            "start": ev["start_at"],
            "end": ev["end_at"],
            "allDay": ev.get("all_day", False),
            "is_recurring": ev.get("is_recurring", False),
            "recurrence_rule": ev.get("recurrence_rule"),
            "recurrence_parent_id": ev.get("recurrence_parent_id"),
            "created_by": ev.get("created_by"),
            "creator_name": creator_name,
            "visibility": ev.get("visibility", "club"),
            "assigned_coach_id": ev.get("assigned_coach_id"),
            "coach_name": coach_name,
            "participant_ids": ev.get("participant_ids"),
            "max_participants": ev.get("max_participants"),
            "lesson_id": ev.get("lesson_id"),
            "competition_id": ev.get("competition_id"),
            "location": ev.get("location"),
            "status": ev.get("status", "scheduled"),
            "created_at": ev.get("created_at"),
            "updated_at": ev.get("updated_at"),
        }


schedule_service = ScheduleService()
