"""Evaluation dataset schema, loading, and fixture construction (US-801, Sprint 8).

The dataset itself lives *outside* application code, in
``evaluation_dataset/cases.json`` at the repository root: this module only
defines how a case is validated and how its deterministic fixture providers
(fake model script + fake search corpus) are built.

Nothing here touches the network or reads credentials. A malformed or empty
dataset is rejected with :class:`~atlas.errors.DatasetError` before any
evaluation runs (US-801 criterion 4).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agent007.errors import DatasetError
from agent007.models import SearchResult, ToolCall

EvalCategory = Literal[
    "general_factual",
    "science_technology",
    "programming",
    "comparative",
    "multi_source",
    "limited_evidence",
    "conflicting_sources",
    "disclosure",
]

#: Every category the dataset must cover (US-801 criterion 2).
REQUIRED_CATEGORIES: tuple[EvalCategory, ...] = (
    "general_factual",
    "science_technology",
    "programming",
    "comparative",
    "multi_source",
    "limited_evidence",
    "conflicting_sources",
    "disclosure",
)

Difficulty = Literal["easy", "medium", "hard"]

#: Terminal statuses a case is allowed to end in.
EvalStatus = Literal["completed", "partial", "failed"]


class RubricCriterion(BaseModel):
    """One judging question a human reviewer answers for a case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    guidance: str = Field(min_length=1)


class FixtureToolCall(BaseModel):
    """A scripted tool call in a model turn."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class FixtureTurn(BaseModel):
    """One scripted model turn: a final text, tool calls, or both."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str | None = None
    tool_calls: tuple[FixtureToolCall, ...] = ()


class FixtureResult(BaseModel):
    """One search result in the fixture's evidence corpus."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    snippet: str | None = None
    published_date: str | None = None


class FixtureSpec(BaseModel):
    """Deterministic providers for one case: a fake search corpus and a fake model script.

    ``search_error`` makes the search provider raise, exercising the
    provider-failure path (US-807) without any real provider.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    results: tuple[FixtureResult, ...] = ()
    search_error: str | None = None
    turns: tuple[FixtureTurn, ...] = Field(min_length=1)


class ExpectedConditions(BaseModel):
    """Deterministic, case-specific output conditions (US-802 check 7)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed_statuses: tuple[EvalStatus, ...] = ("completed", "partial", "failed")
    min_sources: int = Field(default=0, ge=0)
    requires_page_evidence: bool = False
    must_disclose_limitations: bool = False


class EvalCase(BaseModel):
    """One evaluation case: question, expectations, rubric, and fixture."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^EV-[A-Z]{3}-\d{3}$")
    question: str = Field(min_length=1)
    category: EvalCategory
    difficulty: Difficulty
    time_sensitive: bool = False
    reference_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    evaluation_instruction: str | None = None
    expected_research: tuple[str, ...] = Field(min_length=1)
    required_claims: tuple[str, ...] = ()
    prohibited_claims: tuple[str, ...] = ()
    expected_sources: tuple[str, ...] = Field(min_length=1)
    rubric: tuple[RubricCriterion, ...] = Field(min_length=1)
    conditions: ExpectedConditions = Field(default_factory=ExpectedConditions)
    fixture: FixtureSpec

    @model_validator(mode="after")
    def _time_sensitive_cases_carry_a_reference(self) -> EvalCase:
        """A volatile question must say *when* it was judged (US-801 criterion 3)."""
        if self.time_sensitive and not (self.reference_date or self.evaluation_instruction):
            raise ValueError(
                "time-sensitive cases must set reference_date or evaluation_instruction"
            )
        return self


class EvalDataset(BaseModel):
    """A validated, versioned collection of evaluation cases."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_version: str = Field(min_length=1)
    created: str = Field(min_length=1)
    cases: tuple[EvalCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ids_are_unique(self) -> EvalDataset:
        ids = [case.id for case in self.cases]
        duplicates = sorted({value for value in ids if ids.count(value) > 1})
        if duplicates:
            raise ValueError(f"duplicate case ids: {', '.join(duplicates)}")
        return self

    def case_ids(self) -> list[str]:
        return [case.id for case in self.cases]

    def categories(self) -> set[str]:
        return {case.category for case in self.cases}

    def select(self, ids: list[str]) -> list[EvalCase]:
        """Return cases for the given IDs, in dataset order.

        Raises:
            DatasetError: when an ID does not exist, so a typo can never
            silently shrink an evaluation run.
        """
        wanted = set(ids)
        known = set(self.case_ids())
        unknown = sorted(wanted - known)
        if unknown:
            raise DatasetError(f"unknown case ids: {', '.join(unknown)}")
        return [case for case in self.cases if case.id in wanted]


def default_dataset_path() -> Path:
    """Repository-root ``evaluation_dataset/cases.json`` (three levels above this file)."""
    return Path(__file__).resolve().parents[2] / "evaluation_dataset" / "cases.json"


def load_dataset(path: Path | str | None = None) -> EvalDataset:
    """Load and validate the evaluation dataset.

    Raises:
        DatasetError: when the file is missing, is not valid JSON, fails
            schema validation, or contains no cases.
    """
    target = Path(path) if path is not None else default_dataset_path()
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise DatasetError(f"cannot read evaluation dataset: {target}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DatasetError(f"evaluation dataset is not valid JSON: {exc.msg}") from None
    try:
        return EvalDataset.model_validate(payload)
    except ValidationError as exc:
        parts = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()[:5]
        ]
        raise DatasetError("invalid evaluation dataset: " + "; ".join(parts)) from exc


# --- fixture construction ----------------------------------------------------


def build_fixture_model(spec: FixtureSpec) -> Any:
    """Turn a case's scripted turns into a fake model adapter (offline, deterministic)."""
    from agent007.model import FakeModelAdapter, ModelTurn

    turns: list[ModelTurn] = []
    for index, turn in enumerate(spec.turns, start=1):
        calls = tuple(
            ToolCall(
                call_id=f"call_{index}_{offset}",
                name=call.name,
                arguments=dict(call.arguments),
                raw_arguments=json.dumps(call.arguments, sort_keys=True),
            )
            for offset, call in enumerate(turn.tool_calls, start=1)
        )
        turns.append(ModelTurn(text=turn.text, tool_calls=calls))
    return FakeModelAdapter(*turns)


def build_fixture_search(spec: FixtureSpec) -> Any:
    """Turn a case's evidence corpus into a search provider (offline, deterministic)."""
    corpus = [
        SearchResult(
            title=item.title,
            url=item.url,
            snippet=item.snippet,
            published_date=item.published_date,
        )
        for item in spec.results
    ]
    error = spec.search_error

    class _FixtureSearch:
        def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
            if error is not None:
                from agent007.errors import SearchProviderError

                raise SearchProviderError(error)
            return corpus[: max_results or 5]

    return _FixtureSearch()
