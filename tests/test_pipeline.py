"""Tests for the end-to-end research pipeline (US-203, US-401, US-402, US-502).

Every provider is faked, so the full chain — agent loop, tool dispatch, source
registration, citation validation, report building — runs offline and
deterministically (US-503). **No live provider integration was run**; no
credentials exist in this environment.
"""

from __future__ import annotations

import json

from atlas.config import Settings
from atlas.model import FakeModelAdapter, ModelTurn
from atlas.models import SearchResult, ToolCall
from atlas.pipeline import run_research
from atlas.tools.fetch import FetchedPage

PAGE_TEXT = (
    "Atlas is a single-agent research assistant. It searches the web, reads "
    "pages, and writes an evidence-grounded report with validated citations."
)


class FakeSearch:
    """Search provider returning canned results and recording calls."""

    def __init__(self, *results: SearchResult) -> None:
        self.results = list(results)
        self.queries: list[str] = []

    def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        self.queries.append(query)
        return self.results[: max_results or 5]


class FakeFetcher:
    """Page fetcher returning one canned page and recording the URLs asked for."""

    def __init__(self, page: FetchedPage | None = None) -> None:
        self.page = page or FetchedPage(
            url="https://example.com/atlas",
            status_code=200,
            content_type="text/html",
            title="Atlas overview",
            text=PAGE_TEXT,
        )
        self.urls: list[str] = []

    def fetch(self, url: str) -> FetchedPage:
        self.urls.append(url)
        return self.page


def search_call(call_id: str = "call_1") -> ModelTurn:
    return ModelTurn(
        tool_calls=(
            ToolCall(
                call_id=call_id,
                name="web_search",
                arguments={"query": "atlas research agent"},
                raw_arguments=json.dumps({"query": "atlas research agent"}),
            ),
        )
    )


def fetch_call(call_id: str, url: str = "https://example.com/atlas") -> ModelTurn:
    return ModelTurn(
        tool_calls=(
            ToolCall(
                call_id=call_id,
                name="fetch_page",
                arguments={"url": url},
                raw_arguments=json.dumps({"url": url}),
            ),
        )
    )


def test_search_results_are_registered_and_cited_in_the_report() -> None:
    search = FakeSearch(
        SearchResult(
            title="Atlas overview",
            url="https://example.com/atlas",
            snippet="Atlas is a research assistant.",
        )
    )
    model = FakeModelAdapter(search_call(), ModelTurn(text="Atlas is a research assistant."))

    outcome = run_research("What is Atlas?", Settings(), model=model, search=search)

    assert outcome.state.status == "completed"
    assert outcome.sources.ids() == ["S1"]
    report = outcome.report.to_markdown()
    assert "[S1]" in report
    assert "https://example.com/atlas" in report


def test_fetching_a_result_enriches_the_source_with_page_evidence() -> None:
    search = FakeSearch(
        SearchResult(
            title="Atlas overview", url="https://example.com/atlas", snippet="snippet text"
        )
    )
    fetcher = FakeFetcher()
    model = FakeModelAdapter(
        search_call(),
        fetch_call("call_2"),
        ModelTurn(text="Answer grounded in the fetched page."),
    )

    outcome = run_research(
        "What is Atlas?", Settings(), model=model, search=search, fetcher=fetcher
    )

    assert fetcher.urls == ["https://example.com/atlas"]
    record = outcome.sources.get("S1")
    assert record is not None
    assert record.page_text is not None
    assert "search assistant" in record.page_text


def test_report_evidence_is_quoted_from_registered_page_text() -> None:
    search = FakeSearch(SearchResult(title="T", url="https://example.com/atlas", snippet="s"))
    model = FakeModelAdapter(search_call(), fetch_call("call_2"), ModelTurn(text="Final answer."))

    outcome = run_research("q", Settings(), model=model, search=search, fetcher=FakeFetcher())

    findings = outcome.report.findings
    assert findings
    direct = [f for f in findings if f.kind == "direct"]
    assert direct
    excerpt = direct[0].evidence[0].excerpt
    assert "single-agent research assistant" in excerpt


def test_search_only_run_marks_snippet_evidence_as_a_limitation() -> None:
    search = FakeSearch(
        SearchResult(title="T", url="https://example.com/x", snippet="Only a snippet here.")
    )
    model = FakeModelAdapter(search_call(), ModelTurn(text="answer"))

    outcome = run_research("q", Settings(), model=model, search=search)

    assert any("search snippet" in limitation for limitation in outcome.report.limitations)


def test_provider_error_becomes_a_partial_report_not_a_crash() -> None:
    from atlas.errors import SearchProviderError

    class FailingSearch:
        def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
            raise SearchProviderError("quota exceeded")

    model = FakeModelAdapter(search_call(), ModelTurn(text="best-effort answer"))

    outcome = run_research("q", Settings(), model=model, search=FailingSearch())

    assert outcome.state.status == "partial"
    assert outcome.report.status == "partial"
    assert any("quota exceeded" in limitation for limitation in outcome.report.limitations)


def test_run_without_any_tool_succeeds_with_an_empty_source_list() -> None:
    model = FakeModelAdapter(ModelTurn(text="No research needed."))

    outcome = run_research("q", Settings(), model=model)

    assert outcome.state.status == "completed"
    assert outcome.report.sources == ()
    assert "No sources were registered" in outcome.report.to_markdown()


def test_tool_results_include_source_ids_so_the_model_can_cite_them() -> None:
    search = FakeSearch(SearchResult(title="T", url="https://example.com/x", snippet="s"))
    model = FakeModelAdapter(search_call(), ModelTurn(text="answer"))

    run_research("q", Settings(), model=model, search=search)

    observation = model.calls[1]["observations"][0]
    assert "[S1]" in observation.output


def test_iteration_bounded_run_still_produces_a_partial_report() -> None:
    """An endless model is stopped by max_iterations; the report says so."""
    endless = [search_call(f"call_{i}") for i in range(20)]
    many = [SearchResult(title="T", url=f"https://example.com/{i}", snippet="s") for i in range(20)]
    search = FakeSearch(*many)
    settings = Settings(max_iterations=3)
    model = FakeModelAdapter(*endless)

    outcome = run_research("q", settings, model=model, search=search)

    assert outcome.state.termination_reason.value == "max_iterations"
    assert outcome.report.status == "partial"
    assert any("incomplete" in limitation for limitation in outcome.report.limitations)


def test_duplicate_searches_are_suppressed_by_the_pipeline() -> None:
    from atlas.tools.registry import MAX_IDENTICAL_CALLS

    same = [search_call(f"call_{i}") for i in range(6)]
    search = FakeSearch(SearchResult(title="T", url="https://example.com/x", snippet="s"))
    model = FakeModelAdapter(*same, ModelTurn(text="answer"))

    outcome = run_research("q", Settings(max_iterations=10), model=model, search=search)

    assert len(search.queries) == MAX_IDENTICAL_CALLS
    assert outcome.state.duplicate_calls == 3


def test_search_results_with_unusable_urls_do_not_kill_the_run() -> None:
    search = FakeSearch(
        SearchResult(title="Bad", url="ftp://not-supported.example/x", snippet="odd url")
    )
    model = FakeModelAdapter(search_call(), ModelTurn(text="answer"))

    outcome = run_research("q", Settings(), model=model, search=search)

    assert outcome.state.status == "completed"
    assert outcome.sources.ids() == []


def test_settings_bounds_are_respected_by_the_pipeline() -> None:
    endless = [search_call(f"call_{i}") for i in range(20)]
    search = FakeSearch()
    model = FakeModelAdapter(*endless)

    outcome = run_research("q", Settings(max_iterations=2), model=model, search=search)

    assert outcome.state.model_calls == 2


def test_report_markdown_from_a_full_chain_is_stable() -> None:
    def build() -> str:
        search = FakeSearch(
            SearchResult(
                title="T", url="https://example.com/atlas", snippet="Atlas is a research assistant."
            )
        )
        model = FakeModelAdapter(search_call(), fetch_call("call_2"), ModelTurn(text="answer"))
        return run_research(
            "What is Atlas?", Settings(), model=model, search=search, fetcher=FakeFetcher()
        ).report.to_markdown()

    assert build() == build()
