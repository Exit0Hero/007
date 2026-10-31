"""End-to-end research pipeline: request → agent loop → report (US-502).

Dependencies are injected, so the whole chain — agent loop, tool registry,
source registration, and report building — runs in tests with fake providers
and zero network access (US-503). The CLI is the only place real providers are
constructed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent007.agent import ResearchAgent
from agent007.config import Settings
from agent007.models import ResearchState, SearchResult
from agent007.report import Report, build_report_from_state
from agent007.sources import SourceRegistry
from agent007.tools.registry import ToolRegistry, build_default_registry


@dataclass(frozen=True)
class ResearchOutcome:
    """The result of one research run: state plus its traceable report."""

    state: ResearchState
    report: Report
    sources: SourceRegistry


def run_research(
    question: str,
    settings: Settings,
    *,
    model: Any,
    search: Any | None = None,
    fetcher: Any | None = None,
    on_observation: Callable[[Any], None] | None = None,
) -> ResearchOutcome:
    """Run one bounded research run and build its evidence-grounded report.

    Args:
        question: Already-validated research question.
        settings: Run bounds (iterations, deadline, result count).
        model: Model adapter (stateless).
        search: Optional search provider; registers sources as they arrive.
        fetcher: Optional page fetcher; enriches sources with page text.
        on_observation: Optional hook invoked with each tool observation.
    """
    sources = SourceRegistry()
    registry = _registry_with_registration(
        build_default_registry(settings, search=search, fetcher=fetcher),
        sources,
        search=search,
        fetcher=fetcher,
        settings=settings,
    )

    agent = ResearchAgent(
        model,
        registry,
        max_iterations=settings.max_iterations,
        deadline_seconds=settings.deadline_seconds,
        on_observation=on_observation,
    )
    state = agent.run(question)
    report = build_report_from_state(state, sources)
    return ResearchOutcome(state=state, report=report, sources=sources)


def _registry_with_registration(
    registry: ToolRegistry,
    sources: SourceRegistry,
    *,
    search: Any | None,
    fetcher: Any | None,
    settings: Settings,
) -> ToolRegistry:
    """Re-register tools so their handlers record sources as evidence arrives.

    The default registry knows how to call providers; this layer adds source
    registration, which is what makes citations traceable (US-203, US-402).
    """
    from agent007.tools.registry import FetchArgs, SearchArgs

    enriched = ToolRegistry()

    if search is not None:

        def run_search(args: Any) -> str:
            typed: SearchArgs = args
            results = search.search(typed.query, typed.max_results or settings.max_results)
            lines: list[str] = []
            for index, item in enumerate(results, start=1):
                source_id = _register_result(sources, item)
                lines.append(f"{index}. {item.title} — {item.url} [{source_id}]")
                if item.snippet:
                    lines.append(f"   {item.snippet}")
                if item.published_date:
                    lines.append(f"   published: {item.published_date}")
            if not lines:
                return "No results found."
            return "\n".join(lines)

        enriched.register(
            name="web_search",
            description=(
                "Search the web for sources about a topic. Returns titles, URLs, "
                "short snippets, and source IDs like [S1]. Use a focused query; "
                "results are bounded."
            ),
            args_model=SearchArgs,
            handler=run_search,
        )

    if fetcher is not None:

        def run_fetch(args: Any) -> str:
            typed: FetchArgs = args
            page = fetcher.fetch(typed.url)
            sources.register(
                page.url,
                title=page.title,
                page_text=page.text,
                registration_method="fetch",
            )
            header = f"Title: {page.title}" if page.title else f"URL: {page.url}"
            return f"{header}\n{page.text}"

        enriched.register(
            name="fetch_page",
            description=(
                "Retrieve a web page and return its readable text. Only http(s) "
                "URLs are permitted; unsafe destinations are refused."
            ),
            args_model=FetchArgs,
            handler=run_fetch,
        )

    return enriched


def _register_result(sources: SourceRegistry, item: SearchResult) -> str:
    """Register a search result, tolerating provider-level URL oddities."""
    try:
        return sources.register(
            item.url,
            title=item.title,
            published_date=item.published_date,
            search_snippet=item.snippet,
            registration_method="search",
        )
    except Exception:  # noqa: BLE001 - one bad URL must not kill the run
        # Unregisterable results still reach the model as text but can never be
        # cited, because they never receive a source ID.
        return "S?"


__all__ = ["ResearchOutcome", "run_research"]
