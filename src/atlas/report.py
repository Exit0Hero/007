"""Evidence-grounded report generation (US-401, US-402, US-403).

A report is built, not typed: every claim carries citations that must resolve
against the run's :class:`~atlas.sources.SourceRegistry` (ADR-006), and every
excerpt must be verbatim text from the source it attributes. An unregistered ID
or an excerpt that is not actually present in the source raises
:class:`~atlas.errors.CitationValidationError` **before** anything is rendered,
so a report can never ship fabricated evidence (PRD FR-10, US-402).

Direct evidence (quoted page text or search snippet) is kept structurally
separate from interpretation (the model's own synthesis), and the Markdown
output labels them distinctly (US-403).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from atlas.errors import CitationValidationError
from atlas.models import ResearchState, TerminationReason
from atlas.sources import SourceRecord, SourceRegistry

#: Maximum characters of any single evidence excerpt in a report.
MAX_EXCERPT_CHARS = 600

#: Maximum characters of any single report section body.
MAX_SECTION_CHARS = 20_000

#: Maximum findings in one report.
MAX_FINDINGS = 50

EvidenceKind = Literal["page_text", "search_snippet"]
FindingKind = Literal["direct", "interpretation"]


class Evidence(BaseModel):
    """One bounded, verbatim excerpt attributed to a registered source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    excerpt: str
    kind: EvidenceKind


class Finding(BaseModel):
    """One claim, its citations, and the evidence supporting it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    citations: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    kind: FindingKind = "direct"


class Report(BaseModel):
    """A complete, traceable research report (US-401)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question: str
    summary: str
    findings: tuple[Finding, ...] = ()
    limitations: tuple[str, ...] = ()
    sources: tuple[SourceRecord, ...] = ()
    status: Literal["completed", "partial", "failed"] = "failed"
    termination_reason: str | None = None

    def to_markdown(self) -> str:
        """Render stable Markdown with every required section present."""
        lines: list[str] = [
            "# Research report",
            "",
            f"**Question:** {self.question}",
            "",
            f"**Status:** {self.status}"
            + (f" (stopped: {self.termination_reason})" if self.termination_reason else ""),
            "",
            "## Summary",
            "",
            self.summary or "_No summary was produced for this run._",
            "",
            "## Findings",
            "",
        ]

        if not self.findings:
            lines.append("_No findings were recorded for this run._")
        for index, finding in enumerate(self.findings, start=1):
            citation_note = " ".join(f"[{cid}]" for cid in finding.citations)
            label = "Direct evidence" if finding.kind == "direct" else "Interpretation"
            lines.append(f"{index}. **[{label}]** {finding.text} {citation_note}".rstrip())
            for evidence in finding.evidence:
                source = next(
                    (record for record in self.sources if record.id == evidence.source_id), None
                )
                title = source.title if source and source.title else evidence.source_id
                lines.append(
                    f"   > {evidence.excerpt} — _{evidence.kind.replace('_', ' ')} "
                    f"from [{evidence.source_id}] {title}_"
                )
            lines.append("")

        lines.extend(["## Limitations", ""])
        if not self.limitations:
            lines.append("_No limitations were declared for this run._")
        else:
            for limitation in self.limitations:
                lines.append(f"- {limitation}")

        lines.extend(["", "## Sources", ""])
        if not self.sources:
            lines.append("_No sources were registered for this run._")
        else:
            for record in self.sources:
                title = record.title or "(untitled)"
                lines.append(f"- [{record.id}] {title} — <{record.url}>")
                if record.published_date:
                    lines.append(f"  - published: {record.published_date}")
                if record.page_text:
                    lines.append("  - evidence: fetched page text")
                elif record.search_snippet:
                    lines.append("  - evidence: search snippet only (page not read)")

        lines.append("")
        return "\n".join(lines)


class ReportBuilder:
    """Builds a :class:`Report`, validating every citation and excerpt first.

    Args:
        registry: The run's source registry — the sole authority for what may
            be cited.
    """

    def __init__(self, registry: SourceRegistry) -> None:
        self._registry = registry
        self._findings: list[Finding] = []
        self._limitations: list[str] = []

    def add_limitation(self, text: str) -> None:
        cleaned = text.strip()
        if cleaned and cleaned not in self._limitations:
            self._limitations.append(cleaned[:MAX_SECTION_CHARS])

    def add_finding(
        self,
        text: str,
        *,
        citations: tuple[str, ...] | list[str] = (),
        excerpt: str | None = None,
        kind: FindingKind = "direct",
    ) -> Finding:
        """Add one finding, rejecting unknown sources and invented excerpts.

        Raises:
            CitationValidationError: if a cited ID is not registered, or if an
                excerpt is not verbatim text stored on the cited source.
        """
        cleaned = text.strip()
        if not cleaned:
            raise CitationValidationError("a finding must have non-empty text")
        if len(self._findings) >= MAX_FINDINGS:
            raise CitationValidationError(f"report exceeds {MAX_FINDINGS} findings")

        cited = tuple(dict.fromkeys(citations))  # dedupe, keep order
        found, unknown = self._registry.resolve(list(cited))
        if unknown:
            raise CitationValidationError(
                "citations do not resolve to registered sources: " + ", ".join(unknown)
            )

        evidence: list[Evidence] = []
        if excerpt is not None:
            if not cited:
                raise CitationValidationError(
                    "an excerpt requires at least one citation to attribute it to"
                )
            evidence.append(self._evidence_for(cited[0], excerpt))

        if kind == "direct" and not evidence and cited:
            # A direct finding with citations but no quoted excerpt still needs
            # verifiable backing: build an excerpt from the first source that
            # has stored evidence.
            backing = next((record for record in found if record.evidence_kinds), None)
            if backing is None:
                raise CitationValidationError(
                    f"direct finding cites sources with no stored evidence: {', '.join(cited)}"
                )
            evidence.append(self._evidence_for(backing.id, _first_excerpt(backing)))

        finding = Finding(
            text=cleaned[:MAX_SECTION_CHARS],
            citations=cited,
            evidence=tuple(evidence),
            kind=kind,
        )
        self._findings.append(finding)
        return finding

    def build(
        self,
        *,
        question: str,
        summary: str,
        status: Literal["completed", "partial", "failed"] = "completed",
        termination_reason: TerminationReason | str | None = None,
    ) -> Report:
        """Assemble the report, adding automatic uncertainty disclosures."""
        used = {
            source_id
            for finding in self._findings
            for source_id in (*finding.citations, *(e.source_id for e in finding.evidence))
        }

        cited_records = [
            record for record in self._registry.records() if record.id in used or not used
        ]

        for record in cited_records:
            if (
                "search_snippet" in record.evidence_kinds
                and "page_text" not in record.evidence_kinds
            ):
                self.add_limitation(
                    f"[{record.id}] {record.title or record.url} is supported only by a "
                    "search snippet; the page itself was not read, so its contents are "
                    "unverified."
                )

        reason = (
            termination_reason.value
            if isinstance(termination_reason, TerminationReason)
            else termination_reason
        )
        if status != "completed":
            self.add_limitation(
                f"The run ended with status '{status}'"
                + (f" (stopped: {reason})" if reason else "")
                + "; the answer may be incomplete."
            )

        return Report(
            question=question,
            summary=(summary or "").strip()[:MAX_SECTION_CHARS],
            findings=tuple(self._findings),
            limitations=tuple(self._limitations),
            sources=tuple(cited_records),
            status=status,
            termination_reason=reason,
        )

    def _evidence_for(self, source_id: str, excerpt: str) -> Evidence:
        """Verify an excerpt against the stored source text (US-403)."""
        record = self._registry.get(source_id)
        if record is None:
            raise CitationValidationError(
                f"citations do not resolve to registered sources: {source_id}"
            )

        cleaned = " ".join(excerpt.split())
        if not cleaned:
            raise CitationValidationError("an evidence excerpt must not be empty")

        kind = excerpt_support_kind(record, cleaned)
        if kind is None:
            raise CitationValidationError(
                f"excerpt is not present in the stored evidence of [{source_id}]; "
                "evidence must be quoted, not invented"
            )

        return Evidence(source_id=source_id, excerpt=cleaned[:MAX_EXCERPT_CHARS], kind=kind)


def excerpt_support_kind(record: SourceRecord, excerpt: str) -> EvidenceKind | None:
    """Return how (or whether) an excerpt is supported by a source's stored evidence.

    Shared by :class:`ReportBuilder` (build-time rejection of invented
    excerpts) and the evaluation quality checks (US-802 criterion 4), so the
    support rule exists in exactly one place.

    Returns:
        ``"page_text"`` or ``"search_snippet"`` when the excerpt appears
        verbatim in that tier of stored evidence, otherwise ``None``.
    """
    cleaned = " ".join(excerpt.split())
    if not cleaned:
        return None
    if record.page_text and _normalize(record.page_text).find(_normalize(cleaned)) != -1:
        return "page_text"
    if record.search_snippet and _normalize(record.search_snippet).find(_normalize(cleaned)) != -1:
        return "search_snippet"
    return None


def _normalize(text: str) -> str:
    return " ".join(text.split()).lower()


def _first_excerpt(record: SourceRecord) -> str:
    source_text = record.page_text or record.search_snippet or ""
    return source_text[:MAX_EXCERPT_CHARS]


def build_report_from_state(
    state: ResearchState,
    registry: SourceRegistry,
) -> Report:
    """Build a report from a finished run's state (US-401, US-502).

    Sources are the run's registry. Findings are derived honestly: each source
    with stored evidence becomes one direct finding quoting that evidence, and
    the model's final text becomes the summary. Limitations are added for every
    degradation the run actually suffered — never hidden.
    """
    builder = ReportBuilder(registry)
    builder.add_limitation(
        "This report was generated by an automated agent; every claim should be "
        "checked against the linked sources."
    )

    for record in registry.records():
        if not record.evidence_kinds:
            continue
        excerpt = _first_excerpt(record)
        if not excerpt.strip():
            continue
        try:
            builder.add_finding(
                f"Evidence retrieved from {record.title or record.url}.",
                citations=(record.id,),
                excerpt=excerpt,
                kind="direct",
            )
        except CitationValidationError:
            # A source whose stored text does not yield a verifiable excerpt is
            # disclosed rather than cited.
            builder.add_limitation(
                f"[{record.id}] was registered but no verbatim excerpt could be "
                "verified from its stored text."
            )

    if state.unsupported_calls:
        builder.add_limitation(
            f"The model requested {state.unsupported_calls} tool call(s) that are not "
            "in the allowlist; those requests were refused and not executed."
        )
    if state.duplicate_calls:
        builder.add_limitation(
            f"{state.duplicate_calls} repeated identical tool call(s) were suppressed."
        )
    for error in state.errors[:10]:
        builder.add_limitation(f"During the run: {error}")

    return builder.build(
        question=state.question,
        summary=state.final_text or "",
        status=state.status or "failed",
        termination_reason=state.termination_reason,
    )
