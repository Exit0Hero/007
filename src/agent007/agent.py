"""Bounded single-agent research loop (US-301, US-302, US-303; ARCHITECTURE §5).

The loop is deliberately small and explicit:

* every model turn is stateless — the question and all prior observations are
  replayed, so nothing depends on hidden provider-side state;
* iteration count and an overall wall-clock deadline are both hard-bounded, and
  which limit stopped the run is reported as an explicit ``TerminationReason``;
* model output is untrusted: a call is only ever executed after the local
  allowlist registry has validated its name and arguments, and an identical
  call repeated beyond a threshold is suppressed rather than re-run;
* the reported status never overstates the outcome — partial work is labelled
  ``partial``, never ``completed``.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

from agent007.errors import ModelProviderError
from agent007.model import ModelAdapter, ModelTurn
from agent007.models import ResearchState, TerminationReason, ToolCall, ToolObservation

#: Hook type invoked after each executed (or refused) tool call.
ObservationHook = Callable[[ToolObservation], None]


class ResearchAgent:
    """Drives one bounded research run.

    Args:
        model: Stateless model adapter.
        registry: Allowlisted tool registry used for validated dispatch.
        max_iterations: Hard cap on model turns.
        deadline_seconds: Hard cap on total wall-clock time for the loop.
        clock: Monotonic clock, injected so tests are deterministic.
        on_observation: Optional hook called with each observation.
    """

    def __init__(
        self,
        model: ModelAdapter,
        registry: Any,
        *,
        max_iterations: int = 8,
        deadline_seconds: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
        on_observation: ObservationHook | None = None,
    ) -> None:
        if max_iterations < 1:
            raise ValueError("max_iterations must be at least 1")
        if deadline_seconds <= 0:
            raise ValueError("deadline_seconds must be positive")
        self._model = model
        self._registry = registry
        self._max_iterations = max_iterations
        self._deadline_seconds = deadline_seconds
        self._clock = clock
        self._on_observation = on_observation

    def run(self, question: str) -> ResearchState:
        """Run the loop to a terminal state. Never raises for model/tool failure."""
        state = ResearchState(question=question)
        started = self._clock()
        self._registry.reset_call_counts()

        for iteration in range(1, self._max_iterations + 1):
            if self._expired(started):
                state.finish(TerminationReason.DEADLINE_EXCEEDED)
                return state

            state.iterations = iteration

            effective_question = question
            # Fix A: budget-aware prompt on the final turn(s)
            remaining = self._max_iterations - iteration
            if remaining <= 1:
                effective_question = (
                    question
                    + "\n\nBUDGET: You have very few turns left. If you have enough evidence to answer, "
                    + "answer now with no further tool calls. Do not make speculative searches."
                )

            try:
                turn = self._model.complete(effective_question, state.observations, self._registry.specs())
            except ModelProviderError as exc:
                state.errors.append(str(exc))
                state.finish(TerminationReason.MODEL_ERROR)
                return state

            state.model_calls += 1
            if turn.usage is not None:
                state.token_usage = turn.usage

            if not turn.tool_calls:
                # Whitespace-only text is no answer at all.
                state.final_text = (turn.text or "").strip() or None
                state.finish(
                    TerminationReason.COMPLETED if state.final_text else TerminationReason.NO_OUTPUT
                )
                return state

            # Text alongside tool calls is intermediate commentary, not a final
            # answer; it is deliberately not recorded as final_text or as an
            # error, so a recovered run can still complete honestly.

            for call in turn.tool_calls:
                observation = self._execute(call, state)
                state.observations.append(observation)
                if self._on_observation is not None:
                    self._on_observation(observation)

            if self._expired(started):
                state.finish(TerminationReason.DEADLINE_EXCEEDED)
                return state

        state.finish(TerminationReason.MAX_ITERATIONS)
        return state

    def _execute(self, call: ToolCall, state: ResearchState) -> ToolObservation:
        """Execute one call through the registry, counting refusals honestly."""
        observation = self._registry.execute(call)
        if observation.refusal == "unknown_tool":
            state.unsupported_calls += 1
        elif observation.refusal == "duplicate":
            state.duplicate_calls += 1
        elif not observation.ok:
            # The tool ran but failed: real work was attempted and failed, so it
            # belongs in the run's error record.
            state.errors.append(observation.output)
        return observation

    def _expired(self, started: float) -> bool:
        return (self._clock() - started) >= self._deadline_seconds


def observations_as_replay(observations: Sequence[ToolObservation]) -> list[dict[str, Any]]:
    """Plain-dict replay of the conversation, useful for diagnostics."""
    items: list[dict[str, Any]] = []
    for observation in observations:
        items.append(
            {
                "type": "function_call",
                "call_id": f"call_{observation.call_id}",
                "name": observation.name,
            }
        )
        items.append(
            {
                "type": "function_call_output",
                "call_id": observation.call_id,
                "output": observation.output,
            }
        )
    return items


__all__ = ["ResearchAgent", "ObservationHook", "ModelTurn"]
