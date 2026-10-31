"""Opt-in live evaluation against the configured providers (US-805, Sprint 8).

Safety properties, all enforced in code:

* **explicit opt-in**: :func:`run_live_evaluation` refuses before it builds a
  single provider unless ``opt_in`` is set *and* the settings describe a
  configured live run;
* **existing bounds apply**: every case runs through ``run_research`` with the
  user's ``Settings``, so iterations, result count, and the wall-clock deadline
  are enforced exactly as in normal live mode;
* **no automatic retry**: each case gets exactly one attempt; a failed paid
  call is recorded as a provider failure, never retried;
* **no secrets in artifacts**: every recorded string passes through
  :func:`atlas.evalreport.redact_secrets` with the configured credentials;
* **honest outcomes**: a case that merely completed without raising is *not*
  marked ``pass`` — the judgement fields stay ``needs_review``.

This module is never imported by ordinary offline tests' execution paths; the
offline suite exercises it only through refusal tests with fake settings.
"""

from __future__ import annotations

from agent007.config import Settings
from agent007.errors import ConfigurationError
from agent007.evalreport import (
    CaseResult,
    provider_failure_result,
    result_from_outcome,
)
from agent007.evalset import EvalCase

#: Limitations attached to every live evaluation result (US-804/US-806).
LIVE_EVALUATION_LIMITATIONS: tuple[str, ...] = (
    "factual accuracy and completeness/relevance require a recorded human "
    "review; deterministic checks cover structure, citations, and disclosure only",
    "one attempt per case; provider failures are recorded, not retried",
)


def live_secrets(settings: Settings) -> tuple[str, ...]:
    """Configured credential values, used only for redaction."""
    return tuple(
        secret.get_secret_value()
        for secret in (
            settings.openai_api_key,
            settings.tavily_api_key,
            settings.exa_api_key,
        )
        if secret is not None and secret.get_secret_value()
    )


def require_live_opt_in(settings: Settings, *, opt_in: bool) -> None:
    """Refuse to start any live evaluation unless explicitly enabled (US-805).

    Checked *before* providers are constructed, so a refusal performs no work
    and contacts nothing.

    Raises:
        ConfigurationError: without ``--live`` opt-in, without live mode, or
            with incomplete provider configuration. Messages name variables,
            never values.
    """
    if not opt_in:
        raise ConfigurationError(
            "live evaluation requires explicit opt-in; pass --live to enable it"
        )
    if settings.mode != "live":
        raise ConfigurationError(
            "live evaluation requires ATLAS_MODE=live (offline fixtures are the default)"
        )
    missing: list[str] = []
    if not settings.model_name:
        missing.append("ATLAS_MODEL")
    if settings.openai_api_key is None:
        missing.append("OPENAI_API_KEY")
    if settings.tavily_api_key is None and settings.exa_api_key is None:
        missing.append("one of TAVILY_API_KEY or EXA_API_KEY")
    if missing:
        raise ConfigurationError("live evaluation requires " + ", ".join(missing) + " to be set")


def search_provider_label(settings: Settings) -> str:
    if settings.tavily_api_key is not None:
        return "tavily"
    if settings.exa_api_key is not None:
        return "exa"
    return "unconfigured"


def run_live_evaluation(
    cases: list[EvalCase],
    settings: Settings,
    *,
    opt_in: bool,
) -> list[CaseResult]:
    """Run cases against the real configured providers, one attempt each.

    Args:
        cases: Selected evaluation cases (a subset is expected — smoke first).
        settings: The user's live configuration; its bounds are applied as-is.
        opt_in: Must be ``True``; see :func:`require_live_opt_in`.

    Returns:
        One :class:`CaseResult` per case. Cases whose run raised are recorded
        as provider failures with ``completion_status=None`` — they are never
        silently dropped and never counted as passes.
    """
    require_live_opt_in(settings, opt_in=opt_in)
    assert settings.model_name is not None  # noqa: S101 - guarded above

    # Providers are built only after the opt-in gate has passed.
    from agent007.main import _build_search_provider
    from agent007.model import OpenAIModelAdapter
    from agent007.pipeline import run_research
    from agent007.tools.fetch import PageFetcher, UrlPolicy

    secrets = live_secrets(settings)
    model = OpenAIModelAdapter(settings, timeout=settings.timeout_seconds)
    search = _build_search_provider(settings)
    search_label = search_provider_label(settings)
    fetcher = PageFetcher(UrlPolicy(), timeout=settings.timeout_seconds)

    results: list[CaseResult] = []
    for case in cases:
        try:
            outcome = run_research(
                case.question,
                settings,
                model=model,
                search=search,
                fetcher=fetcher,
            )
        except Exception as exc:  # noqa: BLE001 - provider/eval boundary
            # One attempt, no retry (US-805). This is a *provider* failure,
            # recorded separately from research-quality results.
            results.append(
                provider_failure_result(
                    case,
                    mode="live",
                    model_id=settings.model_name or "unknown",
                    search_provider=search_label,
                    limitations=LIVE_EVALUATION_LIMITATIONS,
                    message=f"run raised {type(exc).__name__}: {exc}",
                    secrets=secrets,
                )
            )
            continue

        results.append(
            result_from_outcome(
                case,
                outcome,
                mode="live",
                model_id=settings.model_name,
                search_provider=search_label,
                max_iterations=settings.max_iterations,
                limitations=LIVE_EVALUATION_LIMITATIONS,
                secrets=secrets,
            )
        )
    return results
