import asyncio
import copy
import ipaddress
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from api.schemas.langgraph_integration.examples import EXECUTABLE_EXAMPLES
from api.services.langgraph_integration.configuration import (
    LangGraphFeatureConfiguration,
)
from api.services.langgraph_integration.gateway import (
    DISCOVERY_PATH,
    DiscoveryTimeoutError,
    InvalidManifestError,
    UnsafeDestinationError,
    discover_manifest,
)
from api.utils.url_security import (
    validate_connection_destination,
    validate_initial_destination,
    validate_redirect_destination,
)


class ScriptedDiscoveryTransport:
    def __init__(self, steps: list[dict[str, Any]]):
        self.steps = list(steps)
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.credentials_sent: list[str] = []

    async def get(self, url, *, headers, timeout, validate_connection):
        step = self.steps.pop(0)
        if delay := step.get("delay"):
            await asyncio.sleep(delay)
        # This mirrors the production transport ordering: the connected peer is
        # approved before request headers (and therefore credentials) are sent.
        validate_connection(step["peer"])
        copied_headers = dict(headers)
        self.calls.append((url, copied_headers))
        if "authorization" in {name.lower() for name in copied_headers}:
            self.credentials_sent.append(url)
        request = httpx.Request("GET", url, headers=copied_headers)
        response = httpx.Response(
            step.get("status", 200),
            headers=step.get("headers"),
            json=step.get("json"),
            content=step.get("content"),
            request=request,
        )
        return response, step["peer"]


def _manifest(version: str = "1.0") -> dict[str, Any]:
    return copy.deepcopy(EXECUTABLE_EXAMPLES[version]["manifest"])


def _resolve_to(monkeypatch, *addresses: str) -> None:
    resolved = [ipaddress.ip_address(address) for address in addresses]
    monkeypatch.setattr(
        "api.utils.url_security._resolve_hostname_ips", lambda *_: resolved
    )


@pytest.mark.parametrize("address", ["8.8.8.8", "2606:4700:4700::1111"])
def test_hosted_policy_allows_public_ipv4_and_ipv6(monkeypatch, address):
    monkeypatch.setattr("api.utils.url_security.DEPLOYMENT_MODE", "saas")
    url = f"https://[{address}]/discovery" if ":" in address else f"https://{address}/discovery"
    assert str(validate_initial_destination(url)[0]) == address
    assert str(validate_redirect_destination(url)[0]) == address
    assert str(validate_connection_destination(address)) == address


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.1.1",
        "100.64.0.1",
        "224.0.0.1",
        "0.0.0.0",
        "::1",
        "fc00::1",
        "fe80::1",
        "ff02::1",
        "::",
    ],
)
def test_hosted_policy_blocks_non_public_ipv4_and_ipv6(monkeypatch, address):
    monkeypatch.setattr("api.utils.url_security.DEPLOYMENT_MODE", "saas")
    url = f"https://[{address}]/discovery" if ":" in address else f"https://{address}/discovery"
    with pytest.raises(ValueError):
        validate_initial_destination(url)
    with pytest.raises(ValueError):
        validate_redirect_destination(url)
    with pytest.raises(ValueError):
        validate_connection_destination(address)


@pytest.mark.asyncio
async def test_discovery_uses_well_known_path_and_authenticates_after_approval(monkeypatch):
    monkeypatch.setattr("api.utils.url_security.DEPLOYMENT_MODE", "saas")
    _resolve_to(monkeypatch, "8.8.8.8")
    transport = ScriptedDiscoveryTransport([{"peer": "8.8.8.8", "json": _manifest()}])

    result = await discover_manifest(
        endpoint_url="https://agent.example/base/path",
        auth_headers={"Authorization": "Bearer secret"},
        transport=transport,
    )

    assert result.manifest.endpoint_id == "support-agent"
    assert result.final_url == f"https://agent.example{DISCOVERY_PATH}"
    assert result.peer_address == "8.8.8.8"
    assert transport.credentials_sent == [result.final_url]


@pytest.mark.asyncio
async def test_discovery_selects_declared_supported_schema_version(monkeypatch):
    monkeypatch.setattr("api.utils.url_security.DEPLOYMENT_MODE", "saas")
    _resolve_to(monkeypatch, "8.8.8.8")
    transport = ScriptedDiscoveryTransport(
        [{"peer": "8.8.8.8", "json": _manifest("1.1")}]
    )

    result = await discover_manifest(
        endpoint_url="https://agent.example",
        auth_headers={"Authorization": "Bearer secret"},
        transport=transport,
    )

    assert result.manifest.schema_version == "1.1"
    assert result.manifest.metadata is not None


@pytest.mark.asyncio
async def test_discovery_preserves_explicit_schema_version_pin(monkeypatch):
    monkeypatch.setattr("api.utils.url_security.DEPLOYMENT_MODE", "saas")
    _resolve_to(monkeypatch, "8.8.8.8")

    with pytest.raises(InvalidManifestError) as exc_info:
        await discover_manifest(
            endpoint_url="https://agent.example",
            auth_headers={"Authorization": "Bearer secret"},
            schema_version="1.0",
            transport=ScriptedDiscoveryTransport(
                [{"peer": "8.8.8.8", "json": _manifest("1.1")}]
            ),
        )

    assert exc_info.value.violations == ("schema_version: Input should be '1.0'",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("schema_value", "remove_schema", "expected_violation"),
    [
        (None, True, "schema_version: Field required"),
        (7, False, "schema_version: Input should be a valid string"),
        (
            "9.9",
            False,
            "schema_version: Unsupported schema version '9.9'",
        ),
    ],
)
async def test_discovery_rejects_invalid_schema_discriminators(
    monkeypatch, schema_value, remove_schema, expected_violation
):
    monkeypatch.setattr("api.utils.url_security.DEPLOYMENT_MODE", "saas")
    _resolve_to(monkeypatch, "8.8.8.8")
    manifest = _manifest()
    if remove_schema:
        manifest.pop("schema_version")
    else:
        manifest["schema_version"] = schema_value

    with pytest.raises(InvalidManifestError) as exc_info:
        await discover_manifest(
            endpoint_url="https://agent.example",
            auth_headers={"Authorization": "Bearer secret"},
            transport=ScriptedDiscoveryTransport(
                [{"peer": "8.8.8.8", "json": manifest}]
            ),
        )

    assert exc_info.value.violations == (expected_violation,)


@pytest.mark.asyncio
async def test_dns_rebinding_blocks_credentials_before_http_headers(monkeypatch):
    monkeypatch.setattr("api.utils.url_security.DEPLOYMENT_MODE", "saas")
    _resolve_to(monkeypatch, "8.8.8.8")
    transport = ScriptedDiscoveryTransport([{"peer": "10.0.0.9", "json": _manifest()}])

    with pytest.raises(UnsafeDestinationError):
        await discover_manifest(
            endpoint_url="https://agent.example",
            auth_headers={"Authorization": "Bearer secret"},
            transport=transport,
        )

    assert transport.calls == []
    assert transport.credentials_sent == []


@pytest.mark.asyncio
async def test_private_initial_dns_result_discloses_no_credentials(monkeypatch):
    monkeypatch.setattr("api.utils.url_security.DEPLOYMENT_MODE", "saas")
    _resolve_to(monkeypatch, "192.168.1.8")
    transport = ScriptedDiscoveryTransport([])

    with pytest.raises(UnsafeDestinationError):
        await discover_manifest(
            endpoint_url="https://agent.example",
            auth_headers={"Authorization": "Bearer secret"},
            transport=transport,
        )

    assert transport.calls == []
    assert transport.credentials_sent == []


@pytest.mark.asyncio
async def test_every_redirect_is_validated_before_credentials_are_sent(monkeypatch):
    monkeypatch.setattr("api.utils.url_security.DEPLOYMENT_MODE", "saas")

    def resolve(hostname, _port):
        address = "8.8.8.8" if hostname == "agent.example" else "127.0.0.1"
        return [ipaddress.ip_address(address)]

    monkeypatch.setattr("api.utils.url_security._resolve_hostname_ips", resolve)
    transport = ScriptedDiscoveryTransport(
        [
            {
                "peer": "8.8.8.8",
                "status": 302,
                "headers": {"location": "http://internal.example/manifest"},
            }
        ]
    )

    with pytest.raises(UnsafeDestinationError):
        await discover_manifest(
            endpoint_url="https://agent.example",
            auth_headers={"Authorization": "Bearer secret"},
            transport=transport,
        )

    assert len(transport.calls) == 1
    assert transport.credentials_sent == [f"https://agent.example{DISCOVERY_PATH}"]


@pytest.mark.asyncio
async def test_public_redirect_is_followed_with_validation_and_authentication(monkeypatch):
    monkeypatch.setattr("api.utils.url_security.DEPLOYMENT_MODE", "saas")
    _resolve_to(monkeypatch, "8.8.8.8")
    redirect_url = "https://redirect.example/capabilities"
    transport = ScriptedDiscoveryTransport(
        [
            {
                "peer": "8.8.8.8",
                "status": 307,
                "headers": {"location": redirect_url},
            },
            {"peer": "1.1.1.1", "json": _manifest()},
        ]
    )

    result = await discover_manifest(
        endpoint_url="https://agent.example",
        auth_headers={"Authorization": "Bearer secret"},
        transport=transport,
    )

    assert result.redirects == (redirect_url,)
    assert result.final_url == redirect_url
    assert transport.credentials_sent == [
        f"https://agent.example{DISCOVERY_PATH}",
        redirect_url,
    ]


@pytest.mark.asyncio
async def test_complete_manifest_deadline_covers_body_and_validation(monkeypatch):
    monkeypatch.setattr("api.utils.url_security.DEPLOYMENT_MODE", "saas")
    monkeypatch.setattr(
        "api.services.langgraph_integration.gateway.DISCOVERY_TIMEOUT_SECONDS", 0.01
    )
    _resolve_to(monkeypatch, "8.8.8.8")
    transport = ScriptedDiscoveryTransport(
        [{"peer": "8.8.8.8", "json": _manifest(), "delay": 0.05}]
    )

    with pytest.raises(DiscoveryTimeoutError):
        await discover_manifest(
            endpoint_url="https://agent.example",
            auth_headers={"Authorization": "Bearer secret"},
            transport=transport,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("step", "expected_violation"),
    [
        ({"peer": "8.8.8.8", "content": b"not-json"}, "body: invalid JSON"),
        (
            {"peer": "8.8.8.8", "json": {"schema_version": "1.0"}},
            "endpoint_id",
        ),
    ],
)
async def test_malformed_manifests_report_structured_violations(
    monkeypatch, step, expected_violation
):
    monkeypatch.setattr("api.utils.url_security.DEPLOYMENT_MODE", "saas")
    _resolve_to(monkeypatch, "8.8.8.8")

    with pytest.raises(InvalidManifestError) as exc_info:
        await discover_manifest(
            endpoint_url="https://agent.example",
            auth_headers={"Authorization": "Bearer secret"},
            transport=ScriptedDiscoveryTransport([step]),
        )

    assert any(expected_violation in violation for violation in exc_info.value.violations)


@pytest.mark.asyncio
async def test_self_hosted_private_access_requires_audited_configuration(monkeypatch):
    monkeypatch.setattr("api.utils.url_security.DEPLOYMENT_MODE", "oss")
    private_step = {"peer": "10.0.0.5", "json": _manifest()}

    with pytest.raises(UnsafeDestinationError):
        await discover_manifest(
            endpoint_url="http://10.0.0.5",
            auth_headers={"Authorization": "Bearer secret"},
            transport=ScriptedDiscoveryTransport([private_step]),
        )

    audited = LangGraphFeatureConfiguration(
        private_network_enabled=True,
        private_network_decided_at=datetime.now(UTC),
        private_network_decided_by=7,
    )
    result = await discover_manifest(
        endpoint_url="http://10.0.0.5",
        auth_headers={"Authorization": "Bearer secret"},
        feature_configuration=audited,
        transport=ScriptedDiscoveryTransport([private_step]),
    )
    assert result.peer_address == "10.0.0.5"
