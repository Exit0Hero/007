"""Registered research tools.

Only functions reachable through the explicit allowlist defined here can ever
be dispatched. Model-supplied tool names are matched against this module's
registry by name; there is no dynamic import, ``eval``, or arbitrary dispatch
(ADR-004, SECURITY.md section "Arbitrary tool execution").
"""

from __future__ import annotations

from agent007.tools.fetch import (
    Destination,
    FetchedPage,
    PageFetcher,
    Transport,
    UrlPolicy,
    extract_readable,
)
from agent007.tools.search import (
    ExaSearchProvider,
    SearchProvider,
    TavilySearchProvider,
    build_exa_provider,
)

__all__ = [
    "Destination",
    "ExaSearchProvider",
    "FetchedPage",
    "PageFetcher",
    "SearchProvider",
    "TavilySearchProvider",
    "Transport",
    "UrlPolicy",
    "build_exa_provider",
    "extract_readable",
]
