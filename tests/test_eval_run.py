"""Tests for the evaluation CLI and its safety bounds (Sprint 8, US-802/805/807).

Offline runs must work with no credentials and no network, and live mode must
refuse to start without explicit configuration.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import dotenv
import pytest

from atlas.evalrun import main, select_cases, smoke_subset
from atlas.evalset import load_dataset


@pytest.fixture()
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any attempt to open a socket fails the test loudly."""

    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("offline evaluation attempted network access")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture()
def no_env_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip provider configuration and stop .env from being read."""
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: None)
    for name in (
        "ATLAS_MODE",
        "ATLAS_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "TAVILY_API_KEY",
        "EXA_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


# --- selection (US-801/US-805) -----------------------------------------------


def test_smoke_subset_is_the_first_case_of_the_first_three_categories() -> None:
    subset = smoke_subset(list(load_dataset().cases))
    assert len(subset) == 3
    assert len({case.category for case in subset}) == 3
    assert subset[0].id == "EV-GEN-001"


def test_selection_rejects_unknown_ids() -> None:
    dataset = load_dataset()
    with pytest.raises(Exception, match="unknown case ids"):
        select_cases(dataset, case_ids=["EV-ZZZ-001"])


# --- offline CLI (US-802) ----------------------------------------------------


def test_list_command_reports_every_case(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list"]) == 0
    output = capsys.readouterr().out
    assert "24 cases" in output
    assert "EV-GEN-001" in output


def test_offline_run_writes_both_artifacts(
    tmp_path: Path, no_network: None, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["run", "--case", "EV-GEN-001", "--out", str(tmp_path)])
    assert code == 0
    results = json.loads((tmp_path / "eval_results.json").read_text(encoding="utf-8"))
    summary = (tmp_path / "eval_summary.md").read_text(encoding="utf-8")

    assert len(results["cases"]) == 1
    assert results["mode"] == "offline_fixture"
    assert results["cases"][0]["factual_accuracy"] == "needs_review"
    assert "## Metrics" in summary
    assert "## Reviewer workflow" in summary
    assert "review: **not recorded**" in summary


def test_offline_run_makes_no_network_calls_without_credentials(
    tmp_path: Path, no_network: None, no_env_credentials: None
) -> None:
    code = main(["run", "--smoke", "--out", str(tmp_path)])
    assert code == 0
    results = json.loads((tmp_path / "eval_results.json").read_text(encoding="utf-8"))
    assert len(results["cases"]) == 3
    assert all(c["mode"] == "offline_fixture" for c in results["cases"])


def test_full_offline_run_records_zero_quality_failures(tmp_path: Path, no_network: None) -> None:
    # EV-INC-003 is scripted to fail at the provider, so the exit code is 2;
    # what matters for acceptance is that no deterministic check fails.
    code = main(["run", "--out", str(tmp_path)])
    assert code == 2
    results = json.loads((tmp_path / "eval_results.json").read_text(encoding="utf-8"))
    assert len(results["cases"]) == 24
    failures = [
        check
        for case in results["cases"]
        for check in (case["checks"] or {}).get("checks", [])
        if check["status"] == "fail"
    ]
    assert failures == []
    provider_failures = [c["case_id"] for c in results["cases"] if c["provider_failure"]]
    assert provider_failures == ["EV-INC-003"]
    # every judgement field is still unreviewed
    assert all(c["factual_accuracy"] == "needs_review" for c in results["cases"])


def test_offline_run_never_leaks_environment_secrets(
    tmp_path: Path, no_network: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-appear")
    monkeypatch.setenv("EXA_API_KEY", "exa-should-never-appear")
    main(["run", "--case", "EV-GEN-001", "--out", str(tmp_path)])
    blob = (tmp_path / "eval_results.json").read_text(encoding="utf-8")
    blob += (tmp_path / "eval_summary.md").read_text(encoding="utf-8")
    assert "sk-should-never-appear" not in blob
    assert "exa-should-never-appear" not in blob


def test_missing_dataset_exits_with_code_4(tmp_path: Path) -> None:
    assert main(["list", "--dataset", str(tmp_path / "nope.json")]) == 4


def test_malformed_dataset_exits_with_code_4(tmp_path: Path) -> None:
    target = tmp_path / "cases.json"
    target.write_text("{broken", encoding="utf-8")
    assert main(["run", "--dataset", str(target), "--out", str(tmp_path)]) == 4


# --- summarize with recorded reviews (US-804/US-806) -------------------------


def test_summarize_applies_recorded_reviews(tmp_path: Path, no_network: None) -> None:
    out = tmp_path / "run"
    assert main(["run", "--case", "EV-GEN-001", "--out", str(out)]) == 0

    reviews = tmp_path / "reviews.json"
    reviews.write_text(
        json.dumps(
            {
                "reviews": [
                    {
                        "case_id": "EV-GEN-001",
                        "factual_accuracy": "pass",
                        "completeness_relevance": "pass",
                        "reviewer": "tester",
                        "reviewed_at": "2026-10-25",
                        "reviewed_claims": 2,
                        "unsupported_claims": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    code = main(
        [
            "summarize",
            "--results",
            str(out / "eval_results.json"),
            "--reviews",
            str(reviews),
            "--out",
            str(tmp_path / "rescored"),
        ]
    )
    assert code == 0
    payload = json.loads((tmp_path / "rescored" / "eval_results.json").read_text(encoding="utf-8"))
    case = payload["cases"][0]
    assert case["factual_accuracy"] == "pass"
    assert case["completeness_relevance"] == "pass"
    metrics = {m["id"]: m for m in payload["metrics"]}
    assert metrics["factual_accuracy"]["value"] == 1.0
    assert metrics["unsupported_claim_rate"]["value"] == 0.0
    # unreviewed metrics stay unavailable even after one review
    assert metrics["estimated_cost"]["value"] is None


def test_summarize_with_unknown_review_status_fails_cleanly(
    tmp_path: Path, no_network: None
) -> None:
    out = tmp_path / "run"
    main(["run", "--case", "EV-GEN-001", "--out", str(out)])
    bad_reviews = tmp_path / "reviews.json"
    bad_reviews.write_text(
        json.dumps({"reviews": [{"case_id": "EV-GEN-001", "factual_accuracy": "maybe"}]}),
        encoding="utf-8",
    )
    code = main(
        [
            "run",
            "--case",
            "EV-GEN-001",
            "--reviews",
            str(bad_reviews),
            "--out",
            str(tmp_path / "again"),
        ]
    )
    assert code == 4


# --- live mode refusal (US-805) ----------------------------------------------


def test_live_run_refuses_without_configuration(
    tmp_path: Path, no_network: None, no_env_credentials: None
) -> None:
    code = main(["run", "--live", "--case", "EV-GEN-001", "--out", str(tmp_path)])
    assert code == 5
    assert not (tmp_path / "eval_results.json").exists()


def test_live_refusal_happens_before_any_provider_is_built(
    no_env_credentials: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from atlas.config import Settings
    from atlas.errors import ConfigurationError
    from atlas.evallive import require_live_opt_in

    settings = Settings.from_env({})
    with pytest.raises(ConfigurationError, match="opt-in"):
        require_live_opt_in(settings, opt_in=False)

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("a provider must not be constructed during a refusal")

    monkeypatch.setattr("atlas.main._build_search_provider", explode, raising=False)
    with pytest.raises(ConfigurationError, match="opt-in"):
        require_live_opt_in(settings, opt_in=False)
