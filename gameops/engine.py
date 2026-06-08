"""Core orchestration logic for GameOps Center."""

from __future__ import annotations

from datetime import datetime
import re
from threading import RLock
from typing import Any

from .adapters import CompositeAdapter
from .ai_ops import AIOpsAssistant
from .collectors import DockerMetricsCollector, HostMetricsCollector, KubernetesMetricsCollector
from .notifications import NotificationDispatcher
from .store import GameOpsStore, now_iso, verify_password


VERSION_PATTERN = re.compile(r"^v\d+\.\d+\.\d+$")


class GameOpsError(Exception):
    """Base exception for GameOps operations."""


class ValidationError(GameOpsError):
    """Raised when an operation request is invalid."""


class NotFoundError(GameOpsError):
    """Raised when a requested resource does not exist."""


class AuthenticationError(GameOpsError):
    """Raised when credentials or sessions are invalid."""


class AuthorizationError(GameOpsError):
    """Raised when a user does not have the required permission."""


ROLE_PERMISSIONS = {
    "admin": {"read", "deploy", "restart", "scale", "traffic", "notify", "ai", "users"},
    "release_manager": {"read", "deploy", "restart", "scale", "traffic", "ai"},
    "observer": {"read"},
}


class GameOpsEngine:
    """Operations engine backed by MySQL, real collectors, and runtime adapters."""

    def __init__(
        self,
        store: GameOpsStore | None = None,
        adapter: CompositeAdapter | None = None,
        host_collector: HostMetricsCollector | None = None,
        docker_collector: DockerMetricsCollector | None = None,
        kubernetes_collector: KubernetesMetricsCollector | None = None,
        notifications: NotificationDispatcher | None = None,
        ai_assistant: AIOpsAssistant | None = None,
        seed: int | None = None,
    ) -> None:
        del seed  # Kept for compatibility with the old tests.
        self._lock = RLock()
        self.store = store or GameOpsStore()
        self.adapter = adapter or CompositeAdapter()
        self.host_collector = host_collector or HostMetricsCollector()
        self.docker_collector = docker_collector or DockerMetricsCollector()
        self.kubernetes_collector = kubernetes_collector or KubernetesMetricsCollector()
        self.notifications = notifications or NotificationDispatcher()
        self.ai = ai_assistant or AIOpsAssistant()
        self._last_host_metrics: dict[str, Any] = {
            "cpu_percent": 0.0,
            "memory_percent": 0.0,
            "disk_percent": 0.0,
            "source": "host",
        }

    def login(self, username: str, password: str) -> dict[str, Any]:
        user = self.store.get_user(username)
        if not user or not verify_password(password, user["salt"], user["password_hash"]):
            raise AuthenticationError("用户名或密码错误")
        session = self.store.create_session(username)
        public_user = self._public_user(user)
        self.store.insert_log("INFO", "auth", f"{public_user['display_name']} 登录系统", actor=username)
        return {"token": session["token"], "expires_at": session["expires_at"], "user": public_user}

    def logout(self, token: str) -> None:
        self.store.delete_session(token)

    def session_user(self, token: str) -> dict[str, Any] | None:
        user = self.store.get_session_user(token)
        return self._public_user(user) if user else None

    def require(self, user: dict[str, Any] | None, permission: str) -> None:
        if not user:
            raise AuthenticationError("请先登录")
        allowed = ROLE_PERMISSIONS.get(user["role"], set())
        if permission not in allowed:
            raise AuthorizationError(f"{user['role']} 无权执行该操作")

    def users(self, actor: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.require(actor, "users")
        return self.store.list_users()

    def overview(self) -> dict[str, Any]:
        with self._lock:
            host = self.refresh_metrics()
            workloads = self.store.list_workloads()
            alerts = self._refresh_alerts(workloads, host)
            regions = self._region_summaries(workloads, alerts)
            summary = self._summary(workloads, alerts)
            self.store.record_metric_history(
                {
                    "online_players": summary["online_players"],
                    "avg_latency": summary["avg_latency_p95"],
                    "active_alerts": summary["active_alerts"],
                    "host_cpu": host["cpu_percent"],
                    "host_memory": host["memory_percent"],
                    "host_disk": host["disk_percent"],
                }
            )
            return {
                "generated_at": now_iso(),
                "runtime": self.adapter.name,
                "host": host,
                "summary": summary,
                "regions": regions,
                "trend": self.store.metric_history(),
                "latest_deployments": self.store.list_deployments(limit=4),
            }

    def refresh_metrics(self) -> dict[str, Any]:
        with self._lock:
            workloads = self.store.list_workloads()
            host = self.host_collector.collect()
            self._last_host_metrics = host

            metrics: dict[str, dict[str, Any]] = {}
            if self.adapter.name == "kubernetes":
                metrics.update(self.kubernetes_collector.collect(workloads))
            elif self.adapter.name == "docker":
                metrics.update(self.docker_collector.collect(workloads))
            else:
                metrics.update(self.kubernetes_collector.collect(workloads))
                metrics.update(self.docker_collector.collect(workloads))
            self.store.bulk_update_workload_metrics(metrics)
            return host

    def list_workloads(
        self, region: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            if region and region != "all":
                self._require_region(region)
            return self.store.list_workloads(region=region, status=status)

    def list_servers(
        self, region: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        return self.list_workloads(region=region, status=status)

    def cmdb(self) -> dict[str, Any]:
        workloads = self.store.list_workloads()
        return {
            "regions": self.store.list_regions(),
            "workloads": workloads,
            "relationships": [
                {
                    "region": workload["region"],
                    "deployment": workload["deployment"],
                    "service": workload["service"],
                    "namespace": workload["namespace"],
                    "workload_id": workload["id"],
                }
                for workload in workloads
            ],
        }

    def alerts(self) -> list[dict[str, Any]]:
        with self._lock:
            host = self._last_host_metrics or self.host_collector.collect()
            return self._refresh_alerts(self.store.list_workloads(), host)

    def list_logs(self, level: str | None = None, limit: int = 80) -> list[dict[str, Any]]:
        return self.store.list_logs(level=level, limit=limit)

    def list_deployments(self) -> list[dict[str, Any]]:
        return self.store.list_deployments()

    def restart_workload(self, workload_id: str, operator: str = "ops-user") -> dict[str, Any]:
        with self._lock:
            workload = self._require_workload(workload_id)
            results = self.adapter.restart_workload(workload)
            status = "running" if _commands_ok(results) else "degraded"
            updated = self.store.update_workload(
                workload_id,
                {
                    "status": status,
                    "metrics_source": self.adapter.name,
                },
            )
            message = self.ai.write_operation_log("重启工作负载", operator, workload_id, results)
            self.store.insert_log("INFO" if status == "running" else "WARN", self.adapter.name, message, workload["region"], workload_id, operator)
            self.notifications.notify_event(
                "GameOps 工作负载重启",
                message,
                {"workload": workload_id, "commands": results},
            )
            return {**updated, "command_results": results}

    def restart_server(self, server_id: str, operator: str = "ops-user") -> dict[str, Any]:
        return self.restart_workload(server_id, operator)

    def deploy(
        self,
        region: str,
        version: str,
        strategy: str,
        operator: str = "release-bot",
        image: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if not VERSION_PATTERN.match(version):
                raise ValidationError("版本号格式必须类似 v1.9.0")
            strategy = strategy.lower()
            if strategy not in {"canary", "rolling", "hotfix"}:
                raise ValidationError("发布策略只支持 canary、rolling、hotfix")
            targets = self._deployment_targets(region, strategy)
            if not targets:
                raise ValidationError("没有可发布的目标工作负载")

            deployment_id = self.store.next_deployment_id()
            started_at = now_iso()
            command_results = []
            target_ids = []
            for workload in targets:
                target_image = image or _image_with_version(workload["image"], version)
                results = self.adapter.deploy_image(workload, target_image)
                command_results.append(
                    {
                        "workload_id": workload["id"],
                        "image": target_image,
                        "commands": results,
                    }
                )
                target_ids.append(workload["id"])
                self.store.update_workload(
                    workload["id"],
                    {
                        "version": version,
                        "image": target_image,
                        "status": "running" if _commands_ok(results) else "degraded",
                        "metrics_source": self.adapter.name,
                    },
                )

            status = "success" if all(_commands_ok(item["commands"]) for item in command_results) else "failed"
            deployment = {
                "id": deployment_id,
                "version": version,
                "image": image or f"per-workload:{version}",
                "region": region,
                "strategy": strategy,
                "status": status,
                "operator": operator,
                "target_count": len(targets),
                "workloads": target_ids,
                "command_results": command_results,
                "started_at": started_at,
                "finished_at": now_iso(),
            }
            self.store.insert_deployment(deployment)
            message = self.ai.write_operation_log("镜像版本切换", operator, deployment_id, command_results)
            self.store.insert_log(
                "INFO" if status == "success" else "ERROR",
                self.adapter.name,
                message,
                region if region != "all" else None,
                None,
                operator,
            )
            self.notifications.notify_event(
                f"GameOps 发布 {deployment_id} {status}",
                message,
                deployment,
            )
            return deployment

    def scale_workload(self, workload_id: str, replicas: int, operator: str = "ops-user") -> dict[str, Any]:
        with self._lock:
            workload = self._require_workload(workload_id)
            if replicas < workload["min_replicas"] or replicas > workload["max_replicas"]:
                raise ValidationError(
                    f"副本数必须在 {workload['min_replicas']} 到 {workload['max_replicas']} 之间"
                )
            results = self.adapter.scale_workload(workload, replicas)
            updated = self.store.update_workload(
                workload_id,
                {
                    "replicas": replicas,
                    "desired_replicas": replicas,
                    "status": "running" if _commands_ok(results) else "degraded",
                    "metrics_source": self.adapter.name,
                },
            )
            message = self.ai.write_operation_log("扩缩容 Deployment", operator, workload_id, results)
            self.store.insert_log(
                "INFO" if _commands_ok(results) else "WARN",
                self.adapter.name,
                message,
                workload["region"],
                workload_id,
                operator,
            )
            self.notifications.notify_event(
                "GameOps 扩缩容",
                message,
                {"workload": workload_id, "replicas": replicas, "commands": results},
            )
            return {**updated, "command_results": results}

    def shift_traffic(self, region: str, delta: int, operator: str = "ops-user") -> dict[str, Any]:
        with self._lock:
            target = self._require_region(region)
            old = int(target["traffic_weight"])
            new_weight = max(0, min(100, old + delta))
            updated = self.store.update_region_traffic(region, new_weight)
            self.store.insert_log(
                "INFO",
                "traffic-router",
                f"{operator} 将 {target['name']} 流量权重从 {old}% 调整为 {new_weight}%",
                region,
                None,
                operator,
            )
            return updated or target

    def notify_alerts(self, operator: str = "ops-user") -> list[dict[str, Any]]:
        alerts = self.alerts()
        body = "\n".join(
            f"{item['severity']} {item['workload_name']} {item['title']} 当前值 {item['value']}"
            for item in alerts[:10]
        ) or "当前暂无活跃告警"
        results = self.notifications.notify_event("GameOps 告警汇总", body, {"alerts": alerts[:10]})
        self.store.insert_log("INFO", "notifier", f"{operator} 推送告警汇总，渠道 {len(results)} 个", actor=operator)
        return results

    def receive_alertmanager(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValidationError("Alertmanager payload must be a JSON object")
        alerts = payload.get("alerts", [])
        if alerts is None:
            alerts = []
        if not isinstance(alerts, list):
            raise ValidationError("Alertmanager alerts must be a list")

        with self._lock:
            summary = _summarize_alertmanager_payload(payload, alerts)
            notification_results = self.notifications.notify_event(
                summary["title"],
                summary["body"],
                {
                    "receiver": payload.get("receiver"),
                    "status": payload.get("status"),
                    "group_labels": payload.get("groupLabels", {}),
                    "common_labels": payload.get("commonLabels", {}),
                    "alerts": alerts[:20],
                },
            )
            self.store.insert_log(
                summary["level"],
                "alertmanager",
                summary["message"],
                summary["region"],
                summary["workload_id"],
                "alertmanager",
            )
            return {
                "status": "accepted",
                "received": summary["received"],
                "firing": summary["firing"],
                "resolved": summary["resolved"],
                "severities": summary["severities"],
                "notifications": notification_results,
            }

    def diagnose(self) -> dict[str, Any]:
        alerts = self.alerts()
        workloads = self.store.list_workloads()
        diagnosis = self.ai.diagnose(alerts, workloads)
        self.store.insert_log("INFO", "ai-ops", "AI 生成故障诊断和处置建议", actor="ai-ops")
        return diagnosis

    def report(self) -> dict[str, Any]:
        overview = self.overview()
        alerts = self.alerts()
        deployments = self.list_deployments()
        report = self.ai.write_report(overview, alerts, deployments)
        self.store.insert_log("INFO", "ai-ops", "AI 生成自动化运维数据报告", actor="ai-ops")
        return report

    def prometheus_metrics(self) -> str:
        with self._lock:
            overview = self.overview()
            workloads = self.store.list_workloads()
            alerts = self.store.list_alerts()
            deployments = self.store.list_deployments(limit=200)
            host = overview["host"]
            lines = [
                "# HELP gameops_host_cpu_percent Host CPU usage percent.",
                "# TYPE gameops_host_cpu_percent gauge",
                f"gameops_host_cpu_percent {host['cpu_percent']}",
                "# HELP gameops_host_memory_percent Host memory usage percent.",
                "# TYPE gameops_host_memory_percent gauge",
                f"gameops_host_memory_percent {host['memory_percent']}",
                "# HELP gameops_host_disk_percent Host disk usage percent.",
                "# TYPE gameops_host_disk_percent gauge",
                f"gameops_host_disk_percent {host['disk_percent']}",
                "# HELP gameops_workload_cpu_percent Workload CPU usage percent.",
                "# TYPE gameops_workload_cpu_percent gauge",
            ]
            for workload in workloads:
                labels = _labels(workload)
                lines.extend(
                    [
                        f"gameops_workload_cpu_percent{labels} {workload['cpu']}",
                        f"gameops_workload_memory_percent{labels} {workload['memory']}",
                        f"gameops_workload_latency_p95_ms{labels} {workload['latency_p95']}",
                        f"gameops_workload_packet_loss_percent{labels} {workload['packet_loss']}",
                        f"gameops_workload_rps{labels} {workload['rps']}",
                        f"gameops_workload_players{labels} {workload['players']}",
                        f"gameops_workload_capacity{labels} {workload['capacity']}",
                        f"gameops_workload_replicas{labels} {workload['replicas']}",
                        f"gameops_workload_desired_replicas{labels} {workload['desired_replicas']}",
                        f"gameops_workload_status{labels} {_status_value(workload['status'])}",
                    ]
                )
            counts = {"critical": 0, "warning": 0, "info": 0}
            for alert in alerts:
                counts[alert["severity"]] = counts.get(alert["severity"], 0) + 1
            lines.extend(
                [
                    "# HELP gameops_alerts_active Active alerts by severity.",
                    "# TYPE gameops_alerts_active gauge",
                    *[
                        f'gameops_alerts_active{{severity="{severity}"}} {count}'
                        for severity, count in counts.items()
                    ],
                    "# HELP gameops_deployments_total Deployment records.",
                    "# TYPE gameops_deployments_total counter",
                    f"gameops_deployments_total {len(deployments)}",
                    "",
                ]
            )
            return "\n".join(lines)

    def _deployment_targets(self, region: str, strategy: str) -> list[dict[str, Any]]:
        if region != "all":
            self._require_region(region)
            candidates = self.store.list_workloads(region=region)
        else:
            candidates = self.store.list_workloads()
        candidates = [item for item in candidates if item["status"] != "maintenance"]
        if strategy == "canary":
            count = max(1, round(len(candidates) * 0.25))
            return candidates[:count]
        if strategy == "hotfix":
            degraded = [item for item in candidates if item["status"] == "degraded"]
            return degraded or candidates
        return candidates

    def _region_summaries(
        self, workloads: list[dict[str, Any]], alerts: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        summaries = []
        for region in self.store.list_regions():
            region_workloads = [item for item in workloads if item["region"] == region["id"]]
            region_alerts = [item for item in alerts if item.get("region") == region["id"]]
            players = sum(item["players"] for item in region_workloads)
            capacity = sum(item["capacity"] for item in region_workloads)
            summaries.append(
                {
                    **region,
                    "players": players,
                    "capacity": capacity,
                    "capacity_rate": round(players / capacity, 3) if capacity else 0,
                    "workload_count": len(region_workloads),
                    "server_count": len(region_workloads),
                    "healthy_count": sum(1 for item in region_workloads if item["status"] == "running"),
                    "alert_count": len(region_alerts),
                    "avg_latency_p95": round(_avg(item["latency_p95"] for item in region_workloads), 1),
                }
            )
        return summaries

    def _summary(self, workloads: list[dict[str, Any]], alerts: list[dict[str, Any]]) -> dict[str, Any]:
        total_players = sum(item["players"] for item in workloads)
        total_capacity = sum(item["capacity"] for item in workloads)
        healthy = sum(1 for item in workloads if item["status"] == "running")
        return {
            "online_players": total_players,
            "capacity": total_capacity,
            "capacity_rate": round(total_players / total_capacity, 3) if total_capacity else 0,
            "healthy_workloads": healthy,
            "healthy_servers": healthy,
            "total_workloads": len(workloads),
            "total_servers": len(workloads),
            "active_alerts": len(alerts),
            "avg_latency_p95": round(_avg(item["latency_p95"] for item in workloads), 1),
            "avg_cpu": round(_avg(item["cpu"] for item in workloads), 1),
            "avg_memory": round(_avg(item["memory"] for item in workloads), 1),
        }

    def _refresh_alerts(
        self, workloads: list[dict[str, Any]], host: dict[str, Any]
    ) -> list[dict[str, Any]]:
        alerts = []
        for workload in workloads:
            alerts.extend(self._workload_alerts(workload))
        alerts.extend(_host_alerts(host))
        self.store.replace_alerts(alerts)
        return self.store.list_alerts()

    def _workload_alerts(self, workload: dict[str, Any]) -> list[dict[str, Any]]:
        checks = [
            ("cpu", workload["cpu"], 85, 75, "CPU 压力过高", "扩容 Deployment 或降低入口流量权重"),
            ("memory", workload["memory"], 90, 82, "内存水位过高", "检查房间对象泄漏并滚动重启"),
            ("latency_p95", workload["latency_p95"], 180, 130, "P95 延迟过高", "排查跨区链路和战斗同步耗时"),
            ("packet_loss", workload["packet_loss"], 3.0, 1.0, "丢包率异常", "检查边缘节点和 UDP 网关链路"),
        ]
        alerts = []
        for metric, value, critical, warning, title, runbook in checks:
            severity = ""
            threshold = 0
            if value >= critical:
                severity = "critical"
                threshold = critical
            elif value >= warning:
                severity = "warning"
                threshold = warning
            if severity:
                alerts.append(
                    _alert(
                        f"{workload['id']}-{metric}",
                        severity,
                        title,
                        workload,
                        metric,
                        round(value, 2),
                        threshold,
                        runbook,
                    )
                )
        capacity_rate = workload["players"] / max(1, workload["capacity"])
        if capacity_rate >= 0.92:
            alerts.append(
                _alert(
                    f"{workload['id']}-capacity",
                    "critical" if capacity_rate >= 0.97 else "warning",
                    "玩家容量接近上限",
                    workload,
                    "capacity",
                    round(capacity_rate * 100, 1),
                    92,
                    "扩容 Deployment 并调整匹配入口权重",
                )
            )
        if workload["status"] == "maintenance":
            alerts.append(
                _alert(
                    f"{workload['id']}-maintenance",
                    "info",
                    "工作负载维护中",
                    workload,
                    "status",
                    "maintenance",
                    "running",
                    "确认维护窗口和发布单状态",
                )
            )
        return alerts

    def _require_workload(self, workload_id: str) -> dict[str, Any]:
        workload = self.store.get_workload(workload_id)
        if not workload:
            raise NotFoundError(f"工作负载不存在: {workload_id}")
        return workload

    def _require_region(self, region_id: str) -> dict[str, Any]:
        region = self.store.get_region(region_id)
        if not region:
            raise NotFoundError(f"战区不存在: {region_id}")
        return region

    @staticmethod
    def _public_user(user: dict[str, Any]) -> dict[str, Any]:
        return {
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role"],
            "permissions": sorted(ROLE_PERMISSIONS.get(user["role"], set())),
        }


def _alert(
    alert_id: str,
    severity: str,
    title: str,
    workload: dict[str, Any],
    metric: str,
    value: Any,
    threshold: Any,
    runbook: str,
) -> dict[str, Any]:
    return {
        "id": alert_id,
        "severity": severity,
        "title": title,
        "region": workload["region"],
        "workload_id": workload["id"],
        "workload_name": workload["name"],
        "server_id": workload["id"],
        "server_name": workload["name"],
        "metric": metric,
        "value": value,
        "threshold": threshold,
        "runbook": runbook,
    }


def _host_alerts(host: dict[str, Any]) -> list[dict[str, Any]]:
    pseudo = {
        "id": "host",
        "name": "GameOps 宿主机",
        "region": "platform",
    }
    checks = [
        ("host_cpu", host["cpu_percent"], 90, 80, "宿主机 CPU 过高", "检查后台任务、容器资源限制和扩容计划"),
        ("host_memory", host["memory_percent"], 92, 85, "宿主机内存过高", "检查进程内存、缓存和 OOM 风险"),
        ("host_disk", host["disk_percent"], 90, 82, "宿主机磁盘使用率过高", "清理日志归档、镜像缓存和临时构建产物"),
    ]
    alerts = []
    for metric, value, critical, warning, title, runbook in checks:
        severity = ""
        threshold = 0
        if value >= critical:
            severity = "critical"
            threshold = critical
        elif value >= warning:
            severity = "warning"
            threshold = warning
        if severity:
            alerts.append(_alert(f"platform-{metric}", severity, title, pseudo, metric, value, threshold, runbook))
    return alerts


def _summarize_alertmanager_payload(payload: dict[str, Any], alerts: list[Any]) -> dict[str, Any]:
    received = len(alerts)
    firing = 0
    resolved = 0
    severities: dict[str, int] = {}
    regions = set()
    workload_ids = set()
    alert_names = []
    lines = []

    for item in alerts:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or payload.get("status") or "unknown")
        if status == "resolved":
            resolved += 1
        elif status == "firing":
            firing += 1
        labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
        annotations = item.get("annotations") if isinstance(item.get("annotations"), dict) else {}
        severity = str(labels.get("severity") or "unknown")
        severities[severity] = severities.get(severity, 0) + 1
        region = str(labels.get("region") or labels.get("namespace") or "")
        workload_id = str(labels.get("workload_id") or "")
        alert_name = str(labels.get("alertname") or annotations.get("summary") or "unknown")
        if region:
            regions.add(region)
        if workload_id:
            workload_ids.add(workload_id)
        if alert_name not in alert_names:
            alert_names.append(alert_name)
        if len(lines) < 8:
            description = annotations.get("description") or annotations.get("summary") or ""
            target = workload_id or region or labels.get("deployment") or "platform"
            lines.append(f"[{status}/{severity}] {alert_name} {target} {description}".strip())

    overall_status = str(payload.get("status") or ("firing" if firing else "resolved" if resolved else "unknown"))
    if firing and severities.get("critical", 0):
        level = "ERROR"
    elif firing:
        level = "WARN"
    else:
        level = "INFO"

    receiver = payload.get("receiver") or "default"
    region = next(iter(regions)) if len(regions) == 1 else None
    workload_id = next(iter(workload_ids)) if len(workload_ids) == 1 else None
    names = ", ".join(alert_names[:5]) or "no alert items"
    title = f"GameOps Alertmanager {overall_status}: {received} alerts"
    body = "\n".join(lines) or "Alertmanager webhook delivered without alert items."
    if len(alerts) > len(lines):
        body = f"{body}\n... and {len(alerts) - len(lines)} more alerts"
    message = (
        f"Alertmanager receiver={receiver} status={overall_status} "
        f"received={received} firing={firing} resolved={resolved} alerts={names}"
    )
    return {
        "title": title,
        "body": body,
        "message": message,
        "level": level,
        "received": received,
        "firing": firing,
        "resolved": resolved,
        "severities": severities,
        "region": region,
        "workload_id": workload_id,
    }


def _avg(values: Any) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def _commands_ok(results: list[dict[str, Any]]) -> bool:
    return bool(results) and all(item.get("ok") for item in results)


def _image_with_version(image: str, version: str) -> str:
    if ":" not in image.rsplit("/", 1)[-1]:
        return f"{image}:{version}"
    prefix = image.rsplit(":", 1)[0]
    return f"{prefix}:{version}"


def _labels(workload: dict[str, Any]) -> str:
    items = {
        "workload_id": workload["id"],
        "region": workload["region"],
        "namespace": workload["namespace"],
        "deployment": workload["deployment"],
        "service": workload["service"],
        "source": workload["metrics_source"],
    }
    joined = ",".join(f'{key}="{_escape_label(value)}"' for key, value in items.items())
    return "{" + joined + "}"


def _escape_label(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _status_value(status: str) -> int:
    return {"running": 1, "degraded": 0, "maintenance": -1}.get(status, 0)
