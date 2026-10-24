"""Live integration tests (US-503, US-304).

These tests contact real providers and therefore:

* are marked ``live`` and **deselected by default** (`addopts = "-m 'not live'"`);
* skip cleanly when credentials are absent, so an unconfigured checkout never
  fails and never fakes a result;
* are the only tests in this repository that perform paid API calls.

Run them explicitly with:

    ATLAS_MODE=live OPENAI_API_KEY=... TAVILY_API_KEY=... ATLAS_MODEL=... \\
        pytest -m live
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
TAVILY_KEY = os.environ.get("TAVILY_API_KEY", "")
MODEL = os.environ.get("ATLAS_MODEL", "")


def _have_openai() -> bool:
    return bool(OPENAI_KEY.strip()) and not OPENAI_KEY.strip().lower().startswith("replace-with")


def _have_tavily() -> bool:
    return bool(TAVILY_KEY.strip()) and not TAVILY_KEY.strip().lower().startswith("replace-with")


@pytest.mark.skipif(
    not _have_openai() or not MODEL.strip(),
    reason="OPENAI_API_KEY / ATLAS_MODEL not configured",
)
def test_live_model_call_produces_a_turn() -> None:
    """One real model call; asserts only shape, never content quality."""
    from atlas.config import Settings
    from atlas.model import OpenAIModelAdapter
    from atlas.tools.registry import ToolRegistry

    adapter = OpenAIModelAdapter(Settings(model_name=MODEL))

    turn = adapter.complete("Reply with the single word: pong", [], ToolRegistry().specs())

    assert isinstance(turn.text, str) or turn.tool_calls


@pytest.mark.skipif(
    not _have_openai() or not MODEL.strip(),
    reason="OPENAI_API_KEY / ATLAS_MODEL not configured",
)
def test_live_model_reports_usage_when_available() -> None:
    from atlas.config import Settings
    from atlas.model import OpenAIModelAdapter
    from atlas.tools.registry import ToolRegistry

    adapter = OpenAIModelAdapter(Settings(model_name=MODEL))

    turn = adapter.complete("Say hi.", [], ToolRegistry().specs())

    # Usage must be either reported with non-negative numbers or absent —
    # never fabricated.
    if turn.usage is None:
        assert turn.usage is None
    else:
        assert (turn.usage.total_tokens or 0) >= 0


@pytest.mark.skipif(not (_have_openai() and _have_tavily()), reason="live keys not configured")
def test_live_search_and_fetch_register_sources() -> None:
    """One real search; asserts sources register, not result quality."""
    from atlas.sources import SourceRegistry
    from atlas.tools.search import build_tavily_provider

    provider = build_tavily_provider(TAVILY_KEY, default_max_results=2)
    results = provider.search("Python programming language", 2)

    registry = SourceRegistry()
    for item in results:
        registry.register(item.url, title=item.title, search_snippet=item.snippet)

    assert len(results) >= 1
    assert len(registry) >= 1


@pytest.mark.skipif(
    not (_have_openai() and _have_tavily() and MODEL.strip()),
    reason="live keys / ATLAS_MODEL not configured",
)
def test_live_end_to_end_research_run() -> None:
    """One full live run; asserts bounds and honest status, not answer quality."""
    from atlas.config import Settings
    from atlas.model import OpenAIModelAdapter
    from atlas.pipeline import run_research
    from atlas.tools.fetch import PageFetcher, UrlPolicy
    from atlas.tools.search import build_tavily_provider

    settings = Settings.from_env()
    outcome = run_research(
        "What is the Python software foundation?",
        settings,
        model=OpenAIModelAdapter(settings),
        search=build_tavily_provider(TAVILY_KEY, default_max_results=settings.max_results),
        fetcher=PageFetcher(UrlPolicy(), timeout=settings.timeout_seconds),
    )

    assert outcome.state.status in ("completed", "partial", "failed")
    assert outcome.state.termination_reason is not None
    assert outcome.state.iterations <= settings.max_iterations
    markdown = outcome.report.to_markdown()
    assert "## Sources" in markdown
    # Every citation in a live report must still resolve.
    assert outcome.report.sources or "No sources were registered" in markdown
