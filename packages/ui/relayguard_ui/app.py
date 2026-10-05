"""Local reviewer web UI (FastAPI + server-rendered HTML).

Security posture for a single-operator local tool (IMPLEMENTATION.md §23):
- binds to 127.0.0.1 by default; requests with a non-local Host header are refused
  (DNS-rebinding guard),
- a random access token is printed at startup; ``/login?token=...`` sets an HttpOnly,
  SameSite=Strict cookie; every other route requires it,
- every POST carries a CSRF token and the case ``revision`` (stale forms are rejected),
- the approver identity comes from server configuration, never from the form,
- strict Content-Security-Policy; no third-party assets; nothing is sent anywhere.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import routes_case, routes_intake, routes_settings
from .api_key import SessionKey
from .interpreter import ClaudeInterpreter
from .service import CaseService
from .web_context import WebContext

STATIC_DIR = Path(__file__).parent / "static"
_LOG = logging.getLogger("relayguard.ui.app")
COOKIE = "rg_session"
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "testserver"})
_CSP = (
    "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
)


def _hostname(host_header: str) -> str:
    if host_header.startswith("["):
        return host_header.split("]", 1)[0] + "]"
    return host_header.rsplit(":", 1)[0]


def create_app(
    service: CaseService,
    *,
    access_token: str,
    samples_dir: Path | None = None,
    interpreter: ClaudeInterpreter | None = None,
    api_key: SessionKey | None = None,
) -> FastAPI:
    app = FastAPI(title="RelayGuard Reviewer", docs_url=None, redoc_url=None, openapi_url=None)
    session_value = secrets.token_urlsafe(32)

    @app.exception_handler(RequestValidationError)
    async def bad_form(_request: Request, _error: RequestValidationError) -> Response:
        # FastAPI's default is an English JSON dump of the offending fields; the operator needs one line.
        return PlainTextResponse(
            "入力を受け付けられませんでした。必要な項目を確認し、画面を開き直してからやり直してください。", status_code=400
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, error: StarletteHTTPException) -> Response:
        messages = {
            400: "送信内容を読み取れませんでした（ファイルやフォームが大きすぎる可能性があります）。",
            404: "ページが見つかりません。トップ画面から開き直してください。",
            405: "この操作方法は使えません。画面のボタンからやり直してください。",
        }
        return PlainTextResponse(messages.get(error.status_code, "リクエストを処理できませんでした。"), status_code=error.status_code)

    @app.middleware("http")
    async def guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if _hostname(request.headers.get("host", "")) not in LOCAL_HOSTS:
            return PlainTextResponse("forbidden host", status_code=403)
        if request.url.path not in ("/login", "/static/app.css") and not hmac.compare_digest(
            request.cookies.get(COOKIE, ""), session_value
        ):
            return PlainTextResponse("起動時に表示されたURL（/login?token=...）から開いてください。", status_code=401)
        try:
            response = await call_next(request)
        except Exception as error:  # noqa: BLE001 - last line of defence: never a traceback, never mail text in the log
            # Every route turns Rejection into a page; reaching here is a bug. The crash may come after a
            # state change, so the page must not claim nothing happened (ruling P-6). The log carries the
            # exception type only (an exception message can quote the mail; hash-only log policy).
            _LOG.error("unhandled %s on %s %s", type(error).__name__, request.method, getattr(request.scope.get("route"), "path", "-"))
            response = PlainTextResponse(
                "内部エラーが発生し、操作結果を確認できません。案件一覧で状態を確認してください。"
                "状態が不明なときは再操作せず手動で確認してください。貼り付けた本文は失われた可能性があります。",
                status_code=500,
            )
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    ui = WebContext(service, secrets.token_urlsafe(32), samples_dir, interpreter, api_key)

    @app.get("/login")
    def login(token: str = "") -> Response:
        if not hmac.compare_digest(token, access_token):
            return PlainTextResponse("invalid token", status_code=401)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(COOKIE, session_value, httponly=True, samesite="strict")
        return response

    @app.get("/static/{name}")
    def static(name: str) -> Response:
        allowed = {"app.css": "text/css", "app.js": "application/javascript"}
        if name not in allowed:
            return PlainTextResponse("not found", status_code=404)
        return Response((STATIC_DIR / name).read_text(encoding="utf-8"), media_type=allowed[name])

    routes_case.register(app, ui)
    routes_intake.register(app, ui)
    routes_settings.register(app, ui)
    return app
