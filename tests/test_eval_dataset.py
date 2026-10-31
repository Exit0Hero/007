"""Tests for the evaluation dataset (Sprint 8, US-801).

The dataset lives outside application code and must stay valid, complete, and
honest about time-sensitive questions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent007.errors import DatasetError, SearchProviderError
from agent007.evalset import (
    REQUIRED_CATEGORIES,
    build_fixture_model,
    build_fixture_search,
    default_dataset_path,
    load_dataset,
)


def _minimal_case(**overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "id": "EV-GEN-099",
        "question": "A question?",
        "category": "general_factual",
        "difficulty": "easy",
        "expected_research": ["a source answers it"],
        "expected_sources": ["one reference source"],
        "rubric": [{"id": "accurate", "question": "Is it right?", "guidance": "check facts"}],
        "fixture": {
            "results": [{"title": "T", "url": "https://example.org/a", "snippet": "text"}],
            "turns": [
                {"tool_calls": [{"name": "web_search", "arguments": {"query": "q"}}]},
                {"text": "answer"},
            ],
        },
    }
    case.update(overrides)
    return case


def _write(tmp_path: Path, payload: Any) -> Path:
    target = tmp_path / "cases.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


# --- the shipped dataset -----------------------------------------------------


def test_shipped_dataset_exists_and_loads() -> None:
    dataset = load_dataset()
    assert default_dataset_path().is_file()
    assert dataset.dataset_version


def test_dataset_has_at_least_twenty_cases() -> None:
    dataset = load_dataset()
    assert len(dataset.cases) >= 20


def test_all_required_categories_are_represented() -> None:
    dataset = load_dataset()
    present = dataset.categories()
    assert set(REQUIRED_CATEGORIES) <= present
    # every category is exercised by at least three cases
    for category in REQUIRED_CATEGORIES:
        count = sum(1 for case in dataset.cases if case.category == category)
        assert count >= 3, f"{category} has only {count} cases"


def test_case_ids_are_unique_and_well_formed() -> None:
    dataset = load_dataset()
    ids = dataset.case_ids()
    assert len(ids) == len(set(ids))
    for case_id in ids:
        assert case_id.startswith("EV-")
        assert len(case_id.split("-")) == 3


def test_every_case_carries_expectations_and_a_rubric() -> None:
    for case in load_dataset().cases:
        assert case.question.strip()
        assert case.expected_research, case.id
        assert case.expected_sources, case.id
        assert case.rubric, case.id
        assert case.difficulty in ("easy", "medium", "hard")
        for criterion in case.rubric:
            assert criterion.question and criterion.guidance


def test_time_sensitive_cases_carry_a_reference_date_or_instruction() -> None:
    time_sensitive = [case for case in load_dataset().cases if case.time_sensitive]
    assert time_sensitive, "the dataset must contain time-sensitive questions"
    for case in time_sensitive:
        assert case.reference_date or case.evaluation_instruction, case.id


def test_volatile_questions_are_not_hardcoded_as_permanent_truth() -> None:
    """A volatile question must say how to judge it, not pin a live figure."""
    for case in load_dataset().cases:
        if not case.time_sensitive:
            continue
        assert case.reference_date is not None, case.id
        assert case.evaluation_instruction, case.id
        instruction = case.evaluation_instruction.casefold()
        assert any(
            marker in instruction for marker in ("judge", "check", "do not", "not whether")
        ), f"{case.id} gives no evaluation instruction"


def test_select_rejects_unknown_case_ids() -> None:
    dataset = load_dataset()
    with pytest.raises(DatasetError, match="unknown case ids"):
        dataset.select(["EV-GEN-001", "EV-NOPE-999"])


def test_select_returns_requested_cases_in_dataset_order() -> None:
    dataset = load_dataset()
    picked = dataset.select(["EV-SCI-001", "EV-GEN-001"])
    assert [case.id for case in picked] == ["EV-GEN-001", "EV-SCI-001"]


# --- malformed datasets ------------------------------------------------------


def test_empty_dataset_is_rejected(tmp_path: Path) -> None:
    target = _write(tmp_path, {"dataset_version": "1", "created": "2026-01-01", "cases": []})
    with pytest.raises(DatasetError, match="invalid evaluation dataset"):
        load_dataset(target)


def test_malformed_json_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "cases.json"
    target.write_text("{not json", encoding="utf-8")
    with pytest.raises(DatasetError, match="not valid JSON"):
        load_dataset(target)


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="cannot read evaluation dataset"):
        load_dataset(tmp_path / "absent.json")


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    case = _minimal_case()
    del case["rubric"]
    target = _write(
        tmp_path,
        {"dataset_version": "1", "created": "2026-01-01", "cases": [case]},
    )
    with pytest.raises(DatasetError, match="rubric"):
        load_dataset(target)


def test_duplicate_case_ids_are_rejected(tmp_path: Path) -> None:
    case = _minimal_case()
    target = _write(
        tmp_path,
        {"dataset_version": "1", "created": "2026-01-01", "cases": [case, case]},
    )
    with pytest.raises(DatasetError, match="duplicate case ids"):
        load_dataset(target)


def test_unknown_category_is_rejected(tmp_path: Path) -> None:
    case = _minimal_case(category="made_up_category")
    target = _write(
        tmp_path,
        {"dataset_version": "1", "created": "2026-01-01", "cases": [case]},
    )
    with pytest.raises(DatasetError, match="category"):
        load_dataset(target)


def test_time_sensitive_case_without_reference_is_rejected(tmp_path: Path) -> None:
    case = _minimal_case(time_sensitive=True)
    target = _write(
        tmp_path,
        {"dataset_version": "1", "created": "2026-01-01", "cases": [case]},
    )
    with pytest.raises(DatasetError, match="time-sensitive"):
        load_dataset(target)


def test_malformed_case_id_is_rejected(tmp_path: Path) -> None:
    case = _minimal_case(id="not-an-id")
    target = _write(
        tmp_path,
        {"dataset_version": "1", "created": "2026-01-01", "cases": [case]},
    )
    with pytest.raises(DatasetError, match="id"):
        load_dataset(target)


# --- fixture construction ----------------------------------------------------


def test_fixture_search_returns_its_corpus() -> None:
    case = load_dataset().select(["EV-GEN-001"])[0]
    provider = build_fixture_search(case.fixture)
    results = provider.search("anything")
    assert len(results) == len(case.fixture.results)
    assert results[0].url == case.fixture.results[0].url


def test_fixture_search_can_fail_on_demand() -> None:
    case = load_dataset().select(["EV-INC-003"])[0]
    provider = build_fixture_search(case.fixture)
    with pytest.raises(SearchProviderError):
        provider.search("anything")


def test_fixture_model_returns_scripted_turns_in_order() -> None:
    case = load_dataset().select(["EV-GEN-001"])[0]
    model = build_fixture_model(case.fixture)
    first = model.complete("q", [], [])
    assert first.tool_calls and first.tool_calls[0].name == "web_search"
    second = model.complete("q", [], [])
    assert second.text and not second.tool_calls
