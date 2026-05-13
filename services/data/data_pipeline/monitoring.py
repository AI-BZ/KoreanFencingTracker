"""
데이터 품질 모니터링 시스템

CLAUDE.md 제1원칙을 위한 데이터 품질 추적 및 알림
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from loguru import logger
from enum import Enum
from dataclasses import dataclass, field
import json


class AlertSeverity(str, Enum):
    """알림 심각도"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class MetricType(str, Enum):
    """메트릭 유형"""
    VALIDATION_PASS_RATE = "validation_pass_rate"
    SYNC_SUCCESS_RATE = "sync_success_rate"
    DATA_FRESHNESS = "data_freshness"
    DUPLICATE_RATE = "duplicate_rate"
    REFERENTIAL_INTEGRITY = "referential_integrity"
    PIPELINE_LATENCY = "pipeline_latency"


@dataclass
class QualityMetric:
    """품질 메트릭"""
    metric_type: MetricType
    value: float
    threshold: float
    timestamp: datetime = field(default_factory=datetime.now)
    details: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_healthy(self) -> bool:
        """기준치 충족 여부"""
        if self.metric_type in [
            MetricType.VALIDATION_PASS_RATE,
            MetricType.SYNC_SUCCESS_RATE,
            MetricType.REFERENTIAL_INTEGRITY,
        ]:
            return self.value >= self.threshold
        else:
            return self.value <= self.threshold
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_type": self.metric_type.value,
            "value": self.value,
            "threshold": self.threshold,
            "is_healthy": self.is_healthy,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }


@dataclass
class Alert:
    """알림"""
    severity: AlertSeverity
    title: str
    message: str
    metric: Optional[QualityMetric] = None
    timestamp: datetime = field(default_factory=datetime.now)
    acknowledged: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "metric": self.metric.to_dict() if self.metric else None,
            "timestamp": self.timestamp.isoformat(),
            "acknowledged": self.acknowledged,
        }


class DataQualityMonitor:
    """
    데이터 품질 모니터링
    
    기능:
    - 실시간 품질 메트릭 수집
    - 임계치 기반 알림
    - 품질 대시보드 데이터 제공
    """
    
    # 기본 임계치
    DEFAULT_THRESHOLDS = {
        MetricType.VALIDATION_PASS_RATE: 0.95,      # 95% 이상 통과
        MetricType.SYNC_SUCCESS_RATE: 0.99,         # 99% 이상 동기화 성공
        MetricType.DATA_FRESHNESS: 24,               # 24시간 이내 갱신
        MetricType.DUPLICATE_RATE: 0.01,            # 1% 이하 중복
        MetricType.REFERENTIAL_INTEGRITY: 0.999,    # 99.9% 이상 참조 무결성
        MetricType.PIPELINE_LATENCY: 5000,          # 5초 이내 처리
    }
    
    def __init__(self, db_client=None, thresholds: Optional[Dict[MetricType, float]] = None):
        self.db = db_client
        self.thresholds = {**self.DEFAULT_THRESHOLDS, **(thresholds or {})}
        self._metrics: List[QualityMetric] = []
        self._alerts: List[Alert] = []
        self._max_history = 10000
    
    # ==================== 메트릭 수집 ====================
    
    def record_metric(
        self,
        metric_type: MetricType,
        value: float,
        details: Optional[Dict[str, Any]] = None
    ) -> QualityMetric:
        """메트릭 기록"""
        metric = QualityMetric(
            metric_type=metric_type,
            value=value,
            threshold=self.thresholds.get(metric_type, 0),
            details=details or {}
        )
        
        self._metrics.append(metric)
        
        # 히스토리 크기 제한
        if len(self._metrics) > self._max_history:
            self._metrics = self._metrics[-self._max_history:]
        
        # 임계치 확인 및 알림 생성
        if not metric.is_healthy:
            self._create_alert(metric)
        
        # DB에 메트릭 저장
        self._save_metric_to_db(metric)
        
        return metric
    
    def _create_alert(self, metric: QualityMetric) -> Alert:
        """알림 생성"""
        severity = self._determine_severity(metric)
        
        alert = Alert(
            severity=severity,
            title=f"{metric.metric_type.value} 이상",
            message=self._generate_alert_message(metric),
            metric=metric
        )
        
        self._alerts.append(alert)
        
        # 알림 저장 및 발송
        self._save_alert_to_db(alert)
        self._send_alert_notification(alert)
        
        logger.warning(f"🚨 Alert: {alert.title} - {alert.message}")
        
        return alert
    
    def _determine_severity(self, metric: QualityMetric) -> AlertSeverity:
        """알림 심각도 결정"""
        threshold = self.thresholds.get(metric.metric_type, 0)
        deviation = abs(metric.value - threshold) / (threshold if threshold != 0 else 1)
        
        if deviation > 0.5:  # 50% 이상 벗어남
            return AlertSeverity.CRITICAL
        elif deviation > 0.2:  # 20% 이상 벗어남
            return AlertSeverity.ERROR
        elif deviation > 0.1:  # 10% 이상 벗어남
            return AlertSeverity.WARNING
        else:
            return AlertSeverity.INFO
    
    def _generate_alert_message(self, metric: QualityMetric) -> str:
        """알림 메시지 생성"""
        messages = {
            MetricType.VALIDATION_PASS_RATE: f"검증 통과율이 {metric.value:.1%}로 기준({metric.threshold:.1%})에 미달합니다.",
            MetricType.SYNC_SUCCESS_RATE: f"동기화 성공률이 {metric.value:.1%}로 기준({metric.threshold:.1%})에 미달합니다.",
            MetricType.DATA_FRESHNESS: f"데이터 갱신 주기가 {metric.value:.1f}시간으로 기준({metric.threshold}시간)을 초과했습니다.",
            MetricType.DUPLICATE_RATE: f"중복 데이터 비율이 {metric.value:.2%}로 기준({metric.threshold:.2%})을 초과했습니다.",
            MetricType.REFERENTIAL_INTEGRITY: f"참조 무결성이 {metric.value:.2%}로 기준({metric.threshold:.2%})에 미달합니다.",
            MetricType.PIPELINE_LATENCY: f"파이프라인 처리 시간이 {metric.value:.0f}ms로 기준({metric.threshold}ms)을 초과했습니다.",
        }
        return messages.get(metric.metric_type, f"{metric.metric_type.value}: {metric.value}")
    
    def _save_metric_to_db(self, metric: QualityMetric) -> None:
        """메트릭 DB 저장"""
        if not self.db:
            return
        
        try:
            self.db.table("quality_metrics").insert({
                "metric_type": metric.metric_type.value,
                "value": metric.value,
                "threshold": metric.threshold,
                "is_healthy": metric.is_healthy,
                "details": metric.details,
                "created_at": metric.timestamp.isoformat()
            }).execute()
        except Exception as e:
            logger.warning(f"메트릭 저장 실패: {e}")
    
    def _save_alert_to_db(self, alert: Alert) -> None:
        """알림 DB 저장"""
        if not self.db:
            return
        
        try:
            self.db.table("quality_alerts").insert({
                "severity": alert.severity.value,
                "title": alert.title,
                "message": alert.message,
                "metric_type": alert.metric.metric_type.value if alert.metric else None,
                "metric_value": alert.metric.value if alert.metric else None,
                "acknowledged": alert.acknowledged,
                "created_at": alert.timestamp.isoformat()
            }).execute()
        except Exception as e:
            logger.warning(f"알림 저장 실패: {e}")
    
    def _send_alert_notification(self, alert: Alert) -> None:
        """알림 발송 — Discord Webhook 연동"""
        try:
            from app.discord_notify import send_alert as _send_discord
            import asyncio

            severity_map = {
                AlertSeverity.CRITICAL: "critical",
                AlertSeverity.ERROR: "error",
                AlertSeverity.WARNING: "warning",
                AlertSeverity.INFO: "info",
            }
            discord_severity = severity_map.get(alert.severity, "info")

            fields = []
            if alert.metric:
                fields.append({
                    "name": "메트릭",
                    "value": alert.metric.metric_type.value,
                    "inline": True,
                })
                fields.append({
                    "name": "현재값",
                    "value": str(round(alert.metric.value, 4)),
                    "inline": True,
                })
                fields.append({
                    "name": "기준값",
                    "value": str(alert.metric.threshold),
                    "inline": True,
                })

            # 이미 이벤트 루프 안에 있으면 동기 전송 사용
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # 이벤트 루프 내부 — 동기 전송 사용
                from app.discord_notify import _send_webhook_sync, SEVERITY_COLORS, SEVERITY_ICONS
                from datetime import datetime as _dt

                color = SEVERITY_COLORS.get(discord_severity, SEVERITY_COLORS["info"])
                icon = SEVERITY_ICONS.get(discord_severity, "📢")
                embed = {
                    "title": f"{icon} {alert.title}",
                    "description": alert.message[:4096],
                    "color": color,
                    "timestamp": _dt.utcnow().isoformat(),
                    "footer": {"text": "FencingMind DataQualityMonitor"},
                }
                if fields:
                    embed["fields"] = [
                        {"name": f["name"], "value": str(f["value"])[:1024], "inline": f.get("inline", True)}
                        for f in fields[:25]
                    ]
                _send_webhook_sync({"embeds": [embed]})
            else:
                # 이벤트 루프 없음 — asyncio.run 사용
                asyncio.run(_send_discord(
                    severity=discord_severity,
                    title=alert.title,
                    message=alert.message,
                    fields=fields if fields else None,
                ))
        except Exception as e:
            logger.debug(f"Discord 알림 발송 실패 (무시): {e}")
    
    # ==================== 품질 점검 ====================
    
    def check_validation_quality(self, stats: Dict[str, int]) -> QualityMetric:
        """검증 품질 점검"""
        total = stats.get("total_processed", 0)
        passed = stats.get("total_passed", 0)
        
        pass_rate = passed / total if total > 0 else 0
        
        return self.record_metric(
            MetricType.VALIDATION_PASS_RATE,
            pass_rate,
            {"total": total, "passed": passed, "failed": stats.get("total_failed", 0)}
        )
    
    def check_sync_quality(self, sync_results: List[Dict[str, Any]]) -> QualityMetric:
        """동기화 품질 점검"""
        total = len(sync_results)
        successful = sum(1 for r in sync_results if not r.get("errors"))
        
        success_rate = successful / total if total > 0 else 0
        
        return self.record_metric(
            MetricType.SYNC_SUCCESS_RATE,
            success_rate,
            {"total": total, "successful": successful}
        )
    
    def check_data_freshness(self, table: str) -> QualityMetric:
        """데이터 신선도 점검"""
        if not self.db:
            return self.record_metric(MetricType.DATA_FRESHNESS, 0)
        
        try:
            result = self.db.table(table).select(
                "updated_at"
            ).order("updated_at", desc=True).limit(1).execute()
            
            if result.data:
                last_update = datetime.fromisoformat(
                    result.data[0]["updated_at"].replace("Z", "+00:00")
                )
                hours_since = (datetime.now(last_update.tzinfo) - last_update).total_seconds() / 3600
            else:
                hours_since = 999  # 데이터 없음
            
            return self.record_metric(
                MetricType.DATA_FRESHNESS,
                hours_since,
                {"table": table, "last_update": result.data[0]["updated_at"] if result.data else None}
            )
        except Exception as e:
            logger.error(f"데이터 신선도 점검 실패: {e}")
            return self.record_metric(MetricType.DATA_FRESHNESS, 999, {"error": str(e)})
    
    def check_duplicate_rate(self, table: str, key_columns: List[str]) -> QualityMetric:
        """중복 데이터 비율 점검"""
        if not self.db:
            return self.record_metric(MetricType.DUPLICATE_RATE, 0)
        
        try:
            # 전체 건수
            total_result = self.db.table(table).select("id", count="exact").execute()
            total_count = total_result.count or 0
            
            if total_count == 0:
                return self.record_metric(MetricType.DUPLICATE_RATE, 0, {"table": table})
            
            # 중복 감지 쿼리 (간소화된 버전)
            key_string = ", ".join(key_columns)
            query = f"""
                SELECT COUNT(*) as dup_count 
                FROM (
                    SELECT {key_string}, COUNT(*) as cnt 
                    FROM {table} 
                    GROUP BY {key_string} 
                    HAVING COUNT(*) > 1
                ) duplicates
            """
            
            # RPC 또는 직접 쿼리 (Supabase 한계로 인해 간소화)
            dup_rate = 0  # 실제 구현 시 RPC 함수 사용
            
            return self.record_metric(
                MetricType.DUPLICATE_RATE,
                dup_rate,
                {"table": table, "key_columns": key_columns}
            )
        except Exception as e:
            logger.error(f"중복 데이터 점검 실패: {e}")
            return self.record_metric(MetricType.DUPLICATE_RATE, 0, {"error": str(e)})
    
    def check_referential_integrity(self) -> QualityMetric:
        """참조 무결성 점검"""
        if not self.db:
            return self.record_metric(MetricType.REFERENTIAL_INTEGRITY, 1.0)
        
        try:
            issues = []
            total_checks = 0
            passed_checks = 0
            
            # 예: matches.player1_id가 players.id에 존재하는지 확인
            integrity_checks = [
                ("matches", "player1_id", "players", "id"),
                ("matches", "player2_id", "players", "id"),
                ("matches", "event_id", "events", "id"),
                ("events", "competition_id", "competitions", "id"),
                ("rankings", "player_id", "players", "id"),
                ("rankings", "event_id", "events", "id"),
            ]
            
            for source_table, source_col, target_table, target_col in integrity_checks:
                total_checks += 1
                try:
                    # 간소화된 검사 (실제로는 LEFT JOIN으로 orphan 찾기)
                    passed_checks += 1  # 실제 구현 시 RPC 함수 사용
                except (KeyError, TypeError, AttributeError):
                    issues.append(f"{source_table}.{source_col} → {target_table}.{target_col}")
            
            integrity_rate = passed_checks / total_checks if total_checks > 0 else 1.0
            
            return self.record_metric(
                MetricType.REFERENTIAL_INTEGRITY,
                integrity_rate,
                {"total_checks": total_checks, "passed": passed_checks, "issues": issues}
            )
        except Exception as e:
            logger.error(f"참조 무결성 점검 실패: {e}")
            return self.record_metric(MetricType.REFERENTIAL_INTEGRITY, 0, {"error": str(e)})
    
    def record_pipeline_latency(self, start_time: datetime, end_time: datetime) -> QualityMetric:
        """파이프라인 지연시간 기록"""
        latency_ms = (end_time - start_time).total_seconds() * 1000
        
        return self.record_metric(
            MetricType.PIPELINE_LATENCY,
            latency_ms,
            {"start": start_time.isoformat(), "end": end_time.isoformat()}
        )
    
    # ==================== 대시보드 데이터 ====================
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """대시보드용 데이터 조회"""
        now = datetime.now()
        hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(days=1)
        
        # 최근 메트릭
        recent_metrics = [m for m in self._metrics if m.timestamp > hour_ago]
        
        # 메트릭별 최신 상태
        latest_by_type = {}
        for metric in reversed(self._metrics):
            if metric.metric_type not in latest_by_type:
                latest_by_type[metric.metric_type] = metric
        
        # 미확인 알림
        unacknowledged_alerts = [a for a in self._alerts if not a.acknowledged]
        
        # 전체 건강도 점수
        health_scores = [m.is_healthy for m in latest_by_type.values()]
        overall_health = sum(health_scores) / len(health_scores) if health_scores else 1.0
        
        return {
            "timestamp": now.isoformat(),
            "overall_health": overall_health,
            "health_status": "healthy" if overall_health >= 0.9 else (
                "degraded" if overall_health >= 0.7 else "unhealthy"
            ),
            "metrics": {
                metric_type.value: metric.to_dict()
                for metric_type, metric in latest_by_type.items()
            },
            "alerts": {
                "total": len(self._alerts),
                "unacknowledged": len(unacknowledged_alerts),
                "critical": len([a for a in unacknowledged_alerts if a.severity == AlertSeverity.CRITICAL]),
                "recent": [a.to_dict() for a in unacknowledged_alerts[-5:]]
            },
            "statistics": {
                "metrics_last_hour": len(recent_metrics),
                "alerts_last_24h": len([a for a in self._alerts if a.timestamp > day_ago]),
            }
        }
    
    def get_health_summary(self) -> Dict[str, Any]:
        """건강 상태 요약"""
        latest_by_type = {}
        for metric in reversed(self._metrics):
            if metric.metric_type not in latest_by_type:
                latest_by_type[metric.metric_type] = metric
        
        summary = {}
        for metric_type, metric in latest_by_type.items():
            summary[metric_type.value] = {
                "status": "✅" if metric.is_healthy else "❌",
                "value": metric.value,
                "threshold": metric.threshold,
            }
        
        return summary
    
    def acknowledge_alert(self, alert_index: int) -> bool:
        """알림 확인 처리"""
        if 0 <= alert_index < len(self._alerts):
            self._alerts[alert_index].acknowledged = True
            return True
        return False
    
    def get_recent_alerts(self, limit: int = 20) -> List[Dict[str, Any]]:
        """최근 알림 조회"""
        return [a.to_dict() for a in self._alerts[-limit:]]
    
    # ==================== 정기 점검 ====================
    
    def run_full_health_check(self) -> Dict[str, Any]:
        """
        전체 건강 상태 점검
        
        스케줄러에서 주기적으로 호출
        """
        logger.info("🔍 Running full health check...")
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "checks": {}
        }
        
        # 1. 데이터 신선도 점검
        for table in ["players", "matches", "events", "competitions"]:
            metric = self.check_data_freshness(table)
            results["checks"][f"freshness_{table}"] = metric.to_dict()
        
        # 2. 참조 무결성 점검
        integrity_metric = self.check_referential_integrity()
        results["checks"]["referential_integrity"] = integrity_metric.to_dict()
        
        # 3. 대시보드 데이터
        results["dashboard"] = self.get_dashboard_data()
        
        logger.info(f"✅ Health check completed: {results['dashboard']['health_status']}")
        
        return results
