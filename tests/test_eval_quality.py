"""Tests for the deterministic quality checks (Sprint 8, US-802/US-803).

Every check is exercised with fixtures: no credentials, no network, no LLM
judge. Claim support is asserted to stay ``needs_review`` — never a pass.
"""

from __future__ import annotations

import pytest

from atlas.config import Settings
from atlas.errors import CitationValidationError
from atlas.evalreport import result_from_outcome
from atlas.evalset import build_fixture_model, build_fixture_search, load_dataset
from atlas.evaluation import RunMetrics, benchmark_fixtures, run_benchmark
from atlas.models import ResearchState, TerminationReason, ToolObservation
from atlas.pipeline import run_research
from atlas.quality import CHECK_IDS, cited_source_ids, provider_failure, run_checks
from atlas.report import Finding, Report, ReportBuilder
from atlas.sources import SourceRegistry

SETTINGS = Settings.from_env({})


def metrics(**overrides: object) -> RunMetrics:
    base: dict[str, object] = {
        "status": "completed",
        "termination_reason": "completed",
        "tool_calls": 1,
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


class _Conditions:
    allowed_statuses = ("completed", "partial", "failed")
    min_sources = 1
    requires_page_evidence = False
    must_disclose_limitations = False


class _Case:
    """Duck-typed stand-in for EvalCase: conditions plus claim lists."""

    def __init__(
        self,
        conditions: object,
        required: tuple[str, ...] = (),
        prohibited: tuple[str, ...] = (),
    ) -> None:
        self.conditions = conditions
        self.required_claims = required
        self.prohibited_claims = prohibited


def registry_with_evidence() -> tuple[SourceRegistry, str]:
    registry = SourceRegistry()
    source_id = registry.register(
        "https://example.org/quality",
        title="Quality reference",
        search_snippet="Water boils at 100 degrees Celsius at standard pressure.",
    )
    return registry, source_id


def valid_report(registry: SourceRegistry, source_id: str) -> Report:
    builder = ReportBuilder(registry)
    builder.add_limitation("Automated report; verify against sources.")
    builder.add_finding(
        "Water boils at 100 degrees Celsius at standard pressure.",
        citations=(source_id,),
        excerpt="Water boils at 100 degrees Celsius at standard pressure.",
    )
    return builder.build(
        question="What is the boiling point of water?",
        summary="Water boils at 100 degrees Celsius at standard pressure.",
        status="completed",
        termination_reason=TerminationReason.COMPLETED,
    )


def state_with(reason: TerminationReason, observations: list[ToolObservation]) -> ResearchState:
    state = ResearchState(question="q")
    state.observations = observations
    state.finish(reason)
    return state


# --- US-802: the eight checks ------------------------------------------------


def test_check_ids_are_stable() -> None:
    assert len(CHECK_IDS) == 8
    assert "citation_validation_replay" in CHECK_IDS


def test_valid_report_passes_every_deterministic_check() -> None:
    registry, source_id = registry_with_evidence()
    checks = run_checks(valid_report(registry, source_id), registry, metrics())
    assert checks.all_deterministic_checks_pass, checks.failures
    assert checks.citation_resolution_status == "pass"
    assert checks.evidence_support_status == "pass"


def test_report_without_citations_is_unknown_not_passed() -> None:
    registry = SourceRegistry()
    report = Report(
        question="q",
        summary="An answer with no citations at all.",
        status="completed",
        termination_reason="completed",
    )
    checks = run_checks(report, registry, metrics(sources_registered=0))
    assert checks.get("citations_resolve").status == "unknown"
    assert checks.get("excerpt_support").status == "unknown"
    assert checks.citation_resolution_status == "unknown"
    assert checks.evidence_support_status == "unknown"
    # no citations at all must never read as "everything resolved"
    assert checks.citation_resolution_status != "pass"


def test_unknown_source_id_fails_resolution_and_replay_checks() -> None:
    registry, source_id = registry_with_evidence()
    report = valid_report(registry, source_id)
    fabricated = report.model_copy(
        update={
            "findings": report.findings
            + (
                Finding(
                    text="A claim citing a source that does not exist.",
                    citations=("S999",),
                    evidence=(
                        {
                            "source_id": "S999",
                            "excerpt": "Quoted from a source that does not exist.",
                            "kind": "search_snippet",
                        },
                    ),
                ),
            )
        }
    )
    checks = run_checks(fabricated, registry, metrics())
    assert checks.get("citations_resolve").status == "fail"
    assert "S999" in checks.get("citations_resolve").detail
    assert checks.get("evidence_refs_exist").status == "fail"
    assert checks.get("citation_validation_replay").status == "fail"
    assert checks.citation_resolution_status == "fail"


def test_incorrect_excerpt_fails_excerpt_support() -> None:
    registry, source_id = registry_with_evidence()
    report = valid_report(registry, source_id)
    invented = report.model_copy(
        update={
            "findings": (
                Finding(
                    text="An invented quotation.",
                    citations=(source_id,),
                    evidence=(
                        {
                            "source_id": source_id,
                            "excerpt": "This sentence was never stored anywhere.",
                            "kind": "search_snippet",
                        },
                    ),
                ),
            )
        }
    )
    checks = run_checks(invented, registry, metrics())
    assert checks.get("excerpt_support").status == "fail"
    assert checks.get("citation_validation_replay").status == "fail"
    assert checks.evidence_support_status == "fail"


def test_partial_run_marked_complete_fails_status_honesty() -> None:
    registry, source_id = registry_with_evidence()
    checks = run_checks(
        valid_report(registry, source_id),
        registry,
        metrics(status="completed", termination_reason="max_iterations"),
    )
    result = checks.get("status_honesty")
    assert result.status == "fail"
    assert "completed status without a completed termination reason" in result.detail


def test_partial_run_without_disclosure_fails_the_disclosure_check() -> None:
    registry, source_id = registry_with_evidence()
    report = valid_report(registry, source_id).model_copy(update={"limitations": ()})
    checks = run_checks(
        report,
        registry,
        metrics(status="partial", termination_reason="max_iterations", limitations=0),
    )
    assert checks.get("disclosure").status == "fail"


def test_missing_required_claim_fails_case_conditions() -> None:
    registry, source_id = registry_with_evidence()
    report = valid_report(registry, source_id)
    checks = run_checks(
        report, registry, metrics(), case=_Case(_Conditions(), required=("a claim",))
    )
    assert checks.get("case_conditions").status == "fail"
    assert "required claim missing" in checks.get("case_conditions").detail


def test_prohibited_claim_fails_case_conditions() -> None:
    registry, source_id = registry_with_evidence()
    report = valid_report(registry, source_id)
    checks = run_checks(
        report, registry, metrics(), case=_Case(_Conditions(), prohibited=("100 degrees",))
    )
    assert checks.get("case_conditions").status == "fail"
    assert "prohibited claim present" in checks.get("case_conditions").detail


def test_case_conditions_are_unknown_without_a_case() -> None:
    registry, source_id = registry_with_evidence()
    checks = run_checks(valid_report(registry, source_id), registry, metrics())
    assert checks.get("case_conditions").status == "unknown"
    # unknown is not a failure, but it is also not a pass
    assert checks.get("case_conditions").status != "pass"


def test_fabricated_citation_is_rejected_by_the_builder() -> None:
    builder = ReportBuilder(SourceRegistry())
    with pytest.raises(CitationValidationError, match="do not resolve"):
        builder.add_finding("claim", citations=("S404",))


def test_invented_excerpt_is_rejected_by_the_builder() -> None:
    registry, source_id = registry_with_evidence()
    builder = ReportBuilder(registry)
    with pytest.raises(CitationValidationError, match="not present in the stored evidence"):
        builder.add_finding(
            "claim",
            citations=(source_id,),
            excerpt="An excerpt that was never stored.",
        )


def test_cited_source_ids_deduplicates_and_keeps_order() -> None:
    registry, source_id = registry_with_evidence()
    report = valid_report(registry, source_id)
    assert cited_source_ids(report) == [source_id]


# --- US-803: three-level citation verdicts -----------------------------------


def test_resolving_citation_still_needs_review_for_claim_support() -> None:
    registry, source_id = registry_with_evidence()
    checks = run_checks(valid_report(registry, source_id), registry, metrics())
    verdict = next(v for v in checks.citations if v.source_id == source_id)
    assert verdict.resolves == "pass"
    assert verdict.excerpt_matches_evidence == "pass"
    # a URL that resolves and an excerpt that matches never imply claim support
    assert verdict.supports_claim == "needs_review"
    assert verdict.supports_claim != "pass"


def test_every_citation_verdict_starts_as_needs_review() -> None:
    registry, source_id = registry_with_evidence()
    checks = run_checks(valid_report(registry, source_id), registry, metrics())
    assert checks.citations
    assert all(v.supports_claim == "needs_review" for v in checks.citations)


# --- provider failure classification (US-805/US-807) -------------------------


def test_model_error_is_a_provider_failure() -> None:
    assert provider_failure(state_with(TerminationReason.MODEL_ERROR, [])) is True


def test_failed_executed_tool_is_a_provider_failure() -> None:
    observation = ToolObservation(
        call_id="c1", name="web_search", ok=False, output="quota exceeded"
    )
    assert provider_failure(state_with(TerminationReason.COMPLETED, [observation])) is True


def test_refused_tool_is_not_a_provider_failure() -> None:
    observation = ToolObservation(
        call_id="c1",
        name="not_a_tool",
        ok=False,
        output="unknown tool",
        executed=False,
        refusal="unknown_tool",
    )
    assert provider_failure(state_with(TerminationReason.COMPLETED, [observation])) is False


def test_successful_run_is_not_a_provider_failure() -> None:
    observation = ToolObservation(call_id="c1", name="web_search", ok=True, output="2 results")
    assert provider_failure(state_with(TerminationReason.COMPLETED, [observation])) is False


# --- determinism and offline execution (US-802 criterion 2) ------------------


def _offline_result(case_id: str):
    case = load_dataset().select([case_id])[0]
    outcome = run_research(
        case.question,
        SETTINGS,
        model=build_fixture_model(case.fixture),
        search=build_fixture_search(case.fixture),
    )
    return result_from_outcome(
        case,
        outcome,
        mode="offline_fixture",
        model_id="fixture",
        search_provider="fixture",
        max_iterations=SETTINGS.max_iterations,
        limitations=(),
    )


def test_offline_case_evaluation_is_deterministic() -> None:
    first = _offline_result("EV-GEN-001")
    second = _offline_result("EV-GEN-001")
    assert first.checks == second.checks
    assert first.citation_resolution == second.citation_resolution
    assert first.completion_status == "completed"


def test_provider_failure_case_is_recorded_not_raised() -> None:
    result = _offline_result("EV-INC-003")
    assert result.provider_failure is True
    assert result.completion_status == "partial"
    assert result.factual_accuracy == "needs_review"


def test_sprint6_benchmark_still_passes_after_the_extraction() -> None:
    """The shared excerpt rule must not have changed Sprint 6 behaviour."""
    results = run_benchmark(benchmark_fixtures(), SETTINGS)
    assert results
    assert all(result.meets_criteria for result in results)
