"""Tests for the real HTTP transport (US-202, US-601).

The transport connects to a pinned address, so these tests stand up a local
server and construct :class:`Destination` objects directly — bypassing
:class:`UrlPolicy`, which correctly refuses loopback and is covered separately
in ``test_fetch_policy.py``. No external network is used and no credentials are
required.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent007.errors import FetchError
from agent007.tools.fetch import Destination, RequestsTransport

HOSTNAME = "unit-test.invalid"


class _Recorder:
    """Collects what the server actually received."""

    def __init__(self) -> None:
        self.hosts: list[str | None] = []
        self.paths: list[str] = []
        self.user_agents: list[str | None] = []
        self.authorization: list[str | None] = []


RECORDER = _Recorder()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: object) -> None:  # keep test output clean
        return

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        RECORDER.hosts.append(self.headers.get("Host"))
        RECORDER.paths.append(self.path)
        RECORDER.user_agents.append(self.headers.get("User-Agent"))
        RECORDER.authorization.append(self.headers.get("Authorization"))

        if self.path == "/missing":
            body = b"not found"
            self.send_response(404)
        elif self.path == "/huge":
            body = b"x" * 400_000
            self.send_response(200)
        elif self.path == "/binary":
            body = b"\x00\x01\x02\x03"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
        else:
            body = b"<html><head><title>Local</title></head><p>ok</p></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")

        self.send_header("Content-Length", str(len(body)))
        if self.path not in ("/missing", "/huge", "/binary"):
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)


class _QuietServer(ThreadingHTTPServer):
    """Suppresses handler tracebacks from client disconnects.

    The byte-cap test deliberately aborts mid-response, which makes the handler
    thread see a reset connection. Printing that would look like a test failure.
    """

    def handle_error(self, request: object, client_address: object) -> None:
        return


@pytest.fixture(scope="module")
def local_server() -> tuple[str, int]:
    server = _QuietServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield HOSTNAME, server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def destination_for(host: tuple[str, int], path: str = "/") -> Destination:
    """Bypass policy deliberately: this is a transport-level test on loopback."""
    hostname, port = host
    return Destination(scheme="http", hostname=hostname, port=port, ip="127.0.0.1", path=path)


@pytest.fixture(autouse=True)
def reset_recorder() -> None:
    RECORDER.__init__()


def test_transport_fetches_from_pinned_loopback_address(local_server: tuple[str, int]) -> None:
    transport = RequestsTransport()

    response = transport.get(destination_for(local_server), timeout=10.0, max_bytes=100_000)

    assert response.status_code == 200
    assert b"ok" in response.body
    assert response.headers["Content-Type"].startswith("text/html")


def test_transport_sends_original_hostname_as_host_header(local_server: tuple[str, int]) -> None:
    """The socket goes to the IP, but servers must still see the real hostname."""
    transport = RequestsTransport()

    transport.get(destination_for(local_server), timeout=10.0, max_bytes=100_000)

    assert RECORDER.hosts == [f"{HOSTNAME}:{local_server[1]}"]


def test_transport_does_not_send_authorization(local_server: tuple[str, int]) -> None:
    """No credentials may be forwarded to an origin."""
    transport = RequestsTransport()

    transport.get(destination_for(local_server), timeout=10.0, max_bytes=100_000)

    assert RECORDER.authorization == [None]


def test_transport_sets_identifying_user_agent(local_server: tuple[str, int]) -> None:
    transport = RequestsTransport()

    transport.get(destination_for(local_server), timeout=10.0, max_bytes=100_000)

    assert RECORDER.user_agents[0] is not None
    assert "007" in RECORDER.user_agents[0]


def test_transport_returns_status_codes_verbatim(local_server: tuple[str, int]) -> None:
    transport = RequestsTransport()

    response = transport.get(
        destination_for(local_server, "/missing"), timeout=10.0, max_bytes=100_000
    )

    assert response.status_code == 404


def test_transport_enforces_byte_cap_while_streaming(local_server: tuple[str, int]) -> None:
    """Oversized bodies are aborted mid-stream, not buffered first."""
    transport = RequestsTransport()

    with pytest.raises(FetchError) as excinfo:
        transport.get(destination_for(local_server, "/huge"), timeout=10.0, max_bytes=50_000)

    assert "50000" in str(excinfo.value)


def test_transport_accepts_response_within_cap(local_server: tuple[str, int]) -> None:
    transport = RequestsTransport()

    response = transport.get(
        destination_for(local_server, "/huge"), timeout=10.0, max_bytes=1_000_000
    )

    assert len(response.body) == 400_000


def test_transport_returns_binary_bodies_for_caller_to_reject(
    local_server: tuple[str, int],
) -> None:
    """Content-type rejection is the fetcher's job; the transport just reports."""
    transport = RequestsTransport()

    response = transport.get(
        destination_for(local_server, "/binary"), timeout=10.0, max_bytes=100_000
    )

    assert response.body.startswith(b"\x00\x01")
    assert "octet-stream" in response.headers["Content-Type"]


def test_transport_reports_unreachable_destination(local_server: tuple[str, int]) -> None:
    transport = RequestsTransport()
    closed = Destination(scheme="http", hostname=HOSTNAME, port=1, ip="127.0.0.1", path="/")

    with pytest.raises(FetchError):
        transport.get(closed, timeout=2.0, max_bytes=1000)
