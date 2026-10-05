"""Routes of the case list and a single case: decision, generate, edit, approve, copy, delete, audit."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response

from relayguard.errors import Rejection

from .service import CaseRecord, CaseState
from .view import (
    ORIGIN_INTRO,
    ORIGIN_LEGEND,
    answers_by_question,
    claim_rows,
    finding_rows,
    next_steps,
    no_request_note,
    progress,
    reason_labels,
    reply_origin_lines,
    reply_origin_summary,
    stop_guidance,
)
from .web_context import WebContext, to_case


def register(app: FastAPI, ui: WebContext) -> None:
    service = ui.service

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return ui.home_page(request)

    @app.get("/cases/{case_id}", response_class=HTMLResponse)
    def case_page(request: Request, case_id: str) -> HTMLResponse:
        try:
            record = service.get(case_id)
        except Rejection as error:
            return ui.home_page(request, error=error.explanation_ja, status_code=404)
        shown_error, record.last_error = record.last_error, None
        rows = claim_rows(record)
        return ui.render(
            request,
            "case.html",
            case=record,
            error=shown_error,
            rows=rows,
            # The answer's supporting items, shown by what they say rather than by internal ID.
            related_options=[row for row in rows if row.kind != "Question"],
            progress=progress(record),
            answers=answers_by_question(record),
            findings=finding_rows(record),
            next_steps=next_steps(record),
            no_request_note=no_request_note(record),
            origin_lines=reply_origin_lines(record),
            origin_summary=reply_origin_summary(record),
            ORIGIN_LEGEND=ORIGIN_LEGEND,
            ORIGIN_INTRO=ORIGIN_INTRO,
            pre_reasons=reason_labels(record.pre_assessment["reason_codes"]) if record.pre_assessment else [],
            post_reasons=reason_labels(record.post_assessment["reason_codes"]) if record.post_assessment else [],
            CaseState=CaseState,
            stop_guidance=stop_guidance(record),
            decision_editable=record.state not in (CaseState.COPIED,) and record.origin == "user",
        )

    @app.post("/cases/{case_id}/decision")
    async def decision(request: Request, case_id: str) -> Response:
        form = await request.form()
        record: CaseRecord | None = None
        try:
            record = service.get(case_id)
            ui.check_csrf(str(form.get("csrf", "")))
            choices: dict[str, str] = {}
            answers: dict[str, dict[str, Any]] = {}
            for key, value in form.multi_items():
                if key.startswith("choice__"):
                    choices[key.removeprefix("choice__")] = str(value)
                elif key.startswith("answer__"):
                    answers.setdefault(key.removeprefix("answer__"), {"related_claim_ids": []})["answer_text"] = str(value)
            for key, value in form.multi_items():
                if key.startswith("related__"):
                    answers.setdefault(key.removeprefix("related__"), {"related_claim_ids": []})["related_claim_ids"].append(str(value))
            service.submit_decision(case_id, int(str(form.get("revision", "0"))), choices, answers, str(form.get("notes", "")))
        except (Rejection, ValueError) as error:
            rejection = error if isinstance(error, Rejection) else Rejection("SchemaInvalid", "フォーム値が不正です。")
            return ui.fail(record, rejection)
        return to_case(case_id)

    def action(case_id: str, csrf: str, run: Callable[[CaseRecord], Any]) -> Response:
        record: CaseRecord | None = None
        try:
            record = service.get(case_id)
            ui.check_csrf(csrf)
            run(record)
        except Rejection as error:
            return ui.fail(record, error)
        return to_case(case_id)

    @app.post("/cases/{case_id}/generate")
    def generate(case_id: str, csrf: str = Form(...), revision: int = Form(...), concise: str = Form("")) -> Response:
        return action(case_id, csrf, lambda _r: service.generate(case_id, revision, concise=bool(concise)))

    @app.post("/cases/{case_id}/draft")
    def edit(case_id: str, csrf: str = Form(...), revision: int = Form(...), reply_text: str = Form(...)) -> Response:
        return action(case_id, csrf, lambda _r: service.edit_draft(case_id, revision, reply_text))

    @app.post("/cases/{case_id}/final-approval")
    def approve(case_id: str, csrf: str = Form(...), revision: int = Form(...)) -> Response:
        return action(case_id, csrf, lambda _r: service.final_approve(case_id, revision))

    @app.post("/cases/{case_id}/copied")
    def copied(case_id: str, csrf: str = Form(...), revision: int = Form(...)) -> Response:
        return action(case_id, csrf, lambda _r: service.mark_copied(case_id, revision))

    @app.get("/cases/{case_id}/approved.txt")
    def approved_text(case_id: str) -> Response:
        try:
            return PlainTextResponse(service.copy_text(case_id))
        except Rejection as error:
            return PlainTextResponse(error.explanation_ja, status_code=409)

    @app.post("/cases/{case_id}/delete")
    def delete(request: Request, case_id: str, csrf: str = Form(...)) -> Response:
        try:
            ui.check_csrf(csrf)
        except Rejection as error:
            return ui.home_page(request, error=error.explanation_ja, status_code=400)
        service.delete(case_id)
        return RedirectResponse("/", status_code=303)

    @app.get("/cases/{case_id}/audit.json")
    def audit(case_id: str) -> Response:
        try:
            record = service.get(case_id)
        except Rejection as error:
            return JSONResponse({"error": error.code}, status_code=404)
        body = json.dumps({"case_id": case_id, "events": record.audit}, ensure_ascii=False, indent=2)
        return Response(body, media_type="application/json")
