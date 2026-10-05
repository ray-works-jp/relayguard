"""Routes of the settings page: API key, self-check and the developer imports (sample / JSON)."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from relayguard.errors import Rejection

from .api_key import client_factory as session_client_factory
from .selfcheck import CheckSetup, run_checks
from .web_context import MAX_UPLOAD_BYTES, WebContext, back_url, to_case

_LOG = logging.getLogger("relayguard.ui.app")


def register(app: FastAPI, ui: WebContext) -> None:
    service = ui.service

    @app.get("/settings", response_class=HTMLResponse)
    def settings(request: Request) -> HTMLResponse:
        return ui.settings_page(request)

    @app.post("/cases/import-sample")
    def import_sample(request: Request, csrf: str = Form(...), name: str = Form(...)) -> Response:
        try:
            ui.check_csrf(csrf)
            if ui.samples_dir is None or name not in ui.samples():
                raise Rejection("PolicyViolation", "サンプルが見つかりません。")
            record = service.import_shadow_input((ui.samples_dir / name).read_bytes())
        except Rejection as error:
            return ui.settings_page(request, error=error.explanation_ja, status_code=400)
        return to_case(record.case_id)

    @app.post("/cases/import-json")
    async def import_json(request: Request) -> Response:
        form = await request.form(max_part_size=MAX_UPLOAD_BYTES)
        try:
            ui.check_csrf(str(form.get("csrf", "")))
            payload = str(form.get("payload", "")).encode("utf-8")
            if len(payload) > MAX_UPLOAD_BYTES:
                raise Rejection("UnsupportedInput", "入力が大きすぎます。")
            record = service.import_shadow_input(payload)
        except Rejection as error:
            return ui.settings_page(request, error=f"{error.code}: {error.explanation_ja}", status_code=400)
        return to_case(record.case_id)

    @app.post("/cases/import-interpretation")
    async def import_interpretation(request: Request) -> Response:
        form = await request.form(max_part_size=MAX_UPLOAD_BYTES)
        try:
            ui.check_csrf(str(form.get("csrf", "")))
            body = str(form.get("body", ""))
            if not body.strip():
                raise Rejection("UnsupportedInput", "原文本文が空です。")
            interpretation = str(form.get("interpretation", "")).encode("utf-8")
            record = service.import_interpretation(str(form.get("subject", "")) or None, body, interpretation)
        except Rejection as error:
            return ui.settings_page(request, error=f"{error.code}: {error.explanation_ja}", status_code=400)
        return to_case(record.case_id)

    @app.get("/self-check", response_class=HTMLResponse)
    def self_check(request: Request) -> HTMLResponse:
        """Setup diagnosis on demand. The live part costs a fraction of a cent and sends no mail."""
        root = Path(__file__).resolve().parents[2].parent
        if ui.api_key is not None:
            key = ui.api_key
            setup = CheckSetup(
                root=root,
                samples_dir=ui.samples_dir,
                live=ui.claude_ready(),
                client_factory=session_client_factory(key),
                key=lambda: key.value() or "",
                from_screen=True,
            )
        else:
            setup = CheckSetup(root=root, samples_dir=ui.samples_dir, live=ui.interpreter is not None, from_screen=True)
        return ui.render(request, "selfcheck.html", results=run_checks(setup))

    @app.post("/settings/api-key")
    def set_api_key(
        request: Request, csrf: str = Form(...), key: str = Form(""), consent: str = Form(""), back: str = Form("new")
    ) -> Response:
        """Hold the key in memory for this process. It is never echoed, logged or written anywhere."""
        try:
            ui.check_csrf(csrf)
            if ui.api_key is None or ui.interpreter is None:
                raise Rejection("PolicyViolation", "この起動方法ではAPIキーを画面から設定できません。")
            if consent != "1":
                raise Rejection("PolicyViolation", "「解析する」を押したメールの本文がAnthropicに送られることへの同意が必要です。")
            ui.api_key.set(key)
        except Rejection as error:
            if back == "settings":
                return ui.settings_page(request, error=error.explanation_ja, status_code=400)
            return ui.new_page(request, error=error.explanation_ja, status_code=400)
        _LOG.info("api key set on screen")  # the fact only, never the key
        return RedirectResponse(back_url(back), status_code=303)

    @app.post("/settings/api-key/clear")
    def clear_api_key(request: Request, csrf: str = Form(...), back: str = Form("settings")) -> Response:
        try:
            ui.check_csrf(csrf)
        except Rejection as error:
            return ui.settings_page(request, error=error.explanation_ja, status_code=400)
        if ui.api_key is not None:
            ui.api_key.clear()
        return RedirectResponse(back_url(back), status_code=303)
