"""Evaluation result records, human reviews, and artifacts (US-804, Sprint 8).

Produces the two required artifacts per run:

* a **machine-readable** JSON result (``eval_results.json``), and
* a **human-readable** Markdown summary (``eval_summary.md``).

Status vocabulary is exactly ``pass`` / ``fail`` / ``unknown`` /
``needs_review``. Fresh results always carry ``needs_review`` for the two
judgement fields (factual accuracy, completeness/relevance): an unreviewed
claim is never represented as verified (US-804 criterion 3).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agent007.errors import DatasetError

#: The only statuses an evaluation field may take.
STATUS_VALUES: tuple[str, ...] = ("pass", "fail", "unknown", "needs_review")

CheckStatus = Literal["pass", "fail", "unknown", "needs_review"]

EVAL_MODES = ("offline_fixture", "live")


def utc_now() -> str:
    """Evaluation timestamp, second precision, UTC."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def redact_secrets(text: str, secrets: tuple[str, ...]) -> str:
    """Replace any configured credential that leaked into ``text`` (US-805).

    Mirrors the provider-boundary redaction used by the search and model
    adapters: evaluation artifacts must never carry a key (US-805 criterion 3).
    """
    cleaned = text
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned


class ReviewRecord(BaseModel):
    """A human reviewer's judgment for one case (US-804 workflow).

    Every field is optional-but-explicit: omitting a judgment leaves the
    corresponding metric ``unknown`` rather than inventing a score (US-806).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(pattern=r"^EV-[A-Z]{3}-\d{3}$")
    factual_accuracy: CheckStatus = "needs_review"
    completeness_relevance: CheckStatus = "needs_review"
    supported_source_ids: tuple[str, ...] = ()
    unsupported_source_ids: tuple[str, ...] = ()
    reviewed_claims: int | None = Field(default=None, ge=0)
    unsupported_claims: int | None = Field(default=None, ge=0)
    reviewer: str | None = None
    reviewed_at: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _claims_counts_are_consistent(self) -> ReviewRecord:
        if self.unsupported_claims is not None and self.reviewed_claims is None:
            raise ValueError("unsupported_claims requires reviewed_claims to be recorded")
        overlap = set(self.supported_source_ids) & set(self.unsupported_source_ids)
        if overlap:
            raise ValueError(
                "a source cannot be both supported and unsupported: " + ", ".join(sorted(overlap))
            )
        return self


class CaseResult(BaseModel):
    """Everything recorded for one evaluated case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    question: str
    category: str
    difficulty: str
    evaluated_at: str
    mode: Literal["offline_fixture", "live"]
    model_id: str | None = None
    search_provider: str | None = None
    completion_status: str | None = None
    termination_reason: str | None = None
    citation_resolution: CheckStatus = "unknown"
    evidence_support: CheckStatus = "unknown"
    #: Judgement fields — never ``pass`` before a review exists (US-804).
    factual_accuracy: CheckStatus = "needs_review"
    completeness_relevance: CheckStatus = "needs_review"
    provider_failure: bool = False
    failure_reasons: tuple[str, ...] = ()
    evaluation_limitations: tuple[str, ...] = ()
    run_metrics: dict[str, Any] | None = None
    checks: dict[str, Any] | None = None
    token_usage: dict[str, int] | None = None
    review: ReviewRecord | None = None

    @model_validator(mode="after")
    def _fresh_results_are_unverified(self) -> CaseResult:
        """No recorded review may claim verified accuracy (US-804 criterion 3)."""
        if self.review is None:
            if self.factual_accuracy == "pass" or self.completeness_relevance == "pass":
                raise ValueError("factual accuracy cannot pass before a review is recorded")
        return self

    def apply_review(self, review: ReviewRecord) -> CaseResult:
        """Return a copy with a recorded review applied (US-804/US-803)."""
        return self.model_copy(
            update={
                "review": review,
                "factual_accuracy": review.factual_accuracy,
                "completeness_relevance": review.completeness_relevance,
            }
        )


def apply_reviews(results: list[CaseResult], reviews: list[ReviewRecord]) -> list[CaseResult]:
    """Attach recorded reviews to their cases; unknown case ids are an error."""
    by_id = {review.case_id: review for review in reviews}
    known = {result.case_id for result in results}
    unknown = sorted(set(by_id) - known)
    if unknown:
        raise DatasetError("review references unknown case ids: " + ", ".join(unknown))
    return [
        result.apply_review(by_id[result.case_id]) if result.case_id in by_id else result
        for result in results
    ]


def result_from_outcome(
    case: Any,
    outcome: Any,
    *,
    mode: Literal["offline_fixture", "live"],
    model_id: str,
    search_provider: str,
    max_iterations: int,
    limitations: tuple[str, ...],
    secrets: tuple[str, ...] = (),
) -> CaseResult:
    """Build a :class:`CaseResult` from a finished research run.

    Shared by the offline and live runners so both classify provider failures,
    check statuses, and token usage identically (US-802 criterion 3: one set
    of business rules).
    """
    from agent007.evaluation import measure
    from agent007.quality import provider_failure, run_checks

    state = outcome.state
    metrics = measure(outcome)
    checks = run_checks(
        outcome.report,
        outcome.sources,
        metrics,
        case=case,
        max_iterations=max_iterations,
    )
    failure_reasons = tuple(f"{check.id}: {check.detail}" for check in checks.failures) + tuple(
        redact_secrets(f"run error: {error}", secrets) for error in state.errors
    )
    usage = state.token_usage
    return CaseResult(
        case_id=case.id,
        question=case.question,
        category=case.category,
        difficulty=case.difficulty,
        evaluated_at=utc_now(),
        mode=mode,
        model_id=model_id,
        search_provider=search_provider,
        completion_status=state.status,
        termination_reason=(
            state.termination_reason.value if state.termination_reason is not None else None
        ),
        citation_resolution=checks.citation_resolution_status,
        evidence_support=checks.evidence_support_status,
        provider_failure=provider_failure(state),
        failure_reasons=failure_reasons,
        evaluation_limitations=limitations,
        run_metrics=metrics.as_dict(),
        checks=checks.as_dict(),
        token_usage=(
            {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
            }
            if usage is not None
            else None
        ),
    )


def provider_failure_result(
    case: Any,
    *,
    mode: Literal["offline_fixture", "live"],
    model_id: str,
    search_provider: str,
    limitations: tuple[str, ...],
    message: str,
    secrets: tuple[str, ...] = (),
) -> CaseResult:
    """Record a run that never produced a report (US-805: provider vs quality)."""
    return CaseResult(
        case_id=case.id,
        question=case.question,
        category=case.category,
        difficulty=case.difficulty,
        evaluated_at=utc_now(),
        mode=mode,
        model_id=model_id,
        search_provider=search_provider,
        completion_status=None,
        provider_failure=True,
        failure_reasons=(redact_secrets(message, secrets),),
        evaluation_limitations=limitations,
    )


def load_reviews(path: Path | str) -> list[ReviewRecord]:
    """Load a reviewer's judgments file.

    Raises:
        DatasetError: on unreadable, malformed, or invalid review data —
            including unknown review statuses (US-807).
    """
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DatasetError(f"cannot read reviews file: {target}") from exc
    except json.JSONDecodeError as exc:
        raise DatasetError(f"reviews file is not valid JSON: {exc.msg}") from None
    raw = payload.get("reviews") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        raise DatasetError("reviews file must be an object with a 'reviews' list")
    records: list[ReviewRecord] = []
    for index, item in enumerate(raw):
        try:
            records.append(ReviewRecord.model_validate(item))
        except ValidationError as exc:
            parts = [
                f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}"
                for error in exc.errors()[:3]
            ]
            raise DatasetError(f"invalid review at index {index}: " + "; ".join(parts)) from exc
    return records


class EvalRun(BaseModel):
    """One evaluation run: every case result plus the metrics computed from it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    generated_at: str
    mode: Literal["offline_fixture", "live"]
    dataset_version: str
    dataset_path: str
    model_id: str | None = None
    search_provider: str | None = None
    bounds: dict[str, Any] = Field(default_factory=dict)
    cases: tuple[CaseResult, ...] = ()
    metrics: tuple[dict[str, Any], ...] = ()
    evaluation_limitations: tuple[str, ...] = ()

    def write_json(self, path: Path | str) -> Path:
        """Write the machine-readable artifact (US-804 criterion 1)."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.model_dump(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return target

    @classmethod
    def read_json(cls, path: Path | str) -> EvalRun:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            raise DatasetError(f"cannot read evaluation results: {path}") from exc
        except json.JSONDecodeError as exc:
            raise DatasetError(f"evaluation results are not valid JSON: {exc.msg}") from None
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise DatasetError(f"invalid evaluation results: {exc}") from exc

    def summary_markdown(self) -> str:
        """Render the human-readable summary (US-804 criterion 1)."""
        lines: list[str] = [
            "# Evaluation summary",
            "",
            f"- **Run:** `{self.run_id}`",
            f"- **Generated:** {self.generated_at}",
            f"- **Mode:** {self.mode}",
            f"- **Dataset:** {self.dataset_path} (version {self.dataset_version})",
            f"- **Model:** {self.model_id or 'not recorded'}",
            f"- **Search provider:** {self.search_provider or 'not recorded'}",
            "",
            "## Metrics",
            "",
            "| Metric | Value | Numerator | Denominator | Unknown / unreviewed |",
            "|---|---|---|---|---|",
        ]
        for metric in self.metrics:
            value = metric.get("value")
            rendered = "unavailable" if value is None else f"{value:.2f}"
            lines.append(
                f"| {metric.get('label', metric.get('id'))} | {rendered} "
                f"| {metric.get('numerator')} | {metric.get('denominator')} "
                f"| {metric.get('unknown')} |"
            )

        lines.extend(
            [
                "",
                "## Cases",
                "",
                "| Case | Category | Status | Citations | Excerpts | "
                "Factual accuracy | Completeness | Provider failure |",
                "|---|---|---|---|---|---|---|---|",
            ]
        )
        for case in self.cases:
            lines.append(
                f"| {case.case_id} | {case.category} "
                f"| {case.completion_status or 'no run'} "
                f"| {case.citation_resolution} | {case.evidence_support} "
                f"| {case.factual_accuracy} | {case.completeness_relevance} "
                f"| {'yes' if case.provider_failure else 'no'} |"
            )

        lines.extend(["", "## Per-case detail", ""])
        for case in self.cases:
            lines.append(f"### {case.case_id} — {case.question}")
            lines.append("")
            lines.append(f"- evaluated: {case.evaluated_at} ({case.mode})")
            lines.append(
                f"- model: {case.model_id or 'not recorded'}; "
                f"search: {case.search_provider or 'not recorded'}"
            )
            lines.append(
                f"- run: {case.completion_status or 'no run'}"
                + (f" (stopped: {case.termination_reason})" if case.termination_reason else "")
            )
            lines.append(f"- citation resolution: {case.citation_resolution}")
            lines.append(f"- evidence excerpts: {case.evidence_support}")
            lines.append(f"- factual accuracy: {case.factual_accuracy}")
            lines.append(f"- completeness/relevance: {case.completeness_relevance}")
            if case.failure_reasons:
                for reason in case.failure_reasons:
                    lines.append(f"- failure: {reason}")
            if case.evaluation_limitations:
                for limitation in case.evaluation_limitations:
                    lines.append(f"- limitation: {limitation}")
            if case.review is None:
                lines.append("- review: **not recorded** — see the reviewer workflow below")
            else:
                lines.append(
                    f"- review: {case.review.factual_accuracy} / "
                    f"{case.review.completeness_relevance}"
                    + (f" by {case.review.reviewer}" if case.review.reviewer else "")
                )
                if case.review.notes:
                    lines.append(f"- review notes: {case.review.notes}")
            lines.append("")

        lines.extend(
            [
                "## Reviewer workflow",
                "",
                "1. Open the generated report for a case and its `## Sources` list.",
                "2. For each rubric criterion of that case (see the dataset), decide "
                "`pass`, `fail`, or `needs_review`.",
                "3. Record judgments in a reviews file: "
                '`{"reviews": [{"case_id": "EV-GEN-001", "factual_accuracy": "pass", '
                '"completeness_relevance": "pass", "reviewer": "name", '
                '"reviewed_at": "YYYY-MM-DD"}]}`.',
                "4. Re-run `python -m agent007.evalrun summarize --results <results.json> "
                "--reviews <reviews.json>` to recompute metrics.",
                "",
                "Fields left out of a review stay `needs_review`; metrics only count "
                "cases that were actually reviewed. Nothing here becomes `pass` "
                "without a recorded judgment.",
                "",
                "## What this evaluation cannot establish",
                "",
                "- Structural checks passing does **not** mean the answer is factually "
                "correct; factual accuracy requires the recorded review above.",
                "- Excerpt verification proves a quote exists in stored evidence, not "
                "that the source is trustworthy or that it supports the claim.",
                "- Offline fixture runs measure the pipeline, never a real model's "
                "research quality.",
                "",
            ]
        )

        if self.evaluation_limitations:
            lines.append("## Run limitations")
            lines.append("")
            for limitation in self.evaluation_limitations:
                lines.append(f"- {limitation}")
            lines.append("")

        return "\n".join(lines)
