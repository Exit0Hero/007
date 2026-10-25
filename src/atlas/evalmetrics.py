"""Evaluation metrics with explicit denominators (US-806, Sprint 8).

Rules enforced here:

* every metric reports its numerator, denominator, and how many cases are
  unknown/unreviewed — no naked percentages;
* a metric with no valid observations is ``unavailable`` (``value = None``),
  never ``0``;
* accuracy, unsupported-claim, and completeness metrics count **only reviewed
  cases**; unreviewed cases are reported as unknown, never assumed to pass;
* cost is reported only with reliable pricing data — this project has none, so
  cost is always ``unavailable`` and is never estimated.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from atlas.evalreport import CaseResult

#: Statuses that count as "a review actually happened".
_REVIEWED = ("pass", "fail")
#: Statuses that count as "not reviewed / not decidable".
_UNREVIEWED = ("unknown", "needs_review")


@dataclass(frozen=True)
class Metric:
    """One metric with its full working shown."""

    id: str
    label: str
    numerator: int | None
    denominator: int | None
    unknown: int
    value: float | None
    note: str

    @property
    def unavailable(self) -> bool:
        return self.value is None

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "unknown": self.unknown,
            "value": self.value,
            "unavailable": self.unavailable,
            "note": self.note,
        }


def _ratio(
    metric_id: str, label: str, numerator: int, denominator: int, unknown: int, note: str
) -> Metric:
    return Metric(
        id=metric_id,
        label=label,
        numerator=numerator,
        denominator=denominator,
        unknown=unknown,
        value=(numerator / denominator) if denominator > 0 else None,
        note=note if denominator > 0 else "no valid observations: " + note,
    )


def _counts(result: CaseResult) -> tuple[int, int]:
    checks = result.checks or {}
    counts = checks.get("counts") or {}
    return int(counts.get("cited", 0)), int(counts.get("resolved", 0))


def _excerpt_counts(result: CaseResult) -> tuple[int, int]:
    checks = result.checks or {}
    counts = checks.get("counts") or {}
    return int(counts.get("excerpts_checked", 0)), int(counts.get("excerpts_matched", 0))


def compute_metrics(results: list[CaseResult]) -> list[Metric]:
    """Compute every Sprint 8 metric from recorded case results."""
    total = len(results)

    # 1. completion rate — denominator: cases that actually produced a run
    ran = [r for r in results if r.completion_status is not None]
    completed = sum(1 for r in ran if r.completion_status == "completed")
    no_run = total - len(ran)

    # 2. citation resolution — item level across runs that produced checks
    cited = sum(_counts(r)[0] for r in results if r.checks is not None)
    resolved = sum(_counts(r)[1] for r in results if r.checks is not None)
    cases_without_checks = sum(1 for r in results if r.checks is None)

    # 3. excerpt verification — item level
    excerpts = sum(_excerpt_counts(r)[0] for r in results if r.checks is not None)
    excerpts_matched = sum(_excerpt_counts(r)[1] for r in results if r.checks is not None)

    # 4. unsupported claims — reviewed claim counts only
    reviewed_claims = [
        r.review
        for r in results
        if r.review is not None
        and r.review.reviewed_claims is not None
        and r.review.unsupported_claims is not None
    ]
    claims_denominator = sum(review.reviewed_claims or 0 for review in reviewed_claims)
    claims_numerator = sum(review.unsupported_claims or 0 for review in reviewed_claims)

    # 5. factual accuracy — reviewed cases only
    accuracy_reviewed = [r for r in results if r.factual_accuracy in _REVIEWED]
    accuracy_pass = sum(1 for r in accuracy_reviewed if r.factual_accuracy == "pass")

    # 6. completeness/relevance — reviewed cases only
    completeness_reviewed = [r for r in results if r.completeness_relevance in _REVIEWED]
    completeness_pass = sum(1 for r in completeness_reviewed if r.completeness_relevance == "pass")

    # 7. provider failure rate
    provider_failures = sum(1 for r in results if r.provider_failure)

    # 8. token usage — only when the provider actually reported it
    usage_values = [
        float(r.token_usage["total_tokens"])
        for r in results
        if r.token_usage is not None and r.token_usage.get("total_tokens") is not None
    ]

    metrics = [
        _ratio(
            "completion_rate",
            "Case completion rate",
            completed,
            len(ran),
            no_run,
            "completed runs / runs that produced a report",
        ),
        _ratio(
            "citation_resolution_rate",
            "Citation resolution rate",
            resolved,
            cited,
            cases_without_checks,
            "resolved citation ids / cited citation ids",
        ),
        _ratio(
            "excerpt_verification_rate",
            "Evidence-excerpt verification rate",
            excerpts_matched,
            excerpts,
            cases_without_checks,
            "excerpts found verbatim in stored evidence / excerpts quoted",
        ),
        _ratio(
            "unsupported_claim_rate",
            "Unsupported-claim rate (reviewed claims only)",
            claims_numerator,
            claims_denominator,
            total - len(reviewed_claims),
            "claims judged unsupported / claims actually reviewed",
        ),
        _ratio(
            "factual_accuracy",
            "Factual accuracy (reviewed cases only)",
            accuracy_pass,
            len(accuracy_reviewed),
            total - len(accuracy_reviewed),
            "cases judged pass / cases with a recorded accuracy review",
        ),
        _ratio(
            "completeness_relevance",
            "Completeness and relevance (reviewed cases only)",
            completeness_pass,
            len(completeness_reviewed),
            total - len(completeness_reviewed),
            "cases judged pass / cases with a recorded completeness review",
        ),
        _ratio(
            "provider_failure_rate",
            "Provider failure rate",
            provider_failures,
            total,
            0,
            "runs that hit a model/search/network failure / all cases",
        ),
    ]

    # 9a. average token usage — unavailable unless usage was supplied
    if usage_values:
        metrics.append(
            Metric(
                id="token_usage_average",
                label="Average token usage (reported runs)",
                numerator=int(sum(usage_values)),
                denominator=len(usage_values),
                unknown=total - len(usage_values),
                value=sum(usage_values) / len(usage_values),
                note="mean of provider-reported total tokens; "
                f"{total - len(usage_values)} run(s) reported no usage",
            )
        )
        metrics.append(
            Metric(
                id="token_usage_median",
                label="Median token usage (reported runs)",
                numerator=int(sum(usage_values)),
                denominator=len(usage_values),
                unknown=total - len(usage_values),
                value=float(statistics.median(usage_values)),
                note="median of provider-reported total tokens",
            )
        )
    else:
        metrics.append(
            Metric(
                id="token_usage_average",
                label="Average token usage (reported runs)",
                numerator=0,
                denominator=0,
                unknown=total,
                value=None,
                note="no run reported token usage; usage is never estimated",
            )
        )
        metrics.append(
            Metric(
                id="token_usage_median",
                label="Median token usage (reported runs)",
                numerator=0,
                denominator=0,
                unknown=total,
                value=None,
                note="no run reported token usage; usage is never estimated",
            )
        )

    # 10. cost — no reliable pricing data exists in this project, so it is
    # always unavailable (US-806: never invent a cost estimate).
    metrics.append(
        Metric(
            id="estimated_cost",
            label="Estimated cost (USD)",
            numerator=None,
            denominator=None,
            unknown=total,
            value=None,
            note="unavailable: no reliable per-model pricing is configured; "
            "cost is never estimated",
        )
    )

    return metrics
