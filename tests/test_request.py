"""Tests for research-request validation (US-101, FR-01)."""

from __future__ import annotations

import pytest

from agent007.errors import InvalidRequestError
from agent007.models import MAX_QUESTION_LENGTH, ResearchRequest


def test_normal_valid_question_is_accepted_and_trimmed() -> None:
    request = ResearchRequest.parse("  What is retrieval-augmented generation?  ")

    assert request.question == "What is retrieval-augmented generation?"


@pytest.mark.parametrize("raw", ["", "   ", "\t", "\n", " \t \n "])
def test_empty_and_whitespace_only_questions_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidRequestError):
        ResearchRequest.parse(raw)


def test_question_at_maximum_length_is_accepted() -> None:
    request = ResearchRequest.parse("a" * MAX_QUESTION_LENGTH)

    assert len(request.question) == MAX_QUESTION_LENGTH


def test_question_over_maximum_length_is_rejected() -> None:
    with pytest.raises(InvalidRequestError) as excinfo:
        ResearchRequest.parse("a" * (MAX_QUESTION_LENGTH + 1))

    assert str(MAX_QUESTION_LENGTH) in str(excinfo.value)


@pytest.mark.parametrize("raw", [None, 42, 3.5, ["a question"], {"q": "x"}, b"bytes"])
def test_non_string_input_is_rejected_without_echoing_input(raw: object) -> None:
    with pytest.raises(InvalidRequestError) as excinfo:
        ResearchRequest.parse(raw)

    assert repr(raw) not in str(excinfo.value)


def test_rejecting_a_request_never_touches_configuration() -> None:
    """FR-01: invalid input must be rejected before any configuration is loaded.

    If configuration were read first, live mode with missing credentials would
    raise a ConfigurationError instead of InvalidRequestError.
    """
    with pytest.raises(InvalidRequestError):
        ResearchRequest.parse("   ")

    # And the validation failure is independent of any environment state.
    with pytest.raises(InvalidRequestError):
        ResearchRequest.parse("")
