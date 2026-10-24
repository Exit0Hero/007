"""Tests for destination policy: SSRF protection (US-202, US-601, SECURITY.md).

No test here performs DNS or network I/O: every resolver is faked, so results are
deterministic and run without credentials (US-503).
"""

from __future__ import annotations

import pytest

from atlas.errors import FetchError, ToolValidationError
from atlas.tools.fetch import (
    ALLOWED_PORTS,
    MAX_URL_LENGTH,
    UrlPolicy,
    validate_address,
)

PUBLIC_IP = "93.184.216.34"
PUBLIC_IP_2 = "151.101.1.140"


def policy(responses: dict[str, list[str]] | None = None) -> UrlPolicy:
    """Policy whose resolver answers from a fixed table, or rejects everything."""
    table = responses or {}

    def resolver(hostname: str, port: int) -> list[str]:
        if hostname not in table:
            raise FetchError(f"could not resolve host {hostname!r}")
        return table[hostname]

    return UrlPolicy(resolver)


# --- scheme and URL shape ----------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "gopher://example.com/",
        "jar:http://example.com/a.jar!/",
        "vbscript:msgbox(1)",
        "",
        "   ",
        "not a url at all",
        "//example.com/protocol-relative",
        "/just/a/path",
        "example.com/no-scheme",
    ],
)
def test_disallowed_or_malformed_urls_are_rejected(url: str) -> None:
    with pytest.raises((FetchError, ToolValidationError)):
        policy({}).validate(url)


def test_non_string_url_is_rejected_as_validation_error() -> None:
    with pytest.raises(ToolValidationError):
        policy({}).validate(12345)  # type: ignore[arg-type]


def test_over_long_url_is_rejected() -> None:
    long_url = "https://example.com/" + "a" * MAX_URL_LENGTH
    with pytest.raises(FetchError):
        policy({"example.com": [PUBLIC_IP]}).validate(long_url)


def test_urls_with_embedded_credentials_are_rejected() -> None:
    for url in (
        "http://user:pass@example.com/x",
        "http://admin@example.com/x",
        "https://user@example.com/x",
    ):
        with pytest.raises(FetchError):
            policy({"example.com": [PUBLIC_IP]}).validate(url)


def test_disallowed_port_is_rejected() -> None:
    with pytest.raises(FetchError) as excinfo:
        policy({"example.com": [PUBLIC_IP]}).validate("http://example.com:22/")

    assert "22" in str(excinfo.value)


@pytest.mark.parametrize("port", ALLOWED_PORTS)
def test_allowed_ports_are_accepted(port: int) -> None:
    scheme = "https" if port == 443 else "http"
    destination = policy({"example.com": [PUBLIC_IP]}).validate(
        f"{scheme}://example.com:{port}/page"
    )

    assert destination.port == port


def test_missing_port_defaults_to_scheme_default() -> None:
    assert policy({"a.example": [PUBLIC_IP]}).validate("http://a.example/").port == 80
    assert policy({"a.example": [PUBLIC_IP]}).validate("https://a.example/").port == 443


# --- hostname rules ----------------------------------------------------------


@pytest.mark.parametrize(
    "hostname",
    ["localhost", "LOCALHOST", "localhost.localdomain", "foo.localhost", "ip6-localhost"],
)
def test_localhost_variants_are_rejected_without_dns(hostname: str) -> None:
    """These must be refused before any resolver is consulted."""
    called: list[str] = []

    def resolver(host: str, port: int) -> list[str]:
        called.append(host)
        return [PUBLIC_IP]

    with pytest.raises(FetchError):
        UrlPolicy(resolver).validate(f"http://{hostname}/")

    assert called == []


@pytest.mark.parametrize(
    "url",
    [
        "http://exam ple.com/",
        "http://-bad-.example.com/",
        "http://exa_mple.com/",
        "http://example..com/",
        "http:///",
    ],
)
def test_invalid_hostnames_are_rejected(url: str) -> None:
    with pytest.raises(FetchError):
        policy({"example.com": [PUBLIC_IP]}).validate(url)


def test_valid_hostname_is_accepted_and_pinned() -> None:
    destination = policy({"example.com": [PUBLIC_IP]}).validate("https://example.com/doc")

    assert destination.ip == PUBLIC_IP
    assert destination.hostname == "example.com"
    assert destination.path == "/doc"


def test_hostname_is_lowercased_by_parsing() -> None:
    destination = policy({"example.com": [PUBLIC_IP]}).validate("https://EXAMPLE.COM/")

    assert destination.hostname == "example.com"


# --- address validation (the core SSRF control) ------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "127.1.2.3",
        "0.0.0.0",
        "10.0.0.1",
        "10.255.255.255",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata endpoint
        "169.254.0.1",
        "100.64.0.1",  # carrier-grade NAT
        "198.18.0.1",  # benchmarking
        "224.0.0.1",  # multicast
        "255.255.255.255",
        "240.0.0.1",  # reserved
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "fd12:3456:789a::1",
        "ff02::1",
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::ffff:10.0.0.1",
        "::ffff:169.254.169.254",
    ],
)
def test_non_global_addresses_are_rejected(address: str) -> None:
    with pytest.raises(FetchError):
        validate_address(address)


@pytest.mark.parametrize(
    "address",
    ["93.184.216.34", "151.101.1.140", "2606:2800:220:1:248:1893:25c8:1946"],
)
def test_public_addresses_are_accepted(address: str) -> None:
    assert validate_address(address) == address


def test_obfuscated_loopback_encodings_are_rejected() -> None:
    """Integer/hex/octal encodings must not bypass the loopback check."""
    for host in ("2130706433", "0x7f000001", "0177.0.0.1", "127.0.0.1"):
        with pytest.raises(FetchError):
            UrlPolicy(lambda h, p: [h]).validate(f"http://{host}/")


def test_literal_public_ip_needs_no_dns() -> None:
    called: list[str] = []

    def resolver(host: str, port: int) -> list[str]:
        called.append(host)
        return []

    destination = UrlPolicy(resolver).validate(f"http://{PUBLIC_IP}/")

    assert destination.ip == PUBLIC_IP
    assert called == []


def test_literal_private_ip_is_rejected() -> None:
    for url in (
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://192.168.0.1:443/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[fe80::1]/",
    ):
        with pytest.raises(FetchError):
            UrlPolicy(lambda h, p: []).validate(url)


def test_hostname_resolving_to_private_address_is_rejected() -> None:
    with pytest.raises(FetchError) as excinfo:
        policy({"internal.corp": ["10.0.0.7"]}).validate("http://internal.corp/")

    assert "not publicly routable" in str(excinfo.value)


def test_hostname_resolving_to_loopback_is_rejected() -> None:
    with pytest.raises(FetchError):
        policy({"rebind.test": ["127.0.0.1"]}).validate("http://rebind.test/")


def test_mixed_public_and_private_answers_reject_whole_destination() -> None:
    """Rebinding-style answers (public + private) must fail closed."""
    with pytest.raises(FetchError):
        policy({"evil.test": [PUBLIC_IP, "127.0.0.1"]}).validate("http://evil.test/")
    with pytest.raises(FetchError):
        policy({"evil.test": ["127.0.0.1", PUBLIC_IP]}).validate("http://evil.test/")


def test_unresolvable_host_is_a_fetch_error() -> None:
    with pytest.raises(FetchError):
        policy({}).validate("http://nope.invalid/")


def test_resolver_returning_no_addresses_is_rejected() -> None:
    with pytest.raises(FetchError):
        policy({"empty.test": []}).validate("http://empty.test/")


def test_unparseable_resolver_answer_is_rejected() -> None:
    with pytest.raises(FetchError):
        policy({"odd.test": ["not-an-ip"]}).validate("http://odd.test/")


def test_trailing_dot_on_localhost_still_rejected() -> None:
    with pytest.raises(FetchError):
        UrlPolicy(lambda h, p: ["127.0.0.1"]).validate("http://localhost./")


# --- pinning and headers -----------------------------------------------------


def test_pinned_url_targets_validated_ip() -> None:
    destination = policy({"example.com": [PUBLIC_IP]}).validate("https://example.com/a?b=c")

    assert destination.pinned_url.startswith(f"https://{PUBLIC_IP}/a?b=c")
    assert "example.com" not in destination.pinned_url


def test_pinned_url_for_ipv6_is_bracketed() -> None:
    ipv6 = "2606:2800:220:1:248:1893:25c8:1946"
    destination = UrlPolicy(lambda h, p: [ipv6]).validate("https://example.com/x")

    assert destination.pinned_url.startswith(f"https://[{ipv6}]/x")


def test_host_header_preserves_original_hostname() -> None:
    destination = policy({"example.com": [PUBLIC_IP]}).validate("https://example.com/a")

    assert destination.host_header == "example.com"
    assert destination.tls_hostname == "example.com"


def test_host_header_includes_non_default_port() -> None:
    """http on port 443 is non-default for the scheme, so the port must show."""
    destination = policy({"example.com": [PUBLIC_IP]}).validate("http://example.com:443/a")

    assert destination.port == 443
    assert destination.host_header == "example.com:443"


def test_query_string_is_preserved_in_path() -> None:
    destination = policy({"example.com": [PUBLIC_IP]}).validate(
        "https://example.com/search?q=atlas&page=2"
    )

    assert destination.path == "/search?q=atlas&page=2"
    assert destination.pinned_url.endswith("/search?q=atlas&page=2")
