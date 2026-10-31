"""Tests for user-configurable research depth (US-703, Sprint 7).

Acceptance criteria are in `docs/ROADMAP.md` under US-703. Every test runs
offline with an injected fake runner (US-503); no provider is contacted.

The contract under test: a bad depth option is a *usage error* — exit code 2 —
whether argparse rejects it (``SystemExit``) or the settings validator does
(returned code), and no research may run in either case.
"""

from __future__ import annotations

import contextlib
import io

import pytest

from agent007.config import Settings
from agent007.main import EXIT_CONFIGURATION_ERROR, EXIT_OK, EXIT_USAGE, main
from agent007.models import ResearchState, TerminationReason
from agent007.pipeline import ResearchOutcome
from agent007.report import Report
from agent007.sources import SourceRegistry

LIVE_ENV = {
    "ATLAS_MODE": "live",
    "ATLAS_MODEL": "test-model",
    "OPENAI_API_KEY": "sk-test-placeholder-key",
    "TAVILY_API_KEY": "tvly-placeholder",
}

#: Settings objects actually handed to the research runner during a test.
seen_settings: list[Settings] = []


def _fake_research(question: str, settings: Settings) -> ResearchOutcome:
    seen_settings.append(settings)
    state = ResearchState(question=question, final_text="answer")
    state.finish(TerminationReason.COMPLETED)
    return ResearchOutcome(
        state=state,
        report=Report(question=question, summary="answer", status="completed"),
        sources=SourceRegistry(),
    )


def invoke(argv: list[str], environ: dict[str, str]) -> tuple[int, str, str]:
    """Run main() with the fake runner; normalise SystemExit to an exit code."""
    seen_settings.clear()
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv, environ, research=_fake_research)
        except SystemExit as exc:  # argparse usage errors
            code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


def offline(argv: list[str]) -> tuple[int, str, str]:
    """Run main() with no environment at all (offline mode, no fake runner)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv, environ={})
        except SystemExit as exc:
            code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


# --- criterion 1: flags are accepted -----------------------------------------


def test_all_three_flags_are_accepted() -> None:
    code, _, _ = invoke(
        ["What is Atlas?", "--max-iterations", "3", "--max-results", "2", "--deadline", "30"],
        dict(LIVE_ENV),
    )

    assert code == EXIT_OK
    assert len(seen_settings) == 1


def test_deadline_accepts_fractional_seconds() -> None:
    code, _, _ = invoke(["What is Atlas?", "--deadline", "12.5"], dict(LIVE_ENV))

    assert code == EXIT_OK
    assert seen_settings[0].deadline_seconds == 12.5


# --- criterion 2: override is per-run, environment stays authoritative -------


def test_absent_flags_leave_configured_values_untouched() -> None:
    env = dict(LIVE_ENV)
    env["ATLAS_MAX_ITERATIONS"] = "5"

    invoke(["What is Atlas?"], env)

    assert seen_settings[0].max_iterations == 5


def test_flag_overrides_environment_for_one_run_only() -> None:
    env = dict(LIVE_ENV)
    env["ATLAS_MAX_ITERATIONS"] = "5"

    invoke(["What is Atlas?", "--max-iterations", "2"], env)
    first = seen_settings[0].max_iterations
    invoke(["What is Atlas?"], env)
    second = seen_settings[0].max_iterations

    assert (first, second) == (2, 5)  # environment is authoritative again


def test_override_does_not_mutate_the_settings_class_defaults() -> None:
    invoke(["What is Atlas?", "--max-iterations", "2"], dict(LIVE_ENV))

    assert Settings().max_iterations == 8


# --- criterion 3: bounds enforced like Settings, exit code 2 -----------------


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--max-iterations", "0"),
        ("--max-iterations", "-1"),
        ("--max-iterations", "65"),
        ("--max-results", "0"),
        ("--max-results", "51"),
        ("--deadline", "0"),
        ("--deadline", "-5"),
        ("--deadline", "4000"),
    ],
)
def test_out_of_range_depth_values_are_usage_errors(flag: str, value: str) -> None:
    code, _, err = invoke(["What is Atlas?", flag, value], dict(LIVE_ENV))

    assert code == EXIT_USAGE
    assert seen_settings == []  # no research ran
    assert "error" in err.lower()


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--max-iterations", "many"),
        ("--max-results", "lots"),
        ("--deadline", "soon"),
    ],
)
def test_non_numeric_depth_values_are_usage_errors(flag: str, value: str) -> None:
    code, _, _ = invoke(["What is Atlas?", flag, value], dict(LIVE_ENV))

    assert code == EXIT_USAGE
    assert seen_settings == []


def test_range_error_message_names_the_offending_field() -> None:
    _, _, err = invoke(["What is Atlas?", "--max-iterations", "0"], dict(LIVE_ENV))

    assert "max_iterations" in err


def test_no_research_runs_on_rejection() -> None:
    invoke(["What is Atlas?", "--max-results", "0"], dict(LIVE_ENV))

    assert seen_settings == []


def test_error_output_contains_no_credentials() -> None:
    _, _, err = invoke(["What is Atlas?", "--max-iterations", "0"], dict(LIVE_ENV))

    assert "sk-test-placeholder-key" not in err
    assert "tvly-placeholder" not in err


def test_valid_boundary_values_are_accepted() -> None:
    for flag, value in (
        ("--max-iterations", "1"),
        ("--max-iterations", "64"),
        ("--max-results", "1"),
        ("--max-results", "50"),
        ("--deadline", "0.5"),
        ("--deadline", "3600"),
    ):
        code, _, _ = invoke(["What is Atlas?", flag, value], dict(LIVE_ENV))
        assert code == EXIT_OK, (flag, value)


# --- criterion 4: effective values are visible -------------------------------


def test_offline_status_prints_effective_depth() -> None:
    code, out, _ = offline(["What is Atlas?", "--max-iterations", "3", "--deadline", "45"])

    assert code == EXIT_OK
    assert "depth: max_iterations=3" in out
    assert "max_results=5" in out  # default, since flag was absent
    assert "deadline=45.0s" in out


def test_run_metadata_prints_effective_depth() -> None:
    code, out, _ = invoke(["What is Atlas?", "--max-results", "2"], dict(LIVE_ENV))

    assert code == EXIT_OK
    assert "depth: max_iterations=8" in out
    assert "max_results=2" in out


# --- criterion 5: offline mode validates flags without providers ------------


def test_offline_mode_rejects_bad_flags_without_any_provider() -> None:
    code, _, err = offline(["What is Atlas?", "--deadline", "0"])

    assert code == EXIT_USAGE
    assert "deadline_seconds" in err


def test_offline_mode_with_valid_flags_never_researches() -> None:
    code, out, _ = offline(["What is Atlas?", "--max-iterations", "2"])

    assert code == EXIT_OK
    assert "requires ATLAS_MODE=live" in out
    assert "max_iterations=2" in out


def test_configuration_error_takes_precedence_over_a_bad_flag() -> None:
    """Keys are checked first: a misconfigured run never reaches flag validation."""
    code, _, err = invoke(["What is Atlas?", "--max-iterations", "0"], {"ATLAS_MODE": "live"})

    assert code == EXIT_CONFIGURATION_ERROR
    assert "requires" in err
