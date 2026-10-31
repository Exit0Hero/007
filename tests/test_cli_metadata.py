"""Tests for CLI run metadata reporting (US-603, Sprint 6).

Token usage is printed only when the provider actually reported it; otherwise
the CLI says it is unavailable rather than estimating. Fully offline.
"""

from __future__ import annotations

import contextlib
import io

from agent007.main import EXIT_OK, main
from agent007.models import ResearchState, TerminationReason, TokenUsage, ToolObservation
from agent007.pipeline import ResearchOutcome
from agent007.report import Report
from agent007.sources import SourceRegistry

LIVE_ENV = {
    "ATLAS_MODE": "live",
    "ATLAS_MODEL": "test-model",
    "OPENAI_API_KEY": "sk-test-placeholder-key",
    "TAVILY_API_KEY": "tvly-test-placeholder",
}


def outcome_with(state: ResearchState) -> ResearchOutcome:
    return ResearchOutcome(
        state=state,
        report=Report(
            question=state.question,
            summary=state.final_text or "",
            status=state.status or "failed",
        ),
        sources=SourceRegistry(),
    )


def run(research) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["What is Atlas?"], dict(LIVE_ENV), research=research)
    return code, out.getvalue(), err.getvalue()


def completed_state(**kwargs: object) -> ResearchState:
    state = ResearchState(question="What is Atlas?", final_text="answer", **kwargs)  # type: ignore[arg-type]
    state.finish(TerminationReason.COMPLETED)
    return state


def test_run_metadata_reports_iteration_and_call_counts() -> None:
    state = completed_state()
    state.iterations = 1
    state.observations.append(
        ToolObservation(call_id="c1", name="web_search", ok=True, output="results")
    )

    code, out, _ = run(lambda q, s: outcome_with(state))

    assert code == EXIT_OK
    assert "run metadata:" in out
    assert "tool_calls=1" in out
    assert "iterations=1" in out


def test_token_usage_is_reported_when_the_provider_supplied_it() -> None:
    state = completed_state()
    state.token_usage = TokenUsage(input_tokens=120, output_tokens=45, total_tokens=165)

    _, out, _ = run(lambda q, s: outcome_with(state))

    assert "input=120" in out
    assert "output=45" in out
    assert "total=165" in out


def test_missing_token_usage_is_reported_as_unavailable_not_zero() -> None:
    state = completed_state()

    _, out, _ = run(lambda q, s: outcome_with(state))

    assert "token usage: unavailable" in out
    assert "total=0" not in out


def test_refused_and_suppressed_calls_are_reported() -> None:
    state = completed_state()
    state.unsupported_calls = 2
    state.duplicate_calls = 3

    _, out, _ = run(lambda q, s: outcome_with(state))

    assert "unsupported=2" in out
    assert "duplicates_suppressed=3" in out


def test_metadata_is_printed_even_for_incomplete_runs() -> None:
    state = ResearchState(question="What is Atlas?")
    state.finish(TerminationReason.MODEL_ERROR)

    code, out, err = run(lambda q, s: outcome_with(state))

    assert code == 5
    assert "run metadata:" in out
    assert "model_error" in err


def test_partially_reported_usage_lists_only_the_available_fields() -> None:
    state = completed_state()
    state.token_usage = TokenUsage(input_tokens=10)

    _, out, _ = run(lambda q, s: outcome_with(state))

    assert "input=10" in out
    assert "output=" not in out
    assert "total=" not in out


def test_metadata_contains_no_credentials() -> None:
    state = completed_state()

    _, out, err = run(lambda q, s: outcome_with(state))

    assert "sk-test-placeholder-key" not in out + err
    assert "tvly-test-placeholder" not in out + err
