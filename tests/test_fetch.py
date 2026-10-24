"""Tests for bounded page fetching: redirects, limits, and content handling (US-202).

A fake transport is injected, so these tests perform no network I/O and need no
credentials (US-503). The policy is a real :class:`UrlPolicy` with a faked
resolver, so redirect destinations go through genuine validation.
"""

from __future__ import annotations

import pytest

from atlas.errors import FetchError, ToolValidationError
from atlas.tools.fetch import (
    ALLOWED_CONTENT_TYPES,
    MAX_REDIRECTS,
    Destination,
    PageFetcher,
    TransportResponse,
    UrlPolicy,
)

PUBLIC_IP = "93.184.216.34"
PUBLIC_IP_2 = "151.101.1.140"

HTML_PAGE = b"""<!doctype html>
<html><head><title>Atlas docs</title></head>
<body><h1>Heading</h1><p>Some readable body text.</p></body></html>"""


class SpyPolicy(UrlPolicy):
    """Records every URL passed through validation."""

    def __init__(self, table: dict[str, list[str]] | None = None) -> None:
        def resolver(hostname: str, port: int) -> list[str]:
            if table is None or hostname not in table:
                raise FetchError(f"could not resolve host {hostname!r}")
            return table[hostname]

        super().__init__(resolver)
        self.seen: list[str] = []

    def validate(self, url: object) -> Destination:  # type: ignore[override]
        self.seen.append(str(url))
        return super().validate(url)


class FakeTransport:
    """Returns queued responses and records the destinations it was asked to fetch."""

    def __init__(self, *responses: TransportResponse | Exception) -> None:
        self.queue: list[TransportResponse | Exception] = list(responses)
        self.destinations: list[Destination] = []

    def get(self, destination: Destination, *, timeout: float, max_bytes: int) -> TransportResponse:
        self.destinations.append(destination)
        if not self.queue:
            raise AssertionError("transport called more times than responses queued")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def response(
    status: int = 200,
    *,
    content_type: str = "text/html; charset=utf-8",
    body: bytes = HTML_PAGE,
    headers: dict[str, str] | None = None,
) -> TransportResponse:
    merged = {"Content-Type": content_type}
    if headers:
        merged.update(headers)
    return TransportResponse(status_code=status, headers=merged, body=body)


def make_fetcher(
    *responses: TransportResponse | Exception,
    table: dict[str, list[str]] | None = None,
    **kwargs: object,
) -> tuple[PageFetcher, FakeTransport, SpyPolicy]:
    policy = SpyPolicy(table or {"example.com": [PUBLIC_IP], "other.test": [PUBLIC_IP_2]})
    transport = FakeTransport(*responses)
    fetcher = PageFetcher(policy, transport, **kwargs)  # type: ignore[arg-type]
    return fetcher, transport, policy


# --- happy path --------------------------------------------------------------


def test_successful_fetch_returns_readable_page() -> None:
    fetcher, _, _ = make_fetcher(response())

    page = fetcher.fetch("https://example.com/docs")

    assert page.status_code == 200
    assert page.title == "Atlas docs"
    assert "Some readable body text." in page.text
    assert page.url == "https://example.com/docs"
    assert page.content_type == "text/html"


def test_fetch_pins_the_destination_to_the_validated_ip() -> None:
    fetcher, transport, _ = make_fetcher(response())

    fetcher.fetch("https://example.com/docs")

    destination = transport.destinations[0]
    assert destination.ip == PUBLIC_IP
    assert destination.pinned_url.startswith(f"https://{PUBLIC_IP}/")
    assert "example.com" not in destination.pinned_url


def test_redirect_chain_is_recorded() -> None:
    fetcher, _, _ = make_fetcher(
        response(301, body=b"", headers={"Location": "https://other.test/final"}),
        response(body=b"<html><title>F</title><p>Final page text.</p></html>"),
    )

    page = fetcher.fetch("https://example.com/start")

    assert page.redirect_chain == ("https://other.test/final",)
    assert page.title == "F"


# --- redirect revalidation (the core redirect-SSRF control) -------------------


def test_each_redirect_target_is_validated_again() -> None:
    fetcher, transport, policy = make_fetcher(
        response(302, body=b"", headers={"Location": "https://other.test/next"}),
        response(),
    )

    fetcher.fetch("https://example.com/start")

    assert policy.seen == [
        "https://example.com/start",
        "https://other.test/next",
    ]
    assert len(transport.destinations) == 2
    assert transport.destinations[1].ip == PUBLIC_IP_2


def test_relative_redirect_is_resolved_and_validated() -> None:
    fetcher, transport, policy = make_fetcher(
        response(301, body=b"", headers={"Location": "/relative/path"}),
        response(),
    )

    fetcher.fetch("https://example.com/start")

    assert policy.seen[1] == "https://example.com/relative/path"
    assert transport.destinations[1].path == "/relative/path"


def test_redirect_to_private_address_is_blocked() -> None:
    """A public server redirecting to an internal host must not be followed."""
    fetcher, _, _ = make_fetcher(
        response(302, body=b"", headers={"Location": "http://169.254.169.254/latest/"}),
        table={"example.com": [PUBLIC_IP]},
    )

    with pytest.raises(FetchError):
        fetcher.fetch("https://example.com/start")


def test_redirect_to_localhost_hostname_is_blocked() -> None:
    fetcher, _, _ = make_fetcher(
        response(302, body=b"", headers={"Location": "http://localhost/admin"}),
        table={"example.com": [PUBLIC_IP]},
    )

    with pytest.raises(FetchError):
        fetcher.fetch("https://example.com/start")


def test_redirect_to_hostname_resolving_private_is_blocked() -> None:
    fetcher, _, _ = make_fetcher(
        response(302, body=b"", headers={"Location": "http://internal.corp/"}),
        table={"example.com": [PUBLIC_IP], "internal.corp": ["10.0.0.7"]},
    )

    with pytest.raises(FetchError):
        fetcher.fetch("https://example.com/start")


def test_redirect_without_location_header_is_an_error() -> None:
    fetcher, _, _ = make_fetcher(response(302, body=b""))

    with pytest.raises(FetchError) as excinfo:
        fetcher.fetch("https://example.com/start")

    assert "Location" in str(excinfo.value)


def test_redirect_limit_is_enforced() -> None:
    hops = [
        response(302, body=b"", headers={"Location": f"https://example.com/{i}"})
        for i in range(MAX_REDIRECTS + 5)
    ]
    fetcher, transport, _ = make_fetcher(*hops)

    with pytest.raises(FetchError) as excinfo:
        fetcher.fetch("https://example.com/start")

    assert "too many redirects" in str(excinfo.value)
    assert len(transport.destinations) == MAX_REDIRECTS + 1


def test_custom_redirect_limit_is_respected() -> None:
    fetcher, transport, _ = make_fetcher(
        response(302, body=b"", headers={"Location": "https://example.com/one"}),
        response(302, body=b"", headers={"Location": "https://example.com/two"}),
        response(),
        max_redirects=1,
    )

    with pytest.raises(FetchError):
        fetcher.fetch("https://example.com/start")

    assert len(transport.destinations) == 2


# --- status, content type, size ---------------------------------------------


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 429, 500, 503])
def test_error_status_codes_are_reported(status: int) -> None:
    fetcher, _, _ = make_fetcher(response(status))

    with pytest.raises(FetchError) as excinfo:
        fetcher.fetch("https://example.com/x")

    assert str(status) in str(excinfo.value)


@pytest.mark.parametrize(
    "content_type",
    ["image/png", "image/jpeg", "video/mp4", "audio/mpeg", "application/pdf", "application/zip"],
)
def test_binary_content_types_are_rejected(content_type: str) -> None:
    fetcher, _, _ = make_fetcher(response(content_type=content_type, body=b"\x89PNG"))

    with pytest.raises(FetchError) as excinfo:
        fetcher.fetch("https://example.com/x")

    assert "content type" in str(excinfo.value).lower()


def test_allowed_content_types_are_accepted() -> None:
    for content_type in ALLOWED_CONTENT_TYPES:
        fetcher, _, _ = make_fetcher(response(content_type=content_type))
        page = fetcher.fetch("https://example.com/x")
        assert page.content_type == content_type.split(";")[0]


def test_oversized_response_is_rejected() -> None:
    big = b"a" * 5000
    fetcher, _, _ = make_fetcher(response(body=big), max_bytes=4096)

    with pytest.raises(FetchError) as excinfo:
        fetcher.fetch("https://example.com/x")

    assert "4096" in str(excinfo.value)


def test_empty_page_is_reported_not_returned_as_success() -> None:
    fetcher, _, _ = make_fetcher(response(body=b"   \n  "))

    with pytest.raises(FetchError) as excinfo:
        fetcher.fetch("https://example.com/x")

    assert "no readable text" in str(excinfo.value)


def test_page_containing_only_script_tags_is_not_usable_evidence() -> None:
    """A page whose only content is a script yields no evidence, not 'content'."""
    fetcher, _, _ = make_fetcher(
        response(body=b"<html><body><script>var x = 1;</script></body></html>")
    )

    with pytest.raises(FetchError):
        fetcher.fetch("https://example.com/x")


# --- transport failure normalization ----------------------------------------


def test_timeout_from_transport_becomes_fetch_error() -> None:
    fetcher, _, _ = make_fetcher(TimeoutError("read timed out"))

    with pytest.raises(FetchError) as excinfo:
        fetcher.fetch("https://example.com/x")

    assert "timed out" in str(excinfo.value)


def test_unexpected_transport_failure_is_normalized() -> None:
    fetcher, _, _ = make_fetcher(ConnectionResetError("peer reset"))

    with pytest.raises(FetchError) as excinfo:
        fetcher.fetch("https://example.com/x")

    assert "ConnectionResetError" in str(excinfo.value)


def test_transport_failures_are_chained_for_diagnostics() -> None:
    original = ConnectionResetError("peer reset")
    fetcher, _, _ = make_fetcher(original)

    with pytest.raises(FetchError) as excinfo:
        fetcher.fetch("https://example.com/x")

    assert excinfo.value.__cause__ is original


# --- constructor validation --------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "name"),
    [
        ({"timeout": 0}, "timeout"),
        ({"timeout": -5}, "timeout"),
        ({"max_bytes": 0}, "max_bytes"),
        ({"max_redirects": -1}, "max_redirects"),
    ],
)
def test_invalid_fetcher_bounds_are_rejected(kwargs: dict[str, object], name: str) -> None:
    policy = SpyPolicy({"example.com": [PUBLIC_IP]})

    with pytest.raises(ToolValidationError) as excinfo:
        PageFetcher(policy, FakeTransport(), **kwargs)  # type: ignore[arg-type]

    assert name in str(excinfo.value)


def test_non_string_url_is_rejected_before_transport_is_called() -> None:
    fetcher, transport, _ = make_fetcher(response())

    with pytest.raises(ToolValidationError):
        fetcher.fetch(42)  # type: ignore[arg-type]

    assert transport.destinations == []


def test_no_response_is_returned_after_redirect_budget_is_exhausted() -> None:
    fetcher, transport, _ = make_fetcher(
        response(302, body=b"", headers={"Location": "https://example.com/a"}),
        response(302, body=b"", headers={"Location": "https://example.com/b"}),
        response(),
        max_redirects=0,
    )

    with pytest.raises(FetchError):
        fetcher.fetch("https://example.com/start")

    assert len(transport.destinations) == 1


def test_assertion_errors_from_the_transport_are_not_masked() -> None:
    """A broken transport/test double must fail loudly, not become FetchError."""
    fetcher, _, _ = make_fetcher(AssertionError("transport called too many times"))

    with pytest.raises(AssertionError):
        fetcher.fetch("https://example.com/x")
