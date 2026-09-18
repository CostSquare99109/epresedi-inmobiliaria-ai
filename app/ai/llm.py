"""LLM provider abstraction.

NVIDIAProvider talks to NVIDIA Build (OpenAI-compatible /v1/chat/completions) with
structured tool calling. The provider is swappable: implement LLMProvider to change
vendors without touching the rest of the app (see docs/ai.md).
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)


class LLMError(Exception):
    """Raised on provider failure. Never swallowed into a fabricated answer."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind  # timeout | auth | rate_limit | server | network | unknown


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    finish_reason: str = ""
    usage: dict[str, int] = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str
    model: str

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> LLMResponse: ...


class NVIDIAProvider:
    """NVIDIA Build via OpenAI-compatible API. Credentials come from .env only."""

    name = "nvidia"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        s = get_settings()
        self._api_key = api_key or s.NVIDIA_API_KEY
        self.model = model or s.NVIDIA_MODEL
        self._base_url = s.NVIDIA_BASE_URL.rstrip("/")
        self._timeout = s.NVIDIA_TIMEOUT

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        started = time.monotonic()
        max_retries = 3
        resp = None
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        f"{self._base_url}/chat/completions", json=payload, headers=headers
                    )
            except httpx.TimeoutException as e:
                last_exc = e
                resp = None
            except httpx.HTTPError as e:
                raise LLMError("network", f"NVIDIA network error: {e}") from e

            if resp is not None and resp.status_code < 500:
                break
            if attempt < max_retries:
                await asyncio.sleep(1.5 * (2 ** attempt))
                continue
            if resp is None:
                raise LLMError(
                    "timeout",
                    f"NVIDIA request timed out after {self._timeout}s (retried {max_retries}x): {last_exc}",
                ) from last_exc

        if resp.status_code in (401, 403):
            raise LLMError("auth", "NVIDIA rejected credentials (HTTP 401/403). Check NVIDIA_API_KEY.")
        if resp.status_code == 429:
            raise LLMError("rate_limit", "NVIDIA rate limit reached (HTTP 429). Try again later.")
        if resp.status_code >= 500:
            raise LLMError("server", f"NVIDIA server error (HTTP {resp.status_code}) after {max_retries} retries.")
        if resp.status_code >= 400:
            raise LLMError("unknown", f"NVIDIA request failed (HTTP {resp.status_code}).")

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}
        tool_calls = [
            ToolCall(
                id=tc.get("id", f"call_{i}"),
                name=tc.get("function", {}).get("name", ""),
                arguments=_safe_json(tc.get("function", {}).get("arguments")),
            )
            for i, tc in enumerate(msg.get("tool_calls") or [])
        ]
        usage = data.get("usage") or {}
        log.info(
            "llm_call provider=nvidia model=%s latency_ms=%.0f finish=%s",
            self.model,
            (time.monotonic() - started) * 1000,
            choice.get("finish_reason", ""),
        )
        return LLMResponse(
            content=msg.get("content") or "",
            tool_calls=tool_calls,
            model=data.get("model", self.model),
            finish_reason=choice.get("finish_reason", ""),
            usage={
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            },
        )


def _safe_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def get_llm_provider() -> LLMProvider | None:
    """Returns the configured provider, or None when running deterministic mode."""
    s = get_settings()
    if s.llm_is_nvidia and s.nvidia_configured:
        return NVIDIAProvider()
    return None
