"""Routes that turn a mail into a case: the /new page, .eml reading, manual entry, Claude interpretation."""

from __future__ import annotations

import json

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, Response
from starlette.datastructures import UploadFile

from relayguard.errors import Rejection

from .eml import MAX_EML_BYTES, EmlContent, parse_eml
from .manual_interpretation import build_interpretation, entries_from_form
from .web_context import MAX_UPLOAD_BYTES, WebContext, mode_of, to_case


def register(app: FastAPI, ui: WebContext) -> None:
    service = ui.service

    @app.get("/new", response_class=HTMLResponse)
    def new(request: Request, mode: str = "auto") -> HTMLResponse:
        return ui.new_page(request, mode=mode)

    @app.post("/cases/read-eml", response_class=HTMLResponse)
    async def read_eml(request: Request) -> Response:
        """Step 1 of 2: extract subject/body text from a saved .eml into the form of the same tab.

        No case is created and nothing is sent anywhere; the operator reads the text and presses
        the analyse button (step 2) themselves - a file is never forwarded to the provider on its own.
        """
        form = await request.form(max_part_size=MAX_EML_BYTES)
        mode = mode_of(str(form.get("mode", "")))
        try:
            ui.check_csrf(str(form.get("csrf", "")))
            upload = form.get("file")
            raw = await upload.read() if isinstance(upload, UploadFile) else b""
            content = parse_eml(raw)
        except Rejection as error:
            return ui.new_page(request, mode=mode, error=error.explanation_ja, status_code=400)
        return ui.new_page(request, mode=mode, eml=content)

    @app.post("/cases/import-manual")
    async def import_manual(request: Request) -> Response:
        """Register what the operator marked by hand: no LLM, no API key, nothing leaves the PC."""
        form = await request.form(max_part_size=MAX_UPLOAD_BYTES)
        fields = {key: str(value) for key, value in form.items() if not isinstance(value, UploadFile)}
        subject, body = fields.get("subject", ""), fields.get("body", "")
        try:
            ui.check_csrf(fields.get("csrf", ""))
            if not body.strip():
                raise Rejection("UnsupportedInput", "原文本文が空です。")
            interpretation = build_interpretation(subject or None, body, entries_from_form(fields))
            payload = json.dumps(interpretation, ensure_ascii=False).encode("utf-8")
            record = service.import_interpretation(subject or None, body, payload)
        except Rejection as error:
            kept = EmlContent(subject=subject or None, body=body, attachments=(), source="手入力")
            return ui.new_page(request, mode="manual", error=f"{error.code}: {error.explanation_ja}", eml=kept, status_code=400)
        return to_case(record.case_id)

    @app.post("/cases/interpret")
    def interpret(
        request: Request, csrf: str = Form(...), subject: str = Form(""), body: str = Form(...), consent: str = Form("")
    ) -> Response:
        try:
            ui.check_csrf(csrf)
            if ui.interpreter is None or not ui.claude_ready():
                raise Rejection("PolicyViolation", "Claudeによる読み取りは使えません。先にAPIキーを入れてください。")
            # A key entered on the screen was entered together with the consent to send (owner decision
            # 2026-09-23: once per session, not a tick box per mail). The environment-key path still asks each time.
            if consent != "1" and not (ui.api_key is not None and ui.api_key.source() == "screen"):
                raise Rejection("PolicyViolation", "外部LLMプロバイダへの本文送信への同意が必要です。")
            if not body.strip():
                raise Rejection("UnsupportedInput", "原文本文が空です。")
            record = ui.interpreter.interpret_into_case(service, subject or None, body)
        except Rejection as error:
            # Keep the pasted mail on screen: re-typing it after a provider hiccup is pure friction.
            kept = EmlContent(subject=subject or None, body=body, attachments=(), source="貼り付け")
            return ui.new_page(request, error=f"{error.code}: {error.explanation_ja}", eml=kept, status_code=400)
        return to_case(record.case_id)
