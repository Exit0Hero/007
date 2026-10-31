"""Tests for the Exa search provider (US-706, ADR-018).

Every test runs offline against an injected fake transport; no credential and
no network are ever involved. The contract mirrors the Tavily provider:
bounded inputs, normalized outputs, and errors that never leak the API key.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

from agent007.errors import SearchProviderError, ToolValidationError
from agent007.models import MAX_SNIPPET_CHARS
from agent007.tools.search import (
    EXA_SEARCH_URL,
    ExaSearchProvider,
    ExaTransportError,
    build_exa_provider,
)

API_KEY = "exa-secret-key-abc123"


class FakeTransport:
    """Records the request and returns (or raises) a scripted result."""

    def __init__(
        self,
        payload: Mapping[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.payload = payload if payload is not None else {"results": []}
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        timeout: float,
    ) -> Mapping[str, Any]:
        self.calls.append({"url": url, "headers": dict(headers), "body": body, "timeout": timeout})
        if self.error is not None:
            raise self.error
        return self.payload


def make_provider(
    payload: Mapping[str, Any] | None = None,
    error: Exception | None = None,
    **kwargs: Any,
) -> tuple[ExaSearchProvider, FakeTransport]:
    transport = FakeTransport(payload=payload, error=error)
    provider = ExaSearchProvider(transport, api_key=API_KEY, **kwargs)
    return provider, transport


# --- request shape (US-706 criterion 2 / skill: minimal Exa request) --------


def test_request_targets_the_exa_search_endpoint() -> None:
    provider, transport = make_provider()

    provider.search("q", 1)

    assert transport.calls[0]["url"] == EXA_SEARCH_URL


def test_request_carries_the_api_key_header() -> None:
    provider, transport = make_provider()

    provider.search("python", 3)

    assert transport.calls[0]["headers"]["x-api-key"] == API_KEY
    assert transport.calls[0]["headers"]["Content-Type"] == "application/json"


def test_request_body_is_exactly_query_results_and_contents() -> None:
    provider, transport = make_provider()

    provider.search("  retrieval-augmented generation  ", 3)

    body = json.loads(transport.calls[0]["body"])
    # The skill forbids decorative parameters: nothing beyond the query, the
    # configured result bound, and content extraction may be sent.
    assert set(body) == {"query", "numResults", "contents"}
    assert body["query"] == "retrieval-augmented generation"  # trimmed
    assert body["numResults"] == 3
    assert body["contents"] == {"highlights": True}


def test_no_request_is_made_for_an_invalid_query() -> None:
    provider, transport = make_provider()

    with pytest.raises(ToolValidationError):
        provider.search("   ", 3)

    assert transport.calls == []


def test_no_request_is_made_for_an_invalid_result_count() -> None:
    provider, transport = make_provider()

    for bad in (0, -1, 21, True, "3"):
        with pytest.raises(ToolValidationError):
            provider.search("python", bad)  # type: ignore[arg-type]

    assert transport.calls == []


def test_out_of_range_default_is_rejected_at_construction() -> None:
    with pytest.raises(ToolValidationError):
        make_provider(default_max_results=0)

    with pytest.raises(ToolValidationError):
        make_provider(timeout=0)


# --- normalization ----------------------------------------------------------


def _result(**overrides: Any) -> dict[str, Any]:
    item = {
        "url": "https://example.org/page",
        "title": "Example Page",
        "highlights": ["First highlight.", "Second highlight."],
        "publishedDate": "2026-01-02",
        "score": 0.987,
    }
    item.update(overrides)
    return item


def test_full_result_is_normalized() -> None:
    provider, _ = make_provider(payload={"results": [_result()]})

    [item] = provider.search("q", 1)

    assert item.url == "https://example.org/page"
    assert item.title == "Example Page"
    assert item.snippet == "First highlight.\nSecond highlight."
    assert item.published_date == "2026-01-02"
    assert item.score == pytest.approx(0.987)


def test_missing_title_falls_back_to_the_url() -> None:
    provider, _ = make_provider(payload={"results": [_result(title=None)]})

    [item] = provider.search("q", 1)

    assert item.title == "https://example.org/page"


def test_snippet_is_bounded_to_the_shared_limit() -> None:
    provider, _ = make_provider(
        payload={"results": [_result(highlights=["x" * (MAX_SNIPPET_CHARS * 2)])]}
    )

    [item] = provider.search("q", 1)

    assert item.snippet is not None
    assert len(item.snippet) <= MAX_SNIPPET_CHARS


def test_string_highlights_are_accepted_as_the_snippet() -> None:
    provider, _ = make_provider(payload={"results": [_result(highlights="plain text")]})

    [item] = provider.search("q", 1)

    assert item.snippet == "plain text"


def test_results_without_usable_highlights_have_no_snippet() -> None:
    provider, _ = make_provider(payload={"results": [_result(highlights=[])]})

    [item] = provider.search("q", 1)

    assert item.snippet is None


@pytest.mark.parametrize("url", ["ftp://example.org/x", "javascript:alert(1)", 42, None])
def test_non_http_results_are_dropped(url: Any) -> None:
    provider, _ = make_provider(payload={"results": [_result(url=url), _result()]})

    items = provider.search("q", 5)

    assert [item.url for item in items] == ["https://example.org/page"]


def test_malformed_entries_are_dropped_without_consuming_the_bound() -> None:
    payload = {"results": ["junk", None, 7, _result(), _result(url="https://other.example/")]}
    provider, _ = make_provider(payload=payload)

    items = provider.search("q", 2)

    assert len(items) == 2  # two *usable* results, junk ignored


def test_result_count_is_honoured() -> None:
    provider, _ = make_provider(
        payload={"results": [_result(url=f"https://e.example/{i}") for i in range(10)]}
    )

    items = provider.search("q", 4)

    assert len(items) == 4


def test_empty_results_return_an_empty_list() -> None:
    provider, _ = make_provider(payload={"results": []})

    assert provider.search("q", 5) == []


# --- error normalisation and redaction --------------------------------------


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ExaTransportError("HTTP 401", status_code=401), "credentials"),
        (ExaTransportError("HTTP 429", status_code=429), "usage limit"),
        (ExaTransportError("HTTP 400", status_code=400), "malformed"),
        (ExaTransportError("request timed out"), "search timed out"),
        (RuntimeError("boom"), "search failed"),
    ],
)
def test_transport_errors_are_normalised(error: Exception, expected: str) -> None:
    provider, _ = make_provider(error=error)

    with pytest.raises(SearchProviderError) as excinfo:
        provider.search("q", 1)

    assert expected in str(excinfo.value)


def test_api_key_never_appears_in_an_error() -> None:
    provider, _ = make_provider(error=RuntimeError(f"401 unauthorized for key {API_KEY}"))

    with pytest.raises(SearchProviderError) as excinfo:
        provider.search("q", 1)

    assert API_KEY not in str(excinfo.value)
    assert "[redacted]" in str(excinfo.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"nonsense": []},  # missing results
        {"results": "not-a-list"},  # wrong type
        {"results": {"a": 1}},  # object instead of list
    ],
)
def test_malformed_responses_raise_search_provider_error(payload: Any) -> None:
    provider, _ = make_provider(payload=payload)

    with pytest.raises(SearchProviderError):
        provider.search("q", 1)


# --- construction -----------------------------------------------------------


def test_build_exa_provider_uses_the_injected_transport() -> None:
    transport = FakeTransport(payload={"results": []})

    provider = build_exa_provider(API_KEY, default_max_results=2, transport=transport)

    assert provider.search("q", 1) == []
    assert transport.calls  # the injected transport served the call
