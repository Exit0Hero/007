"""Repeatable research evaluation with documented criteria (Sprint 6, US-504).

The PRD (§10) asks for *recorded* metrics, not promised ones. This module
defines how a run is scored and ships a benchmark of representative questions
whose outcomes are driven by injected providers, so the benchmark is
deterministic and free of paid calls (US-503).

Metrics computed per run (PRD §10):

* completion status and termination reason;
* citation validity — every rendered citation resolves to a registered source;
* tool calls per report (and refusals/suppressions);
* provider usage, when the provider reported it, otherwise recorded as
  unavailable. Never estimated.

**Live evaluation was not run.** No `OPENAI_API_KEY` or `TAVILY_API_KEY` exists
in this environment, so the benchmark below runs on scripted fixtures only and
measures the *pipeline*, not any real model's research quality.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from atlas.config import Settings
from atlas.models import SearchResult, ToolCall
from atlas.pipeline import ResearchOutcome, run_research
from atlas.report import Report


@dataclass(frozen=True)
class RunMetrics:
    """Objective measurements of one finished run."""

    status: str
    termination_reason: str | None
    tool_calls: int
    unsupported_calls: int
    duplicate_calls: int
    findings: int
    direct_findings: int
    sources_registered: int
    citations_valid: bool
    token_usage_reported: bool
    limitations: int

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "termination_reason": self.termination_reason,
            "tool_calls": self.tool_calls,
            "unsupported_calls": self.unsupported_calls,
            "duplicate_calls": self.duplicate_calls,
            "findings": self.findings,
            "direct_findings": self.direct_findings,
            "sources_registered": self.sources_registered,
            "citations_valid": self.citations_valid,
            "token_usage_reported": self.token_usage_reported,
            "limitations": self.limitations,
        }


def measure(outcome: ResearchOutcome) -> RunMetrics:
    """Score one finished run. Pure function of the outcome, no providers."""
    report: Report = outcome.report
    registered = {record.id for record in outcome.sources.records()}
    cited = {
        source_id
        for finding in report.findings
        for source_id in (*finding.citations, *(e.source_id for e in finding.evidence))
    }
    citations_valid = cited <= registered

    return RunMetrics(
        status=outcome.state.status or "failed",
        termination_reason=(
            outcome.state.termination_reason.value
            if outcome.state.termination_reason is not None
            else None
        ),
        tool_calls=len(outcome.state.observations),
        unsupported_calls=outcome.state.unsupported_calls,
        duplicate_calls=outcome.state.duplicate_calls,
        findings=len(report.findings),
        direct_findings=sum(1 for finding in report.findings if finding.kind == "direct"),
        sources_registered=len(registered),
        citations_valid=citations_valid,
        token_usage_reported=outcome.state.token_usage is not None,
        limitations=len(report.limitations),
    )


@dataclass(frozen=True)
class BenchmarkResult:
    """Aggregate metrics for a benchmark question."""

    question: str
    criteria: tuple[str, ...]
    metrics: RunMetrics
    meets_criteria: bool
    notes: tuple[str, ...] = field(default_factory=tuple)


#: Documented acceptance criteria applied to every benchmark question
#: (docs/ROADMAP.md verification lines for US-103/US-402/US-603).
BENCHMARK_CRITERIA = (
    "run reaches an explicit terminal status",
    "partial work is never labelled completed",
    "every rendered citation resolves to a registered source",
    "tool execution stays inside the configured iteration bound",
)


def evaluate(metrics: RunMetrics, *, max_iterations: int) -> tuple[bool, tuple[str, ...]]:
    """Apply the documented criteria to one run's metrics."""
    failures: list[str] = []

    if metrics.status not in ("completed", "partial", "failed"):
        failures.append(f"unexpected status {metrics.status!r}")
    if metrics.termination_reason is None:
        failures.append("no termination reason recorded")
    if metrics.status == "completed" and metrics.termination_reason != "completed":
        failures.append("completed status without a completed termination reason")
    # A run may legitimately stop because the model answered (reason
    # "completed") yet still be reported partial because a tool error occurred.
    # The reason describes why the loop stopped; the status describes outcome
    # quality. Only the status must never overstate the work.
    if not metrics.citations_valid:
        failures.append("a rendered citation does not resolve to a registered source")
    if metrics.tool_calls > max_iterations:
        failures.append(
            f"{metrics.tool_calls} tool calls exceed the iteration bound {max_iterations}"
        )

    return not failures, tuple(failures)


def run_benchmark(
    questions: list[tuple[str, object, object]],
    settings: Settings,
) -> list[BenchmarkResult]:
    """Run each (question, model, search) fixture and score it.

    Args:
        questions: ``(question, model, search)`` triples; providers are fakes
            supplied by the caller, so this never contacts a network.
        settings: Run bounds shared by every question.
    """
    results: list[BenchmarkResult] = []
    for question, model, search in questions:
        outcome = run_research(question, settings, model=model, search=search)
        metrics = measure(outcome)
        ok, failures = evaluate(metrics, max_iterations=settings.max_iterations)
        results.append(
            BenchmarkResult(
                question=question,
                criteria=BENCHMARK_CRITERIA,
                metrics=metrics,
                meets_criteria=ok,
                notes=failures,
            )
        )
    return results


# --- representative fixtures -------------------------------------------------

ATLAS_PAGE = (
    "Atlas is a single-agent research assistant. It searches the web, reads "
    "pages, and writes evidence-grounded Markdown reports with validated "
    "citations. It bounds every run by iterations and a wall-clock deadline."
)


class _FixtureSearch:
    """Deterministic search provider over a fixed result table."""

    def __init__(self, table: dict[str, list[SearchResult]]) -> None:
        self._table = table

    def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        for key, results in self._table.items():
            if key in query.lower():
                return results[: max_results or 5]
        return []


_CALL_COUNTER = itertools.count(1)


def _call(name: str, arguments: dict[str, object]) -> ToolCall:
    """Deterministic tool call: IDs come from a counter, not a hash.

    ``hash()`` is randomised per process, which would make the benchmark
    non-reproducible; IDs only need to be unique within a run.
    """
    import json

    return ToolCall(
        call_id=f"call_{next(_CALL_COUNTER)}",
        name=name,
        arguments=dict(arguments),
        raw_arguments=json.dumps(arguments, sort_keys=True),
    )


def benchmark_fixtures() -> list[tuple[str, object, object]]:
    """Three representative questions with scripted provider behaviour.

    1. a normal search-and-answer run;
    2. a run where the search provider fails and the model must cope;
    3. a run where the model over-calls tools until the iteration bound hits.
    """
    from atlas.model import FakeModelAdapter, ModelTurn

    good_results = [
        SearchResult(
            title="Atlas overview",
            url="https://example.com/atlas",
            snippet="Atlas is a single-agent research assistant.",
        ),
        SearchResult(
            title="Agent loop notes",
            url="https://example.com/loop",
            snippet="Bounded loops stop on iteration limits.",
        ),
    ]
    table = {"atlas": good_results, "agent": good_results}

    from atlas.errors import SearchProviderError

    class FailingSearch:
        def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
            raise SearchProviderError("quota exceeded")

    question_1 = "What is the Atlas research agent?"
    model_1 = FakeModelAdapter(
        ModelTurn(tool_calls=(_call("web_search", {"query": "atlas agent"}),)),
        ModelTurn(text="Atlas is a bounded single-agent research assistant."),
    )

    question_2 = "What is a bounded agent loop?"
    model_2 = FakeModelAdapter(
        ModelTurn(tool_calls=(_call("web_search", {"query": "agent loop"}),)),
        ModelTurn(text="A bounded loop stops on iteration or deadline limits."),
    )

    question_3 = "Tell me about Atlas in detail."
    model_3 = FakeModelAdapter(
        *[ModelTurn(tool_calls=(_call("web_search", {"query": f"atlas {i}"}),)) for i in range(20)]
    )

    return [
        (question_1, model_1, _FixtureSearch(table)),
        (question_2, model_2, FailingSearch()),
        (question_3, model_3, _FixtureSearch(table)),
    ]


def run_offline_benchmark() -> list[BenchmarkResult]:
    """Run the representative benchmark deterministically, offline."""
    return run_benchmark(benchmark_fixtures(), Settings(max_iterations=8))
