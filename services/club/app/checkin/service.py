"""
Checkin Service

멀티 체크인/체크아웃 비즈니스 로직
"""

import math
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional, List, Tuple

from loguru import logger

from ..database import get_supabase_client
from .models import (
    CheckinMethod,
    CheckoutMethod,
    CheckinRequest,
    CheckinResponse,
    CheckoutResponse,
    QRSessionResponse,
    AttendanceRecord,
    AttendanceStats,
    WiFiCheckinConfig,
)


def _now_kst() -> datetime:
    """현재 KST 시간"""
    from datetime import timezone as tz
    KST = tz(timedelta(hours=9))
    return datetime.now(KST)


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    두 좌표 간 거리 계산 (미터 단위)
    Haversine formula
    """
    R = 6_371_000  # 지구 반경 (미터)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


class CheckinService:
    """통합 체크인/체크아웃 서비스"""

    # -----------------------------------------
    # Check-in
    # -----------------------------------------

    async def check_in(
        self,
        org_id: int,
        member_id: str,
        member_name: str,
        request: CheckinRequest,
        client_ip: str = "unknown",
    ) -> CheckinResponse:
        """
        통합 체크인 - 모든 방식 지원

        Args:
            org_id: 조직 ID
            member_id: 회원 ID
            member_name: 회원 이름
            request: 체크인 요청 (method, qr_code, wifi_ssid 등)
            client_ip: 클라이언트 IP
        """
        supabase = get_supabase_client()

        # 1. 오늘 이미 체크인했는지 확인
        today = date.today().isoformat()
        existing = (
            supabase.table("attendance")
            .select("id, checked_out_at")
            .eq("member_id", member_id)
            .eq("organization_id", org_id)
            .gte("check_in_at", f"{today}T00:00:00")
            .execute()
        )

        if existing.data:
            # 이미 체크인한 기록이 있는 경우
            record = existing.data[0]
            if not record.get("checked_out_at"):
                # 아직 체크아웃 안 했으면 중복 체크인 방지
                return CheckinResponse(
                    success=False,
                    member_name=member_name,
                    check_in_at=_now_kst(),
                    method=request.method,
                    message="오늘 이미 체크인했습니다. 먼저 체크아웃해주세요.",
                )
            # 체크아웃 후 재체크인은 허용 (같은 날 여러 세션)

        # 2. 체크인 방식별 검증
        method = request.method
        wifi_ssid_val = None

        if method == CheckinMethod.auto_ip:
            valid = await self._validate_ip(org_id, client_ip)
            if not valid:
                return CheckinResponse(
                    success=False,
                    member_name=member_name,
                    check_in_at=_now_kst(),
                    method=method,
                    message="클럽 IP 범위 밖입니다. 다른 체크인 방식을 시도해주세요.",
                )

        elif method == CheckinMethod.wifi:
            valid, msg = await self._validate_wifi(
                org_id, request.wifi_ssid, request.wifi_bssid, client_ip
            )
            if not valid:
                return CheckinResponse(
                    success=False,
                    member_name=member_name,
                    check_in_at=_now_kst(),
                    method=method,
                    message=msg,
                )
            wifi_ssid_val = request.wifi_ssid

        elif method == CheckinMethod.qr:
            valid, msg = await self._validate_qr(org_id, request.qr_code)
            if not valid:
                return CheckinResponse(
                    success=False,
                    member_name=member_name,
                    check_in_at=_now_kst(),
                    method=method,
                    message=msg,
                )

        elif method == CheckinMethod.gps:
            valid, msg = await self._validate_gps(
                org_id, request.latitude, request.longitude
            )
            if not valid:
                return CheckinResponse(
                    success=False,
                    member_name=member_name,
                    check_in_at=_now_kst(),
                    method=method,
                    message=msg,
                )

        elif method == CheckinMethod.manual:
            # manual은 코치만 가능 - 라우터에서 권한 확인
            pass

        elif method == CheckinMethod.coach_proxy:
            # coach_proxy는 별도 메서드에서 처리
            pass

        # 3. 출석 기록 생성
        now = _now_kst()
        attendance_data = {
            "member_id": member_id,
            "organization_id": org_id,
            "check_in_at": now.isoformat(),
            "attendance_type": request.attendance_type,
            "checkin_method": method.value,
            "client_ip": client_ip,
            "notes": request.notes,
        }
        if wifi_ssid_val:
            attendance_data["wifi_ssid"] = wifi_ssid_val

        response = supabase.table("attendance").insert(attendance_data).execute()

        if not response.data:
            return CheckinResponse(
                success=False,
                member_name=member_name,
                check_in_at=now,
                method=method,
                message="체크인 기록 저장에 실패했습니다.",
            )

        method_labels = {
            CheckinMethod.auto_ip: "IP 자동",
            CheckinMethod.wifi: "WiFi",
            CheckinMethod.qr: "QR 코드",
            CheckinMethod.gps: "위치 인증",
            CheckinMethod.manual: "수동",
            CheckinMethod.coach_proxy: "코치 대리",
        }

        return CheckinResponse(
            success=True,
            member_name=member_name,
            check_in_at=now,
            method=method,
            message=f"{method_labels.get(method, method.value)} 체크인 완료!",
        )

    # -----------------------------------------
    # Check-out
    # -----------------------------------------

    async def check_out(
        self,
        org_id: int,
        member_id: str,
        member_name: str,
        method: CheckoutMethod = CheckoutMethod.manual,
    ) -> CheckoutResponse:
        """체크아웃"""
        supabase = get_supabase_client()

        # 오늘 체크인 중 아직 체크아웃 안 한 기록 찾기
        today = date.today().isoformat()
        existing = (
            supabase.table("attendance")
            .select("id, check_in_at")
            .eq("member_id", member_id)
            .eq("organization_id", org_id)
            .gte("check_in_at", f"{today}T00:00:00")
            .is_("checked_out_at", "null")
            .order("check_in_at", desc=True)
            .limit(1)
            .execute()
        )

        if not existing.data:
            now = _now_kst()
            return CheckoutResponse(
                success=False,
                member_name=member_name,
                checked_out_at=now,
                duration_minutes=0,
                message="체크아웃할 체크인 기록이 없습니다.",
            )

        record = existing.data[0]
        now = _now_kst()
        check_in_at = datetime.fromisoformat(record["check_in_at"])

        # 시간대 정보 통일
        if check_in_at.tzinfo is None:
            KST = timezone(timedelta(hours=9))
            check_in_at = check_in_at.replace(tzinfo=KST)

        duration = now - check_in_at
        duration_minutes = int(duration.total_seconds() / 60)

        # 체크아웃 업데이트
        supabase.table("attendance").update(
            {
                "checked_out_at": now.isoformat(),
                "checkout_method": method.value,
            }
        ).eq("id", record["id"]).execute()

        hours = duration_minutes // 60
        mins = duration_minutes % 60
        if hours > 0:
            duration_str = f"{hours}시간 {mins}분"
        else:
            duration_str = f"{mins}분"

        return CheckoutResponse(
            success=True,
            member_name=member_name,
            checked_out_at=now,
            duration_minutes=duration_minutes,
            message=f"체크아웃 완료! 훈련 시간: {duration_str}",
        )

    # -----------------------------------------
    # QR Session
    # -----------------------------------------

    async def generate_qr_session(self, org_id: int) -> QRSessionResponse:
        """QR 세션 생성 (코치용)"""
        supabase = get_supabase_client()

        # club_settings에서 QR 유효시간 가져오기
        refresh_minutes = 5
        try:
            settings = (
                supabase.table("club_settings")
                .select("qr_refresh_minutes")
                .eq("organization_id", org_id)
                .single()
                .execute()
            )
            if settings.data and settings.data.get("qr_refresh_minutes"):
                refresh_minutes = settings.data["qr_refresh_minutes"]
        except Exception:
            pass

        # QR 코드 생성
        qr_code = uuid.uuid4().hex[:16]
        now = _now_kst()
        valid_until = now + timedelta(minutes=refresh_minutes)

        # 기존 유효 세션 만료시키기
        supabase.table("app_qr_sessions").update(
            {"valid_until": now.isoformat()}
        ).eq("organization_id", org_id).gt(
            "valid_until", now.isoformat()
        ).execute()

        # 새 세션 삽입
        supabase.table("app_qr_sessions").insert(
            {
                "organization_id": org_id,
                "qr_code": qr_code,
                "valid_from": now.isoformat(),
                "valid_until": valid_until.isoformat(),
            }
        ).execute()

        # QR 이미지 생성 (qrcode 라이브러리 사용 시도)
        qr_image_data_url = None
        try:
            import qrcode
            import io
            import base64

            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=10,
                border=2,
            )
            qr.add_data(qr_code)
            qr.make(fit=True)
            img = qr.make_image(fill_color="white", back_color="#0a0a0f")

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            qr_image_data_url = f"data:image/png;base64,{b64}"
        except ImportError:
            logger.warning("qrcode 라이브러리 없음. QR 이미지 미생성.")
        except Exception as e:
            logger.warning(f"QR 이미지 생성 실패: {e}")

        return QRSessionResponse(
            qr_code=qr_code,
            valid_until=valid_until,
            qr_image_data_url=qr_image_data_url,
        )

    async def get_active_qr(self, org_id: int) -> Optional[QRSessionResponse]:
        """현재 유효한 QR 세션 조회"""
        supabase = get_supabase_client()
        now = _now_kst()

        result = (
            supabase.table("app_qr_sessions")
            .select("qr_code, valid_until")
            .eq("organization_id", org_id)
            .gt("valid_until", now.isoformat())
            .lte("valid_from", now.isoformat())
            .order("valid_until", desc=True)
            .limit(1)
            .execute()
        )

        if not result.data:
            return None

        row = result.data[0]
        return QRSessionResponse(
            qr_code=row["qr_code"],
            valid_until=datetime.fromisoformat(row["valid_until"]),
        )

    # -----------------------------------------
    # Attendance Queries
    # -----------------------------------------

    async def get_today_attendance(self, org_id: int) -> List[AttendanceRecord]:
        """오늘 전체 출석 현황"""
        supabase = get_supabase_client()
        today = date.today().isoformat()

        result = (
            supabase.table("attendance")
            .select("id, member_id, check_in_at, checked_out_at, checkin_method, wifi_ssid, members!attendance_member_id_fkey(full_name)")
            .eq("organization_id", org_id)
            .gte("check_in_at", f"{today}T00:00:00")
            .order("check_in_at", desc=True)
            .execute()
        )

        records = []
        for row in result.data or []:
            check_in = datetime.fromisoformat(row["check_in_at"])
            checked_out = None
            duration = None

            if row.get("checked_out_at"):
                checked_out = datetime.fromisoformat(row["checked_out_at"])
                delta = checked_out - check_in
                duration = int(delta.total_seconds() / 60)

            member_name = ""
            members_data = row.get("members")
            if isinstance(members_data, dict):
                member_name = members_data.get("full_name", "")
            elif isinstance(members_data, list) and members_data:
                member_name = members_data[0].get("full_name", "")

            records.append(
                AttendanceRecord(
                    id=row["id"],
                    member_id=row["member_id"],
                    member_name=member_name,
                    check_in_at=check_in,
                    checked_out_at=checked_out,
                    method=row.get("checkin_method"),
                    duration_minutes=duration,
                    wifi_ssid=row.get("wifi_ssid"),
                )
            )
        return records

    async def get_attendance_history(
        self,
        org_id: int,
        member_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 50,
    ) -> List[AttendanceRecord]:
        """출석 히스토리"""
        supabase = get_supabase_client()

        query = (
            supabase.table("attendance")
            .select("id, member_id, check_in_at, checked_out_at, checkin_method, wifi_ssid, members!attendance_member_id_fkey(full_name)")
            .eq("organization_id", org_id)
        )

        if member_id:
            query = query.eq("member_id", member_id)
        if date_from:
            query = query.gte("check_in_at", f"{date_from}T00:00:00")
        if date_to:
            query = query.lte("check_in_at", f"{date_to}T23:59:59")

        result = query.order("check_in_at", desc=True).limit(limit).execute()

        records = []
        for row in result.data or []:
            check_in = datetime.fromisoformat(row["check_in_at"])
            checked_out = None
            duration = None

            if row.get("checked_out_at"):
                checked_out = datetime.fromisoformat(row["checked_out_at"])
                delta = checked_out - check_in
                duration = int(delta.total_seconds() / 60)

            member_name = ""
            members_data = row.get("members")
            if isinstance(members_data, dict):
                member_name = members_data.get("full_name", "")
            elif isinstance(members_data, list) and members_data:
                member_name = members_data[0].get("full_name", "")

            records.append(
                AttendanceRecord(
                    id=row["id"],
                    member_id=row["member_id"],
                    member_name=member_name,
                    check_in_at=check_in,
                    checked_out_at=checked_out,
                    method=row.get("checkin_method"),
                    duration_minutes=duration,
                    wifi_ssid=row.get("wifi_ssid"),
                )
            )
        return records

    async def get_attendance_stats(
        self, org_id: int, member_id: str
    ) -> AttendanceStats:
        """출석 통계"""
        supabase = get_supabase_client()

        # 전체 출석 일수
        all_records = (
            supabase.table("attendance")
            .select("check_in_at, checked_out_at")
            .eq("organization_id", org_id)
            .eq("member_id", member_id)
            .order("check_in_at", desc=True)
            .execute()
        )

        total_days = len(all_records.data or [])

        # 이번 달 출석
        now = _now_kst()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        this_month_records = (
            supabase.table("attendance")
            .select("id")
            .eq("organization_id", org_id)
            .eq("member_id", member_id)
            .gte("check_in_at", month_start.isoformat())
            .execute()
        )
        this_month = len(this_month_records.data or [])

        # 연속 출석 (streak) 계산
        streak = 0
        if all_records.data:
            dates_set = set()
            for r in all_records.data:
                d = datetime.fromisoformat(r["check_in_at"]).date()
                dates_set.add(d)

            check_date = date.today()
            while check_date in dates_set:
                streak += 1
                check_date -= timedelta(days=1)

        # 평균 훈련 시간
        durations = []
        for r in all_records.data or []:
            if r.get("checked_out_at") and r.get("check_in_at"):
                ci = datetime.fromisoformat(r["check_in_at"])
                co = datetime.fromisoformat(r["checked_out_at"])
                mins = (co - ci).total_seconds() / 60
                if 0 < mins < 720:  # 12시간 이내만 유효
                    durations.append(mins)

        avg_duration = None
        if durations:
            avg_duration = round(sum(durations) / len(durations), 1)

        return AttendanceStats(
            total_days=total_days,
            this_month=this_month,
            streak=streak,
            avg_duration_minutes=avg_duration,
        )

    async def get_checkin_status(
        self, org_id: int, member_id: str, client_ip: str
    ) -> dict:
        """오늘 체크인 상태 + 자동 체크인 가능 여부"""
        supabase = get_supabase_client()
        today = date.today().isoformat()

        existing = (
            supabase.table("attendance")
            .select("id, check_in_at, checked_out_at, checkin_method")
            .eq("member_id", member_id)
            .eq("organization_id", org_id)
            .gte("check_in_at", f"{today}T00:00:00")
            .order("check_in_at", desc=True)
            .limit(1)
            .execute()
        )

        already_checked_in = False
        checked_out = False
        checkin_record = None

        if existing.data:
            record = existing.data[0]
            checkin_record = record
            if record.get("checked_out_at"):
                checked_out = True
            else:
                already_checked_in = True

        auto_ip = await self._validate_ip(org_id, client_ip)

        return {
            "already_checked_in": already_checked_in,
            "checked_out": checked_out,
            "checkin_record": checkin_record,
            "auto_checkin_available": auto_ip,
            "client_ip": client_ip,
            "current_time": _now_kst().isoformat(),
        }

    # -----------------------------------------
    # Coach Proxy Check-in
    # -----------------------------------------

    async def coach_proxy_checkin(
        self,
        org_id: int,
        coach_id: str,
        student_member_id: str,
        student_name: str,
    ) -> CheckinResponse:
        """코치 대리 체크인"""
        req = CheckinRequest(
            method=CheckinMethod.coach_proxy,
            notes=f"코치 대리 체크인 (coach_id: {coach_id})",
        )
        return await self.check_in(
            org_id=org_id,
            member_id=student_member_id,
            member_name=student_name,
            request=req,
            client_ip="coach_proxy",
        )

    # -----------------------------------------
    # Auto Checkout
    # -----------------------------------------

    async def auto_checkout(self, org_id: int, timeout_hours: int = 4) -> int:
        """
        자동 체크아웃 배치 처리

        지정 시간 이상 체크아웃하지 않은 기록을 자동으로 체크아웃.
        Returns: 자동 체크아웃된 수
        """
        supabase = get_supabase_client()
        now = _now_kst()
        cutoff = now - timedelta(hours=timeout_hours)

        # 체크아웃 안 한 오래된 기록
        stale = (
            supabase.table("attendance")
            .select("id")
            .eq("organization_id", org_id)
            .is_("checked_out_at", "null")
            .lt("check_in_at", cutoff.isoformat())
            .execute()
        )

        count = 0
        for row in stale.data or []:
            supabase.table("attendance").update(
                {
                    "checked_out_at": now.isoformat(),
                    "checkout_method": CheckoutMethod.timeout.value,
                }
            ).eq("id", row["id"]).execute()
            count += 1

        logger.info(f"Auto-checkout: {count} records for org {org_id}")
        return count

    # -----------------------------------------
    # WiFi Config
    # -----------------------------------------

    async def configure_wifi(
        self, org_id: int, ssid: str, bssid: Optional[str] = None
    ) -> WiFiCheckinConfig:
        """WiFi 설정 저장"""
        supabase = get_supabase_client()

        update_data = {"wifi_ssid": ssid}
        if bssid is not None:
            update_data["wifi_bssid"] = bssid

        supabase.table("club_settings").update(update_data).eq(
            "organization_id", org_id
        ).execute()

        return WiFiCheckinConfig(ssid=ssid, bssid=bssid)

    async def get_wifi_config(self, org_id: int) -> WiFiCheckinConfig:
        """WiFi 설정 조회"""
        supabase = get_supabase_client()

        try:
            result = (
                supabase.table("club_settings")
                .select("wifi_ssid, wifi_bssid")
                .eq("organization_id", org_id)
                .single()
                .execute()
            )
            if result.data:
                return WiFiCheckinConfig(
                    ssid=result.data.get("wifi_ssid"),
                    bssid=result.data.get("wifi_bssid"),
                )
        except Exception:
            pass

        return WiFiCheckinConfig()

    # -----------------------------------------
    # Validation Helpers
    # -----------------------------------------

    async def _validate_ip(self, org_id: int, client_ip: str) -> bool:
        """IP 기반 검증"""
        supabase = get_supabase_client()

        try:
            settings = (
                supabase.table("club_settings")
                .select("auto_checkin_enabled, allowed_ips")
                .eq("organization_id", org_id)
                .single()
                .execute()
            )

            if not settings.data:
                return False

            if not settings.data.get("auto_checkin_enabled"):
                return False

            allowed_ips = settings.data.get("allowed_ips", []) or []
            for allowed_ip in allowed_ips:
                if client_ip == allowed_ip:
                    return True
                if allowed_ip.endswith(".*"):
                    prefix = allowed_ip[:-1]
                    if client_ip.startswith(prefix):
                        return True

            return False
        except Exception:
            return False

    async def _validate_wifi(
        self,
        org_id: int,
        wifi_ssid: Optional[str],
        wifi_bssid: Optional[str],
        client_ip: str,
    ) -> Tuple[bool, str]:
        """WiFi 기반 검증 (SSID 매칭 + IP 이중 검증)"""
        if not wifi_ssid:
            return False, "WiFi SSID가 필요합니다."

        supabase = get_supabase_client()

        try:
            settings = (
                supabase.table("club_settings")
                .select("wifi_ssid, wifi_bssid, allowed_ips")
                .eq("organization_id", org_id)
                .single()
                .execute()
            )

            if not settings.data or not settings.data.get("wifi_ssid"):
                return False, "클럽 WiFi가 설정되어 있지 않습니다."

            club_ssid = settings.data["wifi_ssid"]
            club_bssid = settings.data.get("wifi_bssid")

            # SSID 매칭 (대소문자 무시)
            if wifi_ssid.lower().strip() != club_ssid.lower().strip():
                return False, "클럽 WiFi와 일치하지 않습니다."

            # BSSID 매칭 (설정된 경우)
            if club_bssid and wifi_bssid:
                if wifi_bssid.lower().strip() != club_bssid.lower().strip():
                    return False, "WiFi 접속점(BSSID)이 일치하지 않습니다."

            # IP 이중 검증 (스푸핑 방지)
            allowed_ips = settings.data.get("allowed_ips", []) or []
            ip_match = False
            for allowed_ip in allowed_ips:
                if client_ip == allowed_ip:
                    ip_match = True
                    break
                if allowed_ip.endswith(".*"):
                    prefix = allowed_ip[:-1]
                    if client_ip.startswith(prefix):
                        ip_match = True
                        break

            if not ip_match:
                return False, "WiFi SSID는 일치하지만 IP 주소가 클럽 범위 밖입니다."

            return True, ""

        except Exception as e:
            logger.error(f"WiFi validation error: {e}")
            return False, "WiFi 검증 중 오류가 발생했습니다."

    async def _validate_qr(
        self, org_id: int, qr_code: Optional[str]
    ) -> Tuple[bool, str]:
        """QR 코드 검증"""
        if not qr_code:
            return False, "QR 코드가 필요합니다."

        supabase = get_supabase_client()
        now = _now_kst()

        try:
            result = (
                supabase.table("app_qr_sessions")
                .select("id, valid_from, valid_until")
                .eq("organization_id", org_id)
                .eq("qr_code", qr_code)
                .single()
                .execute()
            )

            if not result.data:
                return False, "유효하지 않은 QR 코드입니다."

            valid_from = datetime.fromisoformat(result.data["valid_from"])
            valid_until = datetime.fromisoformat(result.data["valid_until"])

            # 시간대 통일
            if valid_from.tzinfo is None:
                KST = timezone(timedelta(hours=9))
                valid_from = valid_from.replace(tzinfo=KST)
                valid_until = valid_until.replace(tzinfo=KST)

            if now < valid_from or now > valid_until:
                return False, "QR 코드가 만료되었습니다. 새 QR 코드를 요청하세요."

            return True, ""

        except Exception as e:
            logger.error(f"QR validation error: {e}")
            return False, "QR 코드 검증 중 오류가 발생했습니다."

    async def _validate_gps(
        self,
        org_id: int,
        latitude: Optional[float],
        longitude: Optional[float],
    ) -> Tuple[bool, str]:
        """GPS geofence 검증"""
        if latitude is None or longitude is None:
            return False, "위치 정보가 필요합니다."

        supabase = get_supabase_client()

        try:
            settings = (
                supabase.table("club_settings")
                .select("geofence_lat, geofence_lng, geofence_radius_m")
                .eq("organization_id", org_id)
                .single()
                .execute()
            )

            if not settings.data:
                return False, "클럽 위치가 설정되어 있지 않습니다."

            club_lat = settings.data.get("geofence_lat")
            club_lng = settings.data.get("geofence_lng")
            radius = settings.data.get("geofence_radius_m", 100)

            if club_lat is None or club_lng is None:
                return False, "클럽 GPS 위치가 설정되어 있지 않습니다."

            distance = _haversine_distance(latitude, longitude, club_lat, club_lng)

            if distance > radius:
                return (
                    False,
                    f"클럽 위치에서 {int(distance)}m 떨어져 있습니다. "
                    f"(허용 반경: {radius}m)",
                )

            return True, ""

        except Exception as e:
            logger.error(f"GPS validation error: {e}")
            return False, "위치 검증 중 오류가 발생했습니다."


# Singleton
checkin_service = CheckinService()
