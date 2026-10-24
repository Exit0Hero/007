"""Secure page retrieval (US-202, US-601, US-602; PRD FR-04).

Threat model addressed here (see ``docs/SECURITY.md``):

* **SSRF** — only ``http``/``https``; every destination is resolved first and *all*
  resolved addresses must be globally routable; the connection is pinned to the
  validated address so a later DNS answer (DNS rebinding) cannot redirect it.
* **Redirects** — followed manually, one hop at a time, each revalidated from
  scratch by the same policy.
* **Resource exhaustion** — connect/read timeouts, a response byte cap enforced
  while streaming, a redirect cap, and a URL length cap.
* **Untrusted content** — HTML is parsed with :mod:`html.parser` only. No script,
  stylesheet, or embedded code is ever executed, and no content from a page is
  ever used to dispatch an operation.

Nothing in this module interprets page content as instructions; extracted text is
returned as data.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import urljoin, urlsplit

from atlas.errors import FetchError, ToolValidationError

try:
    from requests.adapters import HTTPAdapter
except ImportError:  # pragma: no cover - requests ships with the Tavily SDK
    HTTPAdapter = object  # type: ignore[assignment,misc]

#: Schemes permitted for retrieval.
ALLOWED_SCHEMES = ("http", "https")

#: Ports permitted for retrieval. Narrow on purpose (SECURITY.md "safe defaults").
ALLOWED_PORTS = (80, 443)

#: Content types accepted as readable text.
ALLOWED_CONTENT_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "text/xml",
    "application/xml",
)

#: Maximum characters accepted for a URL.
MAX_URL_LENGTH = 2048

#: Maximum bytes read from any single response body.
MAX_PAGE_BYTES = 2_000_000

#: Maximum redirects followed within one fetch.
MAX_REDIRECTS = 5

#: Maximum characters of extracted text retained.
MAX_TEXT_CHARS = 100_000

#: Read timeout / connect timeout in seconds.
DEFAULT_TIMEOUT_SECONDS = 30.0

#: Identifies the client to servers. Contains no credentials or internal detail.
USER_AGENT = "atlas-research-agent/0.1 (+local research CLI)"

#: Hostnames always refused, before any DNS lookup.
_ALWAYS_FORBIDDEN_HOSTS = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})

#: RFC 1123-ish hostname: alphanumeric labels separated by dots, optional trailing dot.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\.?$"
)

#: Content types that are never read as text.
_NON_TEXT_CONTENT_TYPES = ("image/", "audio/", "video/", "application/pdf", "application/zip")


@dataclass(frozen=True)
class Destination:
    """A URL that passed policy validation and is pinned to one address."""

    scheme: str
    hostname: str
    port: int
    ip: str
    path: str

    @property
    def tls_hostname(self) -> str:
        """Hostname used for SNI and certificate verification."""
        return self.hostname

    @property
    def host_header(self) -> str:
        """Value for the HTTP ``Host`` header when connecting to the pinned IP."""
        default = 80 if self.scheme == "http" else 443
        return self.hostname if self.port == default else f"{self.hostname}:{self.port}"

    @property
    def pinned_url(self) -> str:
        """URL whose host is the validated IP, so no second lookup occurs."""
        default = 80 if self.scheme == "http" else 443
        host = f"[{self.ip}]" if ":" in self.ip else self.ip
        authority = host if self.port == default else f"{host}:{self.port}"
        return f"{self.scheme}://{authority}{self.path}"


def default_resolver(hostname: str, port: int) -> list[str]:
    """Resolve a hostname to every address it currently maps to."""
    import socket

    try:
        answers = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError(f"could not resolve host {hostname!r}") from exc
    seen: list[str] = []
    for answer in answers:
        address = answer[4][0]
        if address not in seen:
            seen.append(address)
    return seen


def validate_address(address: str) -> str:
    """Return the address if it is safe to connect to, else raise FetchError.

    Uses :mod:`ipaddress` arithmetic rather than string matching, so encodings
    such as ``2130706433``, ``0x7f000001``, ``0177.0.0.1``, ``::ffff:127.0.0.1``
    and ``fe80::1%eth0`` cannot slip through.
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError as exc:
        raise FetchError("destination resolved to an unparseable address") from exc

    # IPv4-mapped IPv6 addresses smuggle an IPv4 address into an IPv6 one.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped

    # Explicit checks, not just is_global: on some Python versions multicast
    # ranges are not covered by is_global alone (e.g. 224.0.0.1, ff02::1).
    blocked = (
        ip.is_unspecified
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_multicast
        or ip.is_reserved
        or not ip.is_global
    )
    if blocked:
        raise FetchError(
            f"destination address is not publicly routable (type: {_address_kind(ip)})"
        )
    return str(ip)


def _address_kind(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link-local"
    if ip.is_private:
        return "private"
    if ip.is_multicast:
        return "multicast"
    if ip.is_reserved:
        return "reserved"
    if ip.is_unspecified:
        return "unspecified"
    return "non-global"


class UrlPolicy:
    """Validates a URL into a pinned :class:`Destination`.

    Args:
        resolver: Maps ``(hostname, port)`` to every address it resolves to.
            Injected so tests are deterministic and offline.
        allowed_ports: Ports the policy accepts.
    """

    def __init__(
        self,
        resolver: Callable[[str, int], list[str]] = default_resolver,
        *,
        allowed_ports: Sequence[int] = ALLOWED_PORTS,
    ) -> None:
        self._resolver = resolver
        self._allowed_ports = tuple(allowed_ports)

    def validate(self, url: object) -> Destination:
        """Validate ``url`` and pin it to a safe address.

        Raises:
            ToolValidationError: if ``url`` is not a string or is too long.
            FetchError: for any disallowed or unsafe destination.
        """
        if not isinstance(url, str):
            raise ToolValidationError("url must be a string")
        if not url.strip():
            raise FetchError("url must not be empty")
        if len(url) > MAX_URL_LENGTH:
            raise FetchError(f"url exceeds {MAX_URL_LENGTH} characters")

        try:
            parts = urlsplit(url.strip())
        except ValueError as exc:
            raise FetchError("url could not be parsed") from exc

        scheme = parts.scheme.lower()
        if scheme not in ALLOWED_SCHEMES:
            raise FetchError(f"scheme {scheme or '(none)'!r} is not permitted")

        if parts.username is not None or parts.password is not None:
            raise FetchError("urls containing credentials are not permitted")

        try:
            hostname = parts.hostname
            port = parts.port
        except ValueError as exc:
            raise FetchError("url has an invalid port") from exc

        if not hostname:
            raise FetchError("url has no host")
        if port is None:
            port = 443 if scheme == "https" else 80
        if port not in self._allowed_ports:
            raise FetchError(f"port {port} is not permitted")

        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        destination_path = _sanitize_path(path)

        return Destination(
            scheme=scheme,
            hostname=hostname,
            port=port,
            ip=self._resolve_safe_address(hostname, port),
            path=destination_path,
        )

    def _resolve_safe_address(self, hostname: str, port: int) -> str:
        lowered = hostname.lower().rstrip(".")
        if lowered in _ALWAYS_FORBIDDEN_HOSTS or lowered.endswith(".localhost"):
            raise FetchError(f"host {hostname!r} is not permitted")

        literal = _try_ip_literal(hostname)
        if literal is not None:
            return validate_address(literal)

        if not _HOSTNAME_RE.match(lowered):
            raise FetchError(f"host {hostname!r} is not a valid hostname")

        answers = self._resolver(lowered, port)
        if not answers:
            raise FetchError(f"host {hostname!r} resolved to no addresses")

        # Validate every answer. Mixed public/private means the destination is
        # unsafe or has been rebound, so the whole result is rejected.
        validated: list[str] = []
        for answer in answers:
            validated.append(validate_address(answer))
        return validated[0]


def _try_ip_literal(host: str) -> str | None:
    """Return the host as an IP literal (including obfuscated forms) if it is one."""
    candidate = host.strip("[]")
    try:
        # inet_aton-style forms (2130706433, 0x7f000001, 0177.0.0.1) are
        # accepted by socket but not by ipaddress; normalise them first.
        import socket

        packed = socket.inet_aton(candidate)
        return str(ipaddress.ip_address(packed))
    except (OSError, ValueError):
        pass
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _sanitize_path(path: str) -> str:
    """Remove any path component that could be read as a scheme or authority."""
    if "//" in path:
        return "/" + path.lstrip("/").replace("//", "/")
    return path if path.startswith("/") else "/" + path


@dataclass
class TransportResponse:
    """Raw response handed back by a transport."""

    status_code: int
    headers: Mapping[str, str]
    body: bytes


class Transport(Protocol):  # type: ignore[protocol-ric]
    """Structural type for the HTTP transport used by :class:`PageFetcher`."""

    def get(
        self, destination: Destination, *, timeout: float, max_bytes: int
    ) -> TransportResponse: ...


@dataclass
class FetchedPage:
    """A retrieved page reduced to bounded, readable data."""

    url: str
    status_code: int
    content_type: str
    title: str | None
    text: str
    redirect_chain: tuple[str, ...] = field(default_factory=tuple)


class _TextExtractor(HTMLParser):
    """Collects visible text and the page title.

    Script/style/etc. content is skipped wholesale: the parser never executes
    anything, and their text is discarded rather than surfaced as evidence.
    """

    _SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "canvas"})
    _BLOCK_TAGS = frozenset(
        {
            "p",
            "div",
            "br",
            "li",
            "ul",
            "ol",
            "tr",
            "td",
            "th",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "section",
            "article",
            "header",
            "footer",
            "blockquote",
            "pre",
            "hr",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []

    @property
    def title(self) -> str | None:
        joined = "".join(self._title_parts).strip()
        return joined or None

    @property
    def text(self) -> str:
        return "".join(self._text_parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "title" and self._skip_depth == 0:
            self._in_title = True
            return
        if tag in self._BLOCK_TAGS:
            self._append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in self._BLOCK_TAGS:
            self._append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title_parts.append(data)
            return
        self._append(data)

    def handle_entityref(self, name: str) -> None:
        # Only reached when convert_charrefs is off; kept for safety.
        self._append(f"&{name};")

    def _append(self, chunk: str) -> None:
        self._text_parts.append(chunk)


def extract_readable(
    html: bytes | str, *, max_chars: int = MAX_TEXT_CHARS
) -> tuple[str | None, str]:
    """Return ``(title, text)`` for HTML/text without executing any page code.

    Args:
        html: Raw response bytes (decoded using the headers, or best-effort) or
            already-decoded text.
        max_chars: Hard cap on returned characters.
    """
    if isinstance(html, bytes):
        html = _decode(html)

    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # noqa: BLE001 - malformed HTML must not crash a run
        # Malformed markup is common; fall back to whatever was collected.
        raise FetchError(f"page content could not be parsed: {type(exc).__name__}") from exc

    return parser.title, _collapse(parser.text)[:max_chars]


def _decode(body: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace")


def _collapse(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    output: list[str] = []
    for line in lines:
        if line:
            output.append(line)
        elif output and output[-1] != "":
            output.append("")
    return "\n".join(output).strip()


class PageFetcher:
    """Fetches pages with destination validation, redirect revalidation, and bounds.

    Args:
        policy: Destination validator, consulted for the initial URL *and* every
            redirect hop.
        transport: HTTP transport. Injected so tests never touch the network.
        timeout: Per-request timeout in seconds.
        max_bytes: Maximum response bytes read.
        max_redirects: Maximum redirect hops followed.
    """

    def __init__(
        self,
        policy: UrlPolicy,
        transport: Transport | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = MAX_PAGE_BYTES,
        max_redirects: int = MAX_REDIRECTS,
    ) -> None:
        if timeout <= 0:
            raise ToolValidationError("timeout must be positive")
        if max_bytes <= 0:
            raise ToolValidationError("max_bytes must be positive")
        if max_redirects < 0:
            raise ToolValidationError("max_redirects must not be negative")
        self._policy = policy
        self._transport = transport or RequestsTransport()
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects

    def fetch(self, url: object) -> FetchedPage:
        """Fetch ``url``, following revalidated redirects, and return readable text.

        Raises:
            ToolValidationError: if ``url`` is not a string.
            FetchError: for policy violations, network failures, timeouts,
                oversized responses, unsupported content types, redirects
                exhausted, or unparsable content.
        """
        current = url
        chain: list[str] = []

        for hop in range(self._max_redirects + 1):
            destination = self._policy.validate(current)
            response = self._get(destination)

            if response.status_code in (301, 302, 303, 307, 308):
                location = _header(response.headers, "location")
                if not location:
                    raise FetchError(f"redirect from {destination.hostname} has no Location header")
                if hop == self._max_redirects:
                    raise FetchError(f"too many redirects (limit {self._max_redirects})")
                next_url = urljoin(_original_url(destination), location)
                chain.append(next_url)
                current = next_url
                continue

            if response.status_code >= 400:
                raise FetchError(
                    f"server responded with HTTP {response.status_code} for {destination.hostname}"
                )

            content_type = _content_type(response.headers)
            if not _is_allowed_content_type(content_type):
                raise FetchError(f"content type {content_type or '(none)'} is not readable text")

            if len(response.body) > self._max_bytes:
                raise FetchError(f"response exceeds {self._max_bytes} bytes")

            title, text = extract_readable(response.body, max_chars=MAX_TEXT_CHARS)
            if not text:
                raise FetchError("page contained no readable text")

            return FetchedPage(
                url=_original_url(destination),
                status_code=response.status_code,
                content_type=content_type,
                title=title,
                text=text,
                redirect_chain=tuple(chain),
            )

        raise FetchError("redirect limit reached")

    def _get(self, destination: Destination) -> TransportResponse:
        """Call the transport, normalising every failure into :class:`FetchError`.

        AssertionError is deliberately re-raised: it signals a broken transport
        or test double, not an expected fetch failure, and must stay visible.
        """
        try:
            return self._transport.get(
                destination, timeout=self._timeout, max_bytes=self._max_bytes
            )
        except (FetchError, AssertionError):
            raise
        except Exception as exc:  # noqa: BLE001 - boundary normalisation
            raise FetchError(
                f"request to {destination.hostname} failed: {type(exc).__name__}: {exc}"
            ) from exc


def _original_url(destination: Destination) -> str:
    """Reconstruct the (policy-approved) original URL for reporting and joins."""
    default = 80 if destination.scheme == "http" else 443
    host = destination.hostname
    if ":" in host:
        host = f"[{host}]"
    authority = host if destination.port == default else f"{host}:{destination.port}"
    return f"{destination.scheme}://{authority}{destination.path}"


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def _content_type(headers: Mapping[str, str]) -> str:
    raw = _header(headers, "content-type") or ""
    return raw.split(";", 1)[0].strip().lower()


def _is_allowed_content_type(content_type: str) -> bool:
    if not content_type:
        # No header at all is treated as unknown; treat as text so extraction
        # decides, but reject clearly binary prefixes.
        return True
    if any(content_type.startswith(prefix) for prefix in _NON_TEXT_CONTENT_TYPES):
        return False
    return content_type in ALLOWED_CONTENT_TYPES or content_type.startswith("text/")


class _PinnedAdapter(HTTPAdapter):
    """HTTP adapter that connects to a pinned IP while validating against its hostname.

    urllib3 accepts ``server_hostname`` and ``assert_hostname`` as pool keyword
    arguments, forwarding them to the connection. Connecting to the validated IP
    with SNI and certificate checks bound to the original hostname means a DNS
    answer obtained *after* validation can never change where the socket goes
    (DNS rebinding defence).
    """

    def __init__(self, tls_hostname: str) -> None:
        super().__init__()
        self.init_poolmanager(
            self._pool_connections,
            self._pool_maxsize,
            block=self._pool_block,
            server_hostname=tls_hostname,
            assert_hostname=tls_hostname,
        )


class RequestsTransport:
    """Real HTTP transport built on :mod:`requests`.

    The module-level import of :mod:`requests` is deferred to construction so the
    rest of the package (and every test) works without it installed.
    """

    def __init__(self) -> None:
        import requests

        self._requests = requests

    def get(self, destination: Destination, *, timeout: float, max_bytes: int) -> TransportResponse:
        requests = self._requests

        session = requests.Session()
        adapter = _PinnedAdapter(destination.tls_hostname)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        # No Authorization, cookies, or referrer: nothing is forwarded to origins.
        session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
                "Accept-Encoding": "identity",
                "Host": destination.host_header,
            }
        )

        try:
            response = session.get(
                destination.pinned_url,
                timeout=(timeout, timeout),
                allow_redirects=False,
                stream=True,
            )
            try:
                body = _read_bounded(response, max_bytes)
            finally:
                response.close()
        except requests.exceptions.Timeout as exc:
            raise FetchError(f"request to {destination.hostname} timed out") from exc
        except requests.exceptions.RequestException as exc:
            raise FetchError(
                f"request to {destination.hostname} failed: {type(exc).__name__}"
            ) from exc
        finally:
            session.close()

        return TransportResponse(
            status_code=response.status_code,
            headers={key: value for key, value in response.headers.items()},
            body=body,
        )


def _read_bounded(response: object, max_bytes: int) -> bytes:
    """Stream at most ``max_bytes``; abort as soon as the cap is exceeded."""
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=8192):  # type: ignore[attr-defined]
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise FetchError(f"response exceeds {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)
