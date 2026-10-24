"""Tests for the source registry: stable IDs, dedup, and citation resolution (US-203)."""

from __future__ import annotations

import pytest

from atlas.errors import ToolValidationError
from atlas.sources import (
    MAX_STORED_PAGE_CHARS,
    MAX_STORED_SNIPPET_CHARS,
    SourceRegistry,
)


def test_ids_are_stable_and_sequential() -> None:
    registry = SourceRegistry()

    first = registry.register("https://example.com/a")
    second = registry.register("https://example.com/b")

    assert (first, second) == ("S1", "S2")
    assert registry.id_for("https://example.com/a") == first
    assert registry.get(first).url == "https://example.com/a"


def test_re_registering_same_url_returns_same_id() -> None:
    registry = SourceRegistry()

    first = registry.register("https://example.com/a", title="Original")
    again = registry.register("https://example.com/a", title="Duplicate title")

    assert again == first
    assert len(registry) == 1


@pytest.mark.parametrize(
    "variant",
    [
        "https://EXAMPLE.com/a",
        "https://example.com/a/",
        "https://example.com/a#section",
        "  https://example.com/a  ",
        "https://example.com:443/a",
    ],
)
def test_canonicalisation_merges_equivalent_urls(variant: str) -> None:
    registry = SourceRegistry()

    original = registry.register("https://example.com/a")

    assert registry.id_for(variant) == original
    assert registry.register(variant) == original


def test_different_schemes_do_not_merge() -> None:
    registry = SourceRegistry()

    http_id = registry.register("http://example.com/a")
    https_id = registry.register("https://example.com/a")

    assert http_id != https_id


def test_different_query_strings_do_not_merge() -> None:
    registry = SourceRegistry()

    first = registry.register("https://example.com/search?id=1")
    second = registry.register("https://example.com/search?id=2")

    assert first != second


def test_duplicate_registration_only_fills_missing_metadata() -> None:
    registry = SourceRegistry()
    original = registry.register("https://example.com/a", title="Known title")

    registry.register(
        "https://example.com/a",
        title="Different title",
        published_date="2025-01-02",
        search_snippet="A snippet.",
    )

    record = registry.get(original)
    assert record.title == "Known title"
    assert record.published_date == "2025-01-02"
    assert record.search_snippet == "A snippet."


def test_first_registration_wins_when_metadata_later_conflicts() -> None:
    registry = SourceRegistry()
    original = registry.register(
        "https://example.com/a", published_date="2025-01-01", search_snippet="first"
    )

    registry.register("https://example.com/a", published_date="2030-12-31", search_snippet="second")

    record = registry.get(original)
    assert record.published_date == "2025-01-01"
    assert record.search_snippet == "first"


def test_snippet_and_page_text_are_distinguished() -> None:
    """US-203: snippet evidence must never be mistaken for full content."""
    registry = SourceRegistry()
    source_id = registry.register(
        "https://example.com/a",
        search_snippet="Search summary.",
        page_text="Full extracted page body.",
    )

    record = registry.get(source_id)

    assert record.search_snippet == "Search summary."
    assert record.page_text == "Full extracted page body."
    assert record.evidence_kinds == ("search_snippet", "page_text")


def test_snippet_only_source_reports_snippet_tier_only() -> None:
    registry = SourceRegistry()
    source_id = registry.register("https://example.com/a", search_snippet="Summary.")

    assert registry.get(source_id).evidence_kinds == ("search_snippet",)


def test_stored_evidence_is_bounded() -> None:
    registry = SourceRegistry()
    source_id = registry.register(
        "https://example.com/a",
        search_snippet="s" * (MAX_STORED_SNIPPET_CHARS * 2),
        page_text="p" * (MAX_STORED_PAGE_CHARS * 2),
    )

    record = registry.get(source_id)

    assert len(record.search_snippet or "") == MAX_STORED_SNIPPET_CHARS
    assert len(record.page_text or "") == MAX_STORED_PAGE_CHARS


@pytest.mark.parametrize("bad", ["", "   ", None, 123])
def test_invalid_urls_are_rejected(bad: object) -> None:
    registry = SourceRegistry()

    with pytest.raises(ToolValidationError):
        registry.register(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/a",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "/relative/path",
    ],
)
def test_non_http_s_urls_are_rejected(url: str) -> None:
    registry = SourceRegistry()

    with pytest.raises(ToolValidationError):
        registry.register(url)


def test_resolve_separates_known_and_unknown_ids() -> None:
    registry = SourceRegistry()
    known = registry.register("https://example.com/a")
    also_known = registry.register("https://example.com/b")

    found, unknown = registry.resolve([known, "S99", also_known])

    assert [r.id for r in found] == [known, also_known]
    assert unknown == ["S99"]


def test_resolve_deduplicates_repeated_citations() -> None:
    registry = SourceRegistry()
    known = registry.register("https://example.com/a")

    found, unknown = registry.resolve([known, known, known])

    assert len(found) == 1
    assert unknown == []


def test_resolve_empty_list_is_harmless() -> None:
    found, unknown = SourceRegistry().resolve([])

    assert found == []
    assert unknown == []


def test_resolve_rejects_non_list_input() -> None:
    with pytest.raises(ToolValidationError):
        SourceRegistry().resolve("S1")  # type: ignore[arg-type]


def test_resolve_rejects_non_string_ids() -> None:
    with pytest.raises(ToolValidationError):
        SourceRegistry().resolve([1, 2])  # type: ignore[list-item]


def test_registry_starts_empty() -> None:
    registry = SourceRegistry()

    assert len(registry) == 0
    assert registry.ids() == []
    assert registry.records() == []
