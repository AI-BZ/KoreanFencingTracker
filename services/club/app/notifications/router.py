"""
Notification Router - FCM Push + Kakao Alimtalk API

코치용: 알림 발송, 구독 관리, 통계
회원용: 알림 조회, 읽음 처리, 푸시 토큰 관리
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from ..club.dependencies import (
    ClubMemberContext,
    get_current_club_member,
    require_coach,
    require_staff,
)
from .models import (
    PushTokenRegister,
    PushTokenResponse,
    NotificationSend,
    NotificationListResponse,
    NotificationResponse,
    NotificationStatsResponse,
    NotificationChannel,
    VacancySubscription,
    VacancySubscriptionResponse,
    VacancyNotifyRequest,
    VacancyNotifyResponse,
)
from .service import notification_service

router = APIRouter(prefix="/notifications", tags=["Notifications"])


# =============================================
# 푸시 토큰 관리 (회원용)
# =============================================

@router.post("/push-token", response_model=PushTokenResponse)
async def register_push_token(
    data: PushTokenRegister,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """FCM 푸시 토큰 등록 (PWA 설치 시)"""
    token = notification_service.register_push_token(
        member_id=member.member_id,
        token=data.token,
        device_type=data.device_type.value,
        device_name=data.device_name,
    )
    return PushTokenResponse(
        id=token["id"],
        device_type=data.device_type,
        device_name=token.get("device_name"),
        is_active=token["is_active"],
        last_used_at=token.get("last_used_at") or token["created_at"],
    )


@router.get("/push-tokens")
async def list_push_tokens(
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """내 푸시 토큰 목록"""
    tokens = notification_service.list_push_tokens(member.member_id)
    return {"tokens": tokens}


@router.delete("/push-token/{token}")
async def deactivate_push_token(
    token: str,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """푸시 토큰 비활성화"""
    success = notification_service.deactivate_push_token(member.member_id, token)
    if not success:
        raise HTTPException(404, "토큰을 찾을 수 없습니다")
    return {"success": True, "message": "푸시 토큰이 비활성화되었습니다"}


# =============================================
# 알림 조회 (회원용)
# =============================================

@router.get("/my", response_model=NotificationListResponse)
async def get_my_notifications(
    limit: int = Query(20, le=50),
    offset: int = Query(0, ge=0),
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """내 알림 목록"""
    notifications, total, unread = notification_service.get_notifications(
        member_id=member.member_id,
        limit=limit,
        offset=offset,
    )

    return NotificationListResponse(
        total=total,
        unread_count=unread,
        notifications=[
            NotificationResponse(
                id=n["id"],
                notification_type=n["notification_type"],
                channel=n["channel"],
                title=n.get("title"),
                message=n.get("message"),
                status=n["status"],
                reference_type=n.get("reference_type"),
                reference_id=n.get("reference_id"),
                sent_at=n.get("sent_at"),
                read_at=n.get("read_at"),
                created_at=n["created_at"],
            )
            for n in notifications
        ],
    )


@router.post("/my/{notification_id}/read")
async def mark_as_read(
    notification_id: int,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """알림 읽음 처리"""
    success = notification_service.mark_as_read(notification_id, member.member_id)
    if not success:
        raise HTTPException(404, "알림을 찾을 수 없습니다")
    return {"success": True}


@router.post("/my/read-all")
async def mark_all_as_read(
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """모든 알림 읽음 처리"""
    count = notification_service.mark_all_as_read(member.member_id)
    return {"success": True, "read_count": count}


# =============================================
# 알림 발송 (코치용)
# =============================================

@router.post("/send")
async def send_notification(
    data: NotificationSend,
    member: ClubMemberContext = Depends(require_coach),
):
    """알림 발송 (코치 이상)"""
    # 알림톡 포함 시 구독 체크
    if NotificationChannel.alimtalk in data.channels:
        sub = notification_service.get_subscription(member.organization_id)
        if not sub or not sub.get("alimtalk_enabled"):
            raise HTTPException(
                403,
                "알림톡은 유료 구독 시에만 사용 가능합니다. FCM/앱 알림을 이용해주세요.",
            )

    results = await notification_service.send_bulk_notification(
        org_id=member.organization_id,
        member_ids=data.member_ids,
        notification_type=data.notification_type.value,
        title=data.title,
        message=data.message,
        channels=[ch.value for ch in data.channels],
        reference_type=data.reference_type,
        reference_id=data.reference_id,
    )

    return {
        "success": True,
        **results,
        "message": f"{results['sent']}명에게 알림을 발송했습니다",
    }


# =============================================
# 구독 & 통계 (코치용)
# =============================================

@router.get("/subscription")
async def get_subscription(
    member: ClubMemberContext = Depends(require_staff),
):
    """알림 구독 정보 (알림톡 한도 포함)"""
    sub = notification_service.get_subscription(member.organization_id)
    if not sub:
        return {
            "tier": "free",
            "is_active": False,
            "fcm_enabled": True,
            "alimtalk_enabled": False,
            "alimtalk_limit": 0,
            "alimtalk_used": 0,
            "alimtalk_remaining": 0,
        }
    return sub


@router.get("/stats", response_model=NotificationStatsResponse)
async def get_notification_stats(
    member: ClubMemberContext = Depends(require_staff),
):
    """이번 달 알림 통계"""
    stats = notification_service.get_notification_stats(member.organization_id)
    return NotificationStatsResponse(**stats)


# =============================================
# 공강 (Vacancy) 알림 (학생/코치용)
# =============================================

@router.post(
    "/vacancy/subscribe",
    response_model=VacancySubscriptionResponse,
)
async def subscribe_vacancy(
    data: VacancySubscription,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """공강 알림 구독 (학생이 원하는 시간대/코치 등록)"""
    result = await notification_service.subscribe_vacancy(
        org_id=member.organization_id,
        member_id=member.member_id,
        data=data.model_dump(),
    )
    return VacancySubscriptionResponse(**result)


@router.delete("/vacancy/{subscription_id}")
async def unsubscribe_vacancy(
    subscription_id: str,
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """공강 알림 구독 해제"""
    success = await notification_service.unsubscribe_vacancy(
        org_id=member.organization_id,
        subscription_id=subscription_id,
        member_id=member.member_id,
    )
    if not success:
        raise HTTPException(404, "구독을 찾을 수 없습니다")
    return {"success": True, "message": "공강 알림 구독이 해제되었습니다"}


@router.get("/vacancy/my")
async def get_my_vacancy_subscriptions(
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """내 공강 알림 구독 목록"""
    subscriptions = await notification_service.get_vacancy_subscriptions(
        org_id=member.organization_id,
        member_id=member.member_id,
    )
    return {
        "subscriptions": [
            VacancySubscriptionResponse(**sub) for sub in subscriptions
        ]
    }


@router.post(
    "/vacancy/notify",
    response_model=VacancyNotifyResponse,
)
async def notify_vacancy(
    data: VacancyNotifyRequest,
    member: ClubMemberContext = Depends(require_coach),
):
    """공강 알림 발송 (코치 이상 - 레슨 자리 발생 시)"""
    result = await notification_service.notify_vacancy(
        org_id=member.organization_id,
        lesson_id=data.lesson_id,
        coach_id=data.coach_id,
        lesson_time={
            "day_of_week": data.day_of_week,
            "time_start": data.time_start,
            "time_end": data.time_end,
        },
    )
    return VacancyNotifyResponse(**result)
