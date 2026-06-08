import os
import unittest
import uuid

from gameops.store import GameOpsStore


@unittest.skipUnless(os.environ.get("GAMEOPS_TEST_MYSQL") == "1", "MySQL integration test disabled")
class MySQLStoreTest(unittest.TestCase):
    def setUp(self):
        self.database = f"gameops_test_{uuid.uuid4().hex[:12]}"
        self.databases_to_drop = [self.database]
        self._create_database(self.database)
        self.store = GameOpsStore(
            host=os.environ.get("GAMEOPS_MYSQL_HOST", "127.0.0.1"),
            port=int(os.environ.get("GAMEOPS_MYSQL_PORT", "3306")),
            user=os.environ.get("GAMEOPS_MYSQL_USER", "gameops"),
            password=os.environ.get("GAMEOPS_MYSQL_PASSWORD", "gameops-pass"),
            database=self.database,
        )

    def tearDown(self):
        try:
            import pymysql

            conn = pymysql.connect(
                host=os.environ.get("GAMEOPS_MYSQL_HOST", "127.0.0.1"),
                port=int(os.environ.get("GAMEOPS_MYSQL_PORT", "3306")),
                user=os.environ.get("GAMEOPS_MYSQL_ROOT_USER", "root"),
                password=os.environ.get("GAMEOPS_MYSQL_ROOT_PASSWORD", "root-pass"),
                charset="utf8mb4",
                autocommit=True,
            )
            with conn.cursor() as cursor:
                for database in getattr(self, "databases_to_drop", [self.database]):
                    cursor.execute(f"DROP DATABASE IF EXISTS `{database}`")
            conn.close()
        except Exception:
            pass

    def _create_database(self, database):
        import pymysql

        conn = pymysql.connect(
            host=os.environ.get("GAMEOPS_MYSQL_HOST", "127.0.0.1"),
            port=int(os.environ.get("GAMEOPS_MYSQL_PORT", "3306")),
            user=os.environ.get("GAMEOPS_MYSQL_ROOT_USER", "root"),
            password=os.environ.get("GAMEOPS_MYSQL_ROOT_PASSWORD", "root-pass"),
            charset="utf8mb4",
            autocommit=True,
        )
        user = os.environ.get("GAMEOPS_MYSQL_USER", "gameops")
        safe_user = user.replace("'", "''")
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cursor.execute(f"GRANT ALL PRIVILEGES ON `{database}`.* TO '{safe_user}'@'%'")
        conn.close()

    def test_seeded_mysql_store_supports_core_records(self):
        regions = self.store.list_regions()
        workloads = self.store.list_workloads()
        user = self.store.get_user("admin")

        self.assertEqual(len(regions), 4)
        self.assertEqual(len(workloads), 8)
        self.assertEqual(user["role"], "admin")

    def test_mysql_store_persists_deployments_and_alerts(self):
        deployment = {
            "id": "DEP-9999",
            "version": "v9.9.9",
            "image": "registry.example.com/game/arena:v9.9.9",
            "region": "cn-east",
            "strategy": "canary",
            "status": "success",
            "operator": "tester",
            "target_count": 1,
            "workloads": ["cn-east-arena"],
            "command_results": [{"ok": True, "command": ["kubectl"], "stdout": "ok", "stderr": "", "returncode": 0}],
            "started_at": "2026-06-08T12:00:00+08:00",
            "finished_at": "2026-06-08T12:00:01+08:00",
        }
        self.store.insert_deployment(deployment)
        self.store.replace_alerts(
            [
                {
                    "id": "test-alert",
                    "severity": "warning",
                    "title": "test alert",
                    "region": "cn-east",
                    "workload_id": "cn-east-arena",
                    "workload_name": "cn-east arena",
                    "metric": "cpu",
                    "value": 88.1,
                    "threshold": 75,
                    "runbook": "scale out",
                }
            ]
        )

        self.assertEqual(self.store.list_deployments()[0]["id"], "DEP-9999")
        self.assertEqual(self.store.list_alerts()[0]["id"], "test-alert")

    def test_mysql_store_persists_approvals_rollbacks_and_pool_metrics(self):
        approval = {
            "id": "APR-9999",
            "status": "pending",
            "region": "cn-east",
            "version": "v9.9.9",
            "strategy": "canary",
            "image": None,
            "requested_by": "release-owner",
            "requested_at": "2026-06-08T12:00:00+08:00",
            "change_window": "01:00-05:00",
            "reason": "test approval",
            "payload": {"version": "v9.9.9"},
        }
        self.store.insert_deployment_approval(approval)
        self.store.update_deployment_approval(
            "APR-9999",
            {
                "status": "approved",
                "approved_by": "admin",
                "approved_at": "2026-06-08T12:01:00+08:00",
            },
        )
        rollback = {
            "id": "RBK-9999",
            "deployment_id": "DEP-9999",
            "operator": "admin",
            "reason": "test rollback",
            "from_version": "v9.9.9",
            "to_version": "v9.9.8",
            "workloads": ["cn-east-arena"],
            "command_results": [{"ok": True, "command": ["kubectl"], "returncode": 0}],
            "created_at": "2026-06-08T12:02:00+08:00",
        }
        self.store.insert_rollback_record(rollback)

        self.assertEqual(self.store.get_deployment_approval("APR-9999")["status"], "approved")
        self.assertEqual(self.store.list_deployment_approvals(status="approved")[0]["id"], "APR-9999")
        self.assertEqual(self.store.list_rollbacks()[0]["id"], "RBK-9999")
        metrics = self.store.mysql_pool_metrics()
        self.assertGreaterEqual(metrics["connections_created_total"], 1)
        self.assertIn("pool_idle", metrics)

    def test_local_login_disabled_skips_demo_account_seed(self):
        database = f"gameops_test_{uuid.uuid4().hex[:12]}"
        self.databases_to_drop.append(database)
        self._create_database(database)
        previous = os.environ.get("GAMEOPS_LOCAL_LOGIN_ENABLED")
        os.environ["GAMEOPS_LOCAL_LOGIN_ENABLED"] = "false"
        try:
            store = GameOpsStore(
                host=os.environ.get("GAMEOPS_MYSQL_HOST", "127.0.0.1"),
                port=int(os.environ.get("GAMEOPS_MYSQL_PORT", "3306")),
                user=os.environ.get("GAMEOPS_MYSQL_USER", "gameops"),
                password=os.environ.get("GAMEOPS_MYSQL_PASSWORD", "gameops-pass"),
                database=database,
            )
        finally:
            if previous is None:
                os.environ.pop("GAMEOPS_LOCAL_LOGIN_ENABLED", None)
            else:
                os.environ["GAMEOPS_LOCAL_LOGIN_ENABLED"] = previous

        self.assertIsNone(store.get_user("admin"))
        user = store.upsert_sso_user("sre@example.com", "SRE", "admin")
        self.assertEqual(user["role"], "admin")


if __name__ == "__main__":
    unittest.main()
