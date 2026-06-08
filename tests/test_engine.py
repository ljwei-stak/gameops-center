from copy import deepcopy
import json
import unittest

from gameops.adapters import CompositeAdapter
from gameops.ai_ops import AIOpsAssistant
from gameops.collectors import CommandRunner, HostMetricsCollector
from gameops.data import INITIAL_LOGS, REGIONS, USERS, WORKLOADS
from gameops.engine import AuthenticationError, AuthorizationError, GameOpsEngine, NotFoundError, ValidationError
from gameops.notifications import NotificationDispatcher
from gameops.store import hash_password, now_iso, verify_password


class SilentNotifier(NotificationDispatcher):
    def notify_event(self, title, body, payload=None):
        return [{"channel": "test", "ok": True}]


class StaticHostCollector(HostMetricsCollector):
    def collect(self):
        return {
            "cpu_percent": 12.5,
            "memory_percent": 34.0,
            "disk_percent": 45.0,
            "source": "test",
        }


class InMemoryStore:
    def __init__(self):
        self.regions = deepcopy(REGIONS)
        self.workloads = [
            self._public_workload(dict(item, updated_at=now_iso(), metrics_source="seed"))
            for item in deepcopy(WORKLOADS)
        ]
        self.users = {}
        for item in USERS:
            salt, password_hash = hash_password(item["password"])
            self.users[item["username"]] = {
                "username": item["username"],
                "display_name": item["display_name"],
                "role": item["role"],
                "password_hash": password_hash,
                "salt": salt,
                "created_at": now_iso(),
            }
        self.sessions = {}
        self.logs = []
        self.alert_rows = []
        self.deployments = []
        self.history = []
        for item in INITIAL_LOGS:
            self.insert_log(
                item["level"],
                item["source"],
                item["message"],
                item.get("region"),
                item.get("workload_id"),
                "system",
            )

    def list_regions(self):
        return deepcopy(sorted(self.regions, key=lambda item: item["id"]))

    def get_region(self, region_id):
        return deepcopy(next((item for item in self.regions if item["id"] == region_id), None))

    def update_region_traffic(self, region_id, traffic_weight):
        for item in self.regions:
            if item["id"] == region_id:
                item["traffic_weight"] = traffic_weight
                return deepcopy(item)
        return None

    def list_workloads(self, region=None, status=None):
        rows = self.workloads
        if region and region != "all":
            rows = [item for item in rows if item["region"] == region]
        if status and status != "all":
            rows = [item for item in rows if item["status"] == status]
        return deepcopy(sorted(rows, key=lambda item: (item["region"], item["id"])))

    def get_workload(self, workload_id):
        return deepcopy(next((item for item in self.workloads if item["id"] == workload_id), None))

    def update_workload(self, workload_id, changes):
        for index, item in enumerate(self.workloads):
            if item["id"] == workload_id:
                item.update(changes)
                item["updated_at"] = now_iso()
                self.workloads[index] = self._public_workload(item)
                return deepcopy(self.workloads[index])
        return None

    def bulk_update_workload_metrics(self, metrics):
        for workload_id, values in metrics.items():
            self.update_workload(workload_id, values)

    def insert_log(self, level, source, message, region=None, workload_id=None, actor=None):
        item = {
            "id": len(self.logs) + 1,
            "time": now_iso(),
            "level": level.upper(),
            "source": source,
            "region": region,
            "workload_id": workload_id,
            "actor": actor,
            "message": message,
        }
        self.logs.insert(0, item)
        return deepcopy(item)

    def list_logs(self, level=None, limit=80):
        rows = self.logs
        if level and level.upper() != "ALL":
            rows = [item for item in rows if item["level"] == level.upper()]
        return deepcopy(rows[:limit])

    def replace_alerts(self, alerts):
        self.alert_rows = [
            {
                **deepcopy(item),
                "active": True,
                "first_seen": now_iso(),
                "last_seen": now_iso(),
            }
            for item in alerts
        ]

    def list_alerts(self, active_only=True):
        rows = self.alert_rows if active_only else self.alert_rows
        return deepcopy(rows)

    def insert_deployment(self, deployment):
        self.deployments.insert(0, deepcopy(deployment))
        return deployment

    def list_deployments(self, limit=50):
        return deepcopy(self.deployments[:limit])

    def next_deployment_id(self):
        return f"DEP-{2401 + len(self.deployments)}"

    def record_metric_history(self, item):
        self.history.append({"id": len(self.history) + 1, **deepcopy(item)})
        self.history = self.history[-48:]

    def metric_history(self, limit=24):
        rows = self.history[-limit:]
        return {
            "players": [row["online_players"] for row in rows],
            "latency": [row["avg_latency"] for row in rows],
            "alerts": [row["active_alerts"] for row in rows],
            "host_cpu": [row["host_cpu"] for row in rows],
            "host_memory": [row["host_memory"] for row in rows],
            "host_disk": [row["host_disk"] for row in rows],
        }

    def get_user(self, username):
        return deepcopy(self.users.get(username))

    def list_users(self):
        rows = []
        for item in sorted(self.users.values(), key=lambda row: row["username"]):
            row = deepcopy(item)
            row.pop("password_hash", None)
            row.pop("salt", None)
            rows.append(row)
        return rows

    def create_session(self, username, ttl_hours=12):
        token = f"token-{username}-{len(self.sessions) + 1}"
        session = {"token": token, "username": username, "expires_at": now_iso()}
        self.sessions[token] = session
        return deepcopy(session)

    def get_session_user(self, token):
        session = self.sessions.get(token)
        if not session:
            return None
        user = self.users[session["username"]]
        return {
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role"],
            "expires_at": session["expires_at"],
        }

    def delete_session(self, token):
        self.sessions.pop(token, None)

    @staticmethod
    def _public_workload(row):
        row = dict(row)
        row["capacity"] = row["replicas"] * row["capacity_per_pod"]
        row["capacity_rate"] = round(row["players"] / max(1, row["capacity"]), 3)
        row["pod_count"] = row["replicas"]
        return row


class GameOpsEngineTest(unittest.TestCase):
    def setUp(self):
        store = InMemoryStore()
        adapter = CompositeAdapter(mode="kubernetes", runner=CommandRunner(dry_run=True))
        self.engine = GameOpsEngine(
            store=store,
            adapter=adapter,
            host_collector=StaticHostCollector(),
            notifications=SilentNotifier(),
            ai_assistant=AIOpsAssistant(),
        )

    def test_login_and_rbac_permissions(self):
        session = self.engine.login("admin", "admin123")

        self.assertEqual(session["user"]["role"], "admin")
        self.engine.require(session["user"], "deploy")

        viewer = self.engine.login("viewer", "viewer123")["user"]
        with self.assertRaises(AuthorizationError):
            self.engine.require(viewer, "deploy")

        with self.assertRaises(AuthenticationError):
            self.engine.login("admin", "bad")

    def test_overview_returns_core_summary_and_host_metrics(self):
        overview = self.engine.overview()

        self.assertIn("summary", overview)
        self.assertGreater(overview["summary"]["online_players"], 0)
        self.assertEqual(overview["summary"]["total_workloads"], 8)
        self.assertEqual(len(overview["regions"]), 4)
        self.assertEqual(overview["host"]["cpu_percent"], 12.5)

    def test_canary_deploy_switches_image_version_and_records_release(self):
        deployment = self.engine.deploy(
            region="cn-east",
            version="v1.9.0",
            strategy="canary",
            operator="tester",
        )

        self.assertEqual(deployment["status"], "success")
        self.assertEqual(deployment["target_count"], 1)
        self.assertEqual(deployment["workloads"], ["cn-east-arena"])
        updated = self.engine.list_workloads(region="cn-east")
        self.assertEqual(updated[0]["version"], "v1.9.0")
        self.assertIn(":v1.9.0", updated[0]["image"])
        self.assertEqual(len(self.engine.list_deployments()), 1)

    def test_invalid_version_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.engine.deploy("cn-east", "1.9.0", "rolling")

    def test_restart_workload_uses_runtime_adapter(self):
        restarted = self.engine.restart_workload("cn-north-arena", "tester")

        self.assertEqual(restarted["status"], "running")
        self.assertTrue(restarted["command_results"][0]["ok"])
        self.assertIn("kubectl", restarted["command_results"][0]["command"])

    def test_scale_workload_updates_desired_replicas(self):
        scaled = self.engine.scale_workload("cn-east-arena", 4, "tester")

        self.assertEqual(scaled["replicas"], 4)
        self.assertEqual(scaled["desired_replicas"], 4)

    def test_scale_workload_checks_bounds(self):
        with self.assertRaises(ValidationError):
            self.engine.scale_workload("cn-east-arena", 99, "tester")

    def test_shift_traffic_clamps_to_bounds(self):
        region = self.engine.shift_traffic("ap-sg", -50, "tester")
        self.assertEqual(region["traffic_weight"], 0)

        region = self.engine.shift_traffic("ap-sg", 150, "tester")
        self.assertEqual(region["traffic_weight"], 100)

    def test_unknown_region_raises_not_found(self):
        with self.assertRaises(NotFoundError):
            self.engine.list_workloads(region="moon")

    def test_prometheus_metrics_contains_real_endpoint_series(self):
        metrics = self.engine.prometheus_metrics()

        self.assertIn("gameops_host_cpu_percent 12.5", metrics)
        self.assertIn("gameops_workload_cpu_percent", metrics)
        self.assertIn("gameops_deployments_total", metrics)

    def test_alertmanager_webhook_is_logged_and_forwarded(self):
        result = self.engine.receive_alertmanager(
            {
                "receiver": "gameops-center",
                "status": "firing",
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {
                            "alertname": "GameOpsHighHostCPU",
                            "severity": "warning",
                            "region": "platform",
                        },
                        "annotations": {
                            "summary": "Host CPU high",
                            "description": "CPU has stayed above 80 percent.",
                        },
                    }
                ],
            }
        )

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["received"], 1)
        self.assertEqual(result["firing"], 1)
        self.assertTrue(result["notifications"][0]["ok"])
        latest_log = self.engine.list_logs(limit=1)[0]
        self.assertEqual(latest_log["source"], "alertmanager")
        self.assertIn("GameOpsHighHostCPU", latest_log["message"])

    def test_ai_report_has_summary(self):
        report = self.engine.report()

        self.assertIn("summary", report)
        self.assertIn("next_actions", report)

    def test_password_hash_helpers_still_work_for_mysql_store(self):
        salt, password_hash = hash_password("secret")
        self.assertTrue(verify_password("secret", salt, password_hash))
        self.assertFalse(verify_password("wrong", salt, password_hash))


if __name__ == "__main__":
    unittest.main()
