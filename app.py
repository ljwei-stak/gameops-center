"""HTTP entrypoint for GameOps Center."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlparse

from gameops.engine import GameOpsEngine, GameOpsError, NotFoundError, ValidationError


PROJECT_ROOT = Path(__file__).parent
WEB_ROOT = PROJECT_ROOT / "web"
ENGINE = GameOpsEngine()


class GameOpsHandler(BaseHTTPRequestHandler):
    """Small API and static-file handler."""

    server_version = "GameOpsCenter/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path == "/api/health":
                self._json({"status": "ok", "service": "gameops-center"})
            elif path == "/api/overview":
                self._json(ENGINE.overview())
            elif path == "/api/servers":
                self._json(
                    ENGINE.list_servers(
                        region=_query_first(query, "region"),
                        status=_query_first(query, "status"),
                    )
                )
            elif path == "/api/alerts":
                self._json(ENGINE.alerts())
            elif path == "/api/logs":
                limit = int(_query_first(query, "limit", "40"))
                self._json(ENGINE.list_logs(level=_query_first(query, "level"), limit=limit))
            elif path == "/api/deployments":
                self._json(ENGINE.list_deployments())
            else:
                self._static(path)
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
            if path == "/api/deploy":
                result = ENGINE.deploy(
                    region=payload.get("region", "all"),
                    version=payload.get("version", ""),
                    strategy=payload.get("strategy", "canary"),
                    operator=payload.get("operator", "release-bot"),
                )
                self._json(result, HTTPStatus.CREATED)
                return

            restart_match = re.match(r"^/api/servers/([^/]+)/restart$", path)
            if restart_match:
                server_id = restart_match.group(1)
                result = ENGINE.restart_server(server_id, payload.get("operator", "ops-user"))
                self._json(result)
                return

            if path == "/api/traffic":
                region = payload.get("region", "")
                delta = int(payload.get("delta", 0))
                operator = payload.get("operator", "ops-user")
                self._json(ENGINE.shift_traffic(region, delta, operator))
                return

            self._json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)
        except NotFoundError as exc:
            self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        except ValidationError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except (ValueError, json.JSONDecodeError) as exc:
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
    run(port=chosen_port)

