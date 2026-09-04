from __future__ import annotations

import ipaddress
from unittest.mock import patch

import pytest
from hypothesis import given
from hypothesis import strategies as st

from api.utils.url_security import (
    validate_connection_destination,
    validate_initial_destination,
    validate_redirect_destination,
)

_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")

_BLOCKED_NETWORKS = (
    ("private_ipv4", ipaddress.ip_network("10.0.0.0/8")),
    ("private_ipv6", ipaddress.ip_network("fc00::/7")),
    ("loopback_ipv4", ipaddress.ip_network("127.0.0.0/8")),
    ("loopback_ipv6", ipaddress.ip_network("::1/128")),
    ("link_local_ipv4", ipaddress.ip_network("169.254.0.0/16")),
    ("link_local_ipv6", ipaddress.ip_network("fe80::/10")),
    ("multicast_ipv4", ipaddress.ip_network("224.0.0.0/4")),
    ("multicast_ipv6", ipaddress.ip_network("ff00::/8")),
    ("reserved_ipv4", ipaddress.ip_network("240.0.0.0/4")),
    ("reserved_ipv6", ipaddress.ip_network("100::/64")),
    ("unspecified_ipv4", ipaddress.ip_network("0.0.0.0/32")),
    ("unspecified_ipv6", ipaddress.ip_network("::/128")),
    ("carrier_grade_nat_ipv4", _CGNAT_NETWORK),
)


def _is_prohibited_hosted_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or (address.version == 4 and address in _CGNAT_NETWORK)
    )


def _address_url(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    host = f"[{address}]" if address.version == 6 else str(address)
    return f"https://{host}/.well-known/mural-langgraph"


def _assert_blocked_at_every_destination_check(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> None:
    url = _address_url(address)
    for validator in (validate_initial_destination, validate_redirect_destination):
        with pytest.raises(ValueError, match="public IP address"):
            validator(url)
    with pytest.raises(ValueError, match="public IP address"):
        validate_connection_destination(str(address))


def _assert_allowed_at_every_destination_check(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> None:
    url = _address_url(address)
    assert validate_initial_destination(url) == (address,)
    assert validate_redirect_destination(url) == (address,)
    assert validate_connection_destination(str(address)) == address


# Feature: langgraph-voice-integration, Property 26: Hosted address classification blocks non-public destinations
@pytest.mark.parametrize(("category", "network"), _BLOCKED_NETWORKS)
@given(data=st.data())
def test_property_26_prohibited_address_classes_are_blocked(
    category,
    network,
    data,
):
    with patch("api.utils.url_security.DEPLOYMENT_MODE", "saas"):
        address = data.draw(st.ip_addresses(network=network), label=category)

        assert _is_prohibited_hosted_address(address), category
        _assert_blocked_at_every_destination_check(address)


# Feature: langgraph-voice-integration, Property 26: Hosted address classification blocks non-public destinations
@pytest.mark.parametrize("version", (4, 6))
@given(data=st.data())
def test_property_26_public_ipv4_and_ipv6_addresses_are_eligible(
    version,
    data,
):
    with patch("api.utils.url_security.DEPLOYMENT_MODE", "saas"):
        address = data.draw(
            st.ip_addresses(v=version).filter(
                lambda candidate: not _is_prohibited_hosted_address(candidate)
            ),
            label=f"public_ipv{version}",
        )

        _assert_allowed_at_every_destination_check(address)
