"""Registered research tools.

Only functions reachable through the explicit allowlist defined here can ever
be dispatched. Model-supplied tool names are matched against this module's
registry by name; there is no dynamic import, ``eval``, or arbitrary dispatch
(ADR-004, SECURITY.md section "Arbitrary tool execution").
"""

from __future__ import annotations

from atlas.tools.fetch import (
    Destination,
    FetchedPage,
    PageFetcher,
    Transport,
    UrlPolicy,
    extract_readable,
)
from atlas.tools.search import SearchProvider, TavilySearchProvider

__all__ = [
    "Destination",
    "FetchedPage",
    "PageFetcher",
    "SearchProvider",
    "TavilySearchProvider",
    "Transport",
    "UrlPolicy",
    "extract_readable",
]
