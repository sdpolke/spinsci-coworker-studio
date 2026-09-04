"""Gateway-only network operations for LangGraph workflow endpoints."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urljoin

import httpx
from opentelemetry import trace
from pydantic import BaseModel

from api.schemas.langgraph_integration import SUPPORTED_SCHEMA_VERSIONS, schema_for
from api.schemas.langgraph_integration.common import InvocationMode
from api.services.langgraph_integration.configuration import (
    LangGraphFeatureConfiguration,
)
from api.services.langgraph_integration.contract import serialize_pinned_request
from api.services.langgraph_integration.contract.negotiation import validate_manifest
from api.services.langgraph_integration.protocol import (
    AcceptedEventLedger,
    AcceptedRuntimeEvent,
    CancellationState,
    ProtocolViolation,
    RuntimeEventReducer,
    asynchronous_deadline_outcome,
    validate_asynchronous_acceptance,
    validate_status_result,
    validate_synchronous_result,
)
from api.services.pipecat.tracing_config import build_remote_parent_context
from api.utils.url_security import (
    validate_connection_destination,
    validate_initial_destination,
    validate_redirect_destination,
)

DISCOVERY_PATH = "/.well-known/mural-langgraph"
DISCOVERY_TIMEOUT_SECONDS = 5.0
MAX_REDIRECTS = 5

ConnectionValidator = Callable[[str], None]


class DiscoveryError(RuntimeError):
    """Base class for safe discovery failures."""


class DiscoveryTimeoutError(DiscoveryError):
    pass


class InvalidManifestError(DiscoveryError):
    def __init__(self, violations: tuple[str, ...]):
        super().__init__("invalid capability manifest")
        self.violations = violations


class UnsafeDestinationError(DiscoveryError):
    pass


class DiscoveryTransport(Protocol):
    async def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        validate_connection: ConnectionValidator,
    ) -> tuple[httpx.Response, str]: ...


@dataclass(frozen=True)
class DiscoveryResult:
    manifest: Any
    final_url: str
    redirects: tuple[str, ...]
    peer_address: str


def _stream_peer_address(stream: Any) -> str:
    peer = stream.get_extra_info("server_addr")
    if not peer:
        raise UnsafeDestinationError(
            "connection peer address was not available for validation"
        )
    return str(peer[0] if isinstance(peer, tuple) else peer)


class HttpxDiscoveryTransport:
    """HTTP transport that approves the connected peer before sending headers."""

    async def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        validate_connection: ConnectionValidator,
    ) -> tuple[httpx.Response, str]:
        peer_address: str | None = None

        async def trace(event_name: str, info: dict[str, Any]) -> None:
            nonlocal peer_address
            if event_name != "connection.connect_tcp.complete":
                return
            peer_address = _stream_peer_address(info["return_value"])
            # httpcore invokes this hook after TCP connect and before TLS or HTTP
            # request headers. Raising here prevents credential disclosure.
            validate_connection(peer_address)

        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=timeout,
            trust_env=False,
        ) as client:
            response = await client.get(
                url,
                headers=dict(headers),
                extensions={"trace": trace},
            )
        if peer_address is None:
            raise UnsafeDestinationError(
                "connection peer address was not available for validation"
            )
        return response, peer_address


def _private_network_allowed(
    configuration: LangGraphFeatureConfiguration | None,
) -> bool:
    """Accept private routing only when its deployment decision is audited."""
    return bool(configuration and configuration.private_network_enabled)


def _select_manifest_schema_version(
    payload: object, requested_version: str | None
) -> str:
    """Select only a registered schema from the untrusted manifest discriminator."""
    if requested_version is not None:
        if requested_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise InvalidManifestError(
                (f"schema_version: Unsupported schema version {requested_version!r}",)
            )
        return requested_version

    if not isinstance(payload, dict) or "schema_version" not in payload:
        raise InvalidManifestError(("schema_version: Field required",))
    declared_version = payload["schema_version"]
    if not isinstance(declared_version, str):
        raise InvalidManifestError(("schema_version: Input should be a valid string",))
    if declared_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise InvalidManifestError(
            (f"schema_version: Unsupported schema version {declared_version!r}",)
        )
    return declared_version


async def discover_manifest(
    *,
    endpoint_url: str,
    auth_headers: Mapping[str, str],
    schema_version: str | None = None,
    feature_configuration: LangGraphFeatureConfiguration | None = None,
    transport: DiscoveryTransport | None = None,
) -> DiscoveryResult:
    """Fetch and validate discovery with one five-second complete-body deadline.

    URL and DNS policy is checked before credentials are attached at every hop.
    The transport then validates the actual connected peer before sending those
    credentials, closing the DNS-rebinding gap.
    """
    client = transport or HttpxDiscoveryTransport()
    discovery_url = urljoin(endpoint_url, DISCOVERY_PATH)
    allow_private = _private_network_allowed(feature_configuration)

    def approve_connection(address: str) -> None:
        try:
            validate_connection_destination(
                address,
                allow_self_hosted_private_network=allow_private,
            )
        except ValueError as exc:
            raise UnsafeDestinationError(str(exc)) from exc

    async def _run() -> DiscoveryResult:
        redirects: list[str] = []
        current = discovery_url
        for hop in range(MAX_REDIRECTS + 1):
            try:
                if hop == 0:
                    validate_initial_destination(
                        current,
                        allow_self_hosted_private_network=allow_private,
                    )
                else:
                    validate_redirect_destination(
                        current,
                        allow_self_hosted_private_network=allow_private,
                    )
            except ValueError as exc:
                raise UnsafeDestinationError(str(exc)) from exc

            response, peer = await client.get(
                current,
                headers=auth_headers,
                timeout=DISCOVERY_TIMEOUT_SECONDS,
                validate_connection=approve_connection,
            )

            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise DiscoveryError("redirect response omitted location")
                if hop == MAX_REDIRECTS:
                    raise DiscoveryError("too many discovery redirects")
                current = urljoin(current, location)
                redirects.append(current)
                continue

            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                raise InvalidManifestError(("body: invalid JSON",)) from exc
            selected_schema_version = _select_manifest_schema_version(
                payload, schema_version
            )
            validated = validate_manifest(payload, selected_schema_version)
            if validated.manifest is None:
                raise InvalidManifestError(validated.violations)
            return DiscoveryResult(validated.manifest, current, tuple(redirects), peer)
        raise DiscoveryError("unreachable redirect state")

    try:
        return await asyncio.wait_for(_run(), timeout=DISCOVERY_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise DiscoveryTimeoutError(
            "complete capability manifest was not received within 5 seconds"
        ) from exc


# Runtime protocol engine ----------------------------------------------------


class CredentialResolver(Protocol):
    async def resolve_headers(
        self, *, organization_id: int, credential_reference: str
    ) -> Mapping[str, str]: ...


@dataclass(frozen=True)
class DatabaseCredentialResolver:
    db_client: Any

    async def resolve_headers(
        self, *, organization_id: int, credential_reference: str
    ) -> Mapping[str, str]:
        from api.utils.credential_auth import build_auth_header

        credential = await self.db_client.get_credential_by_uuid(
            credential_reference, organization_id
        )
        if credential is None:
            raise PermissionError("endpoint credential is unavailable for organization")
        return build_auth_header(credential)


@dataclass(frozen=True)
class StaticCredentialResolver:
    """Explicit resolver useful for already-resolved worker credentials/tests."""

    headers: Mapping[str, str]

    async def resolve_headers(
        self, *, organization_id: int, credential_reference: str
    ) -> Mapping[str, str]:
        del organization_id, credential_reference
        return dict(self.headers)


@dataclass(frozen=True)
class RuntimeEndpointSnapshot:
    """Immutable, workflow-version-pinned network and capability snapshot."""

    organization_id: int
    registration_id: str
    endpoint_url: str
    credential_reference: str
    contract_version: str
    invocation_modes: frozenset[InvocationMode]
    operations: Mapping[str, str]
    request_bytes: int
    response_bytes: int
    event_bytes: int
    tool_argument_bytes: int
    stateful_profile: bool = False
    interrupts_selected: bool = False
    cancellation_declared: bool = False
    distributed_tracing: bool = False
    private_network_enabled: bool = False

    def operation_url(self, operation: str, **identifiers: str) -> str:
        try:
            path = self.operations[operation].format(**identifiers)
        except KeyError as exc:
            raise ProtocolViolation(
                "operation_not_declared", f"endpoint did not declare {operation} operation"
            ) from exc
        return urljoin(self.endpoint_url.rstrip("/") + "/", path.lstrip("/"))


@dataclass(frozen=True)
class GatewayTraceContext:
    organization_id: int
    registration_id: str
    contract_version: str
    trace_id: str
    voice_run_id: str | None = None
    invocation_id: str | None = None
    attempt_id: str | None = None
    workflow_version_id: str | None = None

    @property
    def traceparent(self) -> str:
        trace_id = self.trace_id.lower()
        if len(trace_id) != 32 or any(ch not in "0123456789abcdef" for ch in trace_id):
            raise ValueError("trace_id must be 32 lowercase hexadecimal characters")
        span_id = uuid.uuid4().hex[:16]
        return f"00-{trace_id}-{span_id}-01"

    def span_attributes(self, operation: str) -> dict[str, str | int]:
        values: dict[str, str | int] = {
            "langgraph.operation": operation,
            "langgraph.organization_id": self.organization_id,
            "langgraph.registration_id": self.registration_id,
            "langgraph.contract_version": self.contract_version,
        }
        optional = {
            "langgraph.voice_run_id": self.voice_run_id,
            "langgraph.invocation_id": self.invocation_id,
            "langgraph.attempt_id": self.attempt_id,
            "langgraph.workflow_version_id": self.workflow_version_id,
        }
        values.update({key: value for key, value in optional.items() if value is not None})
        return values


@dataclass
class GatewayMetrics:
    """Bounded, payload-free metric projection used by the gateway."""

    counts: dict[tuple[str, str, str], int] = field(default_factory=lambda: defaultdict(int))
    timings_ms: dict[tuple[str, str, str], list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def increment(self, *, operation: str, registration_id: str, contract_version: str) -> None:
        self.counts[(operation, registration_id, contract_version)] += 1

    def timing(
        self,
        *,
        metric: str,
        registration_id: str,
        contract_version: str,
        milliseconds: float,
    ) -> None:
        self.timings_ms[(metric, registration_id, contract_version)].append(milliseconds)


class RuntimeResponse(Protocol):
    status_code: int
    headers: httpx.Headers

    @property
    def is_redirect(self) -> bool: ...

    async def aiter_bytes(self) -> AsyncIterator[bytes]: ...

    async def aclose(self) -> None: ...


class RuntimeTransport(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        content: bytes | None,
        timeout: float,
        validate_connection: ConnectionValidator,
    ) -> tuple[RuntimeResponse, str]: ...


@dataclass
class _HttpxRuntimeResponse:
    response: httpx.Response
    client: httpx.AsyncClient

    @property
    def status_code(self) -> int:
        return self.response.status_code

    @property
    def headers(self) -> httpx.Headers:
        return self.response.headers

    @property
    def is_redirect(self) -> bool:
        return self.response.is_redirect

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        async for chunk in self.response.aiter_bytes():
            yield chunk

    async def aclose(self) -> None:
        await self.response.aclose()
        await self.client.aclose()


class HttpxRuntimeTransport:
    """Streaming HTTP transport with pre-header peer-address approval."""

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        content: bytes | None,
        timeout: float,
        validate_connection: ConnectionValidator,
    ) -> tuple[RuntimeResponse, str]:
        peer_address: str | None = None

        async def trace_hook(event_name: str, info: dict[str, Any]) -> None:
            nonlocal peer_address
            if event_name == "connection.connect_tcp.complete":
                peer_address = _stream_peer_address(info["return_value"])
                validate_connection(peer_address)

        client = httpx.AsyncClient(follow_redirects=False, timeout=timeout, trust_env=False)
        try:
            request = client.build_request(method, url, headers=dict(headers), content=content)
            request.extensions["trace"] = trace_hook
            response = await client.send(request, stream=True)
        except BaseException:
            await client.aclose()
            raise
        if peer_address is None:
            await response.aclose()
            await client.aclose()
            raise UnsafeDestinationError("connection peer address was not available for validation")
        return _HttpxRuntimeResponse(response, client), peer_address


class DatabaseAcceptedEventLedger:
    """Adapter for Task 2's organization-scoped durable event client."""

    def __init__(self, db_client: Any, *, organization_id: int, invocation_pk: int) -> None:
        self.db_client = db_client
        self.organization_id = organization_id
        self.invocation_pk = invocation_pk

    async def record_event(
        self,
        *,
        sequence: int,
        event_id: str,
        event_type: str,
        payload_digest: str,
        metadata: dict[str, Any],
        mutation_outcome: str,
    ) -> bool:
        row, inserted = await self.db_client.record_langgraph_event(
            organization_id=self.organization_id,
            invocation_id=self.invocation_pk,
            sequence=sequence,
            endpoint_event_id=event_id,
            event_type=event_type,
            payload_digest=payload_digest,
            metadata=metadata,
            mutation_outcome=mutation_outcome,
        )
        if not inserted and (
            row.endpoint_event_id != event_id
            or row.event_type != event_type
            or row.payload_digest != payload_digest
        ):
            raise ProtocolViolation(
                "durable_event_conflict",
                "durable Runtime Event guard contains different content",
            )
        return inserted


class _SSEParser:
    """Bounded UTF-8 SSE parser; each event must contain one data JSON value."""

    def __init__(self, event_limit: int) -> None:
        self.event_limit = event_limit
        self.buffer = bytearray()
        self.data_line: bytes | None = None

    def feed(self, chunk: bytes) -> list[bytes]:
        self.buffer.extend(chunk)
        if len(self.buffer) > self.event_limit and b"\n" not in self.buffer:
            raise ProtocolViolation("event_too_large", "SSE event exceeds its configured size limit")
        events: list[bytes] = []
        while b"\n" in self.buffer:
            line, _, remainder = self.buffer.partition(b"\n")
            self.buffer = bytearray(remainder)
            line = line.rstrip(b"\r")
            if not line:
                if self.data_line is not None:
                    events.append(self.data_line)
                    self.data_line = None
                continue
            if line.startswith(b":"):
                continue
            if line.startswith(b"data:"):
                if self.data_line is not None:
                    raise ProtocolViolation("multiline_sse_data", "multiline SSE data is not supported")
                value = bytes(line[5:].lstrip(b" "))
                if len(value) > self.event_limit:
                    raise ProtocolViolation("event_too_large", "SSE event exceeds its configured size limit")
                self.data_line = value
        return events

    def finish(self) -> list[bytes]:
        events = self.feed(b"\n\n")
        if self.buffer.strip() or self.data_line is not None:
            raise ProtocolViolation("incomplete_sse_event", "stream ended with an incomplete SSE event")
        return events


async def _read_bounded(response: RuntimeResponse, limit: int) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > limit:
            raise ProtocolViolation("response_too_large", "endpoint response exceeds its configured size limit")
    return bytes(body)


class IntegrationGateway:
    """Only runtime network client for contract-compatible workflow endpoints."""

    def __init__(
        self,
        *,
        credential_resolver: CredentialResolver,
        transport: RuntimeTransport | None = None,
        metrics: GatewayMetrics | None = None,
    ) -> None:
        self.credential_resolver = credential_resolver
        self.transport = transport or HttpxRuntimeTransport()
        self.metrics = metrics or GatewayMetrics()
        self._tracer = trace.get_tracer("dograh.langgraph.gateway")

    async def invoke_sync(
        self,
        snapshot: RuntimeEndpointSnapshot,
        request: BaseModel | dict[str, Any],
        *,
        trace_context: GatewayTraceContext,
    ) -> BaseModel:
        self._require_mode(snapshot, InvocationMode.SYNCHRONOUS)
        payload = self._serialize_invocation(snapshot, request)
        invocation_id = payload["invocation_id"]
        started = time.monotonic()
        response = await self._exchange(
            snapshot, "POST", "invoke", payload, trace_context=trace_context
        )
        try:
            body = await _read_bounded(response, snapshot.response_bytes)
            self._raise_http_error(response.status_code)
            return validate_synchronous_result(
                body,
                contract_version=snapshot.contract_version,
                invocation_id=invocation_id,
                response_bytes_limit=snapshot.response_bytes,
            )
        finally:
            await response.aclose()
            self._timing(snapshot, "completion_latency", started)

    async def start_async(
        self,
        snapshot: RuntimeEndpointSnapshot,
        request: BaseModel | dict[str, Any],
        *,
        trace_context: GatewayTraceContext,
    ) -> BaseModel:
        self._require_mode(snapshot, InvocationMode.ASYNCHRONOUS)
        payload = self._serialize_invocation(snapshot, request)
        response = await self._exchange(
            snapshot, "POST", "invoke", payload, trace_context=trace_context
        )
        try:
            body = await _read_bounded(response, snapshot.response_bytes)
            self._raise_http_error(response.status_code)
            return validate_asynchronous_acceptance(
                body,
                contract_version=snapshot.contract_version,
                invocation_id=payload["invocation_id"],
                response_bytes_limit=snapshot.response_bytes,
            )
        finally:
            await response.aclose()

    async def invoke_stream(
        self,
        snapshot: RuntimeEndpointSnapshot,
        request: BaseModel | dict[str, Any],
        *,
        ledger: AcceptedEventLedger,
        cancellation: CancellationState,
        trace_context: GatewayTraceContext,
    ) -> AsyncIterator[AcceptedRuntimeEvent]:
        self._require_mode(snapshot, InvocationMode.STREAMING)
        payload = self._serialize_invocation(snapshot, request)
        invocation_id = payload["invocation_id"]
        response = await self._exchange(
            snapshot,
            "POST",
            "invoke",
            payload,
            trace_context=trace_context,
            accept="text/event-stream",
        )
        parser = _SSEParser(snapshot.event_bytes)
        reducer = RuntimeEventReducer(
            contract_version=snapshot.contract_version,
            invocation_id=invocation_id,
            ledger=ledger,
            event_bytes_limit=snapshot.event_bytes,
            tool_argument_bytes_limit=snapshot.tool_argument_bytes,
            stateful_profile=snapshot.stateful_profile,
            interrupts_selected=snapshot.interrupts_selected,
        )
        started = time.monotonic()
        first_effect = True
        try:
            self._raise_http_error(response.status_code)
            media_type = response.headers.get("content-type", "").lower()
            if "text/event-stream" not in media_type:
                raise ProtocolViolation("invalid_content_type", "streaming invocation did not return SSE")
            async for chunk in response.aiter_bytes():
                for data in parser.feed(chunk):
                    reduced = await reducer.reduce(data)
                    if not cancellation.forwarding_allowed():
                        continue
                    if first_effect and (reduced.speakable_text or reduced.tool_call):
                        self._timing(snapshot, "first_event_latency", started)
                        first_effect = False
                    if reduced.disposition == "accepted":
                        yield reduced
            for data in parser.finish():
                reduced = await reducer.reduce(data)
                if cancellation.forwarding_allowed() and reduced.disposition == "accepted":
                    yield reduced
            if reducer.terminal_sequence is None:
                raise ProtocolViolation("missing_terminal", "stream ended before one terminal event")
        finally:
            await response.aclose()
            self._timing(snapshot, "completion_latency", started)

    async def await_async(
        self,
        snapshot: RuntimeEndpointSnapshot,
        acceptance: BaseModel,
        *,
        deadline_seconds: float,
        poll_interval_seconds: float = 0.05,
        trace_context: GatewayTraceContext,
        cancellation: CancellationState | None = None,
    ) -> BaseModel:
        deadline = time.monotonic() + deadline_seconds
        while time.monotonic() < deadline:
            if cancellation is not None and not cancellation.forwarding_allowed():
                raise ProtocolViolation("cancelled", "asynchronous invocation was cancelled")
            url_values = {"external_run_id": acceptance.external_run_id}
            response = await self._exchange(
                snapshot,
                "GET",
                "status",
                None,
                trace_context=trace_context,
                operation_identifiers=url_values,
            )
            try:
                body = await _read_bounded(response, snapshot.response_bytes)
                self._raise_http_error(response.status_code)
                status = validate_status_result(
                    body,
                    contract_version=snapshot.contract_version,
                    invocation_id=acceptance.invocation_id,
                    external_run_id=acceptance.external_run_id,
                    response_bytes_limit=snapshot.response_bytes,
                )
            finally:
                await response.aclose()
            if status.status != "running":
                return status
            await asyncio.sleep(min(poll_interval_seconds, max(0.0, deadline - time.monotonic())))
        if snapshot.cancellation_declared:
            await self.cancel(
                snapshot,
                invocation_id=acceptance.invocation_id,
                reason="deadline",
                trace_context=trace_context,
            )
        operations = asynchronous_deadline_outcome(
            cancellation_declared=snapshot.cancellation_declared
        ).operations
        raise ProtocolViolation("async_deadline", "asynchronous deadline reached: " + ",".join(operations))

    async def cancel(
        self,
        snapshot: RuntimeEndpointSnapshot,
        *,
        invocation_id: str,
        reason: str,
        trace_context: GatewayTraceContext,
    ) -> BaseModel | None:
        if not snapshot.cancellation_declared:
            return None
        model_type = schema_for(snapshot.contract_version, "cancellation_request")
        payload = model_type.model_validate(
            {
                "contract_version": snapshot.contract_version,
                "operation": "cancel",
                "invocation_id": invocation_id,
                "reason": reason,
            }
        ).model_dump(mode="json", exclude_none=True)
        started = time.monotonic()
        response = await self._exchange(
            snapshot,
            "POST",
            "cancel",
            payload,
            trace_context=trace_context,
            operation_identifiers={"invocation_id": invocation_id},
        )
        try:
            body = await _read_bounded(response, snapshot.response_bytes)
            self._raise_http_error(response.status_code)
            result = schema_for(snapshot.contract_version, "cancellation_response").model_validate_json(body)
            if result.invocation_id != invocation_id:
                raise ProtocolViolation("invocation_mismatch", "cancellation response belongs to another invocation")
            return result
        finally:
            await response.aclose()
            self._timing(snapshot, "cancellation_dispatch_latency", started)

    async def _exchange(
        self,
        snapshot: RuntimeEndpointSnapshot,
        method: str,
        operation: str,
        payload: dict[str, Any] | None,
        *,
        trace_context: GatewayTraceContext,
        operation_identifiers: Mapping[str, str] | None = None,
        accept: str = "application/json",
    ) -> RuntimeResponse:
        if trace_context.organization_id != snapshot.organization_id:
            raise PermissionError("trace and endpoint organization scopes differ")
        content = None
        if payload is not None:
            content = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            if len(content) > snapshot.request_bytes:
                raise ProtocolViolation("request_too_large", "request exceeds its configured size limit")
        auth = await self.credential_resolver.resolve_headers(
            organization_id=snapshot.organization_id,
            credential_reference=snapshot.credential_reference,
        )
        headers = {
            **dict(auth),
            "accept": accept,
            "content-type": "application/json",
            "traceparent": trace_context.traceparent,
        }
        current = snapshot.operation_url(operation, **dict(operation_identifiers or {}))
        allow_private = snapshot.private_network_enabled

        def approve_connection(address: str) -> None:
            try:
                validate_connection_destination(
                    address, allow_self_hosted_private_network=allow_private
                )
            except ValueError as exc:
                raise UnsafeDestinationError(str(exc)) from exc

        parent_context = build_remote_parent_context(trace_context.trace_id)
        with self._tracer.start_as_current_span(
            f"langgraph.{operation}", context=parent_context
        ) as span:
            for key, value in trace_context.span_attributes(operation).items():
                span.set_attribute(key, value)
            for hop in range(MAX_REDIRECTS + 1):
                try:
                    if hop == 0:
                        validate_initial_destination(
                            current, allow_self_hosted_private_network=allow_private
                        )
                    else:
                        validate_redirect_destination(
                            current, allow_self_hosted_private_network=allow_private
                        )
                except ValueError as exc:
                    raise UnsafeDestinationError(str(exc)) from exc
                response, _ = await self.transport.request(
                    method,
                    current,
                    headers=headers,
                    content=content,
                    timeout=300.0,
                    validate_connection=approve_connection,
                )
                if not response.is_redirect:
                    self.metrics.increment(
                        operation=operation,
                        registration_id=snapshot.registration_id,
                        contract_version=snapshot.contract_version,
                    )
                    return response
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    raise ProtocolViolation("invalid_redirect", "redirect omitted location")
                if hop == MAX_REDIRECTS:
                    raise ProtocolViolation("too_many_redirects", "endpoint exceeded redirect limit")
                current = urljoin(current, location)
        raise ProtocolViolation("redirect_state", "unreachable redirect state")

    @staticmethod
    def _serialize_invocation(
        snapshot: RuntimeEndpointSnapshot, request: BaseModel | dict[str, Any]
    ) -> dict[str, Any]:
        payload = request.model_dump(mode="json") if isinstance(request, BaseModel) else dict(request)
        return serialize_pinned_request(
            pinned_version=snapshot.contract_version, payload=payload
        )

    @staticmethod
    def _require_mode(snapshot: RuntimeEndpointSnapshot, mode: InvocationMode) -> None:
        if mode not in snapshot.invocation_modes:
            raise ProtocolViolation("mode_not_selected", f"{mode.value} invocation mode was not selected")

    @staticmethod
    def _raise_http_error(status_code: int) -> None:
        if status_code < 400:
            return
        mapping = {
            401: ("authentication", "endpoint_authentication"),
            403: ("authorization", "endpoint_authorization"),
            408: ("timeout", "http_408"),
            429: ("rate_limited", "http_429"),
            502: ("overloaded", "http_502"),
            503: ("overloaded", "http_503"),
            504: ("timeout", "http_504"),
        }
        category, code = mapping.get(status_code, ("invalid_response", f"http_{status_code}"))
        from api.schemas.langgraph_integration.common import ErrorCategory

        raise ProtocolViolation(code, "endpoint request failed", category=ErrorCategory(category))

    def _timing(self, snapshot: RuntimeEndpointSnapshot, metric: str, started: float) -> None:
        self.metrics.timing(
            metric=metric,
            registration_id=snapshot.registration_id,
            contract_version=snapshot.contract_version,
            milliseconds=(time.monotonic() - started) * 1000,
        )
