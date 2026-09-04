import ipaddress
import socket
from urllib.parse import urlparse

from api.constants import DEPLOYMENT_MODE

_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


def validate_user_configured_service_url(
    url: str,
    *,
    field_name: str,
) -> None:
    """Restrict user-configured service URLs in hosted deployments.

    OSS deployments preserve the existing permissive behavior for local,
    private, and provider-specific URL forms. LangGraph endpoints use the
    explicit destination-policy hooks below, including their separately
    audited private-network decision.
    """
    if DEPLOYMENT_MODE == "oss":
        return
    validate_initial_destination(
        url,
        field_name=field_name,
    )


def validate_initial_destination(
    url: str,
    *,
    field_name: str = "endpoint_url",
    allow_self_hosted_private_network: bool = False,
) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    """Approve an initial destination before credentials or a body are attached."""
    return _validate_destination_url(
        url,
        field_name=field_name,
        allow_self_hosted_private_network=allow_self_hosted_private_network,
    )


def validate_redirect_destination(
    url: str,
    *,
    field_name: str = "redirect_url",
    allow_self_hosted_private_network: bool = False,
) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    """Apply the same destination policy before following every redirect."""
    return _validate_destination_url(
        url,
        field_name=field_name,
        allow_self_hosted_private_network=allow_self_hosted_private_network,
    )


def validate_connection_destination(
    address: str,
    *,
    allow_self_hosted_private_network: bool = False,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Validate the connected peer before request credentials are transmitted."""
    ip = ipaddress.ip_address(address)
    if (
        _private_destination_is_blocked(allow_self_hosted_private_network)
        and _is_blocked_saas_service_ip(ip)
    ):
        raise ValueError("connection destination must be a public IP address")
    return ip


def _private_destination_is_blocked(allow_self_hosted_private_network: bool) -> bool:
    return DEPLOYMENT_MODE != "oss" or not allow_self_hosted_private_network


def _validate_destination_url(
    url: str,
    *,
    field_name: str,
    allow_self_hosted_private_network: bool,
) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.hostname:
        raise ValueError(f"{field_name} must be an http, https, ws, or wss URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field_name} must not contain user information")

    if not _private_destination_is_blocked(allow_self_hosted_private_network):
        return tuple(_resolve_hostname_ips(parsed.hostname, parsed.port))

    hostname = parsed.hostname
    if hostname.lower() == "localhost":
        raise ValueError(f"{field_name} cannot point to localhost in SaaS mode")

    addresses = tuple(_resolve_hostname_ips(hostname, parsed.port))
    if any(_is_blocked_saas_service_ip(ip) for ip in addresses):
        raise ValueError(f"{field_name} must resolve to a public IP address in SaaS mode")
    return addresses


def _resolve_hostname_ips(
    hostname: str, port: int | None
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return [ipaddress.ip_address(hostname)]
    except ValueError:
        pass

    try:
        addr_infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError("Could not resolve service URL hostname") from e

    return [ipaddress.ip_address(addr_info[4][0]) for addr_info in addr_infos]


def _is_blocked_saas_service_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (ip.version == 4 and ip in _CGNAT_NETWORK)
    )
