"""
Discord Webhook 알림 시스템 (Data Guardian)

Discord Webhook을 통한 데이터 품질 알림, 검증 결과 보고, 정기 리포트 발송.
환경변수 DISCORD_WEBHOOK_URL 설정 필요.

사용법:
    from app.discord_notify import send_alert, send_validation_report, send_health_report
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from loguru import logger

import httpx


# Discord embed 색상 (심각도별)
SEVERITY_COLORS = {
    "critical": 0xFF0000,   # 빨강
    "error": 0xE74C3C,      # 진한 빨강
    "warning": 0xF39C12,    # 주황
    "info": 0x3498DB,       # 파랑
    "success": 0x2ECC71,    # 초록
}

# 심각도별 아이콘
SEVERITY_ICONS = {
    "critical": "🚨",
    "error": "❌",
    "warning": "⚠️",
    "info": "ℹ️",
    "success": "✅",
}


def _get_webhook_url() -> Optional[str]:
    """Discord Webhook URL 가져오기"""
    url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        logger.debug("DISCORD_WEBHOOK_URL 미설정 — Discord 알림 비활성")
        return None
    return url


async def _send_webhook(payload: Dict[str, Any]) -> bool:
    """Discord Webhook으로 메시지 전송"""
    url = _get_webhook_url()
    if not url:
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code in (200, 204):
                return True
            else:
                logger.warning(f"Discord webhook 응답 오류: {response.status_code} {response.text[:200]}")
                return False
    except Exception as e:
        logger.error(f"Discord webhook 전송 실패: {e}")
        return False


def _send_webhook_sync(payload: Dict[str, Any]) -> bool:
    """Discord Webhook 동기 전송 (스케줄러 등 sync 컨텍스트용)"""
    url = _get_webhook_url()
    if not url:
        return False

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload)
            if response.status_code in (200, 204):
                return True
            else:
                logger.warning(f"Discord webhook 응답 오류: {response.status_code}")
                return False
    except Exception as e:
        logger.error(f"Discord webhook 전송 실패: {e}")
        return False


# =====================================================================
# 알림 전송 함수들
# =====================================================================

async def send_alert(
    severity: str,
    title: str,
    message: str,
    fields: Optional[List[Dict[str, str]]] = None,
) -> bool:
    """단건 알림 전송

    Args:
        severity: critical | error | warning | info | success
        title: 알림 제목
        message: 알림 본문
        fields: 추가 필드 [{"name": "필드명", "value": "값", "inline": True}]
    """
    color = SEVERITY_COLORS.get(severity, SEVERITY_COLORS["info"])
    icon = SEVERITY_ICONS.get(severity, "📢")

    embed = {
        "title": f"{icon} {title}",
        "description": message[:4096],
        "color": color,
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "FencingMind Data Guardian"},
    }

    if fields:
        embed["fields"] = [
            {
                "name": f["name"],
                "value": str(f["value"])[:1024],
                "inline": f.get("inline", True),
            }
            for f in fields[:25]  # Discord 최대 25 필드
        ]

    return await _send_webhook({"embeds": [embed]})


async def send_validation_report(
    summary: Dict[str, Any],
    issues: Optional[List[Any]] = None,
    trigger: str = "manual",
) -> bool:
    """검증 결과 보고서 전송

    Args:
        summary: run_validation() 결과 (total_issues, errors, warnings, by_rule)
        issues: ValidationIssue 리스트 (상위 10개만 표시)
        trigger: 트리거 유형 (manual, post_scrape, scheduled)
    """
    total = summary.get("total_issues", 0)
    errors = summary.get("errors", 0)
    warnings = summary.get("warnings", 0)
    by_rule = summary.get("by_rule", {})

    if errors == 0 and warnings == 0:
        severity = "success"
        status_text = "모든 검증 통과"
    elif errors > 0:
        severity = "error"
        status_text = f"ERROR {errors}건 발견"
    else:
        severity = "warning"
        status_text = f"WARNING {warnings}건"

    color = SEVERITY_COLORS.get(severity, SEVERITY_COLORS["info"])
    icon = SEVERITY_ICONS.get(severity, "📊")

    # 규칙별 통계 문자열
    rule_stats = "\n".join(
        f"  {rule}: {count}건" for rule, count in sorted(by_rule.items())
    ) or "  (없음)"

    embed = {
        "title": f"{icon} 데이터 검증 결과 — {status_text}",
        "color": color,
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": f"FencingMind Data Guardian | trigger: {trigger}"},
        "fields": [
            {"name": "전체 이슈", "value": str(total), "inline": True},
            {"name": "ERROR", "value": str(errors), "inline": True},
            {"name": "WARNING", "value": str(warnings), "inline": True},
            {"name": "규칙별 분포", "value": f"```\n{rule_stats}\n```", "inline": False},
        ],
    }

    # 상위 이슈 목록 (최대 10개)
    if issues:
        issue_lines = []
        for issue in issues[:10]:
            if hasattr(issue, "rule_id"):
                line = f"[{issue.rule_id}] {issue.severity}: {issue.message[:80]}"
            elif isinstance(issue, dict):
                line = f"[{issue.get('rule_id','')}] {issue.get('severity','')}: {issue.get('message','')[:80]}"
            else:
                line = str(issue)[:80]
            issue_lines.append(line)

        issue_text = "\n".join(issue_lines)
        if len(issues) > 10:
            issue_text += f"\n... 외 {len(issues) - 10}건"

        embed["fields"].append({
            "name": "주요 이슈",
            "value": f"```\n{issue_text[:1024]}\n```",
            "inline": False,
        })

    return await _send_webhook({"embeds": [embed]})


async def send_health_report(health_data: Dict[str, Any]) -> bool:
    """건강 상태 보고서 전송

    Args:
        health_data: DataQualityMonitor.run_full_health_check() 결과
    """
    dashboard = health_data.get("dashboard", {})
    health_status = dashboard.get("health_status", "unknown")
    overall_health = dashboard.get("overall_health", 0)

    if health_status == "healthy":
        severity = "success"
    elif health_status == "degraded":
        severity = "warning"
    else:
        severity = "error"

    color = SEVERITY_COLORS.get(severity, SEVERITY_COLORS["info"])
    icon = SEVERITY_ICONS.get(severity, "🏥")

    # 메트릭 상태 요약
    metrics = dashboard.get("metrics", {})
    metric_lines = []
    for metric_type, metric_data in metrics.items():
        status = "✅" if metric_data.get("is_healthy") else "❌"
        value = metric_data.get("value", "N/A")
        threshold = metric_data.get("threshold", "N/A")
        metric_lines.append(f"{status} {metric_type}: {value} (기준: {threshold})")

    metric_text = "\n".join(metric_lines) or "(메트릭 없음)"

    # 알림 요약
    alerts = dashboard.get("alerts", {})
    alert_text = (
        f"전체: {alerts.get('total', 0)}, "
        f"미확인: {alerts.get('unacknowledged', 0)}, "
        f"CRITICAL: {alerts.get('critical', 0)}"
    )

    embed = {
        "title": f"{icon} 시스템 건강 상태 — {health_status.upper()} ({overall_health:.0%})",
        "color": color,
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "FencingMind Data Guardian | Health Check"},
        "fields": [
            {"name": "전체 건강도", "value": f"{overall_health:.1%}", "inline": True},
            {"name": "상태", "value": health_status.upper(), "inline": True},
            {"name": "알림", "value": alert_text, "inline": True},
            {"name": "메트릭 상세", "value": f"```\n{metric_text[:1024]}\n```", "inline": False},
        ],
    }

    return await _send_webhook({"embeds": [embed]})


async def send_weekly_summary(
    validation_summary: Dict[str, Any],
    scrape_stats: Dict[str, Any],
    analysis_text: str = "",
) -> bool:
    """주간 요약 리포트 전송

    Args:
        validation_summary: 주간 검증 누적 결과
        scrape_stats: 주간 스크래핑 통계
        analysis_text: LLM 분석 요약 (선택)
    """
    embed = {
        "title": "📊 주간 데이터 품질 리포트",
        "color": SEVERITY_COLORS["info"],
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "FencingMind Data Guardian | Weekly Report"},
        "fields": [
            {
                "name": "검증 요약",
                "value": (
                    f"총 검증: {validation_summary.get('total_runs', 0)}회\n"
                    f"ERROR: {validation_summary.get('total_errors', 0)}건\n"
                    f"WARNING: {validation_summary.get('total_warnings', 0)}건"
                ),
                "inline": True,
            },
            {
                "name": "스크래핑 통계",
                "value": (
                    f"대회: {scrape_stats.get('competitions_scraped', 0)}개\n"
                    f"종목: {scrape_stats.get('events_scraped', 0)}개\n"
                    f"변경 감지: {scrape_stats.get('changes_detected', 0)}건"
                ),
                "inline": True,
            },
        ],
    }

    if analysis_text:
        embed["fields"].append({
            "name": "AI 분석",
            "value": analysis_text[:1024],
            "inline": False,
        })

    return await _send_webhook({"embeds": [embed]})


async def send_scrape_complete(
    comp_name: str,
    events_count: int,
    validation_result: Optional[Dict[str, Any]] = None,
) -> bool:
    """스크래핑 완료 + 검증 결과 알림

    Args:
        comp_name: 대회명
        events_count: 수집된 종목 수
        validation_result: 검증 결과 (없으면 검증 안 함)
    """
    fields = [
        {"name": "대회", "value": comp_name, "inline": True},
        {"name": "종목 수", "value": str(events_count), "inline": True},
    ]

    if validation_result:
        errors = validation_result.get("errors", 0)
        warnings = validation_result.get("warnings", 0)
        severity = "error" if errors > 0 else ("warning" if warnings > 0 else "success")
        fields.append({
            "name": "검증 결과",
            "value": f"ERROR: {errors}, WARNING: {warnings}",
            "inline": True,
        })
    else:
        severity = "info"

    return await send_alert(
        severity=severity,
        title=f"스크래핑 완료: {comp_name}",
        message=f"{events_count}개 종목 수집 완료",
        fields=fields,
    )
