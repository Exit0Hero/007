"""Tests for evaluation results, reviews, and metrics (Sprint 8, US-804/US-806).

The central invariant: nothing becomes ``pass`` without a recorded human
review, and a metric without observations is ``unavailable`` — never ``0``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from atlas.errors import DatasetError
from atlas.evalmetrics import compute_metrics
from atlas.evalreport import (
    CaseResult,
    EvalRun,
    ReviewRecord,
    apply_reviews,
    load_reviews,
    provider_failure_result,
    redact_secrets,
)

#: The only fields a fresh result may carry for judgement questions.
FRESH = {
    "case_id": "EV-GEN-001",
    "question": "A question?",
    "category": "general_factual",
    "difficulty": "easy",
    "evaluated_at": "2026-10-25T00:00:00+00:00",
    "mode": "offline_fixture",
}


def case_result(**overrides: Any) -> CaseResult:
    payload: dict[str, Any] = {**FRESH, **overrides}
    return CaseResult.model_validate(payload)


def review(**overrides: Any) -> ReviewRecord:
    payload: dict[str, Any] = {"case_id": "EV-GEN-001", **overrides}
    return ReviewRecord.model_validate(payload)


def run_with(cases: list[CaseResult]) -> EvalRun:
    return EvalRun(
        run_id="eval-test",
        generated_at="2026-10-25T00:00:00+00:00",
        mode="offline_fixture",
        dataset_version="1.0.0",
        dataset_path="evaluation_dataset/cases.json",
        model_id="fixture",
        search_provider="fixture",
        cases=tuple(cases),
        metrics=tuple(m.as_dict() for m in compute_metrics(cases)),
    )


# --- US-804: honest statuses -------------------------------------------------


def test_fresh_result_is_unverified_for_judgement_fields() -> None:
    result = case_result()
    assert result.factual_accuracy == "needs_review"
    assert result.completeness_relevance == "needs_review"
    assert result.review is None


def test_fresh_result_cannot_claim_verified_accuracy() -> None:
    with pytest.raises(ValidationError, match="cannot pass before a review"):
        case_result(factual_accuracy="pass")


def test_fresh_result_cannot_claim_verified_completeness() -> None:
    with pytest.raises(ValidationError, match="cannot pass before a review"):
        case_result(completeness_relevance="pass")


def test_recorded_review_upgrades_the_judgement_fields() -> None:
    result = case_result().apply_review(review(factual_accuracy="pass"))
    assert result.factual_accuracy == "pass"
    assert result.completeness_relevance == "needs_review"
    assert result.review is not None


def test_applying_reviews_rejects_unknown_case_ids() -> None:
    with pytest.raises(DatasetError, match="unknown case ids"):
        apply_reviews([case_result()], [review(case_id="EV-SCI-001")])


def test_applying_reviews_leaves_other_cases_untouched() -> None:
    results = apply_reviews([case_result()], [review(factual_accuracy="pass")])
    assert results[0].factual_accuracy == "pass"


def test_unknown_review_status_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "reviews.json"
    target.write_text(
        json.dumps({"reviews": [{"case_id": "EV-GEN-001", "factual_accuracy": "maybe"}]}),
        encoding="utf-8",
    )
    with pytest.raises(DatasetError, match="invalid review"):
        load_reviews(target)


def test_malformed_reviews_file_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "reviews.json"
    target.write_text("{oops", encoding="utf-8")
    with pytest.raises(DatasetError, match="not valid JSON"):
        load_reviews(target)


def test_reviews_without_a_list_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "reviews.json"
    target.write_text(json.dumps({"cases": []}), encoding="utf-8")
    with pytest.raises(DatasetError, match="reviews"):
        load_reviews(target)


def test_review_claim_counts_must_be_consistent() -> None:
    with pytest.raises(ValidationError, match="reviewed_claims"):
        review(unsupported_claims=1)


def test_a_source_cannot_be_both_supported_and_unsupported() -> None:
    with pytest.raises(ValidationError, match="cannot be both"):
        review(supported_source_ids=("S1",), unsupported_source_ids=("S1",))


def test_load_reviews_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "reviews.json"
    target.write_text(
        json.dumps(
            {
                "reviews": [
                    {
                        "case_id": "EV-GEN-001",
                        "factual_accuracy": "pass",
                        "completeness_relevance": "fail",
                        "reviewer": "tester",
                        "reviewed_claims": 4,
                        "unsupported_claims": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    records = load_reviews(target)
    assert len(records) == 1
    assert records[0].factual_accuracy == "pass"
    assert records[0].unsupported_claims == 1


# --- artifacts (US-804 criterion 1) ------------------------------------------


def test_run_writes_json_and_markdown_artifacts(tmp_path: Path) -> None:
    run = run_with([case_result()])
    json_path = run.write_json(tmp_path / "eval_results.json")
    md_path = tmp_path / "eval_summary.md"
    md_path.write_text(run.summary_markdown(), encoding="utf-8")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["cases"][0]["case_id"] == "EV-GEN-001"
    markdown = md_path.read_text(encoding="utf-8")
    assert "## Metrics" in markdown
    assert "## Reviewer workflow" in markdown
    assert "## What this evaluation cannot establish" in markdown


def test_summary_reports_every_case_field_required_by_the_brief(tmp_path: Path) -> None:
    markdown = run_with([case_result()]).summary_markdown()
    for field in (
        "EV-GEN-001",
        "2026-10-25T00:00:00+00:00",
        "offline_fixture",
        "citation resolution",
        "evidence excerpts",
        "factual accuracy",
        "completeness/relevance",
        "not recorded",
    ):
        assert field in markdown


def test_results_roundtrip_through_json(tmp_path: Path) -> None:
    run = run_with([case_result(citation_resolution="pass")])
    path = run.write_json(tmp_path / "eval_results.json")
    loaded = EvalRun.read_json(path)
    assert loaded.cases[0].citation_resolution == "pass"
    assert loaded.cases[0].factual_accuracy == "needs_review"


def test_reading_invalid_results_is_a_dataset_error(tmp_path: Path) -> None:
    target = tmp_path / "eval_results.json"
    target.write_text("{bad", encoding="utf-8")
    with pytest.raises(DatasetError, match="not valid JSON"):
        EvalRun.read_json(target)


# --- secret redaction (US-805 criterion 3) -----------------------------------


def test_secrets_are_redacted_from_recorded_text() -> None:
    secret = "sk-test-1234567890"
    message = f"provider said 401 for key {secret}"
    cleaned = redact_secrets(message, (secret,))
    assert secret not in cleaned
    assert "[redacted]" in cleaned


def test_provider_failure_result_marks_failure_not_quality() -> None:
    from atlas.evalset import load_dataset

    case = load_dataset().select(["EV-GEN-001"])[0]
    secret = "sk-test-abcdef"
    result = provider_failure_result(
        case,
        mode="live",
        model_id="m",
        search_provider="exa",
        limitations=("bounded",),
        message=f"run raised RuntimeError: bad key {secret}",
        secrets=(secret,),
    )
    assert result.provider_failure is True
    assert result.completion_status is None
    assert result.factual_accuracy == "needs_review"
    assert secret not in " ".join(result.failure_reasons)


# --- US-806: metrics ---------------------------------------------------------


def test_metrics_with_no_results_are_unavailable_not_zero() -> None:
    metrics_list = compute_metrics([])
    assert metrics_list, "the metric set must never be empty"
    for metric in metrics_list:
        assert metric.value is None, metric.id
        assert metric.unavailable is True
        assert not metric.note.endswith("= 0")
        # a metric with no observations reports 0 observations, not 0 as a value
        if metric.id != "estimated_cost":
            assert metric.denominator in (0, None), metric.id


def test_every_metric_shows_working() -> None:
    for metric in compute_metrics([case_result(completion_status="completed")]):
        payload = metric.as_dict()
        assert "numerator" in payload
        assert "denominator" in payload
        assert "unknown" in payload
        assert "value" in payload
        assert "note" in payload


def test_completion_rate_counts_only_runs_that_produced_a_report() -> None:
    results = [
        case_result(completion_status="completed"),
        case_result(case_id="EV-GEN-002", completion_status="partial"),
        case_result(case_id="EV-GEN-003", completion_status=None),
    ]
    completion = next(m for m in compute_metrics(results) if m.id == "completion_rate")
    assert completion.numerator == 1
    assert completion.denominator == 2
    assert completion.unknown == 1
    assert completion.value == pytest.approx(0.5)


def test_accuracy_is_unavailable_until_a_review_exists() -> None:
    results = [case_result(completion_status="completed")]
    accuracy = next(m for m in compute_metrics(results) if m.id == "factual_accuracy")
    assert accuracy.value is None
    assert accuracy.unknown == 1


def test_accuracy_counts_reviewed_cases_only() -> None:
    results = [
        case_result().apply_review(review(factual_accuracy="pass")),
        case_result(case_id="EV-GEN-002"),
    ]
    accuracy = next(m for m in compute_metrics(results) if m.id == "factual_accuracy")
    assert accuracy.numerator == 1
    assert accuracy.denominator == 1
    assert accuracy.unknown == 1
    assert accuracy.value == pytest.approx(1.0)


def test_failed_review_lowers_accuracy() -> None:
    results = [
        case_result().apply_review(review(factual_accuracy="pass")),
        case_result(case_id="EV-GEN-002").apply_review(
            ReviewRecord(case_id="EV-GEN-002", factual_accuracy="fail")
        ),
    ]
    accuracy = next(m for m in compute_metrics(results) if m.id == "factual_accuracy")
    assert accuracy.value == pytest.approx(0.5)


def test_unsupported_claim_rate_uses_reviewed_claims_only() -> None:
    results = [
        case_result().apply_review(
            review(reviewed_claims=4, unsupported_claims=1, factual_accuracy="fail")
        ),
        case_result(case_id="EV-GEN-002"),  # unreviewed: not counted at all
    ]
    metric = next(m for m in compute_metrics(results) if m.id == "unsupported_claim_rate")
    assert metric.numerator == 1
    assert metric.denominator == 4
    assert metric.unknown == 1
    assert metric.value == pytest.approx(0.25)


def test_completeness_metric_requires_review_data() -> None:
    unreviewed = [case_result()]
    metric = next(m for m in compute_metrics(unreviewed) if m.id == "completeness_relevance")
    assert metric.value is None

    reviewed = [case_result().apply_review(review(completeness_relevance="pass"))]
    metric = next(m for m in compute_metrics(reviewed) if m.id == "completeness_relevance")
    assert metric.value == pytest.approx(1.0)


def test_provider_failure_rate_counts_recorded_failures() -> None:
    results = [
        case_result(provider_failure=True),
        case_result(case_id="EV-GEN-002", provider_failure=False),
    ]
    metric = next(m for m in compute_metrics(results) if m.id == "provider_failure_rate")
    assert metric.numerator == 1
    assert metric.denominator == 2


def test_token_usage_is_unavailable_when_nothing_reported_it() -> None:
    results = [case_result(completion_status="completed")]
    for metric_id in ("token_usage_average", "token_usage_median"):
        metric = next(m for m in compute_metrics(results) if m.id == metric_id)
        assert metric.value is None
        assert metric.denominator == 0
        assert metric.unknown == 1


def test_token_usage_is_reported_when_the_provider_supplied_it() -> None:
    results = [
        case_result(token_usage={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}),
        case_result(
            case_id="EV-GEN-002",
            token_usage={"input_tokens": 10, "output_tokens": 40, "total_tokens": 50},
        ),
        case_result(case_id="EV-GEN-003", token_usage=None),
    ]
    average = next(m for m in compute_metrics(results) if m.id == "token_usage_average")
    median = next(m for m in compute_metrics(results) if m.id == "token_usage_median")
    assert average.value == pytest.approx(40.0)
    assert median.value == pytest.approx(40.0)
    assert average.unknown == 1  # the run that reported nothing


def test_cost_is_never_invented() -> None:
    results = [case_result(token_usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})]
    cost = next(m for m in compute_metrics(results) if m.id == "estimated_cost")
    assert cost.value is None
    assert "never estimated" in cost.note


def test_citation_metrics_use_item_counts_from_checks() -> None:
    results = [
        case_result(
            completion_status="completed",
            checks={
                "counts": {"cited": 4, "resolved": 3, "excerpts_checked": 4, "excerpts_matched": 4}
            },
        )
    ]
    resolution = next(m for m in compute_metrics(results) if m.id == "citation_resolution_rate")
    excerpts = next(m for m in compute_metrics(results) if m.id == "excerpt_verification_rate")
    assert resolution.value == pytest.approx(0.75)
    assert excerpts.value == pytest.approx(1.0)
