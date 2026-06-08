import os
import unittest
import uuid

from gameops.store import GameOpsStore


@unittest.skipUnless(os.environ.get("GAMEOPS_TEST_MYSQL") == "1", "MySQL integration test disabled")
class MySQLStoreTest(unittest.TestCase):
    def setUp(self):
        self.database = f"gameops_test_{uuid.uuid4().hex[:12]}"
        self._create_database()
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
                cursor.execute(f"DROP DATABASE IF EXISTS `{self.database}`")
            conn.close()
        except Exception:
            pass

    def _create_database(self):
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
                f"CREATE DATABASE `{self.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cursor.execute(f"GRANT ALL PRIVILEGES ON `{self.database}`.* TO '{safe_user}'@'%'")
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


if __name__ == "__main__":
    unittest.main()
