"""API Key mode for OpenAI-compatible services (OpenAI, DeepSeek, Gemini) with the official OpenAI SDK.

The key comes from Windows Credential Manager. The client is built with the key and the provider's base
URL passed in, while no OPENAI_* environment variable is visible: none can swap the key, redirect the
request, or add organisation/project/custom headers (which would otherwise reach DeepSeek or Google too).
"""
from __future__ import annotations

import base64
import os
import threading
from typing import Callable

import openai

from .api_client import _short
from .claude_client import ENV_LOCK, ClaudeResult
from .providers import Provider

MAX_TOKENS = 4000  # one short line, with room for a reasoning model's thinking


def build_messages(system: str, text: str, jpeg: bytes | None = None) -> list[dict]:
    content: list[dict] = []
    if jpeg:  # images only in the user turn (DeepSeek rejects them anywhere else)
        url = "data:image/jpeg;base64," + base64.standard_b64encode(jpeg).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": url}})
    content.append({"type": "text", "text": text})
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


def clean_client(make_client: Callable[..., openai.OpenAI], **kwargs) -> openai.OpenAI:
    """Build the client while no OPENAI_* variable exists (the SDK reads them in its constructor)."""
    with ENV_LOCK:  # shared with child_env(), which must never see the variables half removed
        hidden = {k: os.environ.pop(k) for k in list(os.environ) if k.upper().startswith("OPENAI_")}
        try:
            return make_client(**kwargs)
        finally:
            os.environ.update(hidden)


class OpenAICompatCall:
    """Same surface as the other calls for the controller: cancelled, cancel() and ask()."""

    def __init__(self, provider: Provider, timeout: float, load_key: Callable[[], str | None],
                 make_client: Callable[..., openai.OpenAI] = openai.OpenAI) -> None:
        self.provider = provider
        self.timeout = timeout
        self._load_key = load_key
        self._make_client = make_client
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._client: openai.OpenAI | None = None

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
            except Exception:  # noqa: BLE001 - best effort; the reply is dropped anyway
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
        client = clean_client(self._make_client, api_key=key, base_url=self.provider.base_url,
                              organization=None, project=None, timeout=self.timeout, max_retries=1)
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

    def _request(self, client: openai.OpenAI, key: str, model: str, system: str, text: str,
                 jpeg: bytes | None) -> ClaudeResult:
        params: dict = {"model": model, "messages": build_messages(system, text, jpeg)}
        # OpenAI's current models only take max_completion_tokens; the compatible endpoints take max_tokens.
        params["max_completion_tokens" if self.provider.id == "openai" else "max_tokens"] = MAX_TOKENS
        name = self.provider.company
        try:
            response = client.chat.completions.create(**params)
        except openai.AuthenticationError:
            return ClaudeResult(False, error=f"{name} API Key 无效（401）", bad_api_key=True)
        except openai.PermissionDeniedError:
            return ClaudeResult(False, error=f"{name} API Key 没有权限（403）", bad_api_key=True)
        except openai.BadRequestError as exc:
            if "api key" in str(exc.message).lower():  # Gemini answers a wrong key with 400, not 401
                return ClaudeResult(False, error=f"{name} API Key 无效（400）", bad_api_key=True)
            return ClaudeResult(False, error=f"{name} API 错误 400：{_short(exc.message, key)}")
        except openai.RateLimitError as exc:
            return ClaudeResult(False, error=f"{name} 请求太频繁或额度不足（429）：{_short(exc.message, key)}")
        except openai.APITimeoutError:
            if self.cancelled:
                return ClaudeResult(False, error="cancelled", cancelled=True)
            return ClaudeResult(False, error="timeout", timed_out=True)
        except openai.APIStatusError as exc:
            return ClaudeResult(False, error=f"{name} API 错误 {exc.status_code}：{_short(exc.message, key)}")
        except openai.APIError as exc:  # connection problems, or the client closed by cancel()
            if self.cancelled:
                return ClaudeResult(False, error="cancelled", cancelled=True)
            return ClaudeResult(False, error=f"连不上 {name} API：{_short(exc, key)}")
        if self.cancelled:
            return ClaudeResult(False, error="cancelled", cancelled=True)
        choice = response.choices[0] if response.choices else None
        if choice is None:
            return ClaudeResult(False, error=f"{name} API 返回了空回复")
        refusal = getattr(choice.message, "refusal", None) if choice.message else None
        if choice.finish_reason == "content_filter" or refusal:  # OpenAI may refuse with message.refusal instead
            return ClaudeResult(False, error="模型拒绝了这次请求")
        reply = (choice.message.content or "").strip() if choice.message else ""
        if not reply:
            return ClaudeResult(False, error=f"{name} API 返回了空回复（{choice.finish_reason}）")
        return ClaudeResult(True, text=reply)
