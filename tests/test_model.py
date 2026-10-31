"""Tests for the model adapter (US-304).

The OpenAI adapter is exercised against a fake client that mimics the Responses
API surface, so these tests contact no provider and need no credentials
(US-503). The goal is to pin the *request shape* and the *error mapping*, not to
re-test the SDK.

**Live provider integration was not run:** no `OPENAI_API_KEY` exists in this
environment, so no real model call was made. See `docs/STATUS.md`.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent007.config import Settings
from agent007.errors import ModelProviderError, ToolValidationError
from agent007.model import (
    MAX_FINAL_TEXT_CHARS,
    REPLAY_OBSERVATION_CHARS,
    FakeModelAdapter,
    ModelTurn,
    OpenAIModelAdapter,
    ToolDefinition,
    _redact,
)
from agent007.models import ToolCall, ToolObservation
from agent007.tools.registry import ToolRegistry


class FakeResponses:
    """Stands in for ``client.responses``; records the request it received."""

    def __init__(self, response: object | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.requests: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def fake_client(response: object | None = None, error: Exception | None = None) -> SimpleNamespace:
    return SimpleNamespace(responses=FakeResponses(response, error))


def adapter_with(response: object | None = None, error: Exception | None = None) -> tuple:
    client = fake_client(response, error)
    adapter = OpenAIModelAdapter(Settings(model_name="test-model"), client)
    return adapter, client.responses


def registry_with_tool() -> ToolRegistry:
    from pydantic import BaseModel

    class Args(BaseModel):
        query: str

    registry = ToolRegistry()
    registry.register(
        name="web_search", description="Search.", args_model=Args, handler=lambda a: "x"
    )
    return registry


# --- construction: no defaulted model ID -------------------------------------


def test_adapter_refuses_to_build_without_a_model() -> None:
    with pytest.raises(ToolValidationError) as excinfo:
        OpenAIModelAdapter(Settings(model_name=None), fake_client())

    assert "ATLAS_MODEL" in str(excinfo.value)


def test_adapter_accepts_an_explicit_model() -> None:
    adapter, _ = adapter_with(response=SimpleNamespace(output=[], output_text="hi", usage=None))

    assert adapter is not None


# --- request shape -----------------------------------------------------------


def test_request_carries_model_instructions_and_tools() -> None:
    adapter, responses = adapter_with(
        response=SimpleNamespace(output=[], output_text="answer", usage=None)
    )
    registry = registry_with_tool()

    adapter.complete("What is Atlas?", [], registry.specs())

    request = responses.requests[0]
    assert request["model"] == "test-model"
    assert "research assistant" in str(request["instructions"]).lower()
    tools = request["tools"]
    assert len(tools) == 1
    assert tools[0]["type"] == "function"
    assert tools[0]["name"] == "web_search"
    assert "parameters" in tools[0]


def test_request_replays_prior_observations_as_function_call_pairs() -> None:
    adapter, responses = adapter_with(
        response=SimpleNamespace(output=[], output_text="done", usage=None)
    )
    observations = [
        ToolObservation(call_id="call_abc", name="web_search", ok=True, output="some results"),
        ToolObservation(call_id="call_def", name="fetch_page", ok=False, output="error: blocked"),
    ]

    adapter.complete("question", observations, [])

    payload = responses.requests[0]["input"]
    assert payload[0] == {"role": "user", "content": "question"}
    assert payload[1]["type"] == "function_call"
    assert payload[1]["call_id"] == "call_call_abc"
    assert payload[2] == {
        "type": "function_call_output",
        "call_id": "call_abc",
        "output": "some results",
    }
    assert payload[4]["call_id"] == "call_def"
    assert len(payload) == 5


def test_replayed_observations_are_bounded() -> None:
    adapter, responses = adapter_with(
        response=SimpleNamespace(output=[], output_text="x", usage=None)
    )
    huge = ToolObservation(call_id="c1", name="fetch_page", ok=True, output="y" * 500_000)

    adapter.complete("q", [huge], [])

    output = responses.requests[0]["input"][2]["output"]
    assert len(output) == REPLAY_OBSERVATION_CHARS


# --- response parsing --------------------------------------------------------


def test_final_text_is_returned() -> None:
    adapter, _ = adapter_with(
        response=SimpleNamespace(output=[], output_text="The answer.", usage=None)
    )

    turn = adapter.complete("q", [], [])

    assert turn.text == "The answer."
    assert turn.tool_calls == ()


def test_tool_calls_are_parsed_including_raw_arguments() -> None:
    function_call = SimpleNamespace(
        type="function_call",
        call_id="call_1",
        name="web_search",
        arguments='{"query": "007"}',
    )
    adapter, _ = adapter_with(
        response=SimpleNamespace(output=[function_call], output_text="", usage=None)
    )

    turn = adapter.complete("q", [], [])

    assert len(turn.tool_calls) == 1
    call = turn.tool_calls[0]
    assert call.call_id == "call_1"
    assert call.name == "web_search"
    assert call.arguments == {"query": "007"}
    assert call.raw_arguments == '{"query": "007"}'


def test_non_function_call_output_items_are_ignored() -> None:
    message_item = SimpleNamespace(type="message", role="assistant")
    function_call = SimpleNamespace(
        type="function_call", call_id="c", name="web_search", arguments="{}"
    )
    adapter, _ = adapter_with(
        response=SimpleNamespace(output=[message_item, function_call], output_text="t", usage=None)
    )

    turn = adapter.complete("q", [], [])

    assert [call.name for call in turn.tool_calls] == ["web_search"]


def test_usage_is_captured_when_the_provider_reports_it() -> None:
    usage = SimpleNamespace(input_tokens=11, output_tokens=7, total_tokens=18)
    adapter, _ = adapter_with(response=SimpleNamespace(output=[], output_text="x", usage=usage))

    turn = adapter.complete("q", [], [])

    assert turn.usage is not None
    assert turn.usage.input_tokens == 11
    assert turn.usage.total_tokens == 18


def test_absent_usage_stays_none_rather_than_zero() -> None:
    adapter, _ = adapter_with(response=SimpleNamespace(output=[], output_text="x", usage=None))

    turn = adapter.complete("q", [], [])

    assert turn.usage is None


def test_oversized_final_text_is_bounded() -> None:
    adapter, _ = adapter_with(
        response=SimpleNamespace(output=[], output_text="z" * 200_000, usage=None)
    )

    turn = adapter.complete("q", [], [])

    assert len(turn.text or "") <= MAX_FINAL_TEXT_CHARS


# --- malformed provider output -----------------------------------------------


def test_malformed_tool_arguments_raise_a_provider_error() -> None:
    function_call = SimpleNamespace(
        type="function_call", call_id="c", name="web_search", arguments="{not json"
    )
    adapter, _ = adapter_with(
        response=SimpleNamespace(output=[function_call], output_text="", usage=None)
    )

    with pytest.raises(ModelProviderError) as excinfo:
        adapter.complete("q", [], [])

    assert "arguments" in str(excinfo.value)


def test_non_object_tool_arguments_raise_a_provider_error() -> None:
    function_call = SimpleNamespace(
        type="function_call", call_id="c", name="web_search", arguments='["a", "b"]'
    )
    adapter, _ = adapter_with(
        response=SimpleNamespace(output=[function_call], output_text="", usage=None)
    )

    with pytest.raises(ModelProviderError):
        adapter.complete("q", [], [])


# --- provider failures are mapped and redacted (US-601) ---------------------


def test_provider_exception_becomes_model_provider_error() -> None:
    adapter, _ = adapter_with(error=RuntimeError("connection reset"))

    with pytest.raises(ModelProviderError) as excinfo:
        adapter.complete("q", [], [])

    assert "connection reset" in str(excinfo.value)


def test_api_key_is_redacted_from_provider_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sk-this-is-a-very-secret-key-0123456789"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    adapter, _ = adapter_with(error=RuntimeError(f"401 unauthorized: {secret}"))

    with pytest.raises(ModelProviderError) as excinfo:
        adapter.complete("q", [], [])

    assert secret not in str(excinfo.value)
    assert "[redacted]" in str(excinfo.value)


def test_redaction_removes_key_patterns_without_the_env_var() -> None:
    message = "error at https://api?key=sk-proj-abcdefghijklmnop"

    redacted = _redact(message)

    assert "sk-proj-abcdefghijklmnop" not in redacted


# --- tool definition validation ----------------------------------------------


def test_tool_definition_rejects_an_empty_name() -> None:
    with pytest.raises(ValidationError):
        ToolDefinition(name="", description="d", parameters={})


def test_malformed_tool_spec_fails_loudly_before_the_network() -> None:
    adapter, responses = adapter_with(
        response=SimpleNamespace(output=[], output_text="x", usage=None)
    )
    broken_spec = SimpleNamespace(name="", description="d", parameters={})

    with pytest.raises(ValidationError):
        adapter.complete("q", [], [broken_spec])

    assert responses.requests == []


# --- fake adapter ------------------------------------------------------------


def test_fake_adapter_replays_scripted_turns_in_order() -> None:
    fake = FakeModelAdapter(ModelTurn(text="one"), ModelTurn(text="two"))

    assert fake.complete("q", [], []).text == "one"
    assert fake.complete("q", [], []).text == "two"


def test_fake_adapter_supports_observation_dependent_turns() -> None:
    def react(observations: list[ToolObservation]) -> ModelTurn:
        return ModelTurn(text=f"saw {observations[0].output}")

    fake = FakeModelAdapter(react)

    turn = fake.complete(
        "q",
        [ToolObservation(call_id="c", name="n", ok=True, output="value")],
        [],
    )

    assert turn.text == "saw value"


def test_fake_adapter_raises_when_script_is_exhausted() -> None:
    fake = FakeModelAdapter()

    with pytest.raises(ModelProviderError):
        fake.complete("q", [], [])


def test_fake_adapter_records_what_it_was_given() -> None:
    fake = FakeModelAdapter(ModelTurn(text="x"))
    calls = registry_with_tool().specs()

    fake.complete("question", [], calls)

    assert fake.calls[0]["question"] == "question"
    assert [spec.name for spec in fake.calls[0]["tools"]] == ["web_search"]


# --- raw tool call construction sanity ---------------------------------------


def test_tool_call_preserves_raw_arguments_exactly() -> None:
    raw = '{"query": "spaces  kept", "n": 1}'

    call = ToolCall(call_id="c", name="web_search", arguments=json.loads(raw), raw_arguments=raw)

    assert call.raw_arguments == raw
