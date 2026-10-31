"""Run-local source registry with stable IDs and a deduplication policy (US-203).

Every source retrieved during a run is registered once and receives an ID that
never changes for the lifetime of the run. Citations in the report must resolve
against this registry (ADR-006), so the registry is the only authority for what
counts as a real source.

Deduplication policy
--------------------
Two references to the same page share one ID when their *canonical* URLs match.
Canonicalisation lowercases scheme and host, drops the fragment, drops a
trailing slash on the path, and removes the default port. Query strings are
kept, because ``?id=1`` and ``?id=2`` are genuinely different pages.

The first registration wins for identity; later registrations may only *fill in*
metadata that was previously absent. A search snippet and fetched page text are
stored in separate fields so that snippet-level evidence is never mistaken for
full page content.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict

from agent007.errors import ToolValidationError

#: Maximum characters retained from a search snippet stored on a source.
MAX_STORED_SNIPPET_CHARS = 1000

#: Maximum characters retained from fetched page text stored on a source.
MAX_STORED_PAGE_CHARS = 20000


class SourceRecord(BaseModel):
    """Immutable view of one registered source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    url: str
    title: str | None = None
    published_date: str | None = None
    search_snippet: str | None = None
    page_text: str | None = None
    registration_method: str = "search"

    @property
    def evidence_kinds(self) -> tuple[str, ...]:
        """Which evidence tiers exist for this source, in increasing depth."""
        kinds: list[str] = []
        if self.search_snippet:
            kinds.append("search_snippet")
        if self.page_text:
            kinds.append("page_text")
        return tuple(kinds)


def canonical_url(url: str) -> str:
    """Reduce a URL to its deduplication key.

    Raises:
        ToolValidationError: if the URL is not absolute HTTP(S).
    """
    if not isinstance(url, str) or not url.strip():
        raise ToolValidationError("source URL must be a non-empty string")

    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ("http", "https"):
        raise ToolValidationError(f"unsupported URL scheme: {parts.scheme or '(none)'}")
    if not parts.netloc:
        raise ToolValidationError("source URL must be absolute")

    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]

    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    return urlunsplit((scheme, netloc, path, parts.query, ""))


class SourceRegistry:
    """Assigns stable, run-scoped IDs and merges duplicate references."""

    def __init__(self) -> None:
        self._records: dict[str, SourceRecord] = {}
        self._by_canonical: dict[str, str] = {}
        self._next_id = 1

    def __len__(self) -> int:
        return len(self._records)

    def ids(self) -> list[str]:
        """Registered IDs in registration order."""
        return list(self._records)

    def records(self) -> list[SourceRecord]:
        """Registered records in registration order."""
        return list(self._records.values())

    def get(self, source_id: str) -> SourceRecord | None:
        return self._records.get(source_id)

    def id_for(self, url: str) -> str | None:
        """Return the ID already assigned to this URL, if any."""
        return self._by_canonical.get(canonical_url(url))

    def register(
        self,
        url: str,
        *,
        title: str | None = None,
        published_date: str | None = None,
        search_snippet: str | None = None,
        page_text: str | None = None,
        registration_method: str = "search",
    ) -> str:
        """Register a source and return its stable ID.

        Registering the same canonical URL twice returns the original ID and
        only fills in metadata that was missing.
        """
        key = canonical_url(url)

        if key in self._by_canonical:
            source_id = self._by_canonical[key]
            existing = self._records[source_id]
            self._records[source_id] = existing.model_copy(
                update={
                    "title": existing.title or title,
                    "published_date": existing.published_date or published_date,
                    "search_snippet": existing.search_snippet or _bound_snippet(search_snippet),
                    "page_text": existing.page_text or _bound_page_text(page_text),
                }
            )
            return source_id

        source_id = f"S{self._next_id}"
        self._next_id += 1
        self._records[source_id] = SourceRecord(
            id=source_id,
            url=url.strip(),
            title=title.strip() if isinstance(title, str) and title.strip() else None,
            published_date=(
                published_date.strip()
                if isinstance(published_date, str) and published_date.strip()
                else None
            ),
            search_snippet=_bound_snippet(search_snippet),
            page_text=_bound_page_text(page_text),
            registration_method=registration_method,
        )
        self._by_canonical[key] = source_id
        return source_id

    def resolve(self, cited_ids: list[str]) -> tuple[list[SourceRecord], list[str]]:
        """Split cited IDs into found records and unknown IDs.

        This is the mechanical citation check required by PRD FR-10: an ID that
        is not in the registry is reported, never invented.
        """
        if not isinstance(cited_ids, list):
            raise ToolValidationError("cited source IDs must be a list of strings")

        found: list[SourceRecord] = []
        unknown: list[str] = []
        seen: set[str] = set()
        for cited in cited_ids:
            if not isinstance(cited, str):
                raise ToolValidationError("cited source IDs must be strings")
            if cited in seen:
                continue
            seen.add(cited)
            record = self._records.get(cited)
            if record is None:
                unknown.append(cited)
            else:
                found.append(record)
        return found, unknown


def _bound_snippet(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped[:MAX_STORED_SNIPPET_CHARS]


def _bound_page_text(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped[:MAX_STORED_PAGE_CHARS]
