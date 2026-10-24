"""Validated settings and environment loading for Atlas.

Secrets are read from environment variables or a local ``.env`` (git-ignored).
Every failure raises :class:`ConfigurationError`, whose message names the
offending variable but never contains a secret value (PRD FR-02, US-501).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from atlas.errors import ConfigurationError

Mode = Literal["offline", "live"]

DEFAULT_MODE: Mode = "offline"
DEFAULT_MAX_ITERATIONS = 8
DEFAULT_MAX_RESULTS = 5
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_DEADLINE_SECONDS = 120.0

ENV_MODE = "ATLAS_MODE"
ENV_MODEL = "ATLAS_MODEL"
ENV_MAX_ITERATIONS = "ATLAS_MAX_ITERATIONS"
ENV_MAX_RESULTS = "ATLAS_MAX_RESULTS"
ENV_TIMEOUT = "ATLAS_TIMEOUT_SECONDS"
ENV_DEADLINE = "ATLAS_DEADLINE_SECONDS"
ENV_OPENAI_KEY = "OPENAI_API_KEY"
ENV_TAVILY_KEY = "TAVILY_API_KEY"

#: Variables that must hold a non-empty value for the application to run live.
LIVE_REQUIRED_ENV_VARS = (ENV_OPENAI_KEY, ENV_TAVILY_KEY, ENV_MODEL)

_NUMERIC_FIELDS = (
    (ENV_MAX_ITERATIONS, "max_iterations", int),
    (ENV_MAX_RESULTS, "max_results", int),
    (ENV_TIMEOUT, "timeout_seconds", float),
    (ENV_DEADLINE, "deadline_seconds", float),
)

_SECRET_FIELDS = (
    (ENV_OPENAI_KEY, "openai_api_key"),
    (ENV_TAVILY_KEY, "tavily_api_key"),
)


def _is_present(value: str | None) -> bool:
    """True when a variable holds a non-placeholder, non-empty value."""
    if value is None:
        return False
    stripped = value.strip()
    if not stripped:
        return False
    return not stripped.lower().startswith("replace-with")


class Settings(BaseModel):
    """Frozen, validated application settings.

    ``SecretStr`` is used for credentials so that logging, ``repr()``, tracebacks,
    and report output can never accidentally reveal them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    mode: Mode = DEFAULT_MODE
    #: No default on purpose: the project does not assume any model ID exists.
    model_name: str | None = None
    max_iterations: int = Field(default=DEFAULT_MAX_ITERATIONS, ge=1, le=64)
    max_results: int = Field(default=DEFAULT_MAX_RESULTS, ge=1, le=50)
    timeout_seconds: float = Field(default=DEFAULT_TIMEOUT_SECONDS, gt=0.0, le=600.0)
    deadline_seconds: float = Field(default=DEFAULT_DEADLINE_SECONDS, gt=0.0, le=3600.0)
    openai_api_key: SecretStr | None = None
    tavily_api_key: SecretStr | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Build settings from a mapping (``os.environ`` when omitted).

        Raises:
            ConfigurationError: on an unknown mode, a malformed or out-of-range
                number, or missing credentials required by live mode.
        """
        env = os.environ if environ is None else environ
        data: dict[str, object] = {}

        raw_mode = env.get(ENV_MODE)
        if raw_mode is not None and raw_mode.strip():
            mode = raw_mode.strip().lower()
            if mode not in ("offline", "live"):
                raise ConfigurationError(f"{ENV_MODE} must be 'offline' or 'live'.")
            data["mode"] = mode

        raw_model = env.get(ENV_MODEL)
        if raw_model is not None and raw_model.strip():
            data["model_name"] = raw_model.strip()

        for env_name, field_name, caster in _NUMERIC_FIELDS:
            raw = env.get(env_name)
            if raw is None or not raw.strip():
                continue
            try:
                data[field_name] = caster(raw.strip())
            except ValueError:
                raise ConfigurationError(f"{env_name} must be a number.") from None

        for env_name, field_name in _SECRET_FIELDS:
            raw = env.get(env_name)
            if _is_present(raw):
                data[field_name] = SecretStr(raw.strip())

        try:
            settings = cls.model_validate(data)
        except ValidationError as exc:
            raise ConfigurationError(_summarize(exc)) from exc

        if settings.mode == "live":
            missing = [name for name in LIVE_REQUIRED_ENV_VARS if not _is_present(env.get(name))]
            if missing:
                raise ConfigurationError("live mode requires " + ", ".join(missing) + " to be set.")

        return settings


def _summarize(exc: ValidationError) -> str:
    """Render field-level configuration errors without echoing raw values."""
    parts = [
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
    ]
    return "invalid configuration: " + "; ".join(parts)
