"""Expected failure categories for Atlas.

Only errors that callers are expected to handle are defined here. Unexpected
failures propagate as ordinary exceptions so they are never silently swallowed.
"""

from __future__ import annotations


class AtlasError(Exception):
    """Base class for expected, categorised Atlas failures."""


class InvalidRequestError(AtlasError):
    """The user-supplied research request failed validation."""


class ConfigurationError(AtlasError):
    """Configuration is missing, malformed, or inconsistent.

    Messages must name the offending variable but must never contain a secret
    value.
    """


class ToolValidationError(AtlasError):
    """A tool name or its arguments failed application-side validation.

    Application code is the security boundary: model-supplied arguments are
    never trusted, so this is raised before any tool function executes.
    """


class SearchProviderError(AtlasError):
    """The search provider failed, timed out, or returned an unusable response.

    Messages must never contain the provider API key or raw response bodies.
    """


class FetchError(AtlasError):
    """Page retrieval failed or the destination was not permitted."""


class ModelProviderError(AtlasError):
    """The model provider failed, timed out, or returned an unusable response.

    Messages must never contain the provider API key or raw request payloads.
    """


class CitationValidationError(AtlasError):
    """A citation did not resolve to a registered source."""
