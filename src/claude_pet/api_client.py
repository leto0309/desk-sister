"""Optional API Key mode: the official Anthropic SDK, billed to the user's own API key.

The key comes from Windows Credential Manager. The client is given the key and the base URL
explicitly, so no ANTHROPIC_* environment variable can swap the key or send it to another host.
"""
from __future__ import annotations

import base64
import re
import threading
from typing import Callable

import anthropic

from . import credstore
from .claude_client import ClaudeResult

API_MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5"}
API_BASE_URL = "https://api.anthropic.com"
MAX_TOKENS = 4000  # one short line, with room for adaptive thinking
EFFORT = "low"  # a one-line remark: the cheapest effort is plenty
_FALLBACK_BETA = "server-side-fallback-2026-07-01"  # Sonnet 5.5: a declined request is retried server-side
_KEY_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def looks_like_key(text: str) -> bool:
    """A plausible key (no spaces or odd characters), so a typo is caught before anything is saved."""
    return 20 <= len(text) <= 512 and set(text) <= _KEY_CHARS


def build_content(text: str, jpeg: bytes | None = None) -> list[dict]:
    content: list[dict] = []
    if jpeg:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(jpeg).decode("ascii")},
        })
    content.append({"type": "text", "text": text})
    return content


_KEY_LIKE = re.compile(r"sk-ant-[A-Za-z0-9_-]+")


def _short(message: object, key: str = "", limit: int = 120) -> str:
    """Server/SDK text for the log and the status line: the key (or anything key-like) never survives."""
    text = " ".join(str(message or "").split())
    if key:
        text = text.replace(key, "[已隐藏]")
    text = _KEY_LIKE.sub("[已隐藏]", text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ApiCall:
    """Same surface as claude_client.ClaudeCall for the controller: cancelled, cancel() and ask().

    cancel() may come from the UI thread at any moment; the reply of a cancelled call is never used.
    """

    def __init__(self, timeout: float, load_key: Callable[[], str | None] = credstore.load_secret,
                 make_client: Callable[..., anthropic.Anthropic] = anthropic.Anthropic) -> None:
        self.timeout = timeout
        self._load_key = load_key
        self._make_client = make_client
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._client: anthropic.Anthropic | None = None

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            client = self._client
        if client is not None:
            try:
                client.close()  # ends the request in flight
            except Exception:  # noqa: BLE001 - closing is best effort; the reply is dropped anyway
                pass

    def ask(self, model: str, system: str, text: str, jpeg: bytes | None = None) -> ClaudeResult:
        if self.cancelled:
            return ClaudeResult(False, error="cancelled", cancelled=True)
        try:
            key = self._load_key()
        except OSError as exc:
            return ClaudeResult(False, error=f"读取 API Key 失败：{exc}")
        if not key:
            return ClaudeResult(False, error="还没有设置 API Key", no_api_key=True)
        client = self._make_client(api_key=key, base_url=API_BASE_URL, timeout=self.timeout, max_retries=1)
        with self._lock:
            self._client = client
        try:
            if self.cancelled:
                return ClaudeResult(False, error="cancelled", cancelled=True)
            return self._request(client, key, model, system, text, jpeg)
        finally:
            with self._lock:
                self._client = None
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass

    def _request(self, client: anthropic.Anthropic, key: str, model: str, system: str, text: str,
                 jpeg: bytes | None) -> ClaudeResult:
        model_id = API_MODELS.get(model, API_MODELS["haiku"])
        params = {
            "model": model_id,
            "max_tokens": MAX_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": build_content(text, jpeg)}],
            "output_config": {"effort": EFFORT},
        }
        try:
            if model_id == API_MODELS["sonnet"]:
                response = client.beta.messages.create(**params, betas=[_FALLBACK_BETA], fallbacks="default")
            else:
                response = client.messages.create(**params)
        except anthropic.AuthenticationError:
            return ClaudeResult(False, error="API Key 无效（401）", bad_api_key=True)
        except anthropic.PermissionDeniedError:
            return ClaudeResult(False, error="API Key 没有权限（403）", bad_api_key=True)
        except anthropic.RateLimitError:
            return ClaudeResult(False, error="API 请求太频繁（429），稍后再试")
        except anthropic.APITimeoutError:
            if self.cancelled:
                return ClaudeResult(False, error="cancelled", cancelled=True)
            return ClaudeResult(False, error="timeout", timed_out=True)
        except anthropic.APIStatusError as exc:
            return ClaudeResult(False, error=f"API 错误 {exc.status_code}：{_short(exc.message, key)}")
        except anthropic.APIError as exc:  # connection problems, or the client closed by cancel()
            if self.cancelled:
                return ClaudeResult(False, error="cancelled", cancelled=True)
            return ClaudeResult(False, error=f"连不上 Anthropic API：{_short(exc, key)}")
        if self.cancelled:
            return ClaudeResult(False, error="cancelled", cancelled=True)
        if response.stop_reason == "refusal":
            return ClaudeResult(False, error="模型拒绝了这次请求")
        reply = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        if not reply.strip():
            return ClaudeResult(False, error=f"API 返回了空回复（{response.stop_reason}）")
        return ClaudeResult(True, text=reply)
