"""HTTP entrypoint for GameOps Center."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlparse

from gameops.engine import (
    AuthenticationError,
    AuthorizationError,
    GameOpsEngine,
    GameOpsError,
    NotFoundError,
    ValidationError,
)


PROJECT_ROOT = Path(__file__).parent
WEB_ROOT = PROJECT_ROOT / "web"
ENGINE = GameOpsEngine()


class GameOpsHandler(BaseHTTPRequestHandler):
    """Small API and static-file handler."""

    server_version = "GameOpsCenter/2.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path == "/metrics":
                self._text(ENGINE.prometheus_metrics(), "text/plain; version=0.0.4; charset=utf-8")
            elif path == "/api/health":
                self._json({"status": "ok", "service": "gameops-center", "runtime": ENGINE.adapter.name})
            elif path == "/api/me":
                user = self._current_user(required=False)
                self._json({"authenticated": bool(user), "user": user})
            elif path == "/api/overview":
                self._require("read")
                self._json(ENGINE.overview())
            elif path == "/api/cmdb":
                self._require("read")
                self._json(ENGINE.cmdb())
            elif path in {"/api/workloads", "/api/servers"}:
                self._require("read")
                self._json(
                    ENGINE.list_workloads(
                        region=_query_first(query, "region"),
                        status=_query_first(query, "status"),
                    )
                )
            elif path == "/api/alerts":
                self._require("read")
                self._json(ENGINE.alerts())
            elif path == "/api/logs":
                self._require("read")
                limit = int(_query_first(query, "limit", "80"))
                self._json(ENGINE.list_logs(level=_query_first(query, "level"), limit=limit))
            elif path == "/api/deployments":
                self._require("read")
                self._json(ENGINE.list_deployments())
            elif path == "/api/ai/diagnosis":
                self._require("ai")
                self._json(ENGINE.diagnose())
            elif path == "/api/ai/report":
                self._require("ai")
                self._json(ENGINE.report())
            elif path == "/api/users":
                self._json(ENGINE.users(self._require("users")))
            else:
                self._static(path)
        except AuthenticationError as exc:
            self._json({"error": str(exc)}, HTTPStatus.UNAUTHORIZED)
        except AuthorizationError as exc:
            self._json({"error": str(exc)}, HTTPStatus.FORBIDDEN)
        except NotFoundError as exc:
            self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        except ValidationError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except (ValueError, GameOpsError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            payload = self._read_json()
            if path == "/api/login":
                self._json(ENGINE.login(payload.get("username", ""), payload.get("password", "")))
                return

            if path == "/api/logout":
                token = self._bearer_token()
                if token:
                    ENGINE.logout(token)
                self._json({"status": "ok"})
                return

            if path == "/api/deploy":
                user = self._require("deploy")
                result = ENGINE.deploy(
                    region=payload.get("region", "all"),
                    version=payload.get("version", ""),
                    strategy=payload.get("strategy", "canary"),
                    operator=payload.get("operator") or user["username"],
                    image=payload.get("image") or None,
                )
                self._json(result, HTTPStatus.CREATED)
                return

            restart_match = re.match(r"^/api/(?:servers|workloads)/([^/]+)/restart$", path)
            if restart_match:
                user = self._require("restart")
                workload_id = restart_match.group(1)
                result = ENGINE.restart_workload(workload_id, payload.get("operator") or user["username"])
                self._json(result)
                return

            scale_match = re.match(r"^/api/workloads/([^/]+)/scale$", path)
            if scale_match:
                user = self._require("scale")
                workload_id = scale_match.group(1)
                replicas = int(payload.get("replicas", 0))
                result = ENGINE.scale_workload(workload_id, replicas, payload.get("operator") or user["username"])
                self._json(result)
                return

            if path == "/api/traffic":
                user = self._require("traffic")
                region = payload.get("region", "")
                delta = int(payload.get("delta", 0))
                operator = payload.get("operator") or user["username"]
                self._json(ENGINE.shift_traffic(region, delta, operator))
                return

            if path == "/api/notify/alerts":
                user = self._require("notify")
                self._json(ENGINE.notify_alerts(payload.get("operator") or user["username"]))
                return

            self._json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)
        except AuthenticationError as exc:
            self._json({"error": str(exc)}, HTTPStatus.UNAUTHORIZED)
        except AuthorizationError as exc:
            self._json({"error": str(exc)}, HTTPStatus.FORBIDDEN)
        except NotFoundError as exc:
            self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        except ValidationError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except (ValueError, json.JSONDecodeError, GameOpsError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stdout.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, payload: str, content_type: str = "text/plain; charset=utf-8") -> None:
        body = payload.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: str) -> None:
        if path in {"", "/", "/index.html"}:
            file_path = WEB_ROOT / "index.html"
        else:
            file_path = WEB_ROOT / path.lstrip("/")
        try:
            resolved = file_path.resolve()
            resolved.relative_to(WEB_ROOT.resolve())
        except ValueError:
            self._json({"error": "非法文件路径"}, HTTPStatus.FORBIDDEN)
            return
        if not resolved.exists() or not resolved.is_file():
            self._json({"error": "资源不存在"}, HTTPStatus.NOT_FOUND)
            return

        body = resolved.read_bytes()
        content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bearer_token(self) -> str:
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            return auth.split(" ", 1)[1].strip()
        return ""

    def _current_user(self, required: bool = True) -> dict | None:
        token = self._bearer_token()
        user = ENGINE.session_user(token)
        if required and not user:
            raise AuthenticationError("请先登录")
        return user

    def _require(self, permission: str) -> dict:
        user = self._current_user()
        ENGINE.require(user, permission)
        return user


def _query_first(query: dict[str, list[str]], name: str, default: str | None = None) -> str | None:
    values = query.get(name)
    if not values:
        return default
    return values[0]


def run(host: str = "127.0.0.1", port: int = 8018) -> None:
    address = (host, port)
    httpd = ThreadingHTTPServer(address, GameOpsHandler)
    print(f"GameOps Center running at http://{host}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    chosen_port = int(sys.argv[1]) if len(sys.argv) > 1 else 8018
    run(host=os.environ.get("GAMEOPS_HOST", "127.0.0.1"), port=chosen_port)
