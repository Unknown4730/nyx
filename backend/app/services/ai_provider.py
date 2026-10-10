"""Optional AI integration behind a provider abstraction.

Guarantees this module is responsible for:

* the business logic never imports a provider SDK — it only sees
  `ChatCompletionProvider.complete_json()`;
* the model can only propose `AiExtractionProposal` values, which are validated
  field by field before anything uses them;
* every failure mode (missing config, timeout, rate limit, non-JSON, empty
  content, schema-invalid, unexpected keys) resolves to a status code and a
  human-readable note, never to an exception that escapes the pipeline;
* a small result cache keyed by model+prompt, plus an optional minimum interval
  between calls, so repeated analyses cannot hammer an endpoint.

No API key is ever read by the frontend; configuration is server-side only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.config import AiConfig, get_settings
from app.schemas.ai import ALLOWED_SIGNAL_KEYS, JSON_SCHEMA
from app.schemas.ai import AiExtractionProposal
from app.schemas.common import AiAttemptStatus, EngineMode
from app.schemas.requirements import ApplicationRequirements

logger = logging.getLogger("nyx.ai")

FENCE_RE = re.compile(r"```(?:json)?\s*(?P<body>.*?)```", re.DOTALL | re.IGNORECASE)
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
RATE_LIMIT_STATUS = 429


class ProviderTransport(Protocol):
    """Minimal HTTP surface; tests inject a stub instead of a network client."""

    def post_json(self, url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> tuple[int, dict[str, Any], str]:
        ...


class HttpxTransport:
    """Default transport using a shared `httpx.Client`."""

    def __init__(self) -> None:
        self._client = None

    def _ensure(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(trust_env=False)
        return self._client

    def post_json(self, url, headers, payload, timeout):  # type: ignore[no-untyped-def]

        client = self._ensure()
        response = client.post(url, headers=headers, json=payload, timeout=timeout)
        try:
            body = response.json()
            if not isinstance(body, dict):
                body = {"_raw": body}
        except (ValueError, json.JSONDecodeError):
            body = {"_text": response.text[:500]}
        return response.status_code, body, response.text[:500]

    def close(self) -> None:  # pragma: no cover - cleanup helper
        if self._client is not None:
            self._client.close()
            self._client = None


@dataclass
class CompletionOutcome:
    status: AiAttemptStatus
    raw: str | None = None
    proposal: AiExtractionProposal | None = None
    attempts: int = 0
    latency_ms: int = 0
    note: str = ""
    model: str | None = None
    provider: str = "none"
    rejected_fields: list[str] = field(default_factory=list)
    cached: bool = False

    @property
    def succeeded(self) -> bool:
        return self.status in {AiAttemptStatus.SUCCESS, AiAttemptStatus.CACHED} and self.proposal is not None


class ChatCompletionProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def complete_json(self, *, system: str, user: str) -> CompletionOutcome: ...


class NullProvider:
    """Used when no endpoint/key is configured. Always cheap, always safe."""

    name = "none"

    def available(self) -> bool:
        return False

    def complete_json(self, *, system: str, user: str) -> CompletionOutcome:
        return CompletionOutcome(
            status=AiAttemptStatus.NOT_CONFIGURED,
            note="No OpenAI-compatible endpoint and API key are configured, so NYX used its local rules engine.",
            provider=self.name,
        )


class OpenAICompatibleProvider:
    """Talks to any OpenAI-compatible `/chat/completions` endpoint."""

    name = "openai-compatible"

    def __init__(
        self,
        config: AiConfig,
        transport: ProviderTransport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or HttpxTransport()
        self._lock = threading.Lock()
        self._last_call = 0.0
        self._cache: dict[str, tuple[float, CompletionOutcome]] = {}

    # ------------------------------------------------------------------ public

    def available(self) -> bool:
        return self.config.configured

    def complete_json(self, *, system: str, user: str) -> CompletionOutcome:
        if not self.available():
            return NullProvider().complete_json(system=system, user=user)

        key = self._cache_key(system, user)
        cached = self._cache_get(key)
        if cached is not None:
            return CompletionOutcome(
                status=AiAttemptStatus.CACHED,
                raw=cached.raw,
                proposal=cached.proposal,
                attempts=0,
                latency_ms=0,
                note="Reused a validated response from the in-process cache.",
                model=self.config.model,
                provider=self.name,
                cached=True,
            )

        self._throttle()
        started = time.perf_counter()
        attempt = 0
        last_status = AiAttemptStatus.FAILED_PROVIDER
        last_note = "The provider did not return."
        last_raw: str | None = None
        rejected: list[str] = []

        while attempt <= self.config.max_retries:
            attempt += 1
            try:
                status, body, text = self.transport.post_json(
                    self._endpoint(),
                    self._headers(),
                    self._payload(system, user),
                    self.config.timeout_s,
                )
            except TimeoutError as exc:
                last_status, last_note = AiAttemptStatus.FAILED_TIMEOUT, f"Request timed out: {exc}"
                if attempt <= self.config.max_retries:
                    time.sleep(min(0.5 * attempt, 1.0))
                    continue
                break
            except Exception as exc:  # network/DNS/refused — never propagate
                last_status = AiAttemptStatus.FAILED_PROVIDER
                last_note = f"Provider request failed: {type(exc).__name__}: {str(exc)[:180]}"
                if attempt <= self.config.max_retries:
                    time.sleep(min(0.5 * attempt, 1.0))
                    continue
                break

            last_raw = text
            if status in RETRY_STATUS:
                last_status = (
                    AiAttemptStatus.FAILED_RATE_LIMIT if status == RATE_LIMIT_STATUS else AiAttemptStatus.FAILED_PROVIDER
                )
                detail = _error_message(body)
                last_note = f"Provider returned HTTP {status}" + (f": {detail}" if detail else ".")
                retry_after = _retry_after_seconds(body)
                if attempt <= self.config.max_retries:
                    time.sleep(min(retry_after if retry_after else 0.5 * attempt, 1.5))
                    continue
                break

            if status >= 400:
                last_status = AiAttemptStatus.FAILED_PROVIDER
                last_note = f"Provider returned HTTP {status}: {_error_message(body) or text[:160]}"
                break

            content, note = _extract_content(body)
            if content is not None and not content.strip():
                # A well-formed envelope with nothing inside is its own failure mode:
                # reporting it as "invalid JSON" would hide the real cause.
                last_status = AiAttemptStatus.FAILED_EMPTY
                last_note = "The provider returned an empty message body."
                break
            if content is None:
                last_status = AiAttemptStatus.FAILED_EMPTY
                last_note = note
                break

            parsed, note = parse_model_json(content)
            if parsed is None:
                last_status = AiAttemptStatus.FAILED_VALIDATION
                last_note = note
                if attempt <= self.config.max_retries:
                    continue
                break

            try:
                proposal = AiExtractionProposal.model_validate(parsed)
            except Exception as exc:
                last_status = AiAttemptStatus.FAILED_VALIDATION
                last_note = f"Model output did not match the required schema: {str(exc)[:220]}"
                rejected = _rejected_field_names(str(exc))
                if attempt <= self.config.max_retries:
                    continue
                break

            elapsed = int((time.perf_counter() - started) * 1000)
            outcome = CompletionOutcome(
                status=AiAttemptStatus.SUCCESS,
                raw=content,
                proposal=proposal,
                attempts=attempt,
                latency_ms=elapsed,
                note="Model output validated against the extraction schema.",
                model=self.config.model,
                provider=self.name,
                rejected_fields=rejected,
            )
            self._cache_put(key, outcome)
            return outcome

        return CompletionOutcome(
            status=last_status,
            raw=last_raw,
            attempts=attempt,
            latency_ms=int((time.perf_counter() - started) * 1000),
            note=last_note,
            model=self.config.model,
            provider=self.name,
            rejected_fields=rejected,
        )

    # ----------------------------------------------------------------- helpers

    def _endpoint(self) -> str:
        base = self.config.base_url
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        headers.update(self.config.extra_headers)
        return headers

    def _payload(self, system: str, user: str) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "response_format": {"type": "json_object"},
        }

    def _throttle(self) -> None:
        if not self.config.min_interval_ms:
            return
        with self._lock:
            wait = self.config.min_interval_ms / 1000.0 - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(min(wait, 2.0))
            self._last_call = time.monotonic()

    def _cache_key(self, system: str, user: str) -> str:
        material = "\n".join([self.config.model, system, user, json.dumps(JSON_SCHEMA, sort_keys=True)])
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> CompletionOutcome | None:
        if self.config.cache_ttl_s <= 0:
            return None
        entry = self._cache.get(key)
        if not entry:
            return None
        expires_at, outcome = entry
        if expires_at < time.monotonic():
            self._cache.pop(key, None)
            return None
        return outcome

    def _cache_put(self, key: str, outcome: CompletionOutcome) -> None:
        if self.config.cache_ttl_s <= 0:
            return
        with self._lock:
            if len(self._cache) >= self.config.cache_max_entries:
                self._cache.pop(next(iter(self._cache)), None)
            self._cache[key] = (time.monotonic() + self.config.cache_ttl_s, outcome)


# ---------------------------------------------------------------------------
# Prompt construction and tolerant parsing
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = f"""You are the requirement-extraction component of NYX, a cloud architecture advisor.

You receive a natural-language description of a software application. Your ONLY job is to
classify the requirements. You must not design an architecture, must not name cloud services,
must not propose security findings, costs or migration steps, and must not invent facts that are
not stated or clearly implied.

Return one JSON object and nothing else, matching exactly this schema:
{json.dumps(JSON_SCHEMA, indent=0, sort_keys=True)}

Rules:
1. Omit a key when the description does not support it. Never guess a number to be helpful.
2. "signals" may only contain these keys: {", ".join(sorted(ALLOWED_SIGNAL_KEYS))}.
3. Booleans in "signals" must be real booleans; counts and durations must be numbers.
4. Put anything you had to assume into "assumptions" as a short sentence.
5. Put anything critical but missing into "open_questions" as a question for the user.
6. Prefer fewer, better-supported fields over a complete-looking guess."""


def build_user_prompt(requirements: ApplicationRequirements, known: dict[str, Any]) -> str:
    stated = {key: value for key, value in known.items() if value not in (None, [], "")}
    return (
        "Application name: " + requirements.name + "\n"
        "Description written by the user:\n" + requirements.description + "\n"
        + ("Additional technical notes:\n" + requirements.additional_requirements + "\n"
           if requirements.additional_requirements else "")
        + "Fields already provided by the user (do not contradict these):\n"
        + json.dumps(stated, indent=2, default=str)
        + "\n\nReturn the JSON object now."
    )


def parse_model_json(content: str) -> tuple[dict[str, Any] | None, str]:
    """Tolerant JSON extraction from a chat completion."""
    text = (content or "").strip()
    if not text:
        return None, "The provider returned an empty message body."
    fence = FENCE_RE.search(text)
    if fence:
        text = fence.group("body").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None, "The provider response was not JSON, so it was discarded."
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            return None, f"The provider response was not valid JSON ({exc.msg} at position {exc.pos})."
    if not isinstance(parsed, dict):
        return None, "The provider returned JSON that was not an object, so it was discarded."
    return parsed, ""


def _extract_content(body: dict[str, Any]) -> tuple[str | None, str]:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return None, "The provider response contained no choices."
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content") or first.get("text")
    if isinstance(content, list):  # some gateways return content parts
        content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    if content is None or str(content).strip() == "":
        return None, "The provider returned an empty completion (possibly an empty or refused response)."
    return str(content), ""


def _error_message(body: dict[str, Any]) -> str:
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("message", ""))[:200]
    return ""


def _retry_after_seconds(body: dict[str, Any]) -> float | None:
    retry_after = body.get("retry_after") or (body.get("error") or {}).get("retry_after") if isinstance(body, dict) else None
    try:
        return float(retry_after) if retry_after is not None else None
    except (TypeError, ValueError):
        return None


def _rejected_field_names(message: str) -> list[str]:
    found = re.findall(r"\n([a-z_]+)\s*:\s*", message)
    extra = re.findall(r"Input should be[^,]*\n([a-z_]+)", message)
    return list(dict.fromkeys(found + extra))[:10]


# ---------------------------------------------------------------------------
# Factory used by the pipeline
# ---------------------------------------------------------------------------


def build_provider(config: AiConfig | None = None, transport: ProviderTransport | None = None) -> ChatCompletionProvider:
    config = config or get_settings().ai
    if not config.configured:
        logger.debug("AI provider not configured; NYX will use deterministic extraction only.")
        return NullProvider()
    return OpenAICompatibleProvider(config, transport=transport)


def engine_mode_for(outcome: CompletionOutcome) -> EngineMode:
    return EngineMode.AI_ASSISTED if outcome.succeeded else EngineMode.DETERMINISTIC


__all__ = [
    "AiAttemptStatus",
    "CompletionOutcome",
    "ChatCompletionProvider",
    "HttpxTransport",
    "NullProvider",
    "OpenAICompatibleProvider",
    "SYSTEM_PROMPT",
    "build_provider",
    "build_user_prompt",
    "engine_mode_for",
    "parse_model_json",
]
