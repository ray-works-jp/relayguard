"""Read a saved e-mail (.eml) into the subject/body text the reviewer works with.

Real mail is mostly markup: the body a person reads is buried in quoted-printable HTML with
tracking pixels and click-wrapped links. This module extracts the readable text so the operator
does not have to do it by hand, and nothing more:

- no network access, ever (remote images, web fonts and tracked links are dropped, not fetched),
- no interpretation and no judgement - the extracted text is still untrusted input that goes
  through the normal Interpretation -> Decision flow,
- attachments are listed by name only; their content is never read (IMPLEMENTATION.md: a reply
  that depends on an attachment is an L3 case for a human).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from email import message_from_bytes, policy
from email.message import EmailMessage
from html.parser import HTMLParser

from relayguard.errors import Rejection
from relayguard.integrity import MAX_SOURCE_BYTES

MAX_EML_BYTES = 4 * 1024 * 1024
LONG_BODY_CHARS = 4000  # above this, one interpretation can run past the §23 total budget (300 s since ruling D-7)
_SKIP = frozenset({"script", "style", "head", "title", "noscript"})
_BLOCK = frozenset({"p", "div", "br", "tr", "table", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "section", "header", "footer"})
_BLANK_RUN = re.compile(r"\n{3,}")
_TRAILING_SPACE = re.compile(r"[ \t]+\n")


@dataclass(frozen=True)
class EmlContent:
    subject: str | None
    body: str
    attachments: tuple[str, ...]
    source: str  # "text/plain" or "text/html"

    @property
    def is_long(self) -> bool:
        """Long mail (newsletters, notices) is slow and expensive to interpret - warn before trying."""
        return len(self.body) > LONG_BODY_CHARS


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip_depth += 1
        elif tag == "li":
            self._parts.append("\n- ")
        elif tag in _BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self._parts.append(re.sub(r"\s+", " ", data).strip() + " ")

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return normalize_text(parser.text())


def normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return _BLANK_RUN.sub("\n\n", _TRAILING_SPACE.sub("\n", "\n".join(lines))).strip()


def _readable_parts(message: EmailMessage) -> tuple[list[EmailMessage], list[str]]:
    bodies: list[EmailMessage] = []
    attachments: list[str] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        disposition = (part.get_content_disposition() or "").lower()
        if disposition == "attachment" or filename:
            attachments.append(filename or part.get_content_type())
        elif part.get_content_type() in ("text/plain", "text/html"):
            bodies.append(part)
    return bodies, attachments


def _decoded(part: EmailMessage) -> str:
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def parse_eml(raw: bytes) -> EmlContent:
    """Extract subject, readable body text and attachment names from a saved .eml file."""
    try:
        return _parse_eml(raw)
    except Rejection:
        raise
    except Exception:  # noqa: BLE001 - the stdlib parser raises assorted errors on hostile headers/MIME
        raise Rejection(
            "UnsupportedInput",
            "メールファイルの構造が壊れているため読み取れませんでした。このファイルからは案件を作成していません。本文を貼り付けてください。",
        ) from None


def _parse_eml(raw: bytes) -> EmlContent:
    if not raw.strip():
        raise Rejection("UnsupportedInput", "ファイルが空です。")
    if len(raw) > MAX_EML_BYTES:
        raise Rejection("UnsupportedInput", f"メールファイルが大きすぎます（上限{MAX_EML_BYTES // (1024 * 1024)} MB）。")
    message = message_from_bytes(raw, policy=policy.default)
    if not isinstance(message, EmailMessage) or not (message.get("subject") or message.get("from") or message.get_payload()):
        raise Rejection("UnsupportedInput", "メール形式（.eml）として読み取れませんでした。")
    bodies, attachments = _readable_parts(message)
    plain = [part for part in bodies if part.get_content_type() == "text/plain"]
    chosen = plain or [part for part in bodies if part.get_content_type() == "text/html"]
    if not chosen:
        raise Rejection("UnsupportedInput", "本文テキストが見つかりませんでした（本文が添付や画像のみの可能性があります）。")
    source = chosen[0].get_content_type()
    raw_text = "\n\n".join(_decoded(part) for part in chosen)
    body = normalize_text(raw_text) if source == "text/plain" else html_to_text(raw_text)
    if not body:
        raise Rejection("UnsupportedInput", "本文テキストが空でした。")
    subject = message.get("subject")
    size = len(body.encode("utf-8")) + len((subject or "").encode("utf-8"))
    if size > MAX_SOURCE_BYTES:
        raise Rejection("UnsupportedInput", "本文が上限64 KiBを超えています。必要な部分だけを貼り付けてください。")
    return EmlContent(subject=str(subject) if subject else None, body=body, attachments=tuple(attachments), source=source)
