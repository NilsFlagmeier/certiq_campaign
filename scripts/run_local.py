"""Local-only campaign admin server — binds 127.0.0.1 only. Never deploy publicly."""

from __future__ import annotations

import importlib.util
import mimetypes
import os
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORT = 8787
BIND_HOST = "127.0.0.1"

REWRITES: dict[str, str] = {
    "/admin": "/api/admin/page?name=dashboard&next=/admin",
    "/admin/campaign": "/api/admin/page?name=campaign&next=/admin/campaign",
    "/admin/campaign/analytics": "/api/admin/page?name=campaign_analytics&next=/admin/campaign/analytics",
    "/admin/lead": "/api/admin/page?name=lead&next=/admin/lead",
    "/admin/login": "/ui/login.html",
    "/api/admin/campaign/sync-last-contact": "/api/admin/campaign/sync_last_contact",
}


def _normalize_path(path: str) -> str:
    parsed = urlsplit(path)
    return parsed.path.rstrip("/") or "/"


def _apply_rewrite(path: str) -> str:
    parsed = urlsplit(path)
    bare = _normalize_path(path)
    destination = REWRITES.get(bare)
    if not destination:
        return path
    dest = urlsplit(destination)
    query = dest.query or parsed.query
    return urlunsplit(("", "", dest.path, query, ""))


def _api_module_file(path: str) -> Path | None:
    parsed = urlsplit(path)
    if not parsed.path.startswith("/api/"):
        return None
    rel = parsed.path.removeprefix("/api/").strip("/")
    if not rel:
        return None
    candidate = ROOT / "api" / f"{rel.replace('/', os.sep)}.py"
    return candidate if candidate.is_file() else None


def _load_handler_class(module_file: Path) -> type[BaseHTTPRequestHandler]:
    module_name = "certiq_campaign_api_" + module_file.relative_to(ROOT).as_posix().replace("/", "_").removesuffix(".py")
    spec = importlib.util.spec_from_file_location(module_name, module_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {module_file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    handler_cls = getattr(module, "handler", None)
    if handler_cls is None:
        raise RuntimeError(f"No handler class in {module_file}")
    return handler_cls


def _resolve_static_file(path: str) -> Path | None:
    parsed = urlsplit(path)
    rel = parsed.path.lstrip("/")
    if not rel or ".." in rel.split("/"):
        return None

    candidates: list[Path] = []
    if rel.startswith("ui/"):
        candidates.append(ROOT / rel)
    if rel.startswith("admin/"):
        candidates.append(ROOT / "ui" / rel.removeprefix("admin/"))
    candidates.extend([
        ROOT / "ui" / rel,
        ROOT / "ui" / f"{rel}.html",
        ROOT / rel,
        ROOT / f"{rel}.html",
    ])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _guess_content_type(file_path: Path) -> str:
    content_type, _ = mimetypes.guess_type(file_path.as_posix())
    return content_type or "application/octet-stream"


class LocalCampaignServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def _port_is_open(host: str, port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(1)
    try:
        return probe.connect_ex((host, port)) == 0
    finally:
        probe.close()


class LocalCampaignHandler(BaseHTTPRequestHandler):
    server_version = "CertiqCampaignLocal/1.0"

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        sys.stderr.write("[%s] %s - %s\n" % (self.log_date_time_string(), self.address_string(), format % args))

    def _dispatch_api(self, path: str) -> bool:
        load_dotenv(ROOT / ".env", override=True)
        module_file = _api_module_file(path)
        if module_file is None:
            return False
        try:
            handler_cls = _load_handler_class(module_file)
        except Exception as err:  # noqa: BLE001
            sys.stderr.write(f"API import error ({path}): {err!s}\n")
            self.send_error(500, f"API import error: {err}")
            return True
        api_handler = handler_cls.__new__(handler_cls)
        api_handler.request = self.request
        api_handler.client_address = self.client_address
        api_handler.server = self.server
        api_handler.close_connection = True
        api_handler.path = path
        api_handler.headers = self.headers
        api_handler.rfile = self.rfile
        api_handler.wfile = self.wfile
        api_handler.command = self.command
        api_handler.request_version = self.request_version
        api_handler.requestline = getattr(self, "requestline", f"{self.command} {path} {self.request_version}")
        method_name = f"do_{self.command}"
        method = getattr(api_handler, method_name, None)
        if method is None:
            self.send_error(501, f"Unsupported method: {self.command}")
            return True
        try:
            method()
        except Exception as err:  # noqa: BLE001
            sys.stderr.write(f"API handler error ({path}): {err!s}\n")
            if not getattr(api_handler, "_headers_sent", False):
                self.send_error(500, f"API handler error: {err}")
        return True

    def _serve_static(self, path: str) -> bool:
        file_path = _resolve_static_file(path)
        if file_path is None:
            return False
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _guess_content_type(file_path))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def _handle(self) -> None:
        rewritten = _apply_rewrite(self.path)
        if rewritten.startswith("/api/"):
            if self._dispatch_api(rewritten):
                return
            self.send_error(404, f"No API handler for {rewritten}")
            return
        if self._serve_static(rewritten):
            return
        self.send_error(404, f"Not found: {self.path}")

    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    def do_POST(self) -> None:  # noqa: N802
        self._handle()

    def do_PUT(self) -> None:  # noqa: N802
        self._handle()

    def do_PATCH(self) -> None:  # noqa: N802
        self._handle()

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._handle()


def main() -> int:
    load_dotenv(ROOT / ".env")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    port = int(os.getenv("PORT", str(DEFAULT_PORT)).strip() or DEFAULT_PORT)
    if _port_is_open(BIND_HOST, port):
        print(
            f"Port {port} is already in use on {BIND_HOST}.",
            flush=True,
        )
        print(
            "Stop other certiq_campaign instances (Ctrl+C in their terminal) "
            "or choose another port: PORT=8788 python scripts/run_local.py",
            flush=True,
        )
        return 1

    try:
        server = LocalCampaignServer((BIND_HOST, port), LocalCampaignHandler)
    except OSError as err:
        print(f"Cannot start server on {BIND_HOST}:{port}: {err}", flush=True)
        return 1

    print(f"certiq_campaign (local only) at http://{BIND_HOST}:{port}", flush=True)
    print(f"Login: http://{BIND_HOST}:{port}/admin/login", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
