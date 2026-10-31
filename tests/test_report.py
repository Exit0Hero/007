"""Tests for evidence-grounded report generation (US-401, US-402, US-403).

Fully offline: sources are registered directly into a SourceRegistry and no
provider is contacted (US-503).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent007.errors import CitationValidationError
from agent007.models import ResearchState, TerminationReason, ToolObservation
from agent007.report import (
    MAX_EXCERPT_CHARS,
    MAX_FINDINGS,
    Evidence,
    Finding,
    ReportBuilder,
    build_report_from_state,
)
from agent007.sources import SourceRegistry

PAGE_TEXT = (
    "Atlas is a single-agent research assistant. It searches the web, reads "
    "pages, and writes an evidence-grounded report. Every citation is validated."
)
SNIPPET = "Atlas is a research assistant that writes evidence-grounded reports."


def registry_with_page() -> tuple[SourceRegistry, str]:
    registry = SourceRegistry()
    source_id = registry.register(
        "https://example.com/atlas",
        title="Atlas overview",
        page_text=PAGE_TEXT,
        search_snippet=SNIPPET,
    )
    return registry, source_id


def registry_with_snippet_only() -> tuple[SourceRegistry, str]:
    registry = SourceRegistry()
    source_id = registry.register(
        "https://example.com/snippet-only",
        title="Snippet only",
        search_snippet=SNIPPET,
    )
    return registry, source_id


# --- US-401: required sections ----------------------------------------------


def test_report_contains_every_required_section() -> None:
    registry, source_id = registry_with_page()
    builder = ReportBuilder(registry)
    builder.add_finding(
        "Atlas validates citations.", citations=(source_id,), excerpt="Every citation is validated."
    )

    report = builder.build(question="What is Atlas?", summary="It is a research assistant.")

    markdown = report.to_markdown()
    for section in (
        "# Research report",
        "## Summary",
        "## Findings",
        "## Limitations",
        "## Sources",
    ):
        assert section in markdown
    assert "**Question:** What is Atlas?" in markdown
    assert "It is a research assistant." in markdown


def test_evidence_free_run_still_renders_all_sections() -> None:
    report = ReportBuilder(SourceRegistry()).build(
        question="Anything?", summary="", status="failed", termination_reason="model_error"
    )

    markdown = report.to_markdown()
    assert "## Summary" in markdown
    assert "No summary was produced" in markdown
    assert "## Findings" in markdown
    assert "No findings were recorded" in markdown
    assert "## Limitations" in markdown
    assert "## Sources" in markdown
    assert "No sources were registered" in markdown


def test_partial_run_is_labelled_and_flags_incompleteness() -> None:
    report = ReportBuilder(SourceRegistry()).build(
        question="q",
        summary="partial answer",
        status="partial",
        termination_reason=TerminationReason.MAX_ITERATIONS,
    )

    markdown = report.to_markdown()
    assert "**Status:** partial" in markdown
    assert "max_iterations" in markdown
    assert any("incomplete" in limitation for limitation in report.limitations)


def test_markdown_output_is_stable_for_identical_input() -> None:
    def render() -> str:
        registry, source_id = registry_with_page()
        builder = ReportBuilder(registry)
        builder.add_finding(
            "Claim.", citations=(source_id,), excerpt="Every citation is validated."
        )
        builder.add_limitation("A limitation.")
        return builder.build(question="q", summary="s").to_markdown()

    assert render() == render()


# --- US-402: citation validation ---------------------------------------------


def test_valid_citation_renders_with_its_source() -> None:
    registry, source_id = registry_with_page()
    builder = ReportBuilder(registry)
    builder.add_finding("Claim.", citations=(source_id,), excerpt="Every citation is validated.")

    markdown = builder.build(question="q", summary="s").to_markdown()

    assert f"[{source_id}]" in markdown
    assert "https://example.com/atlas" in markdown


def test_unknown_citation_id_is_rejected_not_rendered() -> None:
    registry, _ = registry_with_page()
    builder = ReportBuilder(registry)

    with pytest.raises(CitationValidationError) as excinfo:
        builder.add_finding("Claim.", citations=("S999",), excerpt="text")

    assert "S999" in str(excinfo.value)


def test_mixed_known_and_unknown_citations_are_rejected_wholesale() -> None:
    registry, source_id = registry_with_page()
    builder = ReportBuilder(registry)

    with pytest.raises(CitationValidationError) as excinfo:
        builder.add_finding(
            "Claim.", citations=(source_id, "S404"), excerpt="Every citation is validated."
        )

    assert "S404" in str(excinfo.value)


def test_fabricated_excerpt_is_rejected() -> None:
    """An excerpt that is not in the source is fabrication and must raise."""
    registry, source_id = registry_with_page()
    builder = ReportBuilder(registry)

    with pytest.raises(CitationValidationError) as excinfo:
        builder.add_finding(
            "Claim.", citations=(source_id,), excerpt="This sentence was never on the page."
        )

    assert "not present" in str(excinfo.value)


def test_excerpt_requires_a_citation() -> None:
    registry, _ = registry_with_page()
    builder = ReportBuilder(registry)

    with pytest.raises(CitationValidationError):
        builder.add_finding("Claim.", excerpt="Every citation is validated.")


def test_direct_finding_citing_a_source_with_no_evidence_is_rejected() -> None:
    registry = SourceRegistry()
    source_id = registry.register("https://example.com/empty", title="Empty")
    builder = ReportBuilder(registry)

    with pytest.raises(CitationValidationError) as excinfo:
        builder.add_finding("Claim.", citations=(source_id,))

    assert "no stored evidence" in str(excinfo.value)


def test_empty_finding_text_is_rejected() -> None:
    registry, _ = registry_with_page()

    with pytest.raises(CitationValidationError):
        ReportBuilder(registry).add_finding("   ")


def test_findings_are_bounded_in_count() -> None:
    registry, source_id = registry_with_page()
    builder = ReportBuilder(registry)
    for _ in range(MAX_FINDINGS):
        builder.add_finding(
            "Claim.", citations=(source_id,), excerpt="Every citation is validated."
        )

    with pytest.raises(CitationValidationError):
        builder.add_finding(
            "One too many.", citations=(source_id,), excerpt="Every citation is validated."
        )


def test_duplicate_citations_are_deduplicated() -> None:
    registry, source_id = registry_with_page()
    builder = ReportBuilder(registry)

    finding = builder.add_finding(
        "Claim.", citations=(source_id, source_id), excerpt="Every citation is validated."
    )

    assert finding.citations == (source_id,)


# --- US-403: evidence bounds and labelling ----------------------------------


def test_excerpt_length_is_bounded() -> None:
    registry = SourceRegistry()
    long_page = "word " * 5000
    source_id = registry.register("https://example.com/long", title="Long", page_text=long_page)
    builder = ReportBuilder(registry)

    finding = builder.add_finding("Claim.", citations=(source_id,), excerpt=long_page[:1000])

    assert len(finding.evidence[0].excerpt) <= MAX_EXCERPT_CHARS


def test_direct_evidence_and_interpretation_are_distinctly_labelled() -> None:
    registry, source_id = registry_with_page()
    builder = ReportBuilder(registry)
    builder.add_finding(
        "Quoted claim.", citations=(source_id,), excerpt="Every citation is validated."
    )
    builder.add_finding("My synthesis of it.", citations=(source_id,), kind="interpretation")

    markdown = builder.build(question="q", summary="s").to_markdown()

    assert "**[Direct evidence]**" in markdown
    assert "**[Interpretation]**" in markdown


def test_page_text_evidence_is_labelled_deeper_than_snippet() -> None:
    registry = SourceRegistry()
    page_id = registry.register(
        "https://example.com/page", title="P", page_text=PAGE_TEXT, search_snippet=SNIPPET
    )
    builder = ReportBuilder(registry)

    finding = builder.add_finding(
        "Claim.", citations=(page_id,), excerpt="Every citation is validated."
    )

    assert finding.evidence[0].kind == "page_text"


def test_snippet_only_source_yields_snippet_evidence() -> None:
    registry, source_id = registry_with_snippet_only()
    builder = ReportBuilder(registry)

    finding = builder.add_finding(
        "Claim.", citations=(source_id,), excerpt="writes evidence-grounded reports"
    )

    assert finding.evidence[0].kind == "search_snippet"


def test_snippet_only_sources_are_disclosed_as_a_limitation() -> None:
    registry, source_id = registry_with_snippet_only()
    builder = ReportBuilder(registry)
    builder.add_finding(
        "Claim.", citations=(source_id,), excerpt="writes evidence-grounded reports"
    )

    report = builder.build(question="q", summary="s")

    assert any("search snippet" in limitation for limitation in report.limitations)
    assert any("not read" in limitation for limitation in report.limitations)


# --- conflicting evidence ----------------------------------------------------


def test_conflicting_sources_can_be_declared_as_limitations() -> None:
    registry = SourceRegistry()
    first = registry.register("https://a.example/x", title="A", page_text="The sky is blue.")
    second = registry.register("https://b.example/x", title="B", page_text="The sky is green.")
    builder = ReportBuilder(registry)
    builder.add_finding("Sources disagree about the sky.", citations=(first, second))
    builder.add_limitation("Sources [S1] and [S2] report conflicting colour claims.")

    report = builder.build(question="What colour?", summary="Conflicting.")

    assert any("conflicting" in limitation for limitation in report.limitations)
    assert {record.id for record in report.sources} == {first, second}


def test_finding_citing_conflicting_sources_without_evidence_is_rejected() -> None:
    """A 'direct' finding needs real backing, even when sources conflict."""
    registry = SourceRegistry()
    a = registry.register("https://a.example/x", title="A")
    b = registry.register("https://b.example/x", title="B")
    builder = ReportBuilder(registry)

    with pytest.raises(CitationValidationError):
        builder.add_finding("They disagree.", citations=(a, b))


# --- build_report_from_state -------------------------------------------------


def test_state_with_no_evidence_produces_a_failed_report_with_limitations() -> None:
    state = ResearchState(question="What is Atlas?")
    state.finish(TerminationReason.MODEL_ERROR)

    report = build_report_from_state(state, SourceRegistry())

    assert report.status == "failed"
    assert report.findings == ()
    assert report.sources == ()
    assert "## Sources" in report.to_markdown()


def test_state_summary_becomes_the_report_summary() -> None:
    state = ResearchState(question="What is Atlas?", final_text="Atlas is a research assistant.")
    state.finish(TerminationReason.COMPLETED)

    report = build_report_from_state(state, SourceRegistry())

    assert report.summary == "Atlas is a research assistant."
    assert report.status == "completed"


def test_state_with_registered_sources_produces_direct_findings() -> None:
    registry, source_id = registry_with_page()
    state = ResearchState(question="What is Atlas?", final_text="See the evidence.")
    state.finish(TerminationReason.COMPLETED)

    report = build_report_from_state(state, registry)

    assert len(report.findings) == 1
    assert report.findings[0].kind == "direct"
    assert report.findings[0].citations == (source_id,)
    assert report.findings[0].evidence[0].kind == "page_text"
    assert "example.com/atlas" in report.to_markdown()


def test_run_degradations_are_disclosed_not_hidden() -> None:
    registry, _ = registry_with_page()
    state = ResearchState(question="q", final_text="answer", unsupported_calls=2, duplicate_calls=3)
    state.errors.append("error: fetch timed out")
    state.finish(TerminationReason.COMPLETED)

    report = build_report_from_state(state, registry)
    limitations = " ".join(report.limitations)

    assert "not\nin the allowlist" in limitations or "allowlist" in limitations
    assert "suppressed" in limitations
    assert "fetch timed out" in limitations


def test_completing_run_with_errors_is_not_reported_as_clean() -> None:
    """finish() marks errored runs partial; the report must carry that through."""
    registry, _ = registry_with_page()
    state = ResearchState(question="q", final_text="answer")
    state.errors.append("error: something failed")
    state.finish(TerminationReason.COMPLETED)

    report = build_report_from_state(state, registry)

    assert report.status == "partial"


def test_duplicate_citation_across_findings_renders_one_source_entry() -> None:
    registry, source_id = registry_with_page()
    builder = ReportBuilder(registry)
    builder.add_finding("One.", citations=(source_id,), excerpt="Every citation is validated.")
    builder.add_finding(
        "Two.",
        citations=(source_id,),
        excerpt="It searches the web, reads pages",
    )

    report = builder.build(question="q", summary="s")

    assert len(report.sources) == 1


def test_finding_model_is_immutable() -> None:
    finding = Finding(text="t")

    with pytest.raises(ValidationError):
        finding.text = "changed"  # type: ignore[misc]


def test_evidence_model_is_immutable() -> None:
    evidence = Evidence(source_id="S1", excerpt="e", kind="page_text")

    with pytest.raises(ValidationError):
        evidence.excerpt = "changed"  # type: ignore[misc]


def test_observations_from_state_do_not_become_claims_unchecked() -> None:
    """Tool observations alone never fabricate findings; only registered
    evidence does."""
    state = ResearchState(
        question="q",
        final_text="answer",
        observations=[
            ToolObservation(call_id="c", name="web_search", ok=True, output="results text")
        ],
    )
    state.finish(TerminationReason.COMPLETED)

    report = build_report_from_state(state, SourceRegistry())

    assert report.findings == ()
