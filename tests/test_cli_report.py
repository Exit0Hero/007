"""Tests for live-mode CLI behaviour and report output (US-401, US-502).

The research runner is always injected, so no provider is constructed and no
paid API call is possible (US-503). Configuration is validated exactly as the
real CLI does; only the execution step is faked.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

from atlas.config import Settings
from atlas.errors import ModelProviderError
from atlas.main import (
    EXIT_CONFIGURATION_ERROR,
    EXIT_OK,
    EXIT_RESEARCH_INCOMPLETE,
    main,
)
from atlas.models import ResearchState, TerminationReason
from atlas.pipeline import ResearchOutcome
from atlas.report import Report
from atlas.sources import SourceRegistry

LIVE_ENV = {
    "ATLAS_MODE": "live",
    "ATLAS_MODEL": "test-model",
    "OPENAI_API_KEY": "sk-test-placeholder-key",
    "TAVILY_API_KEY": "tvly-test-placeholder",
}


def run(
    argv: list[str],
    environ: dict[str, str],
    research=None,
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv, environ, research=research)
    return code, out.getvalue(), err.getvalue()


def completed_outcome(question: str = "What is Atlas?") -> ResearchOutcome:
    state = ResearchState(question=question, final_text="Atlas is a research assistant.")
    state.finish(TerminationReason.COMPLETED)
    return ResearchOutcome(
        state=state,
        report=Report(
            question=question, summary="Atlas is a research assistant.", status="completed"
        ),
        sources=SourceRegistry(),
    )


def partial_outcome(question: str = "What is Atlas?") -> ResearchOutcome:
    state = ResearchState(question=question)
    state.finish(TerminationReason.MAX_ITERATIONS)
    return ResearchOutcome(
        state=state,
        report=Report(
            question=question, summary="", status="partial", termination_reason="max_iterations"
        ),
        sources=SourceRegistry(),
    )


# --- live mode with an injected runner ---------------------------------------


def test_live_mode_with_completed_run_exits_zero_and_prints_report() -> None:
    code, out, err = run(
        ["What is Atlas?"], dict(LIVE_ENV), research=lambda q, s: completed_outcome(q)
    )

    assert code == EXIT_OK
    assert err == ""
    assert "# Research report" in out
    assert "## Summary" in out
    assert "Atlas is a research assistant." in out


def test_report_can_be_written_to_a_path(tmp_path: Path) -> None:
    target = tmp_path / "report.md"

    code, out, err = run(
        ["What is Atlas?", "--output", str(target)],
        dict(LIVE_ENV),
        research=lambda q, s: completed_outcome(q),
    )

    assert code == EXIT_OK
    assert str(target) in out
    assert err == ""
    written = target.read_text(encoding="utf-8")
    assert "# Research report" in written
    assert written == completed_outcome().report.to_markdown()


def test_short_output_flag_is_accepted(tmp_path: Path) -> None:
    target = tmp_path / "r.md"

    code, _, _ = run(
        ["What is Atlas?", "-o", str(target)],
        dict(LIVE_ENV),
        research=lambda q, s: completed_outcome(q),
    )

    assert code == EXIT_OK
    assert target.exists()


def test_partial_run_exits_5_and_says_so() -> None:
    code, out, err = run(
        ["What is Atlas?"], dict(LIVE_ENV), research=lambda q, s: partial_outcome(q)
    )

    assert code == EXIT_RESEARCH_INCOMPLETE
    assert "**Status:** partial" in out
    assert "max_iterations" in err


def test_runner_exception_is_reported_not_crashed() -> None:
    def boom(question: str, settings: Settings) -> ResearchOutcome:
        raise ModelProviderError("provider unreachable")

    code, _, err = run(["What is Atlas?"], dict(LIVE_ENV), research=boom)

    assert code == EXIT_RESEARCH_INCOMPLETE
    assert "provider unreachable" in err
    assert "Traceback" not in err


def test_unexpected_runner_exception_is_normalized() -> None:
    def boom(question: str, settings: Settings) -> ResearchOutcome:
        raise RuntimeError("internal detail")

    code, _, err = run(["What is Atlas?"], dict(LIVE_ENV), research=boom)

    assert code == EXIT_RESEARCH_INCOMPLETE
    assert "RuntimeError" in err
    assert "internal detail" not in err  # no raw exception detail leaked


def test_unwritable_output_path_is_reported(tmp_path: Path) -> None:
    missing_dir = tmp_path / "nope" / "report.md"

    code, _, err = run(
        ["What is Atlas?", "-o", str(missing_dir)],
        dict(LIVE_ENV),
        research=lambda q, s: completed_outcome(q),
    )

    assert code == EXIT_RESEARCH_INCOMPLETE
    assert "could not write report" in err


# --- live mode without an injected runner (provider construction) -----------


def test_live_mode_with_placeholder_key_is_a_configuration_error() -> None:
    """Placeholder values are treated as absent, so no client is constructed."""
    env = dict(LIVE_ENV)
    env["OPENAI_API_KEY"] = "replace-with-your-openai-api-key"

    code, _, err = run(["What is Atlas?"], env)

    assert code == EXIT_CONFIGURATION_ERROR
    assert "OPENAI_API_KEY" in err


def test_live_mode_without_model_is_a_configuration_error() -> None:
    env = dict(LIVE_ENV)
    env.pop("ATLAS_MODEL")

    code, _, err = run(["What is Atlas?"], env)

    assert code == EXIT_CONFIGURATION_ERROR
    assert "ATLAS_MODEL" in err


def test_invalid_question_is_rejected_before_any_live_execution() -> None:
    called: list[str] = []

    def spy(question: str, settings: Settings) -> ResearchOutcome:
        called.append(question)
        return completed_outcome(question)

    code, _, err = run(["   "], dict(LIVE_ENV), research=spy)

    assert code == 3
    assert called == []


def test_output_is_not_written_when_the_run_never_starts(tmp_path: Path) -> None:
    target = tmp_path / "report.md"

    code, _, _ = run(
        ["What is Atlas?", "-o", str(target)],
        {"ATLAS_MODE": "live", "ATLAS_MODEL": "m"},  # no keys
    )

    assert code == EXIT_CONFIGURATION_ERROR
    assert not target.exists()


# --- secrets never reach output ----------------------------------------------


def test_report_output_contains_no_credentials() -> None:
    env = dict(LIVE_ENV)

    code, out, err = run(["What is Atlas?"], dict(env), research=lambda q, s: completed_outcome(q))

    assert code == EXIT_OK
    assert env["OPENAI_API_KEY"] not in out + err
    assert env["TAVILY_API_KEY"] not in out + err
