"""Core operations logic for game server monitoring and release actions."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import random
import re
from threading import RLock
from typing import Any

from .data import INITIAL_LOGS, INITIAL_SERVERS, REGIONS


CN_TZ = timezone(timedelta(hours=8))
VERSION_PATTERN = re.compile(r"^v\d+\.\d+\.\d+$")


class GameOpsError(Exception):
    """Base exception for GameOps operations."""


class ValidationError(GameOpsError):
    """Raised when an operation request is invalid."""


class NotFoundError(GameOpsError):
    """Raised when a requested resource does not exist."""


class GameOpsEngine:
    """In-memory operations engine for the demo API."""

    def __init__(self, seed: int | None = None) -> None:
        self._lock = RLock()
        self._random = random.Random(seed)
        self.regions = deepcopy(REGIONS)
        self.servers = deepcopy(INITIAL_SERVERS)
        self.deployments: list[dict[str, Any]] = []
        self.logs: list[dict[str, Any]] = []
        self._deployment_seq = 2400
        self._event_seq = 0
        self._trend = {
            "players": [],
            "latency": [],
            "alerts": [],
        }
        for item in INITIAL_LOGS:
            self._append_log(
                item["level"],
                item["source"],
                item["message"],
                item.get("server_id"),
                item.get("region"),
            )
        self._record_trend()

    def overview(self) -> dict[str, Any]:
        with self._lock:
            self.simulate_tick()
            alerts = self.alerts()
            total_players = sum(server["players"] for server in self.servers)
            total_capacity = sum(server["capacity"] for server in self.servers)
            avg_latency = _avg(server["latency_p95"] for server in self.servers)
            healthy = sum(1 for server in self.servers if server["status"] == "running")
            self._record_trend(alert_count=len(alerts))
            return {
                "generated_at": self._now(),
                "summary": {
                    "online_players": total_players,
                    "capacity": total_capacity,
                    "capacity_rate": round(total_players / total_capacity, 3),
                    "healthy_servers": healthy,
                    "total_servers": len(self.servers),
                    "active_alerts": len(alerts),
                    "avg_latency_p95": round(avg_latency, 1),
                    "avg_cpu": round(_avg(server["cpu"] for server in self.servers), 1),
                    "avg_memory": round(_avg(server["memory"] for server in self.servers), 1),
                },
                "regions": self._region_summaries(alerts),
                "trend": deepcopy(self._trend),
                "latest_deployments": deepcopy(self.deployments[:4]),
            }

    def list_servers(
        self, region: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            servers = self.servers
            if region and region != "all":
                self._require_region(region)
                servers = [server for server in servers if server["region"] == region]
            if status and status != "all":
                servers = [server for server in servers if server["status"] == status]
            return [self._public_server(server) for server in servers]

    def alerts(self) -> list[dict[str, Any]]:
        with self._lock:
            alerts: list[dict[str, Any]] = []
            for server in self.servers:
                alerts.extend(self._server_alerts(server))
            severity_order = {"critical": 0, "warning": 1, "info": 2}
            return sorted(
                alerts,
                key=lambda item: (severity_order[item["severity"]], item["server_id"]),
            )

    def list_logs(self, level: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
        with self._lock:
            normalized = level.upper() if level else None
            logs = self.logs
            if normalized and normalized != "ALL":
                logs = [item for item in logs if item["level"] == normalized]
            return deepcopy(logs[:limit])

    def list_deployments(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self.deployments)

    def restart_server(self, server_id: str, operator: str = "ops-user") -> dict[str, Any]:
        with self._lock:
            server = self._require_server(server_id)
            server["status"] = "running"
            server["uptime_hours"] = 0
            server["cpu"] = round(self._random.uniform(34, 54), 1)
            server["memory"] = round(self._random.uniform(48, 66), 1)
            server["latency_p95"] = round(self._random.uniform(32, 68), 1)
            server["packet_loss"] = round(self._random.uniform(0.0, 0.4), 2)
            server["rps"] = max(60, int(server["rps"] * self._random.uniform(0.88, 1.06)))
            self._append_log(
                "INFO",
                "ops-console",
                f"{operator} 重启 {server['name']}，服务恢复到 running",
                server["id"],
                server["region"],
            )
            return self._public_server(server)

    def deploy(
        self,
        region: str,
        version: str,
        strategy: str,
        operator: str = "release-bot",
    ) -> dict[str, Any]:
        with self._lock:
            if not VERSION_PATTERN.match(version):
                raise ValidationError("版本号格式必须类似 v1.9.0")
            strategy = strategy.lower()
            if strategy not in {"canary", "rolling", "hotfix"}:
                raise ValidationError("发布策略只支持 canary、rolling、hotfix")

            targets = self._deployment_targets(region, strategy)
            if not targets:
                raise ValidationError("没有可发布的目标服务器")

            self._deployment_seq += 1
            deployment_id = f"DEP-{self._deployment_seq}"
            self._append_log(
                "INFO",
                "release-bot",
                f"{operator} 发起 {version} {strategy} 发布，目标 {len(targets)} 台",
                None,
                region,
            )

            changed_servers = []
            for server in targets:
                server["version"] = version
                server["status"] = "running"
                server["uptime_hours"] = 0
                server["cpu"] = round(min(96, server["cpu"] + self._random.uniform(2.0, 7.5)), 1)
                server["memory"] = round(min(96, server["memory"] + self._random.uniform(1.0, 4.5)), 1)
                server["latency_p95"] = round(max(24, server["latency_p95"] * self._random.uniform(0.86, 1.08)), 1)
                changed_servers.append(server["id"])

            deployment = {
                "id": deployment_id,
                "version": version,
                "region": region,
                "strategy": strategy,
                "status": "success",
                "operator": operator,
                "target_count": len(targets),
                "servers": changed_servers,
                "started_at": self._now(),
                "finished_at": self._now(),
            }
            self.deployments.insert(0, deployment)
            self._append_log(
                "INFO",
                "release-bot",
                f"{deployment_id} 发布完成，更新 {len(targets)} 台游戏服务",
                None,
                region,
            )
            return deepcopy(deployment)

    def shift_traffic(self, region: str, delta: int, operator: str = "ops-user") -> dict[str, Any]:
        with self._lock:
            target = self._require_region(region)
            old = target["traffic_weight"]
            target["traffic_weight"] = max(0, min(100, old + delta))
            self._append_log(
                "INFO",
                "traffic-router",
                f"{operator} 将 {target['name']} 流量权重从 {old}% 调整为 {target['traffic_weight']}%",
                None,
                region,
            )
            return deepcopy(target)

    def simulate_tick(self) -> None:
        for server in self.servers:
            if server["status"] == "maintenance":
                continue
            pressure = server["players"] / max(1, server["capacity"])
            player_delta = self._random.randint(-90, 120)
            if pressure > 0.9:
                player_delta -= self._random.randint(30, 110)
            server["players"] = max(0, min(server["capacity"], server["players"] + player_delta))
            server["cpu"] = _bounded(
                server["cpu"] + self._random.uniform(-2.4, 3.6) + (pressure - 0.72) * 3.5,
                8,
                97,
            )
            server["memory"] = _bounded(
                server["memory"] + self._random.uniform(-1.2, 2.1) + (pressure - 0.7) * 2,
                18,
                97,
            )
            server["latency_p95"] = round(
                _bounded(
                    server["latency_p95"] + self._random.uniform(-4.5, 6.0) + max(0, pressure - 0.82) * 20,
                    22,
                    240,
                ),
                1,
            )
            server["packet_loss"] = round(
                _bounded(server["packet_loss"] + self._random.uniform(-0.1, 0.18), 0, 5.5),
                2,
            )
            server["rps"] = max(20, int(server["rps"] + self._random.randint(-55, 75)))
            server["uptime_hours"] += 1
            if server["status"] == "degraded" and server["cpu"] < 78 and server["latency_p95"] < 120:
                server["status"] = "running"
            elif server["status"] == "running" and (server["cpu"] > 88 or server["latency_p95"] > 160):
                server["status"] = "degraded"

    def _deployment_targets(self, region: str, strategy: str) -> list[dict[str, Any]]:
        if region != "all":
            self._require_region(region)
            candidates = [server for server in self.servers if server["region"] == region]
        else:
            candidates = list(self.servers)
        candidates = [server for server in candidates if server["status"] != "maintenance"]
        if strategy == "canary":
            count = max(1, round(len(candidates) * 0.25))
            return candidates[:count]
        if strategy == "hotfix":
            degraded = [server for server in candidates if server["status"] == "degraded"]
            return degraded or candidates
        return candidates

    def _region_summaries(self, alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        summaries = []
        for region in self.regions:
            servers = [server for server in self.servers if server["region"] == region["id"]]
            region_alerts = [item for item in alerts if item["region"] == region["id"]]
            players = sum(server["players"] for server in servers)
            capacity = sum(server["capacity"] for server in servers)
            summaries.append(
                {
                    **deepcopy(region),
                    "players": players,
                    "capacity": capacity,
                    "capacity_rate": round(players / capacity, 3) if capacity else 0,
                    "server_count": len(servers),
                    "healthy_count": sum(1 for server in servers if server["status"] == "running"),
                    "alert_count": len(region_alerts),
                    "avg_latency_p95": round(_avg(server["latency_p95"] for server in servers), 1),
                }
            )
        return summaries

    def _server_alerts(self, server: dict[str, Any]) -> list[dict[str, Any]]:
        checks = [
            ("cpu", server["cpu"], 85, 75, "CPU 压力过高", "扩容游戏服或降低匹配入口权重"),
            ("memory", server["memory"], 90, 82, "内存水位过高", "检查房间对象泄漏并滚动重启"),
            ("latency_p95", server["latency_p95"], 180, 130, "P95 延迟过高", "排查跨区路由和战斗同步耗时"),
            ("packet_loss", server["packet_loss"], 3.0, 1.0, "丢包率异常", "检查边缘节点和 UDP 网关链路"),
        ]
        alerts = []
        for metric, value, critical, warning, title, runbook in checks:
            severity = None
            threshold = None
            if value >= critical:
                severity = "critical"
                threshold = critical
            elif value >= warning:
                severity = "warning"
                threshold = warning
            if severity:
                alerts.append(
                    {
                        "id": f"{server['id']}-{metric}",
                        "severity": severity,
                        "title": title,
                        "server_id": server["id"],
                        "server_name": server["name"],
                        "region": server["region"],
                        "metric": metric,
                        "value": round(value, 2),
                        "threshold": threshold,
                        "runbook": runbook,
                    }
                )
        capacity_rate = server["players"] / max(1, server["capacity"])
        if capacity_rate >= 0.92:
            alerts.append(
                {
                    "id": f"{server['id']}-capacity",
                    "severity": "critical" if capacity_rate >= 0.97 else "warning",
                    "title": "玩家容量接近上限",
                    "server_id": server["id"],
                    "server_name": server["name"],
                    "region": server["region"],
                    "metric": "capacity",
                    "value": round(capacity_rate * 100, 1),
                    "threshold": 92,
                    "runbook": "开启备用区服并调整玩家匹配权重",
                }
            )
        if server["status"] == "maintenance":
            alerts.append(
                {
                    "id": f"{server['id']}-maintenance",
                    "severity": "info",
                    "title": "服务器维护中",
                    "server_id": server["id"],
                    "server_name": server["name"],
                    "region": server["region"],
                    "metric": "status",
                    "value": "maintenance",
                    "threshold": "running",
                    "runbook": "确认维护窗口和发布单状态",
                }
            )
        return alerts

    def _require_server(self, server_id: str) -> dict[str, Any]:
        for server in self.servers:
            if server["id"] == server_id:
                return server
        raise NotFoundError(f"服务器不存在: {server_id}")

    def _require_region(self, region_id: str) -> dict[str, Any]:
        for region in self.regions:
            if region["id"] == region_id:
                return region
        raise NotFoundError(f"战区不存在: {region_id}")

    def _public_server(self, server: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(server)
        result["capacity_rate"] = round(result["players"] / max(1, result["capacity"]), 3)
        return result

    def _append_log(
        self,
        level: str,
        source: str,
        message: str,
        server_id: str | None = None,
        region: str | None = None,
    ) -> None:
        self._event_seq += 1
        self.logs.insert(
            0,
            {
                "id": f"EVT-{self._event_seq:05d}",
                "time": self._now(),
                "level": level,
                "source": source,
                "region": region,
                "server_id": server_id,
                "message": message,
            },
        )

    def _record_trend(self, alert_count: int | None = None) -> None:
        total_players = sum(server["players"] for server in self.servers)
        latency = round(_avg(server["latency_p95"] for server in self.servers), 1)
        if alert_count is None:
            alert_count = len(self.alerts())
        self._trend["players"].append(total_players)
        self._trend["latency"].append(latency)
        self._trend["alerts"].append(alert_count)
        for key in self._trend:
            self._trend[key] = self._trend[key][-24:]

    def _now(self) -> str:
        return datetime.now(CN_TZ).isoformat(timespec="seconds")


def _avg(values: Any) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def _bounded(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, value)), 1)

