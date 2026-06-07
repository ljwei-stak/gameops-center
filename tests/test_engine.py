import unittest

from gameops.engine import GameOpsEngine, NotFoundError, ValidationError


class GameOpsEngineTest(unittest.TestCase):
    def setUp(self):
        self.engine = GameOpsEngine(seed=7)

    def test_overview_returns_core_summary(self):
        overview = self.engine.overview()

        self.assertIn("summary", overview)
        self.assertGreater(overview["summary"]["online_players"], 0)
        self.assertEqual(overview["summary"]["total_servers"], 9)
        self.assertEqual(len(overview["regions"]), 4)

    def test_canary_deploy_updates_subset(self):
        deployment = self.engine.deploy(
            region="cn-east",
            version="v1.9.0",
            strategy="canary",
            operator="tester",
        )

        self.assertEqual(deployment["status"], "success")
        self.assertEqual(deployment["target_count"], 1)
        self.assertEqual(deployment["servers"], ["cn-east-arena-01"])
        updated = self.engine.list_servers(region="cn-east")
        self.assertEqual(updated[0]["version"], "v1.9.0")

    def test_invalid_version_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.engine.deploy("cn-east", "1.9.0", "rolling")

    def test_restart_server_restores_running_state(self):
        restarted = self.engine.restart_server("cn-north-arena-01", "tester")

        self.assertEqual(restarted["status"], "running")
        self.assertEqual(restarted["uptime_hours"], 0)
        self.assertLess(restarted["cpu"], 60)

    def test_shift_traffic_clamps_to_bounds(self):
        region = self.engine.shift_traffic("ap-sg", -50, "tester")
        self.assertEqual(region["traffic_weight"], 0)

        region = self.engine.shift_traffic("ap-sg", 150, "tester")
        self.assertEqual(region["traffic_weight"], 100)

    def test_unknown_region_raises_not_found(self):
        with self.assertRaises(NotFoundError):
            self.engine.list_servers(region="moon")


if __name__ == "__main__":
    unittest.main()

