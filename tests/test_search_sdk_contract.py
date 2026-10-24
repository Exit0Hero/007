"""Contract tests against the real installed Tavily SDK (US-201).

These tests import the actual provider package to prove that the class names and
call signature Atlas relies on are the real ones, rather than assumptions. They
skip cleanly when the SDK is not installed, so the suite still runs with no
dependencies and no credentials (US-503).
"""

from __future__ import annotations

import inspect

import pytest

from atlas.errors import SearchProviderError
from atlas.tools.search import _ERROR_CATEGORIES, TavilySearchProvider

tavily_errors = pytest.importorskip("tavily.errors")


class _FailingClient:
    """Minimal client that always raises the configured exception."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def search(self, **kwargs: object) -> dict[str, object]:
        raise self._error


def _make_error(error_class: type[Exception]) -> Exception:
    """Instantiate an SDK error, tolerating classes that take no message.

    e.g. tavily.errors.MissingAPIKeyError defines __init__(self) with no
    message parameter.
    """
    try:
        return error_class("boom")
    except TypeError:
        return error_class()


SDK_ERROR_CLASSES = [
    getattr(tavily_errors, name)
    for name in _ERROR_CATEGORIES
    if isinstance(getattr(tavily_errors, name, None), type)
]


def test_at_least_the_core_sdk_errors_are_recognised() -> None:
    """If the SDK renames its errors, Atlas must not silently fall back."""
    assert len(SDK_ERROR_CLASSES) >= 5
    assert {cls.__name__ for cls in SDK_ERROR_CLASSES} >= {
        "TimeoutError",
        "UsageLimitExceededError",
        "InvalidAPIKeyError",
        "MissingAPIKeyError",
        "BadRequestError",
    }


@pytest.mark.parametrize("error_class", SDK_ERROR_CLASSES)
def test_real_sdk_error_instances_are_categorised(error_class: type[Exception]) -> None:
    """Every known SDK error must map to a category, not 'search failed'."""
    provider = TavilySearchProvider(
        _FailingClient(_make_error(error_class)),
        api_key="tvly-test-key",
    )

    with pytest.raises(SearchProviderError) as excinfo:
        provider.search("a query")

    message = str(excinfo.value)
    assert not message.startswith("search failed:"), f"{error_class.__name__} was not categorised"


def test_real_client_exposes_the_search_signature_atlas_calls() -> None:
    """Verify the exact kwargs Atlas passes actually exist on the SDK."""
    tavily = pytest.importorskip("tavily")
    signature = inspect.signature(tavily.TavilyClient.search)

    for parameter in ("query", "max_results", "timeout"):
        assert parameter in signature.parameters, (
            f"TavilyClient.search has no '{parameter}' parameter"
        )


def test_real_client_constructor_accepts_api_key() -> None:
    tavily = pytest.importorskip("tavily")

    signature = inspect.signature(tavily.TavilyClient.__init__)
    assert "api_key" in signature.parameters
