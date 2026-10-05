"""Fixed ISO 4217 currency set (SCHEMA.md v0.5 §12.3).

The set is pinned to the SIX List One original stored under ``reference/iso4217/`` with
its manifest (source URL, HTTP result, retrieval date, original hashes, extraction rule,
adopted code list hash). Loading is a local file read: no network access at runtime and
no automatic update. A manifest whose code list does not match its recorded hash is a
fatal integrity error rather than a silently different set.

``verify_stored_originals`` re-checks the stored originals against the format and
structure recorded in the manifest, so a soft-404 HTML page served with HTTP 200 (as SIX
does for a missing ``dam`` path) can never pass as an original.

Set version rg-iso4217-20260915-f581922d2a56 was approved by the Architect on 2026-09-16.
Any change needs original diffs, regression runs, Architect review and a policy revision.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "reference" / "iso4217" / "manifest.json"

_HTML_MARKERS = (b"<!doctype html", b"<html", b"<!DOCTYPE HTML")
_OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
_XML_PROLOG = re.compile(rb"\s*<\?xml\s")


class OriginalIntegrityError(RuntimeError):
    """A stored reference original is missing, altered, or not the expected document."""


def code_list_hash(codes: list[str]) -> str:
    """ASCII ascending, LF separated, trailing LF, UTF-8 without BOM (SCHEMA §12.3)."""
    return hashlib.sha256(("\n".join(sorted(codes)) + "\n").encode("utf-8")).hexdigest()


def sniff_format(raw: bytes) -> str:
    """Best-effort format of a downloaded original. HTML is always reported as html so an
    error page can be rejected, whatever extension or content type the server claimed."""
    head = raw[:1024].lstrip()
    if any(marker in head.lower() for marker in (b"<!doctype html", b"<html")):
        return "html"
    if raw.startswith(_OLE_MAGIC):
        return "msword-ole"
    if _XML_PROLOG.match(raw):
        return "xml"
    return "unknown"


def verify_original(raw: bytes, *, expected_format: str, expected_markers: list[str]) -> None:
    actual = sniff_format(raw)
    if actual == "html" or actual != expected_format:
        raise OriginalIntegrityError(
            f"stored original is {actual}, expected {expected_format}"
            + (" (an HTML error page is never a valid original)" if actual == "html" else "")
        )
    for marker in expected_markers:
        if marker.encode("utf-8") not in raw:
            raise OriginalIntegrityError(f"stored original does not contain the expected marker {marker!r}")


def verify_stored_originals(manifest: dict[str, Any] | None = None) -> list[str]:
    """Check every stored original against the manifest. Returns the checked file names."""
    manifest = manifest if manifest is not None else CURRENCY_MANIFEST
    checked: list[str] = []
    for original in manifest["originals"]:
        path = MANIFEST_PATH.parent / original["file"]
        raw = path.read_bytes()
        if len(raw) != original["bytes"] or hashlib.sha256(raw).hexdigest() != original["sha256"]:
            raise OriginalIntegrityError(f"{original['file']}: size or hash does not match the manifest")
        verify_original(raw, expected_format=original["format"], expected_markers=original["expected_markers"])
        checked.append(original["file"])
    return checked


def _load() -> tuple[str, frozenset[str], dict[str, Any]]:
    manifest: dict[str, Any] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    adopted = manifest["adopted"]
    codes: list[str] = list(adopted["codes"])
    if codes != sorted(codes) or len(set(codes)) != len(codes):
        raise RuntimeError("currency manifest: adopted codes are not a sorted unique list")
    computed = code_list_hash(codes)
    if computed != adopted["code_list_sha256"]:
        raise RuntimeError("currency manifest: adopted code list does not match its recorded hash")
    if not adopted["set_version"].endswith(computed[:12]):
        raise RuntimeError("currency manifest: set_version does not carry the adopted code list hash")
    return str(adopted["set_version"]), frozenset(codes), manifest


SUPPORTED_CURRENCY_SET_VERSION, SUPPORTED_CURRENCIES, CURRENCY_MANIFEST = _load()
