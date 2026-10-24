"""Web search adapter (US-201, PRD FR-03).

Responsibilities:

* validate and bound the query and result count before any network call;
* map provider responses into :class:`~atlas.models.SearchResult`;
* normalise provider failures into :class:`~atlas.errors.SearchProviderError`
  without leaking the API key or raw response bodies.

The adapter depends on an injected client rather than constructing one itself,
so all tests run offline with no credentials.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from atlas.errors import SearchProviderError, ToolValidationError
from atlas.models import MAX_QUERY_LENGTH, MAX_SNIPPET_CHARS, SearchResult

#: Absolute ceiling on results returned by any single call, regardless of input.
MAX_RESULTS_PER_CALL = 20

#: Provider exception class names mapped to a safe human-readable category.
#:
#: Names were read from the installed ``tavily.errors`` module (tavily-python
#: 0.8.5), whose members are: TimeoutError, UsageLimitExceededError,
#: TavilyKeylessLimitError, InvalidAPIKeyError, MissingAPIKeyError,
#: ForbiddenError, BadRequestError, KeylessUnsupportedEndpointError. Matching by
#: name keeps this module importable and testable when the SDK is absent.
_ERROR_CATEGORIES: dict[str, str] = {
    "TimeoutError": "search timed out",
    "UsageLimitExceededError": "provider usage limit exceeded",
    "TavilyKeylessLimitError": "provider usage limit exceeded",
    "KeylessUnsupportedEndpointError": "provider endpoint unavailable without credentials",
    "InvalidAPIKeyError": "provider rejected the configured credentials",
    "MissingAPIKeyError": "provider credentials are not configured",
    "ForbiddenError": "provider denied the request",
    "BadRequestError": "provider rejected the query as malformed",
}


class SearchClient(Protocol):
    """Structural type for the provider SDK client."""

    def search(self, **kwargs: Any) -> Mapping[str, Any]: ...


def _is_http_url(value: str) -> bool:
    lowered = value.lower().strip()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _safe_text(exc: BaseException, secrets: Sequence[str] = ()) -> str:
    """Render an exception without exposing configured secrets."""
    text = f"{type(exc).__name__}: {exc}"
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


class SearchProvider(Protocol):
    """Structural type for a bounded, normalized search source."""

    def search(self, query: str, max_results: int) -> list[SearchResult]: ...


class TavilySearchProvider:
    """Adapter over the Tavily SDK search endpoint.

    Args:
        client: Provider client. Injected so tests never construct a real one.
        api_key: Provider credential, used only for redaction in error text.
        default_max_results: Default result bound, validated on every call.
    """

    def __init__(
        self,
        client: SearchClient,
        *,
        api_key: str | None = None,
        default_max_results: int = 5,
    ) -> None:
        if not 1 <= default_max_results <= MAX_RESULTS_PER_CALL:
            raise ToolValidationError(
                f"default_max_results must be between 1 and {MAX_RESULTS_PER_CALL}"
            )
        self._client = client
        self._api_key = api_key or ""
        self._default_max_results = default_max_results

    def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        """Run one bounded search and return normalized results.

        Raises:
            ToolValidationError: for an empty, whitespace-only, or over-long
                query, or an out-of-range result count. Raised before any
                network call.
            SearchProviderError: for provider timeouts, credential problems,
                rate limits, malformed responses, or unexpected failures.
        """
        cleaned = self._validate_query(query)
        limit = self._validate_max_results(
            self._default_max_results if max_results is None else max_results
        )

        try:
            raw = self._client.search(query=cleaned, max_results=limit, timeout=60)
        except Exception as exc:  # noqa: BLE001 - boundary normalisation
            raise SearchProviderError(self._describe_error(exc)) from exc

        return self._normalize(raw, limit)

    def _validate_query(self, query: str) -> str:
        if not isinstance(query, str):
            raise ToolValidationError("query must be a string")
        cleaned = query.strip()
        if not cleaned:
            raise ToolValidationError("query must not be empty or whitespace-only")
        if len(cleaned) > MAX_QUERY_LENGTH:
            raise ToolValidationError(
                f"query must be at most {MAX_QUERY_LENGTH} characters, got {len(cleaned)}"
            )
        return cleaned

    def _validate_max_results(self, max_results: object) -> int:
        if isinstance(max_results, bool) or not isinstance(max_results, int):
            raise ToolValidationError("max_results must be an integer")
        if not 1 <= max_results <= MAX_RESULTS_PER_CALL:
            raise ToolValidationError(f"max_results must be between 1 and {MAX_RESULTS_PER_CALL}")
        return max_results

    def _describe_error(self, exc: BaseException) -> str:
        category = _ERROR_CATEGORIES.get(type(exc).__name__)
        detail = _safe_text(exc, (self._api_key,))
        return f"{category}: {detail}" if category else f"search failed: {detail}"

    def _normalize(self, raw: Any, limit: int) -> list[SearchResult]:
        if not isinstance(raw, Mapping):
            raise SearchProviderError(
                f"search provider returned a malformed response "
                f"(expected object, got {type(raw).__name__})"
            )
        results = raw.get("results")
        if results is None:
            raise SearchProviderError("search provider response is missing 'results'")
        if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
            raise SearchProviderError(f"'results' must be a list, got {type(results).__name__}")

        # Filter unusable entries *before* applying the bound, so malformed items
        # do not consume the result budget meant for usable ones.
        normalized: list[SearchResult] = []
        for item in results:
            candidate = self._normalize_item(item)
            if candidate is None:
                continue
            normalized.append(candidate)
            if len(normalized) >= limit:
                break
        return normalized

    @staticmethod
    def _normalize_item(item: Any) -> SearchResult | None:
        """Normalize one result; return None to drop unusable entries."""
        if not isinstance(item, Mapping):
            return None
        url = item.get("url")
        if not isinstance(url, str) or not _is_http_url(url):
            return None

        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            title = url

        snippet = item.get("snippet")
        if isinstance(snippet, str) and snippet.strip():
            snippet = snippet.strip()[:MAX_SNIPPET_CHARS]
        else:
            snippet = None

        published = item.get("published_date")
        if not isinstance(published, str) or not published.strip():
            published = None

        score = item.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            score = None

        return SearchResult(
            title=title.strip(),
            url=url,
            snippet=snippet,
            published_date=published,
            score=float(score) if score is not None else None,
        )


def build_tavily_provider(
    api_key: str,
    *,
    default_max_results: int = 5,
    client_factory: Callable[[str], SearchClient] | None = None,
) -> TavilySearchProvider:
    """Construct a Tavily provider, importing the SDK only when actually needed.

    Keeping the import here lets the rest of the package (and every test) work
    without the provider SDK installed.
    """
    if client_factory is None:
        try:
            from tavily import TavilyClient
        except ImportError as exc:
            raise SearchProviderError(
                "tavily-python is not installed; install it to enable live search"
            ) from exc
        client_factory = TavilyClient

    return TavilySearchProvider(
        client_factory(api_key),
        api_key=api_key,
        default_max_results=default_max_results,
    )
