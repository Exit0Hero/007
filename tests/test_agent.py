"""Tests for the bounded agent loop (US-301, US-302, US-303, US-304).

A scripted fake model drives the loop, so every test is deterministic and
offline (US-503). No provider is contacted and no credential is required.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ConfigDict, Field

from agent007.agent import ResearchAgent
from agent007.errors import ModelProviderError
from agent007.model import FakeModelAdapter, ModelTurn, TokenUsage
from agent007.models import TerminationReason, ToolCall
from agent007.tools.registry import MAX_IDENTICAL_CALLS, ToolRegistry


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(max_length=100)


class CountingRegistry(ToolRegistry):
    """Registry with one recording tool, ``search``."""

    def __init__(self) -> None:
        super().__init__()
        self.executed: list[str] = []

        def handler(args: SearchArgs) -> str:
            self.executed.append(args.query)
            return f"results for {args.query}"

        self.register(name="search", description="Search.", args_model=SearchArgs, handler=handler)


def tool_call(name: str = "search", **arguments: object) -> ToolCall:
    return ToolCall(
        call_id=f"call_{len(arguments)}_{name}",
        name=name,
        arguments=dict(arguments),
        raw_arguments=json.dumps(arguments),
    )


def run(
    *turns: ModelTurn | object,
    max_iterations: int = 8,
    deadline_seconds: float = 120.0,
    clock=None,
) -> tuple[object, FakeModelAdapter, CountingRegistry]:
    registry = CountingRegistry()
    model = FakeModelAdapter(*turns)
    agent = ResearchAgent(
        model,
        registry,
        max_iterations=max_iterations,
        deadline_seconds=deadline_seconds,
        **({"clock": clock} if clock else {}),
    )
    return agent.run("What is Atlas?"), model, registry


# --- one tool call, then a final answer -------------------------------------


def test_single_tool_call_then_final_answer() -> None:
    state, model, registry = run(
        ModelTurn(tool_calls=(tool_call(query="007"),)),
        ModelTurn(text="Atlas is a research assistant."),
    )

    assert state.status == "completed"
    assert state.termination_reason == TerminationReason.COMPLETED
    assert state.final_text == "Atlas is a research assistant."
    assert state.iterations == 2
    assert state.model_calls == 2
    assert len(state.observations) == 1
    assert state.observations[0].ok is True
    assert registry.executed == ["007"]


def test_observations_are_replayed_to_later_model_calls() -> None:
    """The model must see prior observations — statelessness is explicit."""
    _, model, _ = run(
        ModelTurn(tool_calls=(tool_call(query="007"),)),
        ModelTurn(text="done"),
    )

    second_call = model.calls[1]
    assert len(second_call["observations"]) == 1
    assert second_call["observations"][0].output == "results for 007"


def test_later_action_depends_on_earlier_observation() -> None:
    """The scripted next turn is computed from what the tool actually returned."""

    def follow_up(observations):
        last = observations[-1].output
        return ModelTurn(tool_calls=(tool_call(query=last.upper()),))

    state, _, registry = run(
        ModelTurn(tool_calls=(tool_call(query="007"),)),
        follow_up,
        ModelTurn(text="final"),
    )

    assert registry.executed == ["007", "RESULTS FOR 007"]
    assert state.status == "completed"


def test_model_receives_the_tool_definitions() -> None:
    _, model, _ = run(ModelTurn(text="hi"))

    assert [spec.name for spec in model.calls[0]["tools"]] == ["search"]


# --- final answer only -------------------------------------------------------


def test_direct_answer_with_no_tool_calls() -> None:
    state, _, registry = run(ModelTurn(text="No tools needed."))

    assert state.status == "completed"
    assert state.termination_reason == TerminationReason.COMPLETED
    assert state.iterations == 1
    assert registry.executed == []


def test_empty_final_answer_is_no_output() -> None:
    state, _, _ = run(ModelTurn(text=None), ModelTurn(text=None))

    # First turn has neither tools nor text -> loop stops at NO_OUTPUT.
    assert state.termination_reason == TerminationReason.NO_OUTPUT
    assert state.status == "failed"


def test_whitespace_only_answer_is_treated_as_no_output() -> None:
    state, _, _ = run(ModelTurn(text="   \n  "))

    assert state.termination_reason == TerminationReason.NO_OUTPUT


# --- untrusted model output: invalid tools ----------------------------------


def test_unknown_tool_call_is_counted_and_never_executed() -> None:
    state, _, registry = run(
        ModelTurn(tool_calls=(tool_call(name="delete_everything", path="/"),)),
        ModelTurn(text="recovered"),
    )

    assert state.unsupported_calls == 1
    assert state.observations[0].executed is False
    assert state.observations[0].refusal == "unknown_tool"
    assert registry.executed == []
    # The refusal is replayed to the model, which then recovered.
    assert state.status == "completed"


def test_malformed_arguments_are_refused_and_reported() -> None:
    state, _, registry = run(
        ModelTurn(tool_calls=(tool_call(query=12345),)),
        ModelTurn(text="ok"),
    )

    assert state.observations[0].refusal == "invalid_arguments"
    assert registry.executed == []


# --- duplicate suppression (US-303) ------------------------------------------


def test_repeated_identical_calls_are_suppressed() -> None:
    identical = [tool_call(query="same") for _ in range(MAX_IDENTICAL_CALLS + 3)]
    turns = [ModelTurn(tool_calls=(call,)) for call in identical]
    turns.append(ModelTurn(text="final"))

    state, _, registry = run(*turns, max_iterations=20)

    assert len(registry.executed) == MAX_IDENTICAL_CALLS
    assert state.duplicate_calls == 3
    assert state.status == "completed"


def test_call_counts_reset_between_runs() -> None:
    registry = CountingRegistry()
    model = FakeModelAdapter(
        ModelTurn(tool_calls=(tool_call(query="same"),)),
        ModelTurn(text="a"),
        ModelTurn(tool_calls=(tool_call(query="same"),)),
        ModelTurn(text="b"),
    )
    agent = ResearchAgent(model, registry)

    first = agent.run("q1")
    second = agent.run("q2")

    assert len(registry.executed) == 2  # not suppressed on the second run
    assert first.status == second.status == "completed"


# --- bounded loop: iteration exhaustion --------------------------------------


def test_iteration_limit_stops_the_loop_with_explicit_reason() -> None:
    endless = [ModelTurn(tool_calls=(tool_call(query=f"q{i}"),)) for i in range(20)]

    state, model, registry = run(*endless, max_iterations=3)

    assert state.termination_reason == TerminationReason.MAX_ITERATIONS
    assert state.iterations == 3
    assert state.model_calls == 3
    assert len(model.calls) == 3
    assert len(registry.executed) == 3
    # Work was done but no answer exists: partial, never "completed".
    assert state.status == "partial"


def test_deadline_stops_the_loop() -> None:
    class Clock:
        def __init__(self) -> None:
            self.now = 0.0

        def __call__(self) -> float:
            self.now += 10.0
            return self.now

    clock = Clock()
    endless = [ModelTurn(tool_calls=(tool_call(query=f"q{i}"),)) for i in range(10)]

    state, _, _ = run(*endless, deadline_seconds=15.0, clock=clock)

    assert state.termination_reason == TerminationReason.DEADLINE_EXCEEDED
    assert state.status == "partial"


def test_iteration_limit_of_one_allows_exactly_one_call() -> None:
    state, model, _ = run(ModelTurn(tool_calls=(tool_call(query="x"),)), max_iterations=1)

    assert state.model_calls == 1
    assert state.termination_reason == TerminationReason.MAX_ITERATIONS


# --- provider failure (US-304) -----------------------------------------------


def test_model_provider_error_stops_the_run_and_is_reported() -> None:
    state, _, _ = run(ModelTurn(tool_calls=(tool_call(query="x"),)), ModelProviderError("boom"))

    assert state.termination_reason == TerminationReason.MODEL_ERROR
    assert state.status == "partial"  # one observation exists
    assert any("boom" in error for error in state.errors)


def test_model_error_on_first_turn_is_a_failed_run() -> None:
    state, _, _ = run(ModelProviderError("no key"))

    assert state.status == "failed"
    assert state.termination_reason == TerminationReason.MODEL_ERROR
    assert state.iterations == 1


# --- honest status derivation ------------------------------------------------


def test_failed_tool_then_answer_is_not_labelled_cleanly() -> None:
    def failing_handler(args: SearchArgs) -> str:
        from agent007.errors import SearchProviderError

        raise SearchProviderError("quota exceeded")

    registry = CountingRegistry()
    registry._tools["search"].handler = failing_handler  # type: ignore[union-attr]
    model = FakeModelAdapter(
        ModelTurn(tool_calls=(tool_call(query="x"),)),
        ModelTurn(text="partial answer"),
    )
    agent = ResearchAgent(model, registry)

    state = agent.run("q")

    assert state.final_text == "partial answer"
    assert state.status == "partial"
    assert any("quota exceeded" in error for error in state.errors)


def test_text_alongside_tool_calls_is_not_treated_as_final() -> None:
    state, _, _ = run(
        ModelTurn(text="let me look", tool_calls=(tool_call(query="x"),)),
        ModelTurn(text="the answer"),
    )

    assert state.final_text == "the answer"
    assert state.status == "completed"


def test_token_usage_is_recorded_when_provided() -> None:
    state, _, _ = run(
        ModelTurn(tool_calls=(tool_call(query="x"),), usage=TokenUsage(input_tokens=10)),
        ModelTurn(text="done", usage=TokenUsage(input_tokens=40, output_tokens=5)),
    )

    assert state.token_usage is not None
    assert state.token_usage.input_tokens == 40


# --- constructor validation --------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_iterations": 0}, "max_iterations"),
        ({"deadline_seconds": 0}, "deadline_seconds"),
        ({"deadline_seconds": -1}, "deadline_seconds"),
    ],
)
def test_invalid_agent_bounds_are_rejected(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        ResearchAgent(FakeModelAdapter(), CountingRegistry(), **kwargs)  # type: ignore[arg-type]

    assert message in str(excinfo.value)


def test_fake_model_exhaustion_is_a_provider_error_not_a_crash() -> None:
    registry = CountingRegistry()
    model = FakeModelAdapter()  # no scripted turns at all
    agent = ResearchAgent(model, registry)

    state = agent.run("q")

    assert state.termination_reason == TerminationReason.MODEL_ERROR
    assert state.status == "failed"


def test_budget_aware_prompt_on_last_turn() -> None:
    """Fix A: when near iteration budget, inject budget-aware instructions."""
    registry = CountingRegistry()
    model = FakeModelAdapter(
        ModelTurn(tool_calls=(tool_call(query="007"),)),
        ModelTurn(text="answer"),
    )
    agent = ResearchAgent(model, registry, max_iterations=2)
    state = agent.run("What is 007?")
    assert state.status == "completed"
    # On the last iteration (iteration==2, remaining==0), we inject budget note
    second_call = model.calls[1]
    assert "BUDGET" in second_call["question"]


def test_budget_aware_prompt_not_on_early_turns() -> None:
    """Fix A: budget note only injected near end of iterations."""
    registry = CountingRegistry()
    model = FakeModelAdapter(
        ModelTurn(tool_calls=(tool_call(query="007"),)),
        ModelTurn(tool_calls=(tool_call(query="second"),)),
        ModelTurn(text="answer"),
    )
    agent = ResearchAgent(model, registry, max_iterations=8)
    state = agent.run("Question")
    assert state.status == "completed"
    # First call should not have budget note
    assert "BUDGET" not in model.calls[0]["question"]
