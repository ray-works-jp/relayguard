"""State and helpers shared by the route modules of one app instance (see app.py)."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from relayguard.errors import Rejection

from .api_key import SessionKey
from .eml import EmlContent
from .interpreter import ClaudeInterpreter
from .labels import DECISION_LABELS, LEVEL_LABELS, LEVEL_SHORT, REASON_LABELS, STATE_LABELS
from .service import CaseRecord, CaseService

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
MAX_UPLOAD_BYTES = 512 * 1024
_MODES = ("auto", "manual")
_BACK_URLS = {"new": "/new", "settings": "/settings"}


def mode_of(value: str) -> str:
    """The /new tab; anything else falls back to the default automatic tab."""
    return value if value in _MODES else "auto"


def back_url(value: str) -> str:
    """Where to return after a key change: one of two fixed pages, never a URL taken from the form."""
    return _BACK_URLS.get(value, "/new")


def to_case(case_id: str) -> RedirectResponse:
    return RedirectResponse(f"/cases/{case_id}", status_code=303)


@dataclass(frozen=True)
class WebContext:
    service: CaseService
    csrf_token: str
    samples_dir: Path | None
    interpreter: ClaudeInterpreter | None
    api_key: SessionKey | None

    def claude_ready(self) -> bool:
        # With an on-screen key store, Claude is off until a key is entered (B9 as revised 2026-09-23).
        return self.interpreter is not None and (self.api_key is None or self.api_key.available())

    def render(self, request: Request, name: str, status_code: int = 200, **context: Any) -> HTMLResponse:
        base = {
            "csrf": self.csrf_token,
            "operator": self.service.operator_id,
            "LEVEL_LABELS": LEVEL_LABELS,
            "LEVEL_SHORT": LEVEL_SHORT,
            "STATE_LABELS": STATE_LABELS,
            "REASON_LABELS": REASON_LABELS,
            "DECISION_LABELS": DECISION_LABELS,
            "llm_enabled": self.claude_ready(),
            "key_entry": self.interpreter is not None and self.api_key is not None,
            "key_source": self.api_key.source() if self.api_key is not None else None,
        }
        return TEMPLATES.TemplateResponse(request, name, {**base, **context}, status_code=status_code)

    def check_csrf(self, token: str) -> None:
        if not hmac.compare_digest(token, self.csrf_token):
            raise Rejection("PolicyViolation", "フォームの検証トークンが一致しません。画面を再読み込みしてください。")

    def fail(self, record: CaseRecord | None, error: Rejection) -> RedirectResponse:
        if record is None:  # the case is gone (expired or deleted): back to the list, which shows what is left
            return RedirectResponse("/", status_code=303)
        record.last_error = {"code": error.code, "message": error.explanation_ja}
        return to_case(record.case_id)

    def samples(self) -> list[str]:
        if self.samples_dir is None or not self.samples_dir.is_dir():
            return []
        return sorted(p.name for p in self.samples_dir.glob("*.input.json"))

    def home_page(self, request: Request, *, error: str = "", status_code: int = 200) -> HTMLResponse:
        return self.render(
            request,
            "index.html",
            status_code=status_code,
            page="home",
            cases=self.service.list_cases(),
            samples=self.samples(),
            error=error,
        )

    def new_page(
        self, request: Request, *, mode: str = "auto", error: str = "", eml: EmlContent | None = None, status_code: int = 200
    ) -> HTMLResponse:
        # Without an interpreter the automatic tab can never work, so the page opens on the manual one.
        shown = "manual" if self.interpreter is None else mode_of(mode)
        return self.render(request, "new.html", status_code=status_code, page="new", mode=shown, error=error, eml=eml)

    def settings_page(self, request: Request, *, error: str = "", status_code: int = 200) -> HTMLResponse:
        return self.render(request, "settings.html", status_code=status_code, page="settings", samples=self.samples(), error=error)
