"""Tests for the bounded, normalized search adapter (US-201, US-203).

All tests inject a fake client, so no network access and no credentials are
required (US-503).
"""

from __future__ import annotations

from typing import Any

import pytest

from atlas.errors import SearchProviderError, ToolValidationError
from atlas.models import MAX_QUERY_LENGTH, MAX_SNIPPET_CHARS, SearchResult
from atlas.tools.search import MAX_RESULTS_PER_CALL, TavilySearchProvider

API_KEY = "tvly-secret-key-must-not-leak"


class UsageLimitExceededError(Exception):
    """Mirrors tavily.errors.UsageLimitExceededError."""


class InvalidAPIKeyError(Exception):
    """Mirrors tavily.errors.InvalidAPIKeyError."""


class MissingAPIKeyError(Exception):
    """Mirrors tavily.errors.MissingAPIKeyError."""


class ForbiddenError(Exception):
    """Mirrors tavily.errors.ForbiddenError."""


class BadRequestError(Exception):
    """Mirrors tavily.errors.BadRequestError."""


class FakeClient:
    """Stands in for TavilyClient, recording the arguments it was called with."""

    def __init__(
        self,
        response: Any = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def search(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


def make_response(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"query": "q", "results": items, "response_time": 0.1}


def provider(
    response: Any = None,
    error: Exception | None = None,
    default_max_results: int = 5,
) -> tuple[TavilySearchProvider, FakeClient]:
    client = FakeClient(response=response, error=error)
    return (
        TavilySearchProvider(client, api_key=API_KEY, default_max_results=default_max_results),
        client,
    )


def full_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "title": "Retrieval-augmented generation",
        "url": "https://example.com/rag",
        "snippet": "A technique that grounds generation in retrieved documents.",
        "published_date": "2025-04-01",
        "score": 0.91,
    }
    item.update(overrides)
    return item


# --- successful normalized search -------------------------------------------


def test_successful_search_returns_normalized_results() -> None:
    search, client = provider(response=make_response([full_item()]))

    results = search.search("what is RAG")

    assert len(results) == 1
    first = results[0]
    assert isinstance(first, SearchResult)
    assert first.title == "Retrieval-augmented generation"
    assert first.url == "https://example.com/rag"
    assert first.published_date == "2025-04-01"
    assert first.score == pytest.approx(0.91)
    assert len(client.calls) == 1


def test_query_is_stripped_and_passed_to_client() -> None:
    search, client = provider(response=make_response([]))

    search.search("  what is RAG  ")

    assert client.calls[0]["query"] == "what is RAG"


def test_missing_optional_fields_are_tolerated() -> None:
    search, _ = provider(
        response=make_response([{"title": "Bare", "url": "https://example.com/a"}])
    )

    results = search.search("q")

    assert results[0].snippet is None
    assert results[0].published_date is None
    assert results[0].score is None


def test_missing_title_falls_back_to_url() -> None:
    search, _ = provider(response=make_response([{"url": "https://example.com/x"}]))

    results = search.search("q")

    assert results[0].title == "https://example.com/x"


def test_snippet_is_truncated_to_bound() -> None:
    search, _ = provider(
        response=make_response([full_item(snippet="x" * (MAX_SNIPPET_CHARS + 500))])
    )

    results = search.search("q")

    assert len(results[0].snippet or "") == MAX_SNIPPET_CHARS


def test_non_string_optional_fields_become_none() -> None:
    search, _ = provider(
        response=make_response([full_item(published_date=12345, score="high", snippet=None)])
    )

    results = search.search("q")

    assert results[0].published_date is None
    assert results[0].score is None
    assert results[0].snippet is None


# --- bounds -----------------------------------------------------------------


def test_result_count_is_capped_even_if_provider_over_returns() -> None:
    items = [full_item(url=f"https://example.com/{i}") for i in range(10)]
    search, client = provider(response=make_response(items))

    results = search.search("q", max_results=3)

    assert len(results) == 3
    assert client.calls[0]["max_results"] == 3


def test_default_max_results_is_used_when_not_specified() -> None:
    items = [full_item(url=f"https://example.com/{i}") for i in range(10)]
    search, client = provider(response=make_response(items), default_max_results=2)

    results = search.search("q")

    assert len(results) == 2
    assert client.calls[0]["max_results"] == 2


@pytest.mark.parametrize("limit", [0, -1, MAX_RESULTS_PER_CALL + 1])
def test_out_of_range_result_count_is_rejected(limit: int) -> None:
    search, client = provider(response=make_response([]))

    with pytest.raises(ToolValidationError):
        search.search("q", max_results=limit)

    assert client.calls == []


def test_non_integer_result_count_is_rejected() -> None:
    search, client = provider(response=make_response([]))

    with pytest.raises(ToolValidationError):
        search.search("q", max_results="3")

    assert client.calls == []


@pytest.mark.parametrize("query", ["", "   ", "\t"])
def test_invalid_query_is_rejected_before_any_network_call(query: str) -> None:
    search, client = provider(response=make_response([]))

    with pytest.raises(ToolValidationError):
        search.search(query)

    assert client.calls == []


def test_over_long_query_is_rejected_before_any_network_call() -> None:
    search, client = provider(response=make_response([]))

    with pytest.raises(ToolValidationError) as excinfo:
        search.search("a" * (MAX_QUERY_LENGTH + 1))

    assert str(MAX_QUERY_LENGTH) in str(excinfo.value)
    assert client.calls == []


def test_non_string_query_is_rejected() -> None:
    search, client = provider(response=make_response([]))

    with pytest.raises(ToolValidationError):
        search.search(12345)  # type: ignore[arg-type]

    assert client.calls == []


def test_invalid_default_max_results_rejected_at_construction() -> None:
    with pytest.raises(ToolValidationError):
        TavilySearchProvider(FakeClient(), default_max_results=0)


# --- malformed responses ----------------------------------------------------


@pytest.mark.parametrize("malformed", [None, "a string", 42, ["a", "list"]])
def test_non_object_response_is_reported(malformed: Any) -> None:
    search, _ = provider(response=malformed)

    with pytest.raises(SearchProviderError) as excinfo:
        search.search("q")

    assert "malformed" in str(excinfo.value)
    assert API_KEY not in str(excinfo.value)


def test_missing_results_key_is_reported() -> None:
    search, _ = provider(response={"query": "q"})

    with pytest.raises(SearchProviderError) as excinfo:
        search.search("q")

    assert "results" in str(excinfo.value)


def test_results_must_be_a_list() -> None:
    search, _ = provider(response={"results": "not a list"})

    with pytest.raises(SearchProviderError):
        search.search("q")


def test_unusable_items_are_dropped_not_crash() -> None:
    items = [
        full_item(),  # usable
        {"title": "No URL"},
        {"url": "ftp://example.com/x"},
        {"url": ""},
        "not a mapping",
        None,
        {"url": "https://example.com/usable"},
    ]
    search, _ = provider(response=make_response(items))

    results = search.search("q")

    assert [r.url for r in results] == [
        "https://example.com/rag",
        "https://example.com/usable",
    ]


# --- error normalization ----------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (TimeoutError("timed out"), "timed out"),
        (UsageLimitExceededError("quota"), "usage limit exceeded"),
        (InvalidAPIKeyError("bad key"), "credentials"),
        (MissingAPIKeyError("none"), "credentials are not configured"),
        (ForbiddenError("denied"), "denied"),
        (BadRequestError("bad"), "malformed"),
    ],
)
def test_provider_exceptions_are_normalized(exc: Exception, expected: str) -> None:
    search, _ = provider(error=exc)

    with pytest.raises(SearchProviderError) as excinfo:
        search.search("q")

    assert expected in str(excinfo.value).lower()


def test_api_key_never_leaks_from_provider_error() -> None:
    search, _ = provider(error=Exception(f"request failed with key {API_KEY} in header"))

    with pytest.raises(SearchProviderError) as excinfo:
        search.search("q")

    assert API_KEY not in str(excinfo.value)
    assert "[redacted]" in str(excinfo.value)


def test_unexpected_exception_is_normalized_not_swallowed() -> None:
    search, _ = provider(error=RuntimeError("unexpected boom"))

    with pytest.raises(SearchProviderError) as excinfo:
        search.search("q")

    message = str(excinfo.value)
    assert "RuntimeError" in message
    assert "unexpected boom" in message


def test_original_exception_is_chained_for_diagnostics() -> None:
    original = TimeoutError("timed out")
    search, _ = provider(error=original)

    with pytest.raises(SearchProviderError) as excinfo:
        search.search("q")

    assert excinfo.value.__cause__ is original
