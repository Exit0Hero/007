"""Typed data models for research requests and run state.

Sprint 1 introduces the request model only. Search results, source records, tool
observations, and run status arrive with their own stories (US-203, US-303,
US-403) and are deliberately not modelled yet.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from agent007.errors import InvalidRequestError

#: Maximum accepted question length in characters. Documented default; see
#: ``docs/PRD.md`` FR-01 and ``README.md``.
MAX_QUESTION_LENGTH = 4000


def _format_validation_error(exc: ValidationError) -> str:
    """Render a Pydantic error without echoing raw input values."""
    parts = [
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
    ]
    return "; ".join(parts)


class ResearchRequest(BaseModel):
    """A validated research question.

    Validation runs before configuration is loaded and before any provider
    client could be constructed, so an invalid request can never trigger a paid
    API call (PRD FR-01).
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    question: str

    @field_validator("question")
    @classmethod
    def _question_is_meaningful(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("question must not be empty or whitespace-only")
        if len(cleaned) > MAX_QUESTION_LENGTH:
            raise ValueError(
                f"question must be at most {MAX_QUESTION_LENGTH} characters, got {len(cleaned)}"
            )
        return cleaned

    @classmethod
    def parse(cls, raw: object) -> ResearchRequest:
        """Validate untrusted input, converting failures to InvalidRequestError."""
        try:
            return cls(question=raw)  # type: ignore[arg-type]
        except ValidationError as exc:
            raise InvalidRequestError(_format_validation_error(exc)) from exc


#: Maximum characters accepted for a search query (PRD FR-03 bounds).
MAX_QUERY_LENGTH = 400

#: Maximum characters kept from any single search snippet.
MAX_SNIPPET_CHARS = 1000


class SearchResult(BaseModel):
    """One normalized, bounded search result candidate (PRD FR-03).

    Field names follow the search provider's documented response schema. A
    result is only accepted when it carries a usable HTTP(S) URL; everything
    else is optional and may legitimately be absent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    url: str
    snippet: str | None = None
    published_date: str | None = None
    score: float | None = None


class ToolCall(BaseModel):
    """A tool call exactly as the model requested it.

    ``raw_arguments`` preserves the provider's original JSON text so it can be
    replayed verbatim; ``arguments`` holds the parsed form used for validation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    raw_arguments: str | None = None


class ToolObservation(BaseModel):
    """The bounded result of executing (or refusing) one tool call.

    ``refusal`` names *why* a call was refused without executing, so the loop
    can count unknown tools and suppressed duplicates separately (US-301/303).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: str
    name: str
    ok: bool
    output: str
    executed: bool = True
    refusal: Literal["unknown_tool", "duplicate", "invalid_arguments"] | None = None


class TokenUsage(BaseModel):
    """Provider-reported usage, present only when the provider supplies it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class TerminationReason(StrEnum):
    """Why the agent loop stopped. Always reported, never inferred."""

    COMPLETED = "completed"
    MAX_ITERATIONS = "max_iterations"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    MODEL_ERROR = "model_error"
    NO_OUTPUT = "no_output"


class ResearchState(BaseModel):
    """Everything one research run needs, and nothing persistent (PRD FR-13)."""

    question: str
    observations: list[ToolObservation] = Field(default_factory=list)
    iterations: int = 0
    model_calls: int = 0
    unsupported_calls: int = 0
    duplicate_calls: int = 0
    token_usage: TokenUsage | None = None
    final_text: str | None = None
    termination_reason: TerminationReason | None = None
    status: Literal["completed", "partial", "failed"] | None = None
    errors: list[str] = Field(default_factory=list)

    def finish(self, reason: TerminationReason) -> None:
        """Record the stop reason and derive an honest completion status.

        Partial work is never labelled complete: a run only counts as completed
        when the model produced a final answer with no error recorded.
        """
        if self.termination_reason is None:
            self.termination_reason = reason
        if self.status is not None:
            return
        if reason is TerminationReason.COMPLETED and self.final_text and not self.errors:
            self.status = "completed"
        elif self.observations or self.final_text:
            self.status = "partial"
        else:
            self.status = "failed"
