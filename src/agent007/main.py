"""Command-line entry point for Atlas.

Scope: parse the question, validate it, load and validate configuration, and —
when providers are configured — execute a bounded research run and write its
evidence-grounded Markdown report (US-502, Sprints 1 and 5).

Exit codes:
    0  request validated; in live mode the run completed and a report was written
    2  argument/usage error (raised by argparse)
    3  invalid research request
    4  invalid or incomplete configuration
    5  research executed but did not complete (partial, failed, or provider error)
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence

from dotenv import load_dotenv
from pydantic import ValidationError

from agent007 import __version__
from agent007.config import Settings
from agent007.errors import (
    AtlasError,
    ConfigurationError,
    InvalidRequestError,
    ModelProviderError,
)
from agent007.models import ResearchRequest

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INVALID_REQUEST = 3
EXIT_CONFIGURATION_ERROR = 4
EXIT_RESEARCH_INCOMPLETE = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="007",
        description="Research a question and produce an evidence-grounded Markdown report.",
    )
    parser.add_argument("question", help="The research question to investigate.")
    parser.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        default=None,
        help="Write the Markdown report to PATH instead of stdout.",
    )
    parser.add_argument(
        "--max-iterations",
        metavar="N",
        type=int,
        default=None,
        help="Override the model-turn bound for this run (1-64).",
    )
    parser.add_argument(
        "--max-results",
        metavar="N",
        type=int,
        default=None,
        help="Override the search-result bound for this run (1-50).",
    )
    parser.add_argument(
        "--deadline",
        metavar="SECONDS",
        type=float,
        default=None,
        help="Override the wall-clock run budget for this run, in seconds.",
    )
    parser.add_argument("--version", action="version", version=f"atlas {__version__}")
    return parser


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    *,
    research: object | None = None,
    stdout: object | None = None,
    stderr: object | None = None,
) -> int:
    """Run the CLI and return a process exit code.

    Args:
        argv: Argument list without the program name. Defaults to ``sys.argv``.
        environ: Environment mapping. When ``None``, ``.env`` is loaded and
            ``os.environ`` is used, which is the real CLI behaviour. Tests pass an
            explicit mapping to stay hermetic.
        research: Optional ``run_research``-compatible callable, injected by
            tests so no provider is ever constructed offline.
        stdout: Output stream; ``sys.stdout`` when omitted.
        stderr: Error stream; ``sys.stderr`` when omitted.
    """
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    args = build_parser().parse_args(list(argv) if argv is not None else None)

    # Request validation happens first so an invalid question is rejected before
    # configuration (and therefore any provider client) is ever touched.
    try:
        request = ResearchRequest.parse(args.question)
    except InvalidRequestError as exc:
        print(f"error: {exc}", file=err)
        return EXIT_INVALID_REQUEST

    if environ is None:
        load_dotenv(override=False)
        environ = os.environ

    try:
        settings = Settings.from_env(environ)
    except ConfigurationError as exc:
        print(f"error: {exc}", file=err)
        return EXIT_CONFIGURATION_ERROR

    # Per-run depth overrides (US-703) are validated by the very same Settings
    # constraints as environment configuration, so a flag can never push a run
    # past the documented bounds.
    settings = _apply_depth_overrides(args, settings, err)
    if settings is None:
        return EXIT_USAGE

    if settings.mode != "live":
        print("atlas request accepted", file=out)
        print(f"  question: {request.question}", file=out)
        print(f"  mode: {settings.mode}", file=out)
        print(
            f"  depth: max_iterations={settings.max_iterations} "
            f"max_results={settings.max_results} deadline={settings.deadline_seconds}s",
            file=out,
        )
        print(
            "status: validated; research execution requires ATLAS_MODE=live "
            "with OPENAI_API_KEY, TAVILY_API_KEY, and ATLAS_MODEL set",
            file=out,
        )
        return EXIT_OK

    return _run_live(request, settings, research, args.output, out, err)


def _apply_depth_overrides(
    args: argparse.Namespace, settings: Settings, err: object
) -> Settings | None:
    """Apply ``--max-iterations`` / ``--max-results`` / ``--deadline`` (US-703).

    The override is validated by re-validating the whole settings object, so
    the accepted ranges are defined in exactly one place (``Settings`` fields)
    and cannot drift from the environment-based configuration.

    Returns:
        The overridden settings, or ``None`` when a value is out of range.
    """
    overrides: dict[str, object] = {}
    if args.max_iterations is not None:
        overrides["max_iterations"] = args.max_iterations
    if args.max_results is not None:
        overrides["max_results"] = args.max_results
    if args.deadline is not None:
        overrides["deadline_seconds"] = args.deadline

    if not overrides:
        return settings

    try:
        merged = Settings.model_validate({**settings.model_dump(), **overrides})
    except ValidationError as exc:
        parts = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        ]
        print("error: invalid research-depth option: " + "; ".join(parts), file=err)
        return None
    return merged


def _run_live(
    request: ResearchRequest,
    settings: Settings,
    research: object | None,
    output_path: str | None,
    out: object,
    err: object,
) -> int:
    """Execute a live research run and write its report."""
    runner = research if research is not None else _build_live_runner(settings, err)
    if runner is None:
        return EXIT_CONFIGURATION_ERROR

    try:
        outcome = runner(request.question, settings)
    except AtlasError as exc:
        print(f"error: research run failed: {exc}", file=err)
        return EXIT_RESEARCH_INCOMPLETE
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"error: research run failed: {type(exc).__name__}", file=err)
        return EXIT_RESEARCH_INCOMPLETE

    markdown = outcome.report.to_markdown()

    if output_path:
        try:
            with open(output_path, "w", encoding="utf-8") as handle:
                handle.write(markdown)
        except OSError as exc:
            print(f"error: could not write report to {output_path}: {exc}", file=err)
            return EXIT_RESEARCH_INCOMPLETE
        print(f"report written to {output_path}", file=out)
    else:
        print(markdown, file=out)

    status = outcome.state.status
    reason = outcome.state.termination_reason
    _print_run_metadata(outcome.state, settings, out)
    if status == "completed":
        return EXIT_OK
    print(f"research run ended with status '{status}' (stopped: {reason})", file=err)
    return EXIT_RESEARCH_INCOMPLETE


def _print_run_metadata(state: object, settings: Settings, out: object) -> None:
    """Report bounded-resource usage honestly (US-603).

    Token usage is printed only when the provider actually supplied it;
    otherwise it is reported as unavailable, never guessed.
    """
    usage = getattr(state, "token_usage", None)
    if usage is None:
        usage_line = "token usage: unavailable (provider did not report usage)"
    else:
        parts = []
        if usage.input_tokens is not None:
            parts.append(f"input={usage.input_tokens}")
        if usage.output_tokens is not None:
            parts.append(f"output={usage.output_tokens}")
        if usage.total_tokens is not None:
            parts.append(f"total={usage.total_tokens}")
        usage_line = "token usage: " + (", ".join(parts) if parts else "unavailable")
    print(
        f"run metadata: iterations={getattr(state, 'iterations', 0)} "
        f"model_calls={getattr(state, 'model_calls', 0)} "
        f"tool_calls={len(getattr(state, 'observations', ()))} "
        f"unsupported={getattr(state, 'unsupported_calls', 0)} "
        f"duplicates_suppressed={getattr(state, 'duplicate_calls', 0)}",
        file=out,
    )
    print(usage_line, file=out)
    print(f"depth: {_depth_line(settings)}", file=out)


def _depth_line(settings: Settings) -> str:
    """The effective depth bounds of a run, so it can be reproduced (US-703)."""
    return (
        f"max_iterations={settings.max_iterations} "
        f"max_results={settings.max_results} "
        f"deadline={settings.deadline_seconds}s "
        f"timeout={settings.timeout_seconds}s"
    )


def _build_search_provider(settings: Settings) -> object:
    """Pick the search provider deterministically (US-706): Tavily, else Exa."""
    from agent007.tools.search import build_exa_provider, build_tavily_provider

    if settings.tavily_api_key is not None:
        return build_tavily_provider(
            settings.tavily_api_key.get_secret_value(),
            default_max_results=settings.max_results,
        )
    if settings.exa_api_key is not None:
        return build_exa_provider(
            settings.exa_api_key.get_secret_value(),
            default_max_results=settings.max_results,
        )
    raise ConfigurationError("live mode requires one of TAVILY_API_KEY or EXA_API_KEY to be set.")


def _build_live_runner(settings: Settings, err: object) -> object | None:
    """Construct real providers and return a callable research runner.

    This is the only place paid providers are ever built. A configuration or
    provider problem here is reported as a configuration error, never as a
    partial research result.
    """
    from agent007.model import OpenAIModelAdapter
    from agent007.pipeline import run_research
    from agent007.tools.fetch import PageFetcher, UrlPolicy

    try:
        # Deterministic selection (US-706): Tavily when configured, else Exa.
        # Settings.from_env guarantees at least one is present in live mode.
        search = _build_search_provider(settings)
        fetcher = PageFetcher(UrlPolicy(), timeout=settings.timeout_seconds)
        model = OpenAIModelAdapter(settings, timeout=settings.timeout_seconds)
    except (ConfigurationError, ModelProviderError, AtlasError) as exc:
        print(f"error: {exc}", file=err)
        return None

    def runner(question: str, run_settings: Settings) -> object:
        return run_research(
            question,
            run_settings,
            model=model,
            search=search,
            fetcher=fetcher,
        )

    return runner


if __name__ == "__main__":
    raise SystemExit(main())
