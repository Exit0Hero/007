"""Deterministic quality checks and citation-support verdicts (US-802/803, Sprint 8).

Everything in this module is a pure function of a finished run's report,
source registry, and measured metrics: no providers, no network, no
credentials, and no LLM judge. Structural honesty *can* be verified
deterministically; factual support *cannot* — so every verdict that would
require judgement is returned as ``unknown`` or ``needs_review`` and is never
auto-promoted to ``pass`` (US-803 criterion 3).

Business rules are reused, not duplicated:

* excerpt support comes from :func:`atlas.report.excerpt_support_kind`, the
  exact rule the report builder enforces at build time;
* status honesty and bounds come from :func:`atlas.evaluation.evaluate`, the
  Sprint 6 criteria;
* citation resolution goes through :meth:`atlas.sources.SourceRegistry.resolve`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from atlas.evaluation import RunMetrics, evaluate

CheckStatus = Literal["pass", "fail", "unknown", "needs_review"]

#: Stable identifiers for the eight deterministic checks (US-802).
CHECK_IDS: tuple[str, ...] = (
    "structure",
    "citations_resolve",
    "evidence_refs_exist",
    "excerpt_support",
    "disclosure",
    "status_honesty",
    "case_conditions",
    "citation_validation_replay",
)

REQUIRED_SECTIONS: tuple[str, ...] = (
    "# Research report",
    "**Question:**",
    "**Status:**",
    "## Summary",
    "## Findings",
    "## Limitations",
    "## Sources",
)


@dataclass(frozen=True)
class CheckResult:
    """One deterministic check and its honest outcome."""

    id: str
    status: CheckStatus
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"id": self.id, "status": self.status, "detail": self.detail}


@dataclass(frozen=True)
class CitationVerdict:
    """The three distinct citation-support questions kept separate (US-803).

    ``resolves`` and ``excerpt_matches_evidence`` are deterministic.
    ``supports_claim`` is a *judgement* question: it is ``needs_review`` until
    a human review says otherwise. A resolving URL alone never implies support.
    """

    source_id: str
    resolves: CheckStatus
    excerpt_matches_evidence: CheckStatus
    supports_claim: CheckStatus
    detail: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "resolves": self.resolves,
            "excerpt_matches_evidence": self.excerpt_matches_evidence,
            "supports_claim": self.supports_claim,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class CaseChecks:
    """All checks and citation verdicts for one evaluated case."""

    checks: tuple[CheckResult, ...]
    citations: tuple[CitationVerdict, ...]
    cited_count: int
    resolved_count: int
    excerpts_checked: int
    excerpts_matched: int

    def get(self, check_id: str) -> CheckResult:
        for check in self.checks:
            if check.id == check_id:
                return check
        raise KeyError(check_id)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(check for check in self.checks if check.status == "fail")

    @property
    def all_deterministic_checks_pass(self) -> bool:
        return not self.failures

    @property
    def citation_resolution_status(self) -> CheckStatus:
        """Aggregate of the resolution question only."""
        if self.cited_count == 0:
            return "unknown"  # nothing to resolve — not a pass
        return "pass" if self.resolved_count == self.cited_count else "fail"

    @property
    def evidence_support_status(self) -> CheckStatus:
        """Aggregate of the excerpt-match question only (never claim support)."""
        if self.excerpts_checked == 0:
            return "unknown"
        return "pass" if self.excerpts_matched == self.excerpts_checked else "fail"

    def as_dict(self) -> dict[str, object]:
        return {
            "checks": [check.as_dict() for check in self.checks],
            "citations": [verdict.as_dict() for verdict in self.citations],
            "counts": {
                "cited": self.cited_count,
                "resolved": self.resolved_count,
                "excerpts_checked": self.excerpts_checked,
                "excerpts_matched": self.excerpts_matched,
            },
        }


def cited_source_ids(report: object) -> list[str]:
    """Every source ID a report references, deduplicated, in first-seen order."""
    seen: list[str] = []
    for finding in getattr(report, "findings", ()):
        for source_id in (*finding.citations, *(ev.source_id for ev in finding.evidence)):
            if source_id not in seen:
                seen.append(source_id)
    return seen


def provider_failure(state: object) -> bool:
    """Whether a run hit a model/search/network failure (US-805 classification).

    Provider failures are *infrastructure* outcomes and are kept separate from
    research-quality failures so the metrics never conflate the two.

    A run failed at the provider level when the model call raised
    (``termination_reason == model_error``) or when an executed tool attempt
    failed (refusals such as unknown-tool or duplicate suppression are policy
    outcomes, not provider failures).
    """
    from atlas.models import TerminationReason

    if state.termination_reason is TerminationReason.MODEL_ERROR:
        return True
    return any(
        observation.executed and not observation.ok and observation.refusal is None
        for observation in state.observations
    )


def run_checks(
    report: object,
    registry: object,
    metrics: RunMetrics,
    *,
    case: object | None = None,
    max_iterations: int = 8,
) -> CaseChecks:
    """Run all eight deterministic checks for one evaluated run.

    Args:
        report: The finished :class:`atlas.report.Report`.
        registry: The run-local :class:`atlas.sources.SourceRegistry`.
        metrics: Sprint 6 metrics for the same run (``measure(outcome)``).
        case: Optional evaluation case; its ``conditions`` plus its required
            and prohibited claims drive the ``case_conditions`` check. When
            absent, that check reports ``unknown`` rather than a pass.
        max_iterations: The iteration bound used by the Sprint 6 criteria.
    """
    from atlas.report import excerpt_support_kind

    markdown = report.to_markdown()
    records = {record.id: record for record in registry.records()}
    cited = cited_source_ids(report)
    conditions = getattr(case, "conditions", None)
    required_claims = tuple(getattr(case, "required_claims", ()))
    prohibited_claims = tuple(getattr(case, "prohibited_claims", ()))

    checks: list[CheckResult] = [
        _structure(report, markdown),
        _citations_resolve(registry, cited),
        _evidence_refs(report, registry),
        _excerpt_support(report, records),
        _disclosure(report, metrics),
        _status_honesty(metrics, max_iterations),
        _case_conditions(
            report,
            metrics,
            markdown,
            conditions,
            required_claims,
            prohibited_claims,
        ),
        _citation_validation_replay(report, registry, records),
    ]

    verdicts = _citation_verdicts(report, records)

    # Item-level counts for the excerpt metric (one count per quoted excerpt).
    excerpt_items = [
        (evidence.source_id, evidence.excerpt)
        for finding in report.findings
        for evidence in finding.evidence
    ]
    excerpts_checked = len(excerpt_items)
    excerpts_matched = sum(
        1
        for source_id, excerpt in excerpt_items
        if source_id in records and excerpt_support_kind(records[source_id], excerpt) is not None
    )
    resolved_count = sum(1 for verdict in verdicts if verdict.resolves == "pass")

    return CaseChecks(
        checks=tuple(checks),
        citations=tuple(verdicts),
        cited_count=len(cited),
        resolved_count=resolved_count if cited else 0,
        excerpts_checked=excerpts_checked,
        excerpts_matched=excerpts_matched,
    )


# --- individual checks -------------------------------------------------------


def _structure(report: object, markdown: str) -> CheckResult:
    missing = [section for section in REQUIRED_SECTIONS if section not in markdown]
    if not getattr(report, "question", "").strip():
        missing.append("non-empty question")
    if missing:
        return CheckResult("structure", "fail", "missing: " + ", ".join(missing))
    return CheckResult("structure", "pass", "all required sections rendered")


def _citations_resolve(registry: object, cited: list[str]) -> CheckResult:
    if not cited:
        return CheckResult(
            "citations_resolve", "unknown", "report cites no sources; nothing to resolve"
        )
    _, unresolved = registry.resolve(list(cited))
    if unresolved:
        return CheckResult(
            "citations_resolve",
            "fail",
            "unresolved citation ids: " + ", ".join(unresolved),
        )
    return CheckResult("citations_resolve", "pass", f"all {len(cited)} cited ids resolve")


def _evidence_refs(report: object, registry: object) -> CheckResult:
    missing = sorted(
        {
            evidence.source_id
            for finding in report.findings
            for evidence in finding.evidence
            if registry.get(evidence.source_id) is None
        }
    )
    if missing:
        return CheckResult(
            "evidence_refs_exist",
            "fail",
            "evidence references unknown sources: " + ", ".join(missing),
        )
    checked = sum(len(finding.evidence) for finding in report.findings)
    return CheckResult("evidence_refs_exist", "pass", f"{checked} evidence references all exist")


def _excerpt_support(report: object, records: dict[str, object]) -> CheckResult:
    from atlas.report import excerpt_support_kind

    problems: list[str] = []
    checked = 0
    for finding in report.findings:
        for evidence in finding.evidence:
            checked += 1
            record = records.get(evidence.source_id)
            if record is None or excerpt_support_kind(record, evidence.excerpt) is None:
                problems.append(f"[{evidence.source_id}] excerpt not in stored evidence")
    if problems:
        return CheckResult("excerpt_support", "fail", "; ".join(problems[:3]))
    if checked == 0:
        return CheckResult("excerpt_support", "unknown", "report carries no quoted excerpts")
    return CheckResult("excerpt_support", "pass", f"{checked} excerpts verbatim in evidence")


def _disclosure(report: object, metrics: RunMetrics) -> CheckResult:
    needs_disclosure = metrics.status != "completed" or metrics.sources_registered == 0
    if not needs_disclosure:
        return CheckResult("disclosure", "pass", "complete run with sources; nothing to disclose")
    if not report.limitations:
        return CheckResult(
            "disclosure",
            "fail",
            f"{metrics.status} run with {metrics.sources_registered} sources "
            "declared no limitations",
        )
    return CheckResult("disclosure", "pass", f"{len(report.limitations)} limitation(s) disclosed")


def _status_honesty(metrics: RunMetrics, max_iterations: int) -> CheckResult:
    ok, failures = evaluate(metrics, max_iterations=max_iterations)
    if ok:
        return CheckResult(
            "status_honesty",
            "pass",
            f"status={metrics.status}, termination={metrics.termination_reason}",
        )
    return CheckResult("status_honesty", "fail", "; ".join(failures))


def _case_conditions(
    report: object,
    metrics: RunMetrics,
    markdown: str,
    conditions: object | None,
    required_claims: tuple[str, ...],
    prohibited_claims: tuple[str, ...],
) -> CheckResult:
    if conditions is None:
        return CheckResult(
            "case_conditions",
            "unknown",
            "no case-specific conditions supplied for this run",
        )
    failures: list[str] = []
    if metrics.status not in conditions.allowed_statuses:
        failures.append(
            f"status {metrics.status!r} not in allowed {list(conditions.allowed_statuses)}"
        )
    if metrics.sources_registered < conditions.min_sources:
        failures.append(f"{metrics.sources_registered} sources < required {conditions.min_sources}")
    if conditions.requires_page_evidence and not any(
        "page_text" in record.evidence_kinds for record in report.sources
    ):
        failures.append("no source carries fetched page evidence")
    if conditions.must_disclose_limitations and not report.limitations:
        failures.append("case requires disclosed limitations but none were declared")

    lowered = markdown.casefold()
    for claim in required_claims:
        if claim.casefold() not in lowered:
            failures.append(f"required claim missing: {claim!r}")
    for claim in prohibited_claims:
        if claim.casefold() in lowered:
            failures.append(f"prohibited claim present: {claim!r}")

    if failures:
        return CheckResult("case_conditions", "fail", "; ".join(failures))
    return CheckResult("case_conditions", "pass", "all case-specific conditions satisfied")


def _citation_validation_replay(
    report: object,
    registry: object,
    records: dict[str, object],
) -> CheckResult:
    """Replay the builder's rejection rules with the same shared primitives.

    A report constructed outside the builder could still carry a fabricated
    reference; this check proves the validation would have rejected it.
    """
    from atlas.report import excerpt_support_kind

    problems: list[str] = []
    for finding in report.findings:
        for source_id in finding.citations:
            if source_id not in records:
                problems.append(f"fabricated citation reached the report: [{source_id}]")
        for evidence in finding.evidence:
            record = records.get(evidence.source_id)
            if record is None:
                problems.append(
                    f"fabricated evidence reference reached the report: [{evidence.source_id}]"
                )
            elif excerpt_support_kind(record, evidence.excerpt) is None:
                problems.append(f"invented excerpt reached the report for [{evidence.source_id}]")
    if problems:
        return CheckResult("citation_validation_replay", "fail", "; ".join(problems[:3]))
    return CheckResult(
        "citation_validation_replay",
        "pass",
        "no fabricated reference or invented excerpt would survive builder validation",
    )


def _citation_verdicts(report: object, records: dict[str, object]) -> list[CitationVerdict]:
    from atlas.report import excerpt_support_kind

    verdicts: list[CitationVerdict] = []
    for source_id in cited_source_ids(report):
        record = records.get(source_id)
        resolves: CheckStatus = "pass" if record is not None else "fail"

        excerpts = [
            evidence.excerpt
            for finding in report.findings
            for evidence in finding.evidence
            if evidence.source_id == source_id
        ]
        if not excerpts:
            excerpt_status: CheckStatus = "unknown"
            detail = "no excerpt attached to this citation; nothing to verify"
        elif record is None:
            excerpt_status = "fail"
            detail = "source does not exist, so no excerpt can be supported"
        else:
            supported = [excerpt_support_kind(record, excerpt) for excerpt in excerpts]
            if all(kind is not None for kind in supported):
                excerpt_status = "pass"
                detail = "excerpt(s) verbatim in stored evidence"
            else:
                excerpt_status = "fail"
                detail = "at least one excerpt is not present in stored evidence"

        verdicts.append(
            CitationVerdict(
                source_id=source_id,
                resolves=resolves,
                excerpt_matches_evidence=excerpt_status,
                # US-803: claim support is a judgement question. Never a pass
                # just because a URL resolves; a recorded review may upgrade it.
                supports_claim="needs_review",
                detail=detail,
            )
        )
    return verdicts
