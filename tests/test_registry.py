"""Tests for the allowlisted tool registry (US-301, US-302, US-303).

Model output is untrusted input: these tests assert that unknown names,
malformed arguments, and repeated identical calls never execute anything.
No network I/O and no credentials (US-503).
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict, Field

from agent007.errors import ToolValidationError
from agent007.models import ToolCall
from agent007.tools.registry import (
    MAX_IDENTICAL_CALLS,
    MAX_TOOL_OUTPUT_CHARS,
    ToolRegistry,
    build_default_registry,
)


class EchoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=100)


class RecordingRegistry(ToolRegistry):
    """Registry that records every handler execution."""

    def __init__(self) -> None:
        super().__init__()
        self.executed: list[object] = []

    def register_echo(self) -> None:
        def handler(args: EchoArgs) -> str:
            self.executed.append(args)
            return f"echo:{args.text}"

        self.register(
            name="echo",
            description="Echo text back.",
            args_model=EchoArgs,
            handler=handler,
        )


def registry() -> RecordingRegistry:
    reg = RecordingRegistry()
    reg.register_echo()
    return reg


def call(name: str = "echo", **arguments: object) -> ToolCall:
    import json

    raw = json.dumps(arguments)
    return ToolCall(call_id="c1", name=name, arguments=dict(arguments), raw_arguments=raw)


# --- allowlist enforcement (US-301) -----------------------------------------


def test_registered_tool_executes() -> None:
    reg = registry()

    observation = reg.execute(call(text="hi"))

    assert observation.ok is True
    assert observation.executed is True
    assert observation.output == "echo:hi"
    assert len(reg.executed) == 1


def test_unknown_tool_is_refused_and_nothing_executes() -> None:
    reg = registry()

    observation = reg.execute(call(name="rm_rf", path="/"))

    assert observation.ok is False
    assert observation.executed is False
    assert observation.refusal == "unknown_tool"
    assert reg.executed == []


def test_unknown_tool_error_lists_available_tools() -> None:
    observation = registry().execute(call(name="nope"))

    assert "'nope'" in observation.output
    assert "echo" in observation.output


def test_case_variant_of_tool_name_is_still_rejected() -> None:
    """Dispatch must be exact: ECHO must not fall through to echo."""
    reg = registry()

    observation = reg.execute(call(name="ECHO", text="x"))

    assert observation.refusal == "unknown_tool"
    assert reg.executed == []


def test_duplicate_name_registered_by_application_is_rejected() -> None:
    reg = registry()

    with pytest.raises(ToolValidationError) as excinfo:
        reg.register_echo()

    assert "already registered" in str(excinfo.value)


def test_empty_or_non_string_tool_name_is_rejected() -> None:
    reg = ToolRegistry()
    for bad in ("", None, 42):  # type: ignore[arg-type]
        with pytest.raises(ToolValidationError):
            reg.register(
                name=bad,  # type: ignore[arg-type]
                description="x",
                args_model=EchoArgs,
                handler=lambda args: "x",
            )


def test_registration_without_description_is_rejected() -> None:
    with pytest.raises(ToolValidationError):
        ToolRegistry().register(
            name="t", description="", args_model=EchoArgs, handler=lambda args: "x"
        )


# --- argument validation (US-302) -------------------------------------------


def test_malformed_arguments_are_refused_not_executed() -> None:
    reg = registry()

    observation = reg.execute(
        ToolCall(call_id="c1", name="echo", arguments={"text": 123}, raw_arguments='{"text":123}')
    )

    assert observation.ok is False
    assert observation.executed is False
    assert observation.refusal == "invalid_arguments"
    assert "text" in observation.output
    assert reg.executed == []


def test_missing_required_argument_is_refused() -> None:
    reg = registry()

    observation = reg.execute(ToolCall(call_id="c1", name="echo"))

    assert observation.refusal == "invalid_arguments"
    assert reg.executed == []


def test_extra_arguments_are_rejected_by_pydantic() -> None:
    reg = registry()

    observation = reg.execute(call(text="ok", unexpected="x"))

    assert observation.refusal == "invalid_arguments"
    assert reg.executed == []


def test_over_long_argument_is_refused() -> None:
    observation = registry().execute(call(text="a" * 200))

    assert observation.refusal == "invalid_arguments"


# --- duplicate suppression (US-303) -----------------------------------------


def test_identical_call_runs_up_to_the_threshold() -> None:
    reg = registry()

    for _ in range(MAX_IDENTICAL_CALLS):
        observation = reg.execute(call(text="same"))
        assert observation.ok is True

    assert len(reg.executed) == MAX_IDENTICAL_CALLS


def test_repeated_identical_call_is_suppressed_and_not_re_executed() -> None:
    reg = registry()

    for _ in range(MAX_IDENTICAL_CALLS):
        reg.execute(call(text="same"))

    observation = reg.execute(call(text="same"))

    assert observation.ok is False
    assert observation.executed is False
    assert observation.refusal == "duplicate"
    assert "different action" in observation.output
    assert len(reg.executed) == MAX_IDENTICAL_CALLS


def test_different_arguments_are_not_treated_as_duplicates() -> None:
    reg = registry()

    for text in ("a", "b", "c", "d", "e"):
        observation = reg.execute(call(text=text))
        assert observation.ok is True

    assert len(reg.executed) == 5


def test_reset_call_counts_allows_the_call_again() -> None:
    reg = registry()

    for _ in range(MAX_IDENTICAL_CALLS + 2):
        reg.execute(call(text="same"))
    assert len(reg.executed) == MAX_IDENTICAL_CALLS

    reg.reset_call_counts()
    observation = reg.execute(call(text="same"))

    assert observation.ok is True
    assert len(reg.executed) == MAX_IDENTICAL_CALLS + 1


# --- handler failure containment --------------------------------------------


def test_handler_exception_becomes_a_bounded_error_observation() -> None:
    reg = ToolRegistry()

    def boom(args: EchoArgs) -> str:
        raise RuntimeError("secret internal detail 12345")

    reg.register(name="boom", description="x", args_model=EchoArgs, handler=boom)

    observation = reg.execute(ToolCall(call_id="c1", name="boom", arguments={"text": "x"}))

    assert observation.ok is False
    assert observation.executed is True
    assert "RuntimeError" in observation.output
    assert "12345" not in observation.output  # no traceback detail leaked


def test_non_string_handler_result_is_rejected() -> None:
    reg = ToolRegistry()
    reg.register(name="bad", description="x", args_model=EchoArgs, handler=lambda args: 42)  # type: ignore[arg-type,return-value]

    observation = reg.execute(ToolCall(call_id="c1", name="bad", arguments={"text": "x"}))

    assert observation.ok is False
    assert "non-string" in observation.output


def test_tool_output_is_bounded() -> None:
    reg = ToolRegistry()
    reg.register(name="loud", description="x", args_model=EchoArgs, handler=lambda args: "z" * 9000)

    observation = reg.execute(ToolCall(call_id="c1", name="loud", arguments={"text": "x"}))

    assert len(observation.output) <= MAX_TOOL_OUTPUT_CHARS
    assert observation.output.endswith("[truncated]")


# --- registry introspection -------------------------------------------------


def test_specs_are_sorted_and_complete() -> None:
    reg = registry()
    reg.register(name="alpha", description="a", args_model=EchoArgs, handler=lambda args: "a")

    specs = reg.specs()

    assert [spec.name for spec in specs] == ["alpha", "echo"]
    assert all(spec.description for spec in specs)
    assert all("properties" in spec.parameters or "$" in str(spec.parameters) for spec in specs)


def test_specs_instances_are_independent() -> None:
    """Registries must not share state through a class-level cache."""
    first = registry()
    second = registry()
    second.register(name="extra", description="x", args_model=EchoArgs, handler=lambda args: "x")

    assert "extra" not in [spec.name for spec in first.specs()]
    assert "extra" in [spec.name for spec in second.specs()]


# --- default registry wiring ------------------------------------------------


def test_default_registry_registers_only_available_tools() -> None:
    from agent007.config import Settings

    class FakeSearch:
        def search(self, query: str, max_results: int | None = None):  # noqa: ARG001
            return []

    reg = build_default_registry(Settings(), search=FakeSearch())

    assert reg.names() == ["web_search"]

    empty = build_default_registry(Settings())
    assert empty.names() == []


def test_default_registry_formats_search_results() -> None:
    from agent007.config import Settings
    from agent007.models import SearchResult

    class FakeSearch:
        def search(self, query: str, max_results: int | None = None):  # noqa: ARG001
            return [
                SearchResult(
                    title="Atlas docs", url="https://example.com/docs", snippet="A snippet."
                )
            ]

    reg = build_default_registry(Settings(), search=FakeSearch())
    observation = reg.execute(
        ToolCall(call_id="c1", name="web_search", arguments={"query": "007"})
    )

    assert observation.ok is True
    assert "Atlas docs" in observation.output
    assert "https://example.com/docs" in observation.output
    assert "A snippet." in observation.output
