"""
Lessons Service - 레슨 패키지 & 예약 비즈니스 로직
"""

from datetime import date, datetime, time, timedelta
from typing import Optional, List, Tuple
from loguru import logger

from ..database import get_supabase_client
from .models import PackageStatus, LessonRequestStatus


class LessonService:
    """레슨 패키지 & 예약 서비스"""

    @property
    def supabase(self):
        return get_supabase_client()

    # ─────────────────────────────────────────
    # 회원 이름 매핑 헬퍼
    # ─────────────────────────────────────────

    def _get_members_map(self, org_id: int) -> dict:
        """회원 ID → {name, role} 매핑"""
        result = self.supabase.table("members").select(
            "id, full_name, club_role"
        ).eq("organization_id", org_id).execute()
        return {
            str(m["id"]): {"name": m["full_name"], "role": m.get("club_role")}
            for m in (result.data or [])
        }

    # ─────────────────────────────────────────
    # 레슨 패키지 CRUD
    # ─────────────────────────────────────────

    def create_package(
        self,
        org_id: int,
        member_id: str,
        coach_id: str,
        package_type: str,
        total_sessions: int,
        total_price: int,
        price_per_session: Optional[int] = None,
        expires_at: Optional[datetime] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """레슨 패키지 생성"""
        data = {
            "organization_id": org_id,
            "member_id": member_id,
            "coach_id": coach_id,
            "package_type": package_type,
            "total_sessions": total_sessions,
            "total_price": total_price,
            "price_per_session": price_per_session,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "notes": notes,
            "status": PackageStatus.active.value,
        }

        result = self.supabase.table("app_lesson_packages").insert(data).execute()
        package = result.data[0]

        logger.info(
            "레슨 패키지 생성: member={}, coach={}, type={}, sessions={}",
            member_id, coach_id, package_type, total_sessions,
        )
        return package

    def list_packages(
        self,
        org_id: int,
        member_id: Optional[str] = None,
        coach_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[dict], int]:
        """패키지 목록 조회"""
        query = self.supabase.table("app_lesson_packages").select(
            "*", count="exact"
        ).eq("organization_id", org_id)

        if member_id:
            query = query.eq("member_id", member_id)
        if coach_id:
            query = query.eq("coach_id", coach_id)
        if status:
            query = query.eq("status", status)

        result = query.order("created_at", desc=True).range(
            offset, offset + limit - 1
        ).execute()

        return result.data or [], result.count or 0

    def get_package(self, package_id: str, org_id: int) -> Optional[dict]:
        """패키지 상세 조회"""
        result = self.supabase.table("app_lesson_packages").select(
            "*"
        ).eq("id", package_id).eq("organization_id", org_id).execute()

        if not result.data:
            return None
        return result.data[0]

    def get_package_with_deductions(self, package_id: str, org_id: int) -> Optional[dict]:
        """패키지 상세 + 차감 이력"""
        package = self.get_package(package_id, org_id)
        if not package:
            return None

        deductions = self.supabase.table("app_lesson_deductions").select(
            "*"
        ).eq("package_id", package_id).order("deducted_at", desc=True).execute()

        package["deductions"] = deductions.data or []
        return package

    def get_my_packages(self, org_id: int, member_id: str) -> dict:
        """학생의 활성 패키지 현황"""
        result = self.supabase.table("app_lesson_packages").select(
            "*"
        ).eq("organization_id", org_id).eq(
            "member_id", member_id
        ).eq("status", "active").order("created_at", desc=True).execute()

        packages = result.data or []
        total_remaining = sum(p.get("remaining_sessions", 0) for p in packages)

        return {
            "total_active_packages": len(packages),
            "total_remaining": total_remaining,
            "packages": packages,
        }

    def update_package(
        self, package_id: str, org_id: int, **kwargs
    ) -> Optional[dict]:
        """패키지 수정"""
        if "status" in kwargs and isinstance(kwargs["status"], PackageStatus):
            kwargs["status"] = kwargs["status"].value
        if "expires_at" in kwargs and isinstance(kwargs["expires_at"], datetime):
            kwargs["expires_at"] = kwargs["expires_at"].isoformat()

        result = self.supabase.table("app_lesson_packages").update(
            kwargs
        ).eq("id", package_id).eq("organization_id", org_id).execute()

        return result.data[0] if result.data else None

    # ─────────────────────────────────────────
    # 레슨 차감
    # ─────────────────────────────────────────

    def deduct_lesson(
        self,
        org_id: int,
        lesson_id: Optional[str],
        student_id: str,
        coach_id: str,
        deducted_by: str,
        notes: Optional[str] = None,
    ) -> Optional[dict]:
        """레슨 완료 시 차감

        1. 해당 학생-코치의 active 패키지 찾기
        2. used_sessions += 1
        3. remaining == 0이면 status → exhausted
        4. 차감 기록 생성
        """
        # 해당 학생-코치의 active 패키지 (가장 오래된 것 우선)
        packages = self.supabase.table("app_lesson_packages").select(
            "*"
        ).eq("organization_id", org_id).eq(
            "member_id", student_id
        ).eq("coach_id", coach_id).eq(
            "status", "active"
        ).order("purchased_at").execute()

        if not packages.data:
            logger.warning(
                "차감 가능한 패키지 없음: student={}, coach={}", student_id, coach_id
            )
            return None

        package = packages.data[0]
        remaining = package.get("remaining_sessions", 0)
        if remaining <= 0:
            logger.warning("잔여 회수 0: package={}", package["id"])
            return None

        new_used = package["used_sessions"] + 1
        new_remaining = package["total_sessions"] - new_used
        new_status = "exhausted" if new_remaining <= 0 else "active"

        # 패키지 업데이트
        self.supabase.table("app_lesson_packages").update({
            "used_sessions": new_used,
            "status": new_status,
        }).eq("id", package["id"]).execute()

        # 차감 기록 생성
        deduction_data = {
            "package_id": package["id"],
            "lesson_id": lesson_id,
            "deducted_by": deducted_by,
            "notes": notes,
        }
        deduction_result = self.supabase.table("app_lesson_deductions").insert(
            deduction_data
        ).execute()

        deduction = deduction_result.data[0] if deduction_result.data else None

        logger.info(
            "레슨 차감: package={}, used={}/{}, remaining={}",
            package["id"], new_used, package["total_sessions"], new_remaining,
        )

        # 잔여 2회 이하 알림 트리거 (향후 notification service 연동)
        if 0 < new_remaining <= 2:
            logger.info(
                "잔여 회수 부족 알림: student={}, remaining={}",
                student_id, new_remaining,
            )

        return deduction

    # ─────────────────────────────────────────
    # 레슨 신청
    # ─────────────────────────────────────────

    def create_request(
        self,
        org_id: int,
        student_id: str,
        coach_id: str,
        requested_by: str,
        requested_date: date,
        requested_start_time: time,
        duration_minutes: int = 60,
    ) -> dict:
        """레슨 신청"""
        data = {
            "organization_id": org_id,
            "student_id": student_id,
            "coach_id": coach_id,
            "requested_by": requested_by,
            "requested_date": requested_date.isoformat(),
            "requested_start_time": requested_start_time.isoformat(),
            "duration_minutes": duration_minutes,
            "status": LessonRequestStatus.pending.value,
        }

        result = self.supabase.table("app_lesson_requests").insert(data).execute()
        request = result.data[0]

        logger.info(
            "레슨 신청: student={}, coach={}, date={} {}",
            student_id, coach_id, requested_date, requested_start_time,
        )
        return request

    def list_requests(
        self,
        org_id: int,
        coach_id: Optional[str] = None,
        student_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        """레슨 신청 목록"""
        query = self.supabase.table("app_lesson_requests").select(
            "*"
        ).eq("organization_id", org_id)

        if coach_id:
            query = query.eq("coach_id", coach_id)
        if student_id:
            query = query.eq("student_id", student_id)
        if status:
            query = query.eq("status", status)

        result = query.order("created_at", desc=True).limit(limit).execute()
        return result.data or []

    def get_request(self, request_id: str, org_id: int) -> Optional[dict]:
        """레슨 신청 상세"""
        result = self.supabase.table("app_lesson_requests").select(
            "*"
        ).eq("id", request_id).eq("organization_id", org_id).execute()
        return result.data[0] if result.data else None

    def approve_request(
        self, request_id: str, org_id: int, coach_note: Optional[str] = None
    ) -> Optional[dict]:
        """레슨 신청 승인"""
        result = self.supabase.table("app_lesson_requests").update({
            "status": LessonRequestStatus.approved.value,
            "coach_note": coach_note,
            "responded_at": datetime.now().isoformat(),
        }).eq("id", request_id).eq("organization_id", org_id).eq(
            "status", "pending"
        ).execute()

        if not result.data:
            return None

        req = result.data[0]

        # 승인 시 스케줄에 자동 등록
        self._create_schedule_from_request(req, org_id)

        logger.info("레슨 신청 승인: request={}", request_id)
        return req

    def reject_request(
        self, request_id: str, org_id: int, coach_note: Optional[str] = None
    ) -> Optional[dict]:
        """레슨 신청 거절"""
        result = self.supabase.table("app_lesson_requests").update({
            "status": LessonRequestStatus.rejected.value,
            "coach_note": coach_note,
            "responded_at": datetime.now().isoformat(),
        }).eq("id", request_id).eq("organization_id", org_id).eq(
            "status", "pending"
        ).execute()

        if result.data:
            logger.info("레슨 신청 거절: request={}", request_id)
        return result.data[0] if result.data else None

    def reschedule_request(
        self,
        request_id: str,
        org_id: int,
        new_date: date,
        new_time: time,
        coach_note: Optional[str] = None,
    ) -> Optional[dict]:
        """레슨 시간 변경 제안"""
        result = self.supabase.table("app_lesson_requests").update({
            "status": LessonRequestStatus.rescheduled.value,
            "rescheduled_date": new_date.isoformat(),
            "rescheduled_time": new_time.isoformat(),
            "coach_note": coach_note,
            "responded_at": datetime.now().isoformat(),
        }).eq("id", request_id).eq("organization_id", org_id).eq(
            "status", "pending"
        ).execute()

        if result.data:
            logger.info(
                "레슨 시간 변경 제안: request={}, new={} {}",
                request_id, new_date, new_time,
            )
        return result.data[0] if result.data else None

    def cancel_request(self, request_id: str, org_id: int, member_id: str) -> Optional[dict]:
        """레슨 신청 취소 (학생/학부모 본인만)"""
        result = self.supabase.table("app_lesson_requests").update({
            "status": LessonRequestStatus.cancelled.value,
            "responded_at": datetime.now().isoformat(),
        }).eq("id", request_id).eq("organization_id", org_id).in_(
            "status", ["pending", "rescheduled"]
        ).execute()

        # 권한 확인 (본인 신청만 취소 가능)
        if result.data:
            req = result.data[0]
            if req["student_id"] != member_id and req["requested_by"] != member_id:
                # 롤백
                self.supabase.table("app_lesson_requests").update({
                    "status": "pending",
                    "responded_at": None,
                }).eq("id", request_id).execute()
                return None
            logger.info("레슨 신청 취소: request={}", request_id)
        return result.data[0] if result.data else None

    def _create_schedule_from_request(self, req: dict, org_id: int):
        """승인된 레슨 신청을 스케줄에 등록"""
        try:
            req_date = req["requested_date"]
            req_time = req["requested_start_time"]
            duration = req.get("duration_minutes", 60)

            # start_at, end_at 계산
            start_str = f"{req_date}T{req_time}"
            start_dt = datetime.fromisoformat(start_str)
            end_dt = start_dt + timedelta(minutes=duration)

            schedule_data = {
                "organization_id": org_id,
                "title": "레슨",
                "event_type": "lesson",
                "start_at": start_dt.isoformat(),
                "end_at": end_dt.isoformat(),
                "all_day": False,
                "visibility": "coaches",
                "assigned_coach_id": req["coach_id"],
                "participant_ids": [req["student_id"]],
                "status": "scheduled",
                "created_by": req["coach_id"],
            }

            self.supabase.table("app_schedules").insert(schedule_data).execute()
            logger.info("스케줄 자동 등록: date={}, coach={}", req_date, req["coach_id"])
        except Exception as e:
            logger.error("스케줄 자동 등록 실패: {}", e)

    # ─────────────────────────────────────────
    # 코치 빈 시간 조회
    # ─────────────────────────────────────────

    def get_coach_available_slots(
        self,
        org_id: int,
        coach_id: str,
        target_date: date,
        slot_duration: int = 60,
    ) -> List[dict]:
        """코치의 빈 시간 슬롯 조회

        1. 해당 날짜의 코치 일정 조회
        2. 클럽 운영 시간 내에서 빈 슬롯 계산
        3. 다른 학생 레슨은 "예약됨"으로만 표시 (이름 비공개)
        """
        date_str = target_date.isoformat()

        # 코치의 해당 날짜 일정
        try:
            events = self.supabase.table("app_schedules").select(
                "start_at, end_at, event_type, participant_ids"
            ).eq("organization_id", org_id).eq(
                "assigned_coach_id", coach_id
            ).gte("start_at", f"{date_str}T00:00:00").lt(
                "start_at", f"{date_str}T23:59:59"
            ).neq("status", "cancelled").execute()
        except Exception as e:
            logger.warning("코치 일정 조회 실패: coach={}, error={}", coach_id, e)
            events = type("R", (), {"data": []})()  # empty result

        busy_slots = []
        for ev in (events.data or []):
            start = datetime.fromisoformat(ev["start_at"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(ev["end_at"].replace("Z", "+00:00"))
            busy_slots.append({
                "start": start.strftime("%H:%M"),
                "end": end.strftime("%H:%M"),
                "type": ev.get("event_type", ""),
                "is_lesson": ev.get("event_type") == "lesson",
            })

        # 운영 시간 (기본: 09:00~21:00, 향후 club_settings에서 조회)
        open_hour, close_hour = 9, 21
        available_slots = []

        current = datetime.combine(target_date, time(open_hour, 0))
        end_of_day = datetime.combine(target_date, time(close_hour, 0))

        while current + timedelta(minutes=slot_duration) <= end_of_day:
            slot_start = current.strftime("%H:%M")
            slot_end = (current + timedelta(minutes=slot_duration)).strftime("%H:%M")

            is_busy = any(
                not (slot_end <= b["start"] or slot_start >= b["end"])
                for b in busy_slots
            )

            available_slots.append({
                "date": date_str,
                "start_time": slot_start,
                "end_time": slot_end,
                "is_available": not is_busy,
            })

            current += timedelta(minutes=30)  # 30분 단위 슬롯

        return available_slots

    # ─────────────────────────────────────────
    # 공강 알림 구독
    # ─────────────────────────────────────────

    def subscribe_vacancy(
        self,
        org_id: int,
        member_id: str,
        coach_id: Optional[str] = None,
        weekdays: Optional[List[int]] = None,
        time_range_start: Optional[time] = None,
        time_range_end: Optional[time] = None,
    ) -> dict:
        """공강 알림 구독 등록"""
        data = {
            "organization_id": org_id,
            "member_id": member_id,
            "coach_id": coach_id,
            "weekdays": weekdays,
            "time_range_start": time_range_start.isoformat() if time_range_start else None,
            "time_range_end": time_range_end.isoformat() if time_range_end else None,
            "is_active": True,
        }

        result = self.supabase.table("app_vacancy_subscribers").upsert(
            data, on_conflict="organization_id,member_id,coach_id"
        ).execute()
        return result.data[0] if result.data else data

    def unsubscribe_vacancy(self, sub_id: str, org_id: int, member_id: str) -> bool:
        """공강 알림 구독 해제"""
        result = self.supabase.table("app_vacancy_subscribers").update({
            "is_active": False,
        }).eq("id", sub_id).eq("organization_id", org_id).eq(
            "member_id", member_id
        ).execute()
        return bool(result.data)

    def get_my_subscriptions(self, org_id: int, member_id: str) -> List[dict]:
        """내 공강 알림 구독 목록"""
        result = self.supabase.table("app_vacancy_subscribers").select(
            "*"
        ).eq("organization_id", org_id).eq(
            "member_id", member_id
        ).eq("is_active", True).execute()
        return result.data or []


# 싱글톤
lesson_service = LessonService()
