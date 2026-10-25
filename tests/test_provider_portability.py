"""Tests for provider portability (US-706, ADR-018).

Covers the one-of search credential rule (Tavily *or* Exa), the optional
``OPENAI_BASE_URL`` for OpenAI-compatible endpoints, deterministic provider
selection in the CLI, and the model adapter passing endpoint/credential from
``Settings``. All offline: client construction performs no network calls.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from atlas.config import (
    ENV_EXA_KEY,
    ENV_MODE,
    ENV_MODEL,
    ENV_OPENAI_BASE_URL,
    ENV_OPENAI_KEY,
    ENV_TAVILY_KEY,
    Settings,
)
from atlas.errors import ConfigurationError
from atlas.main import _build_search_provider
from atlas.model import OpenAIModelAdapter
from atlas.tools.search import ExaSearchProvider, TavilySearchProvider

SECRET = "sk-live-placeholder-000"
EXA_KEY = "exa-live-placeholder-000"

LIVE_BASE = {
    ENV_MODE: "live",
    ENV_OPENAI_KEY: SECRET,
    ENV_MODEL: "example-model",
}


# --- one-of search credential rule (criterion 1) ----------------------------


def test_exa_alone_satisfies_live_search_credentials() -> None:
    settings = Settings.from_env({**LIVE_BASE, ENV_EXA_KEY: EXA_KEY})

    assert settings.mode == "live"
    assert settings.exa_api_key is not None
    assert settings.tavily_api_key is None


def test_tavily_alone_still_satisfies_live_search_credentials() -> None:
    settings = Settings.from_env({**LIVE_BASE, ENV_TAVILY_KEY: "tvly-x"})

    assert settings.tavily_api_key is not None
    assert settings.exa_api_key is None


def test_neither_search_key_is_a_configuration_error_naming_both() -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        Settings.from_env(dict(LIVE_BASE))

    message = str(excinfo.value)
    assert ENV_TAVILY_KEY in message
    assert ENV_EXA_KEY in message


def test_both_search_keys_are_accepted() -> None:
    settings = Settings.from_env({**LIVE_BASE, ENV_TAVILY_KEY: "tvly-x", ENV_EXA_KEY: EXA_KEY})

    assert settings.tavily_api_key is not None
    assert settings.exa_api_key is not None


def test_exa_key_is_a_secret_and_never_echoed() -> None:
    settings = Settings.from_env({**LIVE_BASE, ENV_EXA_KEY: EXA_KEY})

    assert isinstance(settings.exa_api_key, SecretStr)
    assert EXA_KEY not in repr(settings)
    assert EXA_KEY not in str(settings)


def test_placeholder_exa_key_does_not_satisfy_live_mode() -> None:
    with pytest.raises(ConfigurationError):
        Settings.from_env({**LIVE_BASE, ENV_EXA_KEY: "replace-with-your-exa-api-key"})


# --- OPENAI_BASE_URL (criterion 3) ------------------------------------------


def test_base_url_is_loaded() -> None:
    settings = Settings.from_env(
        {**LIVE_BASE, ENV_EXA_KEY: EXA_KEY, ENV_OPENAI_BASE_URL: "https://openrouter.ai/api/v1"}
    )

    assert settings.openai_base_url == "https://openrouter.ai/api/v1"


def test_base_url_defaults_to_none() -> None:
    settings = Settings.from_env({**LIVE_BASE, ENV_EXA_KEY: EXA_KEY})

    assert settings.openai_base_url is None


@pytest.mark.parametrize("bad", ["openrouter.ai/api/v1", "ftp://x.example", "not a url"])
def test_non_http_base_url_is_rejected(bad: str) -> None:
    with pytest.raises(ConfigurationError):
        Settings.from_env({**LIVE_BASE, ENV_EXA_KEY: EXA_KEY, ENV_OPENAI_BASE_URL: bad})


def test_model_adapter_passes_base_url_and_key_to_the_client() -> None:
    settings = Settings(
        model_name="example-model",
        openai_api_key=SecretStr(SECRET),
        openai_base_url="https://openrouter.ai/api/v1",
    )

    adapter = OpenAIModelAdapter(settings)

    assert str(adapter._client.base_url).startswith("https://openrouter.ai/api/v1")
    assert adapter._client.api_key == SECRET


def test_model_adapter_without_base_url_keeps_the_sdk_default() -> None:
    settings = Settings(model_name="example-model", openai_api_key=SecretStr(SECRET))

    adapter = OpenAIModelAdapter(settings)

    assert str(adapter._client.base_url).startswith("https://api.openai.com/v1")


# --- deterministic provider selection (criterion 4) -------------------------


def test_tavily_is_preferred_when_both_keys_exist() -> None:
    settings = Settings.from_env({**LIVE_BASE, ENV_TAVILY_KEY: "tvly-x", ENV_EXA_KEY: EXA_KEY})

    assert isinstance(_build_search_provider(settings), TavilySearchProvider)


def test_exa_is_used_when_only_the_exa_key_exists() -> None:
    settings = Settings.from_env({**LIVE_BASE, ENV_EXA_KEY: EXA_KEY})

    assert isinstance(_build_search_provider(settings), ExaSearchProvider)


def test_no_search_key_raises_a_configuration_error() -> None:
    # Bypass from_env's rule to prove the builder defends itself too.
    settings = Settings(model_name="example-model")

    with pytest.raises(ConfigurationError) as excinfo:
        _build_search_provider(settings)

    assert ENV_TAVILY_KEY in str(excinfo.value)
    assert ENV_EXA_KEY in str(excinfo.value)
