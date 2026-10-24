"""Tests for validated configuration and environment loading (US-102, US-501)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atlas.config import (
    DEFAULT_DEADLINE_SECONDS,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MAX_RESULTS,
    DEFAULT_TIMEOUT_SECONDS,
    ENV_DEADLINE,
    ENV_MAX_ITERATIONS,
    ENV_MAX_RESULTS,
    ENV_MODE,
    ENV_MODEL,
    ENV_OPENAI_KEY,
    ENV_TAVILY_KEY,
    ENV_TIMEOUT,
    Settings,
)
from atlas.errors import ConfigurationError

SECRET = "sk-super-secret-value-do-not-leak"


def test_defaults_are_used_when_env_is_empty() -> None:
    settings = Settings.from_env({})

    assert settings.mode == "offline"
    assert settings.max_iterations == DEFAULT_MAX_ITERATIONS
    assert settings.max_results == DEFAULT_MAX_RESULTS
    assert settings.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
    assert settings.deadline_seconds == DEFAULT_DEADLINE_SECONDS
    assert settings.model_name is None
    assert settings.openai_api_key is None


def test_documented_default_deadline_is_120_seconds() -> None:
    assert Settings.from_env({}).deadline_seconds == 120.0


def test_documented_default_iteration_bound_is_eight() -> None:
    assert Settings.from_env({}).max_iterations == 8


def test_valid_overrides_are_parsed() -> None:
    settings = Settings.from_env(
        {
            ENV_MODE: "live",
            ENV_MODEL: "example-model",
            ENV_MAX_ITERATIONS: "4",
            ENV_MAX_RESULTS: "3",
            ENV_TIMEOUT: "12.5",
            ENV_DEADLINE: "45",
            ENV_OPENAI_KEY: SECRET,
            ENV_TAVILY_KEY: "tvly-placeholder",
        }
    )

    assert settings.mode == "live"
    assert settings.model_name == "example-model"
    assert settings.max_iterations == 4
    assert settings.max_results == 3
    assert settings.timeout_seconds == 12.5
    assert settings.deadline_seconds == 45.0
    assert settings.openai_api_key is not None


def test_mode_is_case_insensitive() -> None:
    assert Settings.from_env({ENV_MODE: "OFFLINE"}).mode == "offline"


def test_blank_env_values_fall_back_to_defaults() -> None:
    settings = Settings.from_env({ENV_MODE: "  ", ENV_MODEL: "  ", ENV_MAX_ITERATIONS: "   "})

    assert settings.mode == "offline"
    assert settings.model_name is None
    assert settings.max_iterations == DEFAULT_MAX_ITERATIONS


@pytest.mark.parametrize("bad_mode", ["sometimes", "on", "live2", "yes"])
def test_invalid_mode_is_rejected(bad_mode: str) -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        Settings.from_env({ENV_MODE: bad_mode})

    assert ENV_MODE in str(excinfo.value)


@pytest.mark.parametrize(
    ("env_name", "raw_value"),
    [
        (ENV_MAX_ITERATIONS, "eight"),
        (ENV_MAX_RESULTS, "1.5"),
        (ENV_TIMEOUT, "soon"),
        (ENV_DEADLINE, "whenever"),
    ],
)
def test_non_numeric_limits_are_rejected(env_name: str, raw_value: str) -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        Settings.from_env({env_name: raw_value})

    assert env_name in str(excinfo.value)


@pytest.mark.parametrize(
    ("env_name", "raw_value"),
    [
        (ENV_MAX_ITERATIONS, "0"),
        (ENV_MAX_ITERATIONS, "-1"),
        (ENV_MAX_ITERATIONS, "10000"),
        (ENV_MAX_RESULTS, "0"),
        (ENV_TIMEOUT, "0"),
        (ENV_TIMEOUT, "-5"),
        (ENV_DEADLINE, "0"),
        (ENV_DEADLINE, "-1"),
    ],
)
def test_out_of_range_limits_are_rejected(env_name: str, raw_value: str) -> None:
    with pytest.raises(ConfigurationError):
        Settings.from_env({env_name: raw_value})


def test_live_mode_without_credentials_is_rejected() -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        Settings.from_env({ENV_MODE: "live"})

    message = str(excinfo.value)
    assert ENV_OPENAI_KEY in message
    assert ENV_TAVILY_KEY in message
    assert ENV_MODEL in message


def test_live_mode_with_keys_but_no_model_is_rejected() -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        Settings.from_env({ENV_MODE: "live", ENV_OPENAI_KEY: SECRET, ENV_TAVILY_KEY: "tvly-x"})

    assert ENV_MODEL in str(excinfo.value)


def test_live_mode_with_full_credentials_is_accepted() -> None:
    settings = Settings.from_env(
        {
            ENV_MODE: "live",
            ENV_OPENAI_KEY: SECRET,
            ENV_TAVILY_KEY: "tvly-x",
            ENV_MODEL: "example-model",
        }
    )

    assert settings.mode == "live"


def test_placeholder_credentials_do_not_satisfy_live_mode() -> None:
    """The placeholder text shipped in .env.example must never enable live mode."""
    with pytest.raises(ConfigurationError):
        Settings.from_env(
            {
                ENV_MODE: "live",
                ENV_OPENAI_KEY: "replace-with-your-openai-api-key",
                ENV_TAVILY_KEY: "replace-with-your-tavily-api-key",
                ENV_MODEL: "example-model",
            }
        )


@pytest.mark.parametrize("env_name", [ENV_OPENAI_KEY, ENV_TAVILY_KEY])
def test_secret_never_appears_in_repr_or_errors(env_name: str) -> None:
    settings = Settings.from_env({env_name: SECRET})

    assert SECRET not in repr(settings)
    assert SECRET not in str(settings)

    with pytest.raises(ConfigurationError) as excinfo:
        Settings.from_env({ENV_MODE: "live", ENV_OPENAI_KEY: SECRET})

    assert SECRET not in str(excinfo.value)


def test_settings_are_immutable() -> None:
    """Frozen settings reject mutation, so runtime state cannot be altered."""
    settings = Settings.from_env({})

    with pytest.raises(ValidationError):
        settings.max_iterations = 99
