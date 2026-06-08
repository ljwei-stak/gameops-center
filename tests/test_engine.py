from copy import deepcopy
import base64
from datetime import datetime, timedelta
import json
import os
import unittest
from unittest.mock import patch

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
        self.approvals = []
        self.rollbacks = []
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

    def get_deployment(self, deployment_id):
        return deepcopy(next((item for item in self.deployments if item["id"] == deployment_id), None))

    def next_deployment_id(self):
        return f"DEP-{2401 + len(self.deployments)}"

    def insert_deployment_approval(self, approval):
        item = deepcopy(approval)
        item.setdefault("approved_by", None)
        item.setdefault("approved_at", None)
        item.setdefault("executed_at", None)
        item.setdefault("rejection_reason", None)
        item.setdefault("deployment_id", None)
        self.approvals.insert(0, item)
        return deepcopy(item)

    def update_deployment_approval(self, approval_id, changes):
        for index, item in enumerate(self.approvals):
            if item["id"] == approval_id:
                item.update(deepcopy(changes))
                self.approvals[index] = item
                return deepcopy(item)
        return None

    def get_deployment_approval(self, approval_id):
        return deepcopy(next((item for item in self.approvals if item["id"] == approval_id), None))

    def list_deployment_approvals(self, status=None, limit=80):
        rows = self.approvals
        if status and status != "all":
            rows = [item for item in rows if item["status"] == status]
        return deepcopy(rows[:limit])

    def next_approval_id(self):
        return f"APR-{2401 + len(self.approvals)}"

    def insert_rollback_record(self, rollback):
        self.rollbacks.insert(0, deepcopy(rollback))
        return deepcopy(rollback)

    def list_rollbacks(self, limit=50):
        return deepcopy(self.rollbacks[:limit])

    def next_rollback_id(self):
        return f"RBK-{2401 + len(self.rollbacks)}"

    def mysql_pool_metrics(self):
        return {
            "pool_size": 5,
            "pool_in_use": 0,
            "pool_idle": 1,
            "connections_created_total": 1,
            "pool_overflow_total": 0,
            "slow_queries_total": 0,
            "slow_query_seconds": 1.0,
            "managed": True,
        }

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

    def upsert_sso_user(self, username, display_name, role):
        user = self.users.get(username, {})
        user.update(
            {
                "username": username,
                "display_name": display_name,
                "role": role,
                "password_hash": user.get("password_hash", ""),
                "salt": user.get("salt", ""),
                "created_at": user.get("created_at", now_iso()),
            }
        )
        self.users[username] = user
        return deepcopy(user)

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
        approval = self.engine.deploy(
            region="cn-east",
            version="v1.9.0",
            strategy="canary",
            operator="tester",
        )
        self.assertEqual(approval["status"], "pending")
        self.assertEqual(approval["version"], "v1.9.0")

        approved = self.engine.approve_deployment(approval["id"], "admin")
        self.assertEqual(approved["status"], "approved")
        deployment = self.engine.execute_deployment(approval["id"], "tester")

        self.assertEqual(deployment["status"], "success")
        self.assertEqual(deployment["target_count"], 1)
        self.assertEqual(deployment["workloads"], ["cn-east-arena"])
        updated = self.engine.list_workloads(region="cn-east")
        self.assertEqual(updated[0]["version"], "v1.9.0")
        self.assertIn(":v1.9.0", updated[0]["image"])
        self.assertEqual(len(self.engine.list_deployments()), 1)
        self.assertEqual(self.engine.list_deployment_approvals()[0]["status"], "executed")

    def test_release_manager_cannot_approve_deployments(self):
        user = self.engine.login("release", "release123")["user"]
        self.assertIn("execute_deploy", user["permissions"])
        self.assertNotIn("approve_deploy", user["permissions"])
        with self.assertRaises(AuthorizationError):
            self.engine.require(user, "approve_deploy")

    def test_change_window_blocks_execution_outside_window(self):
        approval = self.engine.deploy(
            region="cn-east",
            version="v1.9.1",
            strategy="canary",
            operator="tester",
            change_window=_future_window(),
        )
        self.engine.approve_deployment(approval["id"], "admin")
        with self.assertRaises(ValidationError):
            self.engine.execute_deployment(approval["id"], "tester")

    def test_sso_login_maps_oidc_groups_to_role(self):
        previous_issuer = os.environ.get("GAMEOPS_OIDC_ISSUER")
        previous_audience = os.environ.get("GAMEOPS_OIDC_CLIENT_ID")
        previous_allow_unsigned = os.environ.get("GAMEOPS_OIDC_ALLOW_UNSIGNED_DEV_TOKENS")
        os.environ["GAMEOPS_OIDC_ISSUER"] = "https://sso.example.com"
        os.environ["GAMEOPS_OIDC_CLIENT_ID"] = "gameops-center"
        os.environ["GAMEOPS_OIDC_ALLOW_UNSIGNED_DEV_TOKENS"] = "true"
        try:
            token = _unsigned_jwt(
                {
                    "iss": "https://sso.example.com",
                    "aud": "gameops-center",
                    "preferred_username": "sre@example.com",
                    "name": "SRE Owner",
                    "groups": ["gameops-admins"],
                }
            )
            session = self.engine.sso_login(token)
        finally:
            _restore_env("GAMEOPS_OIDC_ISSUER", previous_issuer)
            _restore_env("GAMEOPS_OIDC_CLIENT_ID", previous_audience)
            _restore_env("GAMEOPS_OIDC_ALLOW_UNSIGNED_DEV_TOKENS", previous_allow_unsigned)

        self.assertEqual(session["user"]["username"], "sre@example.com")
        self.assertEqual(session["user"]["role"], "admin")
        with self.assertRaises(AuthenticationError):
            self.engine.login("sre@example.com", "anything")

    def test_rollback_records_restore_previous_image(self):
        first = self.engine.deploy("cn-east", "v1.9.0", "canary", operator="tester")
        self.engine.approve_deployment(first["id"], "admin")
        first_deployment = self.engine.execute_deployment(first["id"], "tester")

        second = self.engine.deploy("cn-east", "v1.9.1", "canary", operator="tester")
        self.engine.approve_deployment(second["id"], "admin")
        second_deployment = self.engine.execute_deployment(second["id"], "tester")

        rollback = self.engine.rollback_deployment(second_deployment["id"], "admin", "bad canary")
        updated = self.engine.list_workloads(region="cn-east")[0]

        self.assertEqual(rollback["from_version"], "v1.9.1")
        self.assertEqual(updated["version"], "v1.9.0")
        self.assertEqual(updated["image"], first_deployment["command_results"][0]["image"])
        self.assertEqual(self.engine.list_rollbacks()[0]["id"], rollback["id"])

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
        self.assertIn("gameops_mysql_pool_idle", metrics)
        self.assertIn("gameops_deployment_approvals_pending", metrics)
        self.assertIn("gameops_rollbacks_total", metrics)

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

    def test_ai_chat_sends_gateway_friendly_headers(self):
        previous_key = os.environ.get("GAMEOPS_LLM_API_KEY")
        previous_base = os.environ.get("GAMEOPS_LLM_API_BASE")
        previous_model = os.environ.get("GAMEOPS_LLM_MODEL")
        previous_user_agent = os.environ.get("GAMEOPS_LLM_USER_AGENT")
        os.environ["GAMEOPS_LLM_API_KEY"] = "test-key"
        os.environ["GAMEOPS_LLM_API_BASE"] = "https://llm.example/v1"
        os.environ["GAMEOPS_LLM_MODEL"] = "gpt-test"
        os.environ["GAMEOPS_LLM_USER_AGENT"] = "GameOps-Test/1.0"
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"choices":[{"message":{"content":"pong"}}]}'

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.headers)
            captured["timeout"] = timeout
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse()

        try:
            with patch("gameops.ai_ops.request.urlopen", fake_urlopen):
                result = AIOpsAssistant()._chat("system", {"task": "ping"})
        finally:
            _restore_env("GAMEOPS_LLM_API_KEY", previous_key)
            _restore_env("GAMEOPS_LLM_API_BASE", previous_base)
            _restore_env("GAMEOPS_LLM_MODEL", previous_model)
            _restore_env("GAMEOPS_LLM_USER_AGENT", previous_user_agent)

        self.assertEqual(result, "pong")
        self.assertEqual(captured["url"], "https://llm.example/v1/chat/completions")
        self.assertEqual(captured["headers"]["Accept"], "application/json")
        self.assertEqual(captured["headers"]["Content-type"], "application/json; charset=utf-8")
        self.assertEqual(captured["headers"]["User-agent"], "GameOps-Test/1.0")
        self.assertEqual(captured["body"]["model"], "gpt-test")
        self.assertEqual(captured["timeout"], 20)

    def test_password_hash_helpers_still_work_for_mysql_store(self):
        salt, password_hash = hash_password("secret")
        self.assertTrue(verify_password("secret", salt, password_hash))
        self.assertFalse(verify_password("wrong", salt, password_hash))


def _unsigned_jwt(claims):
    header = {"alg": "none", "typ": "JWT"}
    return ".".join(
        [
            _b64url(json.dumps(header).encode("utf-8")),
            _b64url(json.dumps(claims).encode("utf-8")),
            "",
        ]
    )


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _restore_env(name, value):
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def _future_window():
    start = datetime.now() + timedelta(hours=2)
    end = start + timedelta(minutes=1)
    return f"{start:%H:%M}-{end:%H:%M}"


if __name__ == "__main__":
    unittest.main()
