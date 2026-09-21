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
    # Set when the provider sent arguments that are not valid JSON. The loop
    # reports this back to the model instead of silently calling with {}.
    arguments_error: str = ""


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
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse: ...


class NVIDIAProvider:
    """NVIDIA Build via OpenAI-compatible API. Credentials come from .env only."""

    name = "nvidia"

    # Supported reasoning effort levels per OpenAI API spec
    SUPPORTED_REASONING_LEVELS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh"})

    def __init__(self, api_key: str | None = None, model: str | None = None):
        s = get_settings()
        self._api_key = api_key or s.NVIDIA_API_KEY
        self.model = model or s.NVIDIA_MODEL
        self._base_url = s.NVIDIA_BASE_URL.rstrip("/")
        self._timeout = s.NVIDIA_TIMEOUT
        self._reasoning_level = self._normalize_reasoning_level(s.LLM_REASONING_LEVEL)

    def _normalize_reasoning_level(self, level: str) -> str | None:
        """Normalize and validate reasoning level. Returns None if disabled/unsupported."""
        if not level:
            return None
        normalized = level.strip().lower()
        if normalized in ("none", "off", "disabled", "false", "0"):
            return None
        if normalized in self.SUPPORTED_REASONING_LEVELS:
            return normalized
        log.warning(
            "reasoning_level_invalid level=%r supported=%s defaulting_to_high",
            level, sorted(self.SUPPORTED_REASONING_LEVELS),
        )
        return "high"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self._reasoning_level:
            payload["reasoning_effort"] = self._reasoning_level
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if response_format:
            payload["response_format"] = response_format
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        started = time.monotonic()
        max_retries = max(0, int(get_settings().LLM_RETRY_MAX))
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

            retryable = resp is None or resp.status_code >= 500 or resp.status_code == 429
            if not retryable:
                break
            if attempt < max_retries:
                delay = 1.5 * (2 ** attempt)
                if resp is not None and resp.status_code == 429:
                    try:
                        delay = min(float(resp.headers.get("retry-after", delay)), 30.0)
                    except (TypeError, ValueError):
                        pass
                log.warning(
                    "llm_retry provider=nvidia attempt=%s/%s status=%s delay_s=%.1f",
                    attempt + 1, max_retries,
                    None if resp is None else resp.status_code, delay,
                )
                await asyncio.sleep(delay)
                continue
            if resp is None:
                raise LLMError(
                    "timeout",
                    f"NVIDIA request timed out after {self._timeout}s (retried {max_retries}x): {last_exc}",
                ) from last_exc

        if resp.status_code in (401, 403):
            raise LLMError("auth", "NVIDIA rejected credentials (HTTP 401/403). Check NVIDIA_API_KEY.")
        if resp.status_code == 404:
            raise LLMError("model_not_found", f"NVIDIA model not found (HTTP 404). Check NVIDIA_MODEL.")
        if resp.status_code == 429:
            raise LLMError("rate_limit", "NVIDIA rate limit reached (HTTP 429). Try again later.")
        if resp.status_code >= 500:
            raise LLMError("server", f"NVIDIA server error (HTTP {resp.status_code}) after {max_retries} retries.")
        if resp.status_code >= 400:
            raise LLMError("unknown", f"NVIDIA request failed (HTTP {resp.status_code}).")

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}
        tool_calls = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            raw_args = tc.get("function", {}).get("arguments")
            arguments, arg_error = _parse_tool_arguments(raw_args)
            tool_calls.append(ToolCall(
                id=tc.get("id", f"call_{i}"),
                name=tc.get("function", {}).get("name", ""),
                arguments=arguments,
                arguments_error=arg_error,
            ))
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


def _parse_tool_arguments(raw: Any) -> tuple[dict[str, Any], str]:
    """Returns (arguments, error). Malformed JSON is reported, never guessed."""
    if raw is None or raw == "":
        return {}, ""
    if isinstance(raw, dict):
        return raw, ""
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            return {}, f"argumentos JSON inválidos: {e.msg}"
        if isinstance(parsed, dict):
            return parsed, ""
        return {}, "los argumentos deben ser un objeto JSON"
    return {}, "argumentos con tipo no soportado"


class LLMProviderChain:
    """Ordered provider fallback: NVIDIA → otro proveedor → error honesto.

    El backend no inventa respuestas cuando todos los proveedores fallan: la
    excepción LLMError sube y el orquestador cae al modo determinista (failsafe).
    """

    name = "chain"

    def __init__(self, providers: list[LLMProvider]):
        if not providers:
            raise ValueError("LLMProviderChain requiere al menos un proveedor")
        self._providers = list(providers)
        self.model = ",".join(getattr(p, "model", "") or p.name for p in self._providers)

    @property
    def providers(self) -> list[str]:
        return [p.name for p in self._providers]

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        last_error: LLMError | None = None
        for provider in self._providers:
            try:
                return await provider.chat(
                    messages, tools=tools, temperature=temperature,
                    max_tokens=max_tokens, response_format=response_format,
                )
            except LLMError as e:
                last_error = e
                log.warning(
                    "llm_provider_fallback provider=%s kind=%s error=%s",
                    provider.name, e.kind, e,
                )
                continue
        assert last_error is not None
        raise last_error


def _build_provider(name: str) -> LLMProvider | None:
    s = get_settings()
    if name == "nvidia":
        return NVIDIAProvider() if s.nvidia_configured else None
    return None


def build_llm_providers() -> list[LLMProvider]:
    """Configured provider chain (LLM_PROVIDERS, only .env). Unknown → ignored."""
    s = get_settings()
    names = [n.strip().lower() for n in (s.LLM_PROVIDERS or "").split(",") if n.strip()]
    providers = [p for p in (_build_provider(n) for n in names) if p is not None]
    if not providers and s.llm_is_nvidia and s.nvidia_configured:
        providers = [NVIDIAProvider()]
    return providers


def get_llm_provider() -> LLMProvider | None:
    """Returns the configured provider chain, or None for deterministic mode."""
    s = get_settings()
    if not s.llm_is_nvidia:
        return None
    providers = build_llm_providers()
    if not providers:
        return None
    if len(providers) == 1:
        return providers[0]
    return LLMProviderChain(providers)
