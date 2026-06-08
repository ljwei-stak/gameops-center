"""MySQL persistence layer for GameOps Center."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import secrets
from typing import Any, Iterable

from .data import INITIAL_LOGS, REGIONS, USERS, WORKLOADS


CN_TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


class GameOpsStore:
    """Repository backed by MySQL.

    Connection settings are read from environment variables:

    - GAMEOPS_MYSQL_HOST
    - GAMEOPS_MYSQL_PORT
    - GAMEOPS_MYSQL_USER
    - GAMEOPS_MYSQL_PASSWORD
    - GAMEOPS_MYSQL_DATABASE
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ) -> None:
        self.host = host or os.environ.get("GAMEOPS_MYSQL_HOST", "127.0.0.1")
        self.port = int(port or os.environ.get("GAMEOPS_MYSQL_PORT", "3306"))
        self.user = user or os.environ.get("GAMEOPS_MYSQL_USER", "gameops")
        self.password = password if password is not None else os.environ.get("GAMEOPS_MYSQL_PASSWORD", "gameops-pass")
        self.database = database or os.environ.get("GAMEOPS_MYSQL_DATABASE", "gameops")
        self.ensure_database()
        self.init_schema()
        self.seed()

    @contextmanager
    def connect(self) -> Iterable[Any]:
        pymysql = _pymysql()
        conn = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset="utf8mb4",
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
        )
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def ensure_database(self) -> None:
        pymysql = _pymysql()
        try:
            conn = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                charset="utf8mb4",
                autocommit=True,
            )
            conn.close()
            return
        except Exception:
            pass

        conn = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            charset="utf8mb4",
            autocommit=True,
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{_identifier(self.database)}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
        finally:
            conn.close()

    def init_schema(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS regions (
                id VARCHAR(64) PRIMARY KEY,
                name VARCHAR(128) NOT NULL,
                city VARCHAR(128) NOT NULL,
                owner VARCHAR(128) NOT NULL,
                traffic_weight INT NOT NULL DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS workloads (
                id VARCHAR(128) PRIMARY KEY,
                name VARCHAR(128) NOT NULL,
                region VARCHAR(64) NOT NULL,
                game_mode VARCHAR(128) NOT NULL,
                namespace VARCHAR(128) NOT NULL,
                deployment VARCHAR(128) NOT NULL,
                service VARCHAR(128) NOT NULL,
                container VARCHAR(128) NOT NULL,
                image VARCHAR(512) NOT NULL,
                version VARCHAR(64) NOT NULL,
                replicas INT NOT NULL,
                desired_replicas INT NOT NULL,
                min_replicas INT NOT NULL,
                max_replicas INT NOT NULL,
                players INT NOT NULL,
                capacity_per_pod INT NOT NULL,
                cpu DOUBLE NOT NULL,
                memory DOUBLE NOT NULL,
                latency_p95 DOUBLE NOT NULL,
                packet_loss DOUBLE NOT NULL,
                rps INT NOT NULL,
                status VARCHAR(32) NOT NULL,
                metrics_source VARCHAR(64) NOT NULL DEFAULT 'seed',
                updated_at VARCHAR(40) NOT NULL,
                CONSTRAINT fk_workloads_region FOREIGN KEY (region) REFERENCES regions(id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS logs (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                time VARCHAR(40) NOT NULL,
                level VARCHAR(16) NOT NULL,
                source VARCHAR(128) NOT NULL,
                region VARCHAR(64),
                workload_id VARCHAR(128),
                actor VARCHAR(128),
                message TEXT NOT NULL,
                INDEX idx_logs_level_id (level, id),
                INDEX idx_logs_time (time)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id VARCHAR(191) PRIMARY KEY,
                active TINYINT(1) NOT NULL DEFAULT 1,
                severity VARCHAR(16) NOT NULL,
                title VARCHAR(191) NOT NULL,
                region VARCHAR(64),
                workload_id VARCHAR(128),
                workload_name VARCHAR(128),
                metric VARCHAR(64) NOT NULL,
                value_text VARCHAR(128) NOT NULL,
                threshold_text VARCHAR(128) NOT NULL,
                runbook TEXT NOT NULL,
                first_seen VARCHAR(40) NOT NULL,
                last_seen VARCHAR(40) NOT NULL,
                INDEX idx_alerts_active_severity (active, severity)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS deployments (
                id VARCHAR(64) PRIMARY KEY,
                version VARCHAR(64) NOT NULL,
                image VARCHAR(512) NOT NULL,
                region VARCHAR(64) NOT NULL,
                strategy VARCHAR(32) NOT NULL,
                status VARCHAR(32) NOT NULL,
                operator VARCHAR(128) NOT NULL,
                target_count INT NOT NULL,
                workloads_json JSON NOT NULL,
                command_results_json JSON NOT NULL,
                started_at VARCHAR(40) NOT NULL,
                finished_at VARCHAR(40) NOT NULL,
                INDEX idx_deployments_started_at (started_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS metric_history (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                time VARCHAR(40) NOT NULL,
                online_players INT NOT NULL,
                avg_latency DOUBLE NOT NULL,
                active_alerts INT NOT NULL,
                host_cpu DOUBLE NOT NULL,
                host_memory DOUBLE NOT NULL,
                host_disk DOUBLE NOT NULL,
                INDEX idx_metric_history_id (id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS users (
                username VARCHAR(128) PRIMARY KEY,
                display_name VARCHAR(128) NOT NULL,
                role VARCHAR(64) NOT NULL,
                password_hash VARCHAR(128) NOT NULL,
                salt VARCHAR(64) NOT NULL,
                created_at VARCHAR(40) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token VARCHAR(191) PRIMARY KEY,
                username VARCHAR(128) NOT NULL,
                expires_at VARCHAR(40) NOT NULL,
                created_at VARCHAR(40) NOT NULL,
                CONSTRAINT fk_sessions_user FOREIGN KEY (username) REFERENCES users(username),
                INDEX idx_sessions_expires_at (expires_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """,
        ]
        with self.connect() as conn:
            with conn.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)

    def seed(self) -> None:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS count FROM regions")
                if cursor.fetchone()["count"] == 0:
                    cursor.executemany(
                        """
                        INSERT INTO regions (id, name, city, owner, traffic_weight)
                        VALUES (%(id)s, %(name)s, %(city)s, %(owner)s, %(traffic_weight)s)
                        """,
                        REGIONS,
                    )

                cursor.execute("SELECT COUNT(*) AS count FROM workloads")
                if cursor.fetchone()["count"] == 0:
                    rows = [dict(item, updated_at=now_iso(), metrics_source="seed") for item in WORKLOADS]
                    cursor.executemany(
                        """
                        INSERT INTO workloads (
                            id, name, region, game_mode, namespace, deployment, service,
                            container, image, version, replicas, desired_replicas,
                            min_replicas, max_replicas, players, capacity_per_pod, cpu,
                            memory, latency_p95, packet_loss, rps, status, metrics_source,
                            updated_at
                        )
                        VALUES (
                            %(id)s, %(name)s, %(region)s, %(game_mode)s, %(namespace)s,
                            %(deployment)s, %(service)s, %(container)s, %(image)s,
                            %(version)s, %(replicas)s, %(desired_replicas)s,
                            %(min_replicas)s, %(max_replicas)s, %(players)s,
                            %(capacity_per_pod)s, %(cpu)s, %(memory)s, %(latency_p95)s,
                            %(packet_loss)s, %(rps)s, %(status)s, %(metrics_source)s,
                            %(updated_at)s
                        )
                        """,
                        rows,
                    )

                cursor.execute("SELECT COUNT(*) AS count FROM users")
                if cursor.fetchone()["count"] == 0:
                    for user in USERS:
                        salt, password_hash = hash_password(user["password"])
                        cursor.execute(
                            """
                            INSERT INTO users (
                                username, display_name, role, password_hash, salt, created_at
                            )
                            VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                            (
                                user["username"],
                                user["display_name"],
                                user["role"],
                                password_hash,
                                salt,
                                now_iso(),
                            ),
                        )

                cursor.execute("SELECT COUNT(*) AS count FROM logs")
                if cursor.fetchone()["count"] == 0:
                    for item in INITIAL_LOGS:
                        cursor.execute(
                            """
                            INSERT INTO logs (
                                time, level, source, region, workload_id, actor, message
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                now_iso(),
                                item["level"],
                                item["source"],
                                item.get("region"),
                                item.get("workload_id"),
                                "system",
                                item["message"],
                            ),
                        )

    def list_regions(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM regions ORDER BY id")
                return list(cursor.fetchall())

    def get_region(self, region_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM regions WHERE id = %s", (region_id,))
                return cursor.fetchone()

    def update_region_traffic(self, region_id: str, traffic_weight: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE regions SET traffic_weight = %s WHERE id = %s",
                    (traffic_weight, region_id),
                )
                cursor.execute("SELECT * FROM regions WHERE id = %s", (region_id,))
                return cursor.fetchone()

    def list_workloads(
        self, region: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM workloads WHERE 1 = 1"
        params: list[Any] = []
        if region and region != "all":
            sql += " AND region = %s"
            params.append(region)
        if status and status != "all":
            sql += " AND status = %s"
            params.append(status)
        sql += " ORDER BY region, id"
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return [_public_workload(row) for row in cursor.fetchall()]

    def get_workload(self, workload_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM workloads WHERE id = %s", (workload_id,))
                row = cursor.fetchone()
                return _public_workload(row) if row else None

    def update_workload(self, workload_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        if not changes:
            return self.get_workload(workload_id)
        changes = dict(changes)
        changes["updated_at"] = now_iso()
        assignments = ", ".join(f"`{_identifier(key)}` = %s" for key in changes)
        params = list(changes.values()) + [workload_id]
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"UPDATE workloads SET {assignments} WHERE id = %s", params)
                cursor.execute("SELECT * FROM workloads WHERE id = %s", (workload_id,))
                row = cursor.fetchone()
                return _public_workload(row) if row else None

    def bulk_update_workload_metrics(self, metrics: dict[str, dict[str, Any]]) -> None:
        if not metrics:
            return
        allowed = {
            "cpu",
            "memory",
            "latency_p95",
            "packet_loss",
            "rps",
            "replicas",
            "status",
            "metrics_source",
        }
        with self.connect() as conn:
            with conn.cursor() as cursor:
                for workload_id, values in metrics.items():
                    changes = {key: values[key] for key in values if key in allowed}
                    if not changes:
                        continue
                    changes["updated_at"] = now_iso()
                    assignments = ", ".join(f"`{_identifier(key)}` = %s" for key in changes)
                    cursor.execute(
                        f"UPDATE workloads SET {assignments} WHERE id = %s",
                        [*changes.values(), workload_id],
                    )

    def insert_log(
        self,
        level: str,
        source: str,
        message: str,
        region: str | None = None,
        workload_id: str | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO logs (time, level, source, region, workload_id, actor, message)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (now_iso(), level.upper(), source, region, workload_id, actor, message),
                )
                cursor.execute("SELECT * FROM logs WHERE id = %s", (cursor.lastrowid,))
                return cursor.fetchone()

    def list_logs(self, level: str | None = None, limit: int = 80) -> list[dict[str, Any]]:
        sql = "SELECT * FROM logs"
        params: list[Any] = []
        if level and level.upper() != "ALL":
            sql += " WHERE level = %s"
            params.append(level.upper())
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(max(1, min(limit, 500)))
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())

    def replace_alerts(self, alerts: list[dict[str, Any]]) -> None:
        timestamp = now_iso()
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE alerts SET active = 0 WHERE active = 1")
                for item in alerts:
                    cursor.execute("SELECT first_seen FROM alerts WHERE id = %s", (item["id"],))
                    existing = cursor.fetchone()
                    first_seen = existing["first_seen"] if existing else timestamp
                    cursor.execute(
                        """
                        INSERT INTO alerts (
                            id, active, severity, title, region, workload_id, workload_name,
                            metric, value_text, threshold_text, runbook, first_seen, last_seen
                        )
                        VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            active = VALUES(active),
                            severity = VALUES(severity),
                            title = VALUES(title),
                            region = VALUES(region),
                            workload_id = VALUES(workload_id),
                            workload_name = VALUES(workload_name),
                            metric = VALUES(metric),
                            value_text = VALUES(value_text),
                            threshold_text = VALUES(threshold_text),
                            runbook = VALUES(runbook),
                            last_seen = VALUES(last_seen)
                        """,
                        (
                            item["id"],
                            item["severity"],
                            item["title"],
                            item.get("region"),
                            item.get("workload_id"),
                            item.get("workload_name"),
                            item["metric"],
                            str(item["value"]),
                            str(item["threshold"]),
                            item["runbook"],
                            first_seen,
                            timestamp,
                        ),
                    )

    def list_alerts(self, active_only: bool = True) -> list[dict[str, Any]]:
        sql = """
            SELECT
              id, active, severity, title, region, workload_id, workload_name,
              metric, value_text AS value, threshold_text AS threshold,
              runbook, first_seen, last_seen
            FROM alerts
        """
        if active_only:
            sql += " WHERE active = 1"
        sql += """
            ORDER BY
              CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
              workload_id
        """
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                rows = list(cursor.fetchall())
        for row in rows:
            row["active"] = bool(row["active"])
            row["value"] = _decode_metric_value(row["value"])
            row["threshold"] = _decode_metric_value(row["threshold"])
        return rows

    def insert_deployment(self, deployment: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO deployments (
                        id, version, image, region, strategy, status, operator,
                        target_count, workloads_json, command_results_json,
                        started_at, finished_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        deployment["id"],
                        deployment["version"],
                        deployment["image"],
                        deployment["region"],
                        deployment["strategy"],
                        deployment["status"],
                        deployment["operator"],
                        deployment["target_count"],
                        json.dumps(deployment["workloads"], ensure_ascii=False),
                        json.dumps(deployment["command_results"], ensure_ascii=False),
                        deployment["started_at"],
                        deployment["finished_at"],
                    ),
                )
        return deployment

    def list_deployments(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM deployments ORDER BY started_at DESC LIMIT %s",
                    (max(1, min(limit, 200)),),
                )
                rows = list(cursor.fetchall())
        for row in rows:
            row["workloads"] = json.loads(row.pop("workloads_json"))
            row["command_results"] = json.loads(row.pop("command_results_json"))
        return rows

    def next_deployment_id(self) -> str:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS count FROM deployments")
                count = cursor.fetchone()["count"]
        return f"DEP-{2401 + count}"

    def record_metric_history(self, item: dict[str, Any]) -> None:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO metric_history (
                        time, online_players, avg_latency, active_alerts,
                        host_cpu, host_memory, host_disk
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        now_iso(),
                        item["online_players"],
                        item["avg_latency"],
                        item["active_alerts"],
                        item["host_cpu"],
                        item["host_memory"],
                        item["host_disk"],
                    ),
                )
                cursor.execute(
                    """
                    DELETE FROM metric_history
                    WHERE id NOT IN (
                        SELECT id FROM (
                            SELECT id FROM metric_history ORDER BY id DESC LIMIT 48
                        ) AS keep_rows
                    )
                    """
                )

    def metric_history(self, limit: int = 24) -> dict[str, list[Any]]:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM metric_history
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (max(1, min(limit, 48)),),
                )
                rows = list(cursor.fetchall())
        rows.reverse()
        return {
            "players": [row["online_players"] for row in rows],
            "latency": [row["avg_latency"] for row in rows],
            "alerts": [row["active_alerts"] for row in rows],
            "host_cpu": [row["host_cpu"] for row in rows],
            "host_memory": [row["host_memory"] for row in rows],
            "host_disk": [row["host_disk"] for row in rows],
        }

    def get_user(self, username: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
                return cursor.fetchone()

    def list_users(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM users ORDER BY username")
                rows = list(cursor.fetchall())
        for row in rows:
            row.pop("password_hash", None)
            row.pop("salt", None)
        return rows

    def create_session(self, username: str, ttl_hours: int = 12) -> dict[str, Any]:
        token = secrets.token_urlsafe(32)
        created_at = now_iso()
        expires_at = (datetime.now(CN_TZ) + timedelta(hours=ttl_hours)).isoformat(timespec="seconds")
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO sessions (token, username, expires_at, created_at) VALUES (%s, %s, %s, %s)",
                    (token, username, expires_at, created_at),
                )
        return {"token": token, "username": username, "expires_at": expires_at}

    def get_session_user(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT u.username, u.display_name, u.role, s.expires_at
                    FROM sessions s
                    JOIN users u ON u.username = s.username
                    WHERE s.token = %s
                    """,
                    (token,),
                )
                user = cursor.fetchone()
        if not user:
            return None
        if datetime.fromisoformat(user["expires_at"]) < datetime.now(CN_TZ):
            self.delete_session(token)
            return None
        return user

    def delete_session(self, token: str) -> None:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM sessions WHERE token = %s", (token,))


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return salt, digest.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    _, actual_hash = hash_password(password, salt)
    return secrets.compare_digest(actual_hash, expected_hash)


def _public_workload(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    capacity = row["replicas"] * row["capacity_per_pod"]
    row["capacity"] = capacity
    row["capacity_rate"] = round(row["players"] / max(1, capacity), 3)
    row["pod_count"] = row["replicas"]
    return row


def _decode_metric_value(value: str) -> str | int | float:
    try:
        if "." in value:
            return float(value)
        return int(value)
    except (TypeError, ValueError):
        return value


def _identifier(value: str) -> str:
    if not value.replace("_", "").isalnum():
        raise ValueError(f"Unsafe MySQL identifier: {value}")
    return value


def _pymysql() -> Any:
    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError("MySQL support requires PyMySQL. Run: pip install -r requirements.txt") from exc
    return pymysql
