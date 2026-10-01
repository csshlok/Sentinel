"""Local, one-use GitHub App manifest conversion with broker-only secret storage."""

from __future__ import annotations

import html
import json
import re
import secrets
import socketserver
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from typing import Literal
from urllib.parse import parse_qs, quote, urlsplit

from backend.app.credentials.broker import CredentialBroker
from backend.app.providers.http_transport import HttpTransport, TransportTimeout, UrllibHttpTransport

_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
_MAX_CALLBACK_PATH = 4096
_MAX_CONVERSION_BYTES = 256_000


def app_provider_name(owner: str) -> str:
    """A broker provider namespace unique to one GitHub user or organization."""
    if not _OWNER.fullmatch(owner):
        raise ValueError("Invalid GitHub account name")
    return f"github-app-{owner.lower()}"


@dataclass(frozen=True, slots=True)
class AppFlowView:
    flow_id: str
    owner: str
    status: Literal["PENDING", "COMPLETE", "FAILED", "EXPIRED"]
    registration_url: str | None = None
    app_slug: str | None = None
    reason: str | None = None


class _CallbackServer(socketserver.TCPServer):
    allow_reuse_address = False


class GitHubAppManifestFlow:
    """One browser registration and exactly one state-bound callback attempt."""

    def __init__(
        self,
        *,
        owner: str,
        account_kind: Literal["user", "organization"],
        broker: CredentialBroker,
        transport: HttpTransport,
        timeout_seconds: float = 300,
    ) -> None:
        app_provider_name(owner)
        if account_kind not in {"user", "organization"}:
            raise ValueError("Invalid GitHub account kind")
        if not 1 <= timeout_seconds <= 300:
            raise ValueError("Invalid callback timeout")
        self.owner = owner
        self.account_kind = account_kind
        self._broker = broker
        self._transport = transport
        self._timeout = timeout_seconds
        self._state = secrets.token_urlsafe(32)
        self._flow_id = secrets.token_urlsafe(24)
        self._status: Literal["PENDING", "COMPLETE", "FAILED", "EXPIRED"] = "PENDING"
        self._reason: str | None = None
        self._slug: str | None = None
        self._lock = threading.Lock()
        self._server: _CallbackServer | None = None
        self._thread: threading.Thread | None = None
        self._callback_received = threading.Event()

    @property
    def flow_id(self) -> str:
        return self._flow_id

    def start(self) -> AppFlowView:
        if self._server is not None:
            raise RuntimeError("Manifest flow already started")
        flow = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == f"/register/{flow._flow_id}":
                    page = flow.registration_html().encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(page)))
                    self.end_headers()
                    self.wfile.write(page)
                    return
                parsed = urlsplit(self.path)
                if parsed.path != "/callback":
                    self.send_error(404)
                    return
                status = 400
                query = parse_qs(parsed.query, keep_blank_values=True)
                if (len(self.path) > _MAX_CALLBACK_PATH or set(query) != {"code", "state"}
                        or any(len(v) != 1 for v in query.values())
                        or not secrets.compare_digest(query["state"][0], flow._state)):
                    self.send_error(400)
                    return
                try:
                    code = query["code"][0]
                    if not code or len(code) > 512:
                        raise ValueError("Invalid callback code")
                    flow._convert(code)
                    status = 200
                except (ValueError, TransportTimeout):
                    flow._finish("FAILED", reason="App registration could not be verified")
                except Exception:
                    # Never put GitHub response bodies, callback codes or PEM data in errors.
                    flow._finish("FAILED", reason="App registration failed")
                flow._callback_received.set()
                body = (b"Sentinel GitHub App registration complete."
                        if status == 200 else b"Sentinel GitHub App registration failed.")
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                # The URL contains a one-use conversion code and must never be logged.
                return

        self._server = _CallbackServer(("127.0.0.1", 0), Handler)
        self._server.timeout = min(self._timeout, 0.5)

        def receive_once() -> None:
            assert self._server is not None
            try:
                deadline = time.monotonic() + self._timeout
                while not self._callback_received.is_set() and time.monotonic() < deadline:
                    self._server.handle_request()
                with self._lock:
                    if self._status == "PENDING":
                        self._status = "EXPIRED"
                        self._reason = "Registration callback expired"
            finally:
                self._server.server_close()

        self._thread = threading.Thread(target=receive_once, daemon=True,
                                        name="sentinel-github-app-callback")
        self._thread.start()
        return self.view()

    def view(self) -> AppFlowView:
        with self._lock:
            registration_url = None
            if self._status == "PENDING" and self._server is not None:
                registration_url = (f"http://127.0.0.1:{self._server.server_address[1]}"
                                    f"/register/{quote(self._flow_id)}")
            return AppFlowView(
                flow_id=self._flow_id, owner=self.owner, status=self._status,
                registration_url=registration_url,
                app_slug=self._slug, reason=self._reason,
            )

    def registration_html(self) -> str:
        if self.view().status != "PENDING" or self._server is None:
            raise ValueError("Manifest flow has expired")
        port = self._server.server_address[1]
        redirect_url = f"http://127.0.0.1:{port}/callback"
        manifest = {
            "name": f"Sentinel {self.owner}",
            "url": "https://github.com",
            "redirect_url": redirect_url,
            "hook_attributes": {"url": redirect_url, "active": False},
            "public": False,
            "default_permissions": {"checks": "write", "contents": "read",
                                    "pull_requests": "read"},
            "default_events": [],
        }
        if self.account_kind == "organization":
            action = f"https://github.com/organizations/{quote(self.owner)}/settings/apps/new"
        else:
            action = "https://github.com/settings/apps/new"
        action += f"?state={quote(self._state)}"
        value = html.escape(json.dumps(manifest, separators=(",", ":")), quote=True)
        return ("<!doctype html><html lang='en'><meta charset='utf-8'>"
                "<title>Create Sentinel GitHub App</title>"
                f"<form action='{html.escape(action, quote=True)}' method='post'>"
                f"<input type='hidden' name='manifest' value='{value}'>"
                "<button type='submit'>Create Sentinel GitHub App</button></form></html>")

    def _convert(self, code: str) -> None:
        response = self._transport.request(
            "POST", f"https://api.github.com/app-manifests/{quote(code, safe='')}/conversions",
            headers={"Accept": "application/vnd.github+json",
                     "Content-Type": "application/json"}, body=b"{}", timeout_seconds=15,
        )
        if response.status_code != 201 or len(response.body) > _MAX_CONVERSION_BYTES:
            raise ValueError("App conversion failed")
        try:
            data = json.loads(response.body)
            app_id = data["id"]
            slug = data["slug"]
            pem = data["pem"]
            webhook_secret = data.get("webhook_secret")
            if (type(app_id) is not int or app_id <= 0 or not isinstance(slug, str)
                    or not _SLUG.fullmatch(slug) or not isinstance(pem, str)
                    or not pem.startswith("-----BEGIN RSA PRIVATE KEY-----")
                    or len(pem) > 100_000
                    or (webhook_secret is not None
                        and (not isinstance(webhook_secret, str)
                             or len(webhook_secret) > 4096))):
                raise ValueError("Invalid App conversion")
        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise ValueError("Invalid App conversion") from exc
        secret = json.dumps({"id": app_id, "slug": slug, "pem": pem,
                             "webhook_secret": webhook_secret}, separators=(",", ":"))
        self._broker.store_provider_secret(app_provider_name(self.owner), secret)
        self._finish("COMPLETE", slug=slug)

    def _finish(self, status: Literal["COMPLETE", "FAILED"], *,
                slug: str | None = None, reason: str | None = None) -> None:
        with self._lock:
            self._status = status
            self._slug = slug
            self._reason = reason


class GitHubAppManifestFlows:
    """Bounded in-memory registry; durable App credentials live in the broker."""

    def __init__(self, broker: CredentialBroker, *,
                 transport: HttpTransport | None = None) -> None:
        self._broker = broker
        self._transport = transport or UrllibHttpTransport()
        self._flows: dict[str, GitHubAppManifestFlow] = {}
        self._lock = threading.Lock()

    def create(self, *, owner: str,
               account_kind: Literal["user", "organization"]) -> AppFlowView:
        with self._lock:
            for key, flow in list(self._flows.items()):
                if flow.view().status != "PENDING":
                    del self._flows[key]
            if len(self._flows) >= 32:
                raise ValueError("Too many pending GitHub App registrations")
            if any(flow.owner.lower() == owner.lower() for flow in self._flows.values()):
                raise ValueError("GitHub App registration already pending for this account")
            flow = GitHubAppManifestFlow(
                owner=owner, account_kind=account_kind,
                broker=self._broker, transport=self._transport,
            )
            result = flow.start()
            self._flows[flow.flow_id] = flow
            return result

    def get(self, flow_id: str) -> AppFlowView | None:
        with self._lock:
            flow = self._flows.get(flow_id)
        return flow.view() if flow is not None else None

