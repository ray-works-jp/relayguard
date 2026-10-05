"""Reading a saved .eml into subject/body text (relayguard_ui/eml.py) and the /cases/read-eml route.

The extracted text is untrusted input like any other: the reader only strips markup, it never
fetches anything, never reads attachment content and never decides anything.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from relayguard.errors import Rejection
from relayguard_ui.app import create_app
from relayguard_ui.eml import html_to_text, parse_eml
from relayguard_ui.interpreter import ClaudeInterpreter
from relayguard_ui.service import CaseService

TOKEN = "eml-test-token-value"


def csrf_of(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match, "csrf token missing"
    return match.group(1)


PLAIN = b"""From: Customer <customer@example.com>
To: sales@example.co.jp
Subject: Refund for order 4471
Content-Type: text/plain; charset=utf-8

Hello,

The kettle arrived damaged. I would like a refund of USD 49.00 this week.

Regards,
Customer
"""

QUOTED_PRINTABLE_HTML = b"""From: Shop <no-reply@example.com>
Subject: =?utf-8?q?Order_=E2=80=94_update?=
Content-Type: text/html; charset=utf-8
Content-Transfer-Encoding: quoted-printable

<html><head><style>p { color: red }</style><title>ignored</title></head><body>
<p>Hi there,</p><p>Your refund of USD=C2=A049.00 is scheduled.</p>
<ul><li>Item one</li><li>Item two</li></ul>
<script>alert('x')</script>
<a href=3D"https://track.example.com/click?id=3D1">Manage preferences</a>
<img src=3D"https://track.example.com/open.gif" width=3D"1" height=3D"1">
</body></html>
"""

WITH_ATTACHMENT = b"""From: Customer <customer@example.com>
Subject: Invoice question
Content-Type: multipart/mixed; boundary="BOUND"

--BOUND
Content-Type: text/plain; charset=utf-8

Please see the attached invoice.
--BOUND
Content-Type: application/pdf; name="invoice.pdf"
Content-Disposition: attachment; filename="invoice.pdf"
Content-Transfer-Encoding: base64

JVBERi0xLjQK
--BOUND--
"""


def test_plain_text_mail_keeps_the_body_verbatim() -> None:
    content = parse_eml(PLAIN)
    assert content.subject == "Refund for order 4471"
    assert content.source == "text/plain"
    assert "I would like a refund of USD 49.00 this week." in content.body
    assert content.attachments == ()


def test_html_mail_is_reduced_to_readable_text_without_markup_or_tracking() -> None:
    content = parse_eml(QUOTED_PRINTABLE_HTML)
    assert content.subject == "Order — update"
    assert content.source == "text/html"
    assert "Your refund of USD 49.00 is scheduled." in content.body  # the NBSP in the source becomes a plain space
    assert "\xa0" not in content.body
    assert "- Item one" in content.body and "- Item two" in content.body
    assert "Manage preferences" in content.body
    for leaked in ("<p>", "color: red", "alert(", "track.example.com", "ignored"):
        assert leaked not in content.body


def test_attachment_names_are_listed_but_never_read() -> None:
    content = parse_eml(WITH_ATTACHMENT)
    assert content.attachments == ("invoice.pdf",)
    assert content.body == "Please see the attached invoice."
    assert "JVBERi" not in content.body


def test_html_to_text_keeps_line_structure_and_drops_blank_runs() -> None:
    assert html_to_text("<div>One</div><div><br><br></div><div>Two</div>") == "One\n\nTwo"


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("empty", "ファイルが空です。"),
        ("too_large", "メールファイルが大きすぎます（上限4 MB）。"),
        ("no_text_part", "本文テキストが見つかりませんでした（本文が添付や画像のみの可能性があります）。"),
    ],
)
def test_unreadable_files_are_rejected_not_guessed(case: str, reason: str) -> None:
    raw = {
        "empty": b"   ",
        "too_large": b"\x00" * (4 * 1024 * 1024 + 1),
        "no_text_part": b"Subject: image only\nContent-Type: image/png\n\nnot text",
    }[case]
    with pytest.raises(Rejection) as caught:
        parse_eml(raw)
    assert caught.value.code == "UnsupportedInput"
    assert caught.value.explanation_ja == reason


def test_oversized_body_is_rejected() -> None:
    with pytest.raises(Rejection) as caught:
        parse_eml(b"Subject: big\nContent-Type: text/plain; charset=utf-8\n\n" + b"a" * (64 * 1024 + 1))
    assert caught.value.code == "UnsupportedInput"


def client() -> TestClient:
    client = TestClient(create_app(CaseService("op_test"), access_token=TOKEN))
    assert client.get(f"/login?token={TOKEN}", follow_redirects=False).status_code == 303
    return client


def test_route_shows_the_extracted_text_and_imports_nothing() -> None:
    web = client()
    page = web.get("/new").text
    response = web.post("/cases/read-eml", data={"csrf": csrf_of(page)}, files={"file": ("mail.eml", PLAIN, "message/rfc822")})
    assert response.status_code == 200
    assert "I would like a refund of USD 49.00 this week." in response.text
    # Step 1 of 2 only: the text lands in the form; no case exists until the operator submits it.
    assert "案件はまだありません" in web.get("/").text


def test_route_reports_an_unreadable_file_without_crashing() -> None:
    web = client()
    page = web.get("/new").text
    response = web.post("/cases/read-eml", data={"csrf": csrf_of(page)}, files={"file": ("x.eml", b"  ", "message/rfc822")})
    assert response.status_code == 400
    assert "ファイルが空です。" in response.text


def test_route_requires_the_csrf_token() -> None:
    web = client()
    response = web.post("/cases/read-eml", data={"csrf": "forged"}, files={"file": ("mail.eml", PLAIN, "message/rfc822")})
    assert response.status_code == 400
    assert "検証トークン" in response.text


def test_extracted_mail_is_prefilled_into_the_interpret_form() -> None:
    app = create_app(CaseService("op_test"), access_token=TOKEN, interpreter=ClaudeInterpreter(lambda: None))  # type: ignore[arg-type,return-value]
    web = TestClient(app)
    assert web.get(f"/login?token={TOKEN}", follow_redirects=False).status_code == 303
    page = web.get("/new").text
    response = web.post("/cases/read-eml", data={"csrf": csrf_of(page)}, files={"file": ("mail.eml", PLAIN, "message/rfc822")})
    form = response.text.split('action="/cases/interpret"', 1)[1]
    assert "I would like a refund of USD 49.00 this week." in form.split("</form>", 1)[0]
    assert 'value="Refund for order 4471"' in form.split("</form>", 1)[0]


def test_long_mail_is_flagged_so_the_operator_can_trim_it() -> None:
    short = parse_eml(PLAIN)
    assert not short.is_long
    long_mail = b"Subject: newsletter\nContent-Type: text/plain; charset=utf-8\n\n" + b"word " * 1200
    assert parse_eml(long_mail).is_long


def test_long_mail_warning_is_shown_after_extraction() -> None:
    web = client()
    page = web.get("/new").text
    long_mail = b"Subject: newsletter\nContent-Type: text/plain; charset=utf-8\n\n" + b"word " * 1200
    response = web.post("/cases/read-eml", data={"csrf": csrf_of(page)}, files={"file": ("n.eml", long_mail, "message/rfc822")})
    assert "本文が長め" in response.text
