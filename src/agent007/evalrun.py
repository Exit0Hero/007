"""Offline evaluation runner and CLI (US-802/804/806, Sprint 8).

Entry point::

    python -m agent007.evalrun run                 # offline, no credentials, no network
    python -m agent007.evalrun run --smoke         # three-case smoke subset (offline)
    python -m agent007.evalrun run --live --smoke  # opt-in live subset (US-805)
    python -m agent007.evalrun summarize --results <eval_results.json> [--reviews <r.json>]
    python -m agent007.evalrun list

Offline runs build providers exclusively from each case's declarative fixture
(fake model script + fake search corpus): nothing reads the environment
(``Settings.from_env({})``), so results are reproducible and require no
credentials or network access (US-802 criterion 2).

Exit codes: ``0`` every deterministic check passed and no provider failure;
``2`` at least one case recorded a quality failure or provider failure;
``4`` dataset error; ``5`` configuration error (e.g. live mode without opt-in).
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from agent007.config import Settings
from agent007.errors import AtlasError, ConfigurationError, DatasetError
from agent007.evalmetrics import compute_metrics
from agent007.evalreport import (
    CaseResult,
    EvalRun,
    apply_reviews,
    load_reviews,
    provider_failure_result,
    result_from_outcome,
    utc_now,
)
from agent007.evalset import (
    EvalCase,
    build_fixture_model,
    build_fixture_search,
    default_dataset_path,
    load_dataset,
)

#: Recorded for every fixture run so no reader mistakes it for a real model.
OFFLINE_MODEL_ID = "scripted-fixture-model"
OFFLINE_SEARCH_ID = "scripted-fixture-search"
OFFLINE_LIMITATIONS: tuple[str, ...] = (
    "offline fixture run: providers are scripted fakes, so this measures the "
    "pipeline, never a real model's research quality",
    "factual accuracy and completeness/relevance require a recorded human review",
)


def evaluate_case_offline(case: EvalCase, settings: Settings) -> CaseResult:
    """Run one case against its own fixture providers — offline and deterministic.

    Never raises for a fixture/provider problem: a failure is recorded as a
    provider failure so it can never be mistaken for a quality pass.
    """
    from agent007.pipeline import run_research

    try:
        outcome = run_research(
            case.question,
            settings,
            model=build_fixture_model(case.fixture),
            search=build_fixture_search(case.fixture),
        )
    except Exception as exc:  # noqa: BLE001 - evaluation boundary
        return provider_failure_result(
            case,
            mode="offline_fixture",
            model_id=OFFLINE_MODEL_ID,
            search_provider=OFFLINE_SEARCH_ID,
            limitations=OFFLINE_LIMITATIONS,
            message=f"fixture run raised {type(exc).__name__}: {exc}",
        )
    return result_from_outcome(
        case,
        outcome,
        mode="offline_fixture",
        model_id=OFFLINE_MODEL_ID,
        search_provider=OFFLINE_SEARCH_ID,
        max_iterations=settings.max_iterations,
        limitations=OFFLINE_LIMITATIONS,
    )


def run_offline_evaluation(
    cases: list[EvalCase], settings: Settings | None = None
) -> list[CaseResult]:
    """Evaluate every selected case offline, in order."""
    effective = settings if settings is not None else Settings.from_env({})
    return [evaluate_case_offline(case, effective) for case in cases]


def smoke_subset(cases: list[EvalCase]) -> list[EvalCase]:
    """The first case of the first three categories present — a small smoke set."""
    picked: list[EvalCase] = []
    seen: set[str] = set()
    for case in cases:
        if case.category in seen:
            continue
        seen.add(case.category)
        picked.append(case)
        if len(picked) == 3:
            break
    return picked


def select_cases(
    dataset: Any,
    *,
    case_ids: list[str] | None = None,
    smoke: bool = False,
) -> list[EvalCase]:
    """Resolve the case selection, rejecting unknown IDs (US-801 criterion 4)."""
    if case_ids:
        return dataset.select(case_ids)
    if smoke:
        return smoke_subset(list(dataset.cases))
    return list(dataset.cases)


def build_run(
    *,
    mode: Literal["offline_fixture", "live"],
    dataset: Any,
    dataset_path: Path,
    results: list[CaseResult],
    settings: Settings,
    model_id: str,
    search_provider: str,
) -> EvalRun:
    """Assemble the machine-readable run with metrics computed from its results."""
    return EvalRun(
        run_id=f"eval-{mode}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        generated_at=utc_now(),
        mode=mode,
        dataset_version=dataset.dataset_version,
        dataset_path=str(dataset_path),
        model_id=model_id,
        search_provider=search_provider,
        bounds={
            "max_iterations": settings.max_iterations,
            "max_results": settings.max_results,
            "deadline_seconds": settings.deadline_seconds,
        },
        cases=tuple(results),
        metrics=tuple(metric.as_dict() for metric in compute_metrics(results)),
        evaluation_limitations=_run_limitations(mode),
    )


def _run_limitations(mode: str) -> tuple[str, ...]:
    limitations = [
        "deterministic checks cover structure, citations, excerpt support, "
        "disclosure, status honesty, and case conditions only",
        "factual accuracy and completeness/relevance stay needs_review until a "
        "human review is recorded; no accuracy figure is computed without one",
        "cost is always unavailable: no reliable per-model pricing is configured",
    ]
    if mode == "offline_fixture":
        limitations.append(
            "providers are scripted fixtures; offline results say nothing about "
            "a real model's answer quality"
        )
    return tuple(limitations)


def write_artifacts(run: EvalRun, out_dir: Path) -> tuple[Path, Path]:
    """Write ``eval_results.json`` and ``eval_summary.md`` (US-804 criterion 1)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = run.write_json(out_dir / "eval_results.json")
    md_path = out_dir / "eval_summary.md"
    md_path.write_text(run.summary_markdown(), encoding="utf-8")
    return json_path, md_path


def _load_run(path: str, reviews_path: str | None) -> EvalRun:
    run = EvalRun.read_json(path)
    if reviews_path is None:
        return run
    reviews = load_reviews(reviews_path)
    results = apply_reviews(list(run.cases), reviews)
    return run.model_copy(
        update={
            "cases": tuple(results),
            "metrics": tuple(metric.as_dict() for metric in compute_metrics(results)),
        }
    )


def _has_quality_failure(case: CaseResult) -> bool:
    if case.checks is None:
        return False
    return any(check.get("status") == "fail" for check in case.checks.get("checks", []))


def _report(run: EvalRun, json_path: Path, md_path: Path) -> None:
    quality_failures = sum(1 for case in run.cases if _has_quality_failure(case))
    provider_failures = sum(1 for case in run.cases if case.provider_failure)
    reviewed = sum(1 for case in run.cases if case.review is not None)
    print(f"mode: {run.mode} | cases: {len(run.cases)}")
    print(f"results: {json_path}")
    print(f"summary: {md_path}")
    print(
        f"quality failures: {quality_failures} | provider failures: "
        f"{provider_failures} | cases with recorded review: {reviewed}"
    )
    for metric in run.metrics:
        value = "unavailable" if metric["value"] is None else f"{metric['value']:.2f}"
        print(
            f"  {metric['id']}: {value} "
            f"({metric['numerator']}/{metric['denominator']}, unknown={metric['unknown']})"
        )


def _default_out_dir(run_id: str) -> Path:
    return Path("evaluation_results") / run_id


def _cmd_run(args: argparse.Namespace) -> int:
    dataset_path = Path(args.dataset) if args.dataset else default_dataset_path()
    dataset = load_dataset(dataset_path)
    cases = select_cases(dataset, case_ids=args.case, smoke=args.smoke)

    if args.live:
        from dotenv import load_dotenv

        from agent007.evallive import require_live_opt_in, run_live_evaluation, search_provider_label

        load_dotenv()
        settings = Settings.from_env()  # real environment, live validation
        require_live_opt_in(settings, opt_in=True)  # refuses before any provider
        results = run_live_evaluation(cases, settings, opt_in=True)
        model_id = settings.model_name or "unknown"
        search_provider = search_provider_label(settings)
        mode: Literal["offline_fixture", "live"] = "live"
    else:
        # Offline: the environment is ignored on purpose — reproducible and
        # credential-free (US-802 criterion 2).
        settings = Settings.from_env({})
        results = run_offline_evaluation(cases, settings)
        model_id = OFFLINE_MODEL_ID
        search_provider = OFFLINE_SEARCH_ID
        mode = "offline_fixture"

    if args.reviews:
        results = apply_reviews(results, load_reviews(args.reviews))

    run = build_run(
        mode=mode,
        dataset=dataset,
        dataset_path=dataset_path,
        results=results,
        settings=settings,
        model_id=model_id,
        search_provider=search_provider,
    )
    out_dir = Path(args.out) if args.out else _default_out_dir(run.run_id)
    json_path, md_path = write_artifacts(run, out_dir)
    _report(run, json_path, md_path)

    if any(_has_quality_failure(case) for case in run.cases) or any(
        case.provider_failure for case in run.cases
    ):
        return 2
    return 0


def _cmd_summarize(args: argparse.Namespace) -> int:
    run = _load_run(args.results, args.reviews)
    out_dir = Path(args.out) if args.out else Path(args.results).parent
    json_path = run.write_json(out_dir / "eval_results.json")
    md_path = out_dir / "eval_summary.md"
    md_path.write_text(run.summary_markdown(), encoding="utf-8")
    _report(run, json_path, md_path)
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    dataset = load_dataset(args.dataset)
    print(f"dataset {dataset.dataset_version}: {len(dataset.cases)} cases")
    for case in dataset.cases:
        flags = "time-sensitive" if case.time_sensitive else "stable"
        print(f"  {case.id}  {case.category:<20} {case.difficulty:<6} {flags:<14} {case.question}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agent007.evalrun",
        description="Run and summarize the Atlas research-quality evaluation (Sprint 8).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="evaluate cases and write JSON + Markdown artifacts")
    run.add_argument("--dataset", default=None, help="path to cases.json")
    run.add_argument(
        "--case",
        action="append",
        default=None,
        metavar="ID",
        help="evaluate only this case ID (repeatable)",
    )
    run.add_argument("--smoke", action="store_true", help="three-case smoke subset")
    run.add_argument(
        "--live",
        action="store_true",
        help="opt-in live run against configured providers (makes paid API calls)",
    )
    run.add_argument("--reviews", default=None, help="reviews JSON to apply before metrics")
    run.add_argument("--out", default=None, help="artifact output directory")
    run.set_defaults(func=_cmd_run)

    summary = sub.add_parser("summarize", help="recompute metrics from saved results")
    summary.add_argument("--results", required=True, help="path to eval_results.json")
    summary.add_argument("--reviews", default=None, help="reviews JSON to apply")
    summary.add_argument("--out", default=None, help="artifact output directory")
    summary.set_defaults(func=_cmd_summarize)

    listing = sub.add_parser("list", help="list dataset cases")
    listing.add_argument("--dataset", default=None, help="path to cases.json")
    listing.set_defaults(func=_cmd_list)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except DatasetError as exc:
        print(f"dataset error: {exc}", file=sys.stderr)
        return 4
    except ConfigurationError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 5
    except AtlasError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 5


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess tests
    raise SystemExit(main())
