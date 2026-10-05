"""The Anthropic API key, entered on the screen and held in this process's memory only.

Product owner decision (2026-09-23): the people who want this tool want Claude to read the mail,
and a command prompt plus an environment variable stood between them and that. Entering the
key on the page replaces the startup flag as the way to turn Claude on (Builder decision B9 as
revised). What does not change: nothing is sent until the operator presses "解析する" and
consents for that mail, and a model output is still only a draft that must pass validation.

The key is never written to disk, never logged, never put in a page or an error message, and
never sent anywhere but the Anthropic client. It is gone when the process ends.
The environment variable still works, but only when the operator started with
``--enable-llm-interpreter`` - an old variable left in the environment must not switch Claude on.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable

from relayguard.errors import Rejection

from .interpreter import ClaudeClient, default_client

KEY_PREFIX = "sk-ant-"
_KEY_SHAPE = re.compile(r"[A-Za-z0-9_\-]{20,400}")


class SessionKey:
    def __init__(self, *, env_allowed: bool = False) -> None:
        self._env_allowed = env_allowed
        self._entered: str | None = None
        self._lock = threading.Lock()

    def set(self, raw: str) -> None:
        """Accept a key typed or pasted on the screen. The rejection never repeats what was typed."""
        key = raw.strip()
        if not key:
            raise Rejection("PolicyViolation", "APIキーが空です。")
        if not key.startswith(KEY_PREFIX) or not _KEY_SHAPE.fullmatch(key):
            # Most likely something else was pasted (mail text, a URL). Echoing it back would put
            # whatever it was into the page, so the message only says what a key looks like.
            raise Rejection(
                "PolicyViolation",
                f"APIキーの形式ではありません。Anthropic Consoleで作った「{KEY_PREFIX}」で始まるキーを貼り付けてください。",
            )
        with self._lock:
            self._entered = key

    def clear(self) -> None:
        with self._lock:
            self._entered = None

    def value(self) -> str | None:
        with self._lock:
            if self._entered is not None:
                return self._entered
        if self._env_allowed:
            return os.environ.get("ANTHROPIC_API_KEY") or None
        return None

    def available(self) -> bool:
        return self.value() is not None

    def source(self) -> str | None:
        """Where the key in use comes from, for the page: "screen", "env" or None."""
        with self._lock:
            if self._entered is not None:
                return "screen"
        if self._env_allowed and os.environ.get("ANTHROPIC_API_KEY"):
            return "env"
        return None


def client_factory(key: SessionKey) -> Callable[[], ClaudeClient]:
    """Build clients from this session's key only - never a silent fall back to the environment."""

    def build() -> ClaudeClient:
        value = key.value()
        if value is None:
            raise Rejection("ProviderUnavailable", "APIキーが設定されていません。トップ画面の「APIキーを入れる」から貼り付けてください。")
        return default_client(value)

    return build
