"""Explicit allowlisted tool registry (US-301, ADR-004, SECURITY.md).

Model output is untrusted. The only functions the agent can ever invoke are the
ones registered here by name at construction time in application code:

* a call to an unregistered name yields an ``ok=False`` observation and
  **nothing executes**;
* arguments are validated against a Pydantic model before the handler runs;
* handler output is bounded before it reaches the model context;
* an identical call repeated beyond a threshold is answered by a suppression
  rule instead of being re-executed, so a stuck model cannot burn budget (US-303).

There is no ``eval``, no dynamic import, and no dispatch on a model-supplied
object — only a dictionary lookup on an allowlisted string.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic import Field as PField

from atlas.config import Settings
from atlas.errors import (
    AtlasError,
    FetchError,
    SearchProviderError,
    ToolValidationError,
)
from atlas.models import MAX_QUERY_LENGTH, ToolCall, ToolObservation

#: Maximum characters of any tool result handed back to the model.
MAX_TOOL_OUTPUT_CHARS = 4000

#: Executions of one identical (name, arguments) pair before it is suppressed.
MAX_IDENTICAL_CALLS = 3


class ToolSpec(BaseModel):
    """Provider-facing description of one registered tool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str
    parameters: dict[str, Any]


class SearchArgs(BaseModel):
    """Arguments for the ``web_search`` tool."""

    model_config = ConfigDict(extra="forbid")

    query: str = PField(description="Focused search query", max_length=MAX_QUERY_LENGTH)
    max_results: int | None = PField(default=None, ge=1, le=20, description="Result bound")


class FetchArgs(BaseModel):
    """Arguments for the ``fetch_page`` tool."""

    model_config = ConfigDict(extra="forbid")

    url: str = PField(description="Absolute http(s) URL to retrieve")


class _Registration(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    spec: ToolSpec
    args_model: type[BaseModel]
    handler: Callable[[Any], str]


class ToolRegistry:
    """Name allowlist plus validated dispatch."""

    def __init__(self) -> None:
        self._tools: dict[str, _Registration] = {}
        self._identical_counts: dict[tuple[str, str], int] = {}

    def __len__(self) -> int:
        return len(self._tools)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[ToolSpec]:
        """Tool definitions to hand to the model, in a stable order."""
        return [self._tools[name].spec for name in self.names()]

    def register(
        self,
        *,
        name: str,
        description: str,
        args_model: type[BaseModel],
        handler: Callable[[Any], str],
        parameters: dict[str, Any] | None = None,
    ) -> None:
        """Register a tool. Application code is the only caller of this method."""
        if not isinstance(name, str) or not name:
            raise ToolValidationError("tool name must be a non-empty string")
        if name in self._tools:
            raise ToolValidationError(f"tool {name!r} is already registered")
        if not description:
            raise ToolValidationError(f"tool {name!r} needs a description")

        self._tools[name] = _Registration(
            spec=ToolSpec(
                name=name,
                description=description,
                parameters=parameters or _json_schema(args_model),
            ),
            args_model=args_model,
            handler=handler,
        )

    def reset_call_counts(self) -> None:
        """Clear duplicate tracking, e.g. at the start of a new run."""
        self._identical_counts.clear()

    def execute(self, call: ToolCall) -> ToolObservation:
        """Validate and run one model-requested call.

        Unknown names and malformed arguments produce an ``ok=False``
        observation that is returned to the model — the call is refused, never
        executed, and never dispatched by an unvalidated name.
        """
        registration = self._tools.get(call.name)
        if registration is None:
            return ToolObservation(
                call_id=call.call_id,
                name=call.name,
                ok=False,
                executed=False,
                refusal="unknown_tool",
                output=_bounded(
                    f"error: tool {call.name!r} is not registered; "
                    f"available tools: {', '.join(self.names()) or '(none)'}"
                ),
            )

        key = _key(call)
        if self._identical_counts.get(key, 0) >= MAX_IDENTICAL_CALLS:
            self._identical_counts[key] += 1
            return ToolObservation(
                call_id=call.call_id,
                name=call.name,
                ok=False,
                executed=False,
                refusal="duplicate",
                output=_bounded(
                    f"error: identical {call.name!r} call executed "
                    f"{MAX_IDENTICAL_CALLS} times already; choose a different action"
                ),
            )

        try:
            args = registration.args_model.model_validate(call.arguments)
        except ValidationError as exc:
            return ToolObservation(
                call_id=call.call_id,
                name=call.name,
                ok=False,
                executed=False,
                refusal="invalid_arguments",
                output=_bounded(f"error: invalid arguments: {_field_errors(exc)}"),
            )

        try:
            output = registration.handler(args)
        except (ToolValidationError, SearchProviderError, FetchError) as exc:
            observation = _failed(call, f"error: {exc}", executed=True)
        except AtlasError as exc:
            observation = _failed(call, f"error: {type(exc).__name__}: {exc}", executed=True)
        except Exception as exc:  # noqa: BLE001 - tool boundary must stay bounded
            # Never surface a traceback or anything it may embed.
            observation = _failed(
                call, f"error: tool failed with {type(exc).__name__}", executed=True
            )
        else:
            if not isinstance(output, str):
                observation = _failed(
                    call, "error: tool returned a non-string result", executed=True
                )
            else:
                self._identical_counts[key] = self._identical_counts.get(key, 0) + 1
                observation = ToolObservation(
                    call_id=call.call_id,
                    name=call.name,
                    ok=True,
                    executed=True,
                    output=_bounded(output),
                )

        return observation


def _failed(call: ToolCall, output: str, *, executed: bool) -> ToolObservation:
    return ToolObservation(
        call_id=call.call_id,
        name=call.name,
        ok=False,
        executed=executed,
        output=_bounded(output),
    )


def _key(call: ToolCall) -> tuple[str, str]:
    return (call.name, call.raw_arguments or json.dumps(call.arguments, sort_keys=True))


def _bounded(text: str) -> str:
    if len(text) <= MAX_TOOL_OUTPUT_CHARS:
        return text
    return text[: MAX_TOOL_OUTPUT_CHARS - 14] + "\n[truncated]"


def _field_errors(exc: ValidationError) -> str:
    parts = [
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
    ]
    return "; ".join(parts)


def _json_schema(args_model: type[BaseModel]) -> dict[str, Any]:
    schema = args_model.model_json_schema()
    schema.pop("title", None)
    return schema


def build_default_registry(
    settings: Settings,
    *,
    search: Any | None = None,
    fetcher: Any | None = None,
) -> ToolRegistry:
    """Build the allowlist of tools for a run.

    Tools are only registered when their backing provider is actually available,
    so an unconfigured installation never advertises a tool it cannot call.
    """
    registry = ToolRegistry()

    if search is not None:

        def run_search(args: Any) -> str:
            typed: SearchArgs = args
            results = search.search(typed.query, typed.max_results or settings.max_results)
            if not results:
                return "No results found."
            lines: list[str] = []
            for index, item in enumerate(results, start=1):
                lines.append(f"{index}. {item.title} — {item.url}")
                if item.snippet:
                    lines.append(f"   {item.snippet}")
                if item.published_date:
                    lines.append(f"   published: {item.published_date}")
            return "\n".join(lines)

        registry.register(
            name="web_search",
            description=(
                "Search the web for sources about a topic. Returns titles, URLs, "
                "and short snippets. Use a focused query; results are bounded."
            ),
            args_model=SearchArgs,
            handler=run_search,
        )

    if fetcher is not None:

        def run_fetch(args: Any) -> str:
            typed: FetchArgs = args
            page = fetcher.fetch(typed.url)
            header = f"Title: {page.title}" if page.title else f"URL: {page.url}"
            return f"{header}\n{page.text}"

        registry.register(
            name="fetch_page",
            description=(
                "Retrieve a web page and return its readable text. Only http(s) "
                "URLs are permitted; unsafe destinations are refused."
            ),
            args_model=FetchArgs,
            handler=run_fetch,
        )

    return registry
