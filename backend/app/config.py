"""Runtime configuration for the NYX backend.

Everything is environment-driven so that the same container image can run in
demonstration mode (no AI key) or AI-assisted mode.  No secret values are
stored in this module; they are read from the process environment only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from functools import lru_cache

# ---------------------------------------------------------------------------
# Defaults (documented in README.md / .env.example)
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = "backend/data/nyx.sqlite3"
DEFAULT_AI_TIMEOUT_S = 12.0
DEFAULT_AI_MAX_RETRIES = 1
DEFAULT_AI_MAX_TOKENS = 1200
DEFAULT_AI_TEMPERATURE = 0.0
DEFAULT_AI_MIN_INTERVAL_MS = 0
DEFAULT_AI_CACHE_TTL_S = 900
DEFAULT_AI_CACHE_MAX_ENTRIES = 128


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None else value.strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name, "1" if default else "0").lower()
    return raw in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_path(name: str, default: str) -> str:
    """Resolve a path relative to the repository root when not absolute."""
    raw = _env(name, default)
    if not raw:
        raw = default
    candidate = os.path.abspath(raw)
    if os.path.isabs(raw) or os.path.exists(candidate):
        return candidate
    # backend/app/config.py -> the repository root is three directories up
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(repo_root, raw)


@dataclass(frozen=True)
class AiConfig:
    """Configuration of the optional OpenAI-compatible chat provider."""

    enabled: bool
    base_url: str
    api_key: str = field(repr=False, default="")
    model: str = ""
    timeout_s: float = DEFAULT_AI_TIMEOUT_S
    max_retries: int = DEFAULT_AI_MAX_RETRIES
    max_tokens: int = DEFAULT_AI_MAX_TOKENS
    temperature: float = DEFAULT_AI_TEMPERATURE
    min_interval_ms: int = DEFAULT_AI_MIN_INTERVAL_MS
    cache_ttl_s: float = DEFAULT_AI_CACHE_TTL_S
    cache_max_entries: int = DEFAULT_AI_CACHE_MAX_ENTRIES
    extra_headers: dict[str, str] = field(repr=False, default_factory=dict)

    @property
    def configured(self) -> bool:
        """True only when a key *and* endpoint are available.

        The provider abstraction deliberately treats "endpoint but no key" as
        unconfigured so that local demos never depend on network access.
        """
        return bool(self.enabled and self.base_url and self.api_key and self.model)

    def public_status(self) -> dict[str, object]:
        """Non-secret status snapshot exposed through the API."""
        reason: str | None = None
        if not self.enabled:
            reason = "AI assist is disabled by configuration (NYX_AI_ENABLED=0)."
        elif not self.base_url:
            reason = "No OpenAI-compatible endpoint configured (NYX_AI_BASE_URL)."
        elif not self.api_key:
            reason = "No API key configured (NYX_AI_API_KEY); using the local rules engine."
        elif not self.model:
            reason = "No model name configured (NYX_AI_MODEL)."
        return {
            "configured": self.configured,
            "enabled": self.enabled,
            "base_url_set": bool(self.base_url),
            "api_key_set": bool(self.api_key),
            "model": self.model or None,
            "timeout_s": self.timeout_s,
            "max_retries": self.max_retries,
            "max_tokens": self.max_tokens,
            "unavailable_reason": reason,
        }


@dataclass(frozen=True)
class Settings:
    """Immutable application settings, built once per process."""

    app_name: str = "NYX"
    app_title: str = "AI-Assisted Serverless Migration and Cloud Architecture Advisor"
    tagline: str = "Rethink your architecture."
    version: str = "1.0.0"
    environment: str = "development"
    db_path: str = DEFAULT_DB_PATH
    seed_examples: bool = True
    cors_origins: tuple[str, ...] = ()
    static_dir: str | None = None
    log_level: str = "INFO"
    ai: AiConfig = field(default_factory=lambda: AiConfig(enabled=False, base_url=""))

    @property
    def db_directory(self) -> str:
        return os.path.dirname(self.db_path) or "."


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    origins = tuple(
        item.strip()
        for item in _env(
            "NYX_CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173",
        ).split(",")
        if item.strip()
    )
    ai = AiConfig(
        # Enabled by default: the provider degrades gracefully when a key is
        # missing, and an explicit 0 lets a demo force deterministic mode.
        enabled=_env_bool("NYX_AI_ENABLED", True),
        base_url=_env("NYX_AI_BASE_URL").rstrip("/"),
        api_key=_env("NYX_AI_API_KEY"),
        model=_env("NYX_AI_MODEL"),
        timeout_s=_env_float("NYX_AI_TIMEOUT_S", DEFAULT_AI_TIMEOUT_S),
        max_retries=max(0, min(3, _env_int("NYX_AI_MAX_RETRIES", DEFAULT_AI_MAX_RETRIES))),
        max_tokens=_env_int("NYX_AI_MAX_TOKENS", DEFAULT_AI_MAX_TOKENS),
        temperature=_env_float("NYX_AI_TEMPERATURE", DEFAULT_AI_TEMPERATURE),
        min_interval_ms=max(0, _env_int("NYX_AI_MIN_INTERVAL_MS", DEFAULT_AI_MIN_INTERVAL_MS)),
        cache_ttl_s=_env_float("NYX_AI_CACHE_TTL_S", DEFAULT_AI_CACHE_TTL_S),
        cache_max_entries=_env_int("NYX_AI_CACHE_MAX_ENTRIES", DEFAULT_AI_CACHE_MAX_ENTRIES),
    )
    return Settings(
        environment=_env("NYX_ENV", "development"),
        version=_env("NYX_VERSION", "1.0.0"),
        db_path=_env_path("NYX_DB_PATH", DEFAULT_DB_PATH),
        seed_examples=_env_bool("NYX_SEED_EXAMPLES", True),
        cors_origins=origins,
        static_dir=_env("NYX_STATIC_DIR") or None,
        log_level=_env("NYX_LOG_LEVEL", "INFO").upper(),
        ai=ai,
    )


def settings_as_dict(settings: Settings | None = None) -> dict[str, object]:
    """Serialisable, secret-free view of the settings (used by /api/health)."""
    settings = settings or get_settings()
    payload = asdict(settings)
    payload.pop("ai", None)
    payload["ai"] = settings.ai.public_status()
    return payload
