"""Tests for the offline evaluation harness (Sprint 6, US-504).

The benchmark runs on scripted fixtures with no network access and no
credentials (US-503). It measures the pipeline, not any real model.
"""

from __future__ import annotations

from agent007.config import Settings
from agent007.errors import SearchProviderError
from agent007.evaluation import (
    BENCHMARK_CRITERIA,
    RunMetrics,
    benchmark_fixtures,
    evaluate,
    measure,
    run_benchmark,
    run_offline_benchmark,
)
from agent007.model import FakeModelAdapter, ModelTurn
from agent007.models import SearchResult, TerminationReason
from agent007.pipeline import run_research


def completed_metrics(**overrides: object) -> RunMetrics:
    base: dict[str, object] = {
        "status": "completed",
        "termination_reason": "completed",
        "tool_calls": 2,
        "unsupported_calls": 0,
        "duplicate_calls": 0,
        "findings": 1,
        "direct_findings": 1,
        "sources_registered": 1,
        "citations_valid": True,
        "token_usage_reported": False,
        "limitations": 1,
    }
    base.update(overrides)
    return RunMetrics(**base)  # type: ignore[arg-type]


# --- metric computation ------------------------------------------------------


def test_completed_run_metrics_are_recorded() -> None:
    search = _search_provider()
    model = _model_search_then_answer()

    metrics = measure(run_research("What is Atlas?", Settings(), model=model, search=search))

    assert metrics.status == "completed"
    assert metrics.termination_reason == "completed"
    assert metrics.tool_calls == 1
    assert metrics.citations_valid is True
    assert metrics.sources_registered == 1
    assert metrics.token_usage_reported is False  # provider reported none


def test_token_usage_is_reported_only_when_actually_available() -> None:
    from agent007.models import TokenUsage

    model = FakeModelAdapter(
        ModelTurn(
            text="answer", usage=TokenUsage(input_tokens=12, output_tokens=4, total_tokens=16)
        )
    )

    metrics = measure(run_research("q", Settings(), model=model))

    assert metrics.token_usage_reported is True


def test_partial_run_is_measured_as_partial() -> None:
    endless = [ModelTurn(tool_calls=(_tool_call(f"q{i}"),)) for i in range(10)]
    model = FakeModelAdapter(*endless)

    metrics = measure(run_research("q", Settings(max_iterations=3), model=model))

    assert metrics.status == "partial"
    assert metrics.termination_reason == "max_iterations"


# --- criteria application ----------------------------------------------------


def test_clean_run_meets_every_criterion() -> None:
    ok, failures = evaluate(completed_metrics(), max_iterations=8)

    assert ok
    assert failures == ()


def test_partial_run_with_answered_loop_is_not_a_criterion_failure() -> None:
    """Reason 'completed' + status 'partial' is honest, not contradictory.

    The loop stopped because the model produced an answer, but a tool error
    occurred, so the outcome is partial. Only the status must never overstate
    the work.
    """
    ok, failures = evaluate(
        completed_metrics(status="partial", termination_reason="completed"), max_iterations=8
    )

    assert ok, failures


def test_invalid_citation_fails_the_criterion() -> None:
    ok, failures = evaluate(completed_metrics(citations_valid=False), max_iterations=8)

    assert not ok
    assert any("citation" in failure for failure in failures)


def test_missing_termination_reason_fails_the_criterion() -> None:
    ok, failures = evaluate(completed_metrics(termination_reason=None), max_iterations=8)

    assert not ok
    assert any("termination reason" in failure for failure in failures)


def test_tool_calls_beyond_the_iteration_bound_fail_the_criterion() -> None:
    ok, failures = evaluate(completed_metrics(tool_calls=9), max_iterations=8)

    assert not ok
    assert any("iteration bound" in failure for failure in failures)


def test_completed_status_requires_completed_reason() -> None:
    ok, _ = evaluate(completed_metrics(termination_reason="max_iterations"), max_iterations=8)

    assert not ok


# --- benchmark ---------------------------------------------------------------


def test_benchmark_covers_three_representative_questions() -> None:
    fixtures = benchmark_fixtures()

    assert len(fixtures) == 3
    assert all(isinstance(question, str) for question, _, _ in fixtures)


def test_offline_benchmark_is_deterministic() -> None:
    first = [r.metrics.as_dict() for r in run_offline_benchmark()]
    second = [r.metrics.as_dict() for r in run_offline_benchmark()]

    assert first == second


def test_normal_question_completes_and_meets_criteria() -> None:
    results = run_offline_benchmark()

    assert results[0].meets_criteria, results[0].notes
    assert results[0].metrics.status == "completed"
    assert results[0].metrics.citations_valid is True


def test_provider_failure_question_still_reports_honestly() -> None:
    results = run_offline_benchmark()

    failing = results[1]
    # The search provider raised; the run must not be silently "completed" with
    # clean evidence.
    assert failing.metrics.status in ("completed", "partial")
    if failing.metrics.status == "completed":
        assert failing.metrics.limitations >= 1
    assert failing.meets_criteria, failing.notes


def test_over_calling_model_is_stopped_at_the_iteration_bound() -> None:
    results = run_offline_benchmark()

    over = results[2]
    assert over.metrics.termination_reason == "max_iterations"
    assert over.metrics.status == "partial"
    assert over.meets_criteria, over.notes


def test_every_benchmark_result_declares_the_criteria() -> None:
    for result in run_offline_benchmark():
        assert result.criteria == BENCHMARK_CRITERIA


def test_benchmark_never_labels_partial_work_completed() -> None:
    for result in run_offline_benchmark():
        if result.metrics.termination_reason != "completed":
            assert result.metrics.status != "completed"


# --- helpers -----------------------------------------------------------------


class _search_provider:
    """Callable-style fake returning one Atlas result."""

    def __init__(self) -> None:
        self.results = [
            SearchResult(
                title="Atlas overview",
                url="https://example.com/atlas",
                snippet="Atlas is a single-agent research assistant.",
            )
        ]

    def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:  # noqa: ARG002
        return self.results


def _tool_call(query: str):
    import json

    from agent007.models import ToolCall

    return ToolCall(
        call_id=f"c_{query}",
        name="web_search",
        arguments={"query": query},
        raw_arguments=json.dumps({"query": query}),
    )


def _model_search_then_answer() -> FakeModelAdapter:
    return FakeModelAdapter(
        ModelTurn(tool_calls=(_tool_call("007"),)),
        ModelTurn(text="Atlas is a bounded single-agent research assistant."),
    )


def test_benchmark_run_never_raises_for_provider_errors() -> None:
    class Angry:
        def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
            raise SearchProviderError("everything is broken")

    model = FakeModelAdapter(
        ModelTurn(tool_calls=(_tool_call("x"),)),
        ModelTurn(text="answer"),
    )

    results = run_benchmark([("q", model, Angry())], Settings())

    assert len(results) == 1
    assert results[0].metrics.tool_calls == 1


def test_measure_counts_only_registered_sources() -> None:
    model = FakeModelAdapter(ModelTurn(text="no research"))

    metrics = measure(run_research("q", Settings(), model=model))

    assert metrics.sources_registered == 0
    assert metrics.findings == 0
    assert metrics.citations_valid is True  # nothing cited, nothing invalid


def test_termination_reason_enum_is_summarized_as_its_value() -> None:
    from agent007.errors import ModelProviderError

    model = FakeModelAdapter(ModelProviderError("boom"))

    metrics = measure(run_research("q", Settings(), model=model))

    assert metrics.termination_reason == TerminationReason.MODEL_ERROR.value
