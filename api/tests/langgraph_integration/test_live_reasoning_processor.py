import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pipecat.frames.frames import (
    CancelFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from api.schemas.workflow_configurations import LangGraphEndpointBinding
from api.services.langgraph_integration.configuration import (
    LangGraphFeatureConfiguration,
)
from api.services.langgraph_integration.endpoint_registration import (
    FeatureDisabledError,
)
from api.services.langgraph_integration.gateway import (
    GatewayMetrics,
    RuntimeEndpointSnapshot,
)
from api.services.langgraph_integration.protocol import (
    AcceptedRuntimeEvent,
    ReductionDisposition,
)
from api.services.pipecat.langgraph_reasoning_processor import (
    LangGraphReasoningProcessor,
)
from api.services.pipecat.run_pipeline import (
    _create_non_realtime_reasoner,
    _resolve_live_langgraph_binding,
)
from api.services.workflow.langgraph_adapter import (
    DataSharingPolicy,
    PinnedReasoningState,
)
from api.services.workflow.pipecat_engine import PipecatEngine
from api.services.workflow.reasoning import ReasoningMessage


def _binding() -> LangGraphEndpointBinding:
    return LangGraphEndpointBinding(
        registration_uuid="registration-1",
        validation_report_uuid="report-1",
        validation_report_digest="report-digest",
        contract_version="1.1",
        compatibility_profile="chat",
        state_mode="mural_authoritative",
        live_invocation_mode="streaming",
        selected_capabilities=["streaming"],
        capability_snapshot_uuid="snapshot-1",
        capability_snapshot_digest="snapshot-digest",
        capability_snapshot={},
        data_sharing_policy={"context_fields": ["locale"]},
        data_region="us-east",
        first_event_deadline_ms=1500,
        first_event_action="fallback_message",
        terminal_failure_action="transfer",
        evidence={
            "text_session_conformance": True,
            "accepted_transition": True,
            "cancellation_verified": True,
            "recording_verified": True,
        },
        endpoint_url="https://agent.example.com",
        credential_reference="credential-1",
        operations={"invoke": "/v1/invocations"},
        limits={},
    )


def _snapshot(*, cancellation_declared: bool = False) -> RuntimeEndpointSnapshot:
    operations = {"invoke": "/v1/invocations"}
    if cancellation_declared:
        operations["cancel"] = "/v1/invocations/{invocation_id}/cancel"
    return RuntimeEndpointSnapshot(
        organization_id=7,
        registration_id="registration-1",
        endpoint_url="https://agent.example.com",
        credential_reference="credential-1",
        contract_version="1.1",
        invocation_modes=frozenset({"streaming"}),
        operations=operations,
        request_bytes=1_048_576,
        response_bytes=2_097_152,
        event_bytes=65_536,
        tool_argument_bytes=262_144,
        cancellation_declared=cancellation_declared,
    )


class _Gateway:
    def __init__(self):
        self.requests = []
        self.metrics = GatewayMetrics()

    async def invoke_stream(self, snapshot, request, **kwargs):
        self.requests.append((snapshot, request, kwargs))
        yield AcceptedRuntimeEvent(
            event=SimpleNamespace(),
            disposition=ReductionDisposition.ACCEPTED,
            speakable_text="Hello ",
        )
        yield AcceptedRuntimeEvent(
            event=SimpleNamespace(),
            disposition=ReductionDisposition.ACCEPTED,
            speakable_text="there.",
        )


@pytest.mark.asyncio
async def test_remote_reasoner_emits_standard_pipecat_text_frames_only():
    gateway = _Gateway()
    state = PinnedReasoningState(
        organization_id=7,
        voice_run_id="42",
        workflow_version_id="9",
        registration_id="registration-1",
        contract_version="1.1",
        active_node_id="agent",
        node_prompt="Help the caller",
        history=(ReasoningMessage("user", "Hello"),),
        tools=(),
        context={"locale": "en-US", "raw_audio": b"never-send"},
    )
    processor = LangGraphReasoningProcessor(
        endpoint_snapshot=_snapshot(),
        gateway=gateway,
        state_factory=lambda _context: state,
        sharing_policy=DataSharingPolicy(context_fields=frozenset({"locale"})),
    )
    pushed = []
    processor.push_frame = AsyncMock(side_effect=lambda frame, *_args: pushed.append(frame))
    processor.start_processing_metrics = AsyncMock()
    processor.stop_processing_metrics = AsyncMock()
    processor.start_ttfb_metrics = AsyncMock()
    processor.stop_ttfb_metrics = AsyncMock()

    await processor._process_context(LLMContext())

    assert isinstance(pushed[0], LLMFullResponseStartFrame)
    assert [frame.text for frame in pushed if isinstance(frame, LLMTextFrame)] == [
        "Hello ",
        "there.",
    ]
    assert isinstance(pushed[-1], LLMFullResponseEndFrame)
    request = gateway.requests[0][1]
    assert request["context"] == {"locale": "en-US"}
    assert "raw_audio" not in repr(request)


class _CancellableGateway:
    def __init__(self):
        self.metrics = GatewayMetrics()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancellations: list[tuple[str, str, float]] = []

    async def invoke_stream(self, snapshot, request, **kwargs):
        self.cancellation_state = kwargs["cancellation"]
        yield AcceptedRuntimeEvent(
            event=SimpleNamespace(),
            disposition=ReductionDisposition.ACCEPTED,
            speakable_text="before cancellation",
        )
        self.started.set()
        await self.release.wait()
        yield AcceptedRuntimeEvent(
            event=SimpleNamespace(),
            disposition=ReductionDisposition.ACCEPTED,
            speakable_text="late duplicate speech",
        )

    async def cancel(self, snapshot, *, invocation_id, reason, trace_context):
        self.cancellations.append((invocation_id, reason, time.monotonic()))
        self.release.set()
        return SimpleNamespace(status="cancelled")


def _reasoning_state() -> PinnedReasoningState:
    return PinnedReasoningState(
        organization_id=7,
        voice_run_id="42",
        workflow_version_id="9",
        registration_id="registration-1",
        contract_version="1.1",
        active_node_id="agent",
        node_prompt="Help the caller",
        history=(ReasoningMessage("user", "Hello"),),
        tools=(),
        context={},
    )


def _cancellable_processor(gateway: _CancellableGateway):
    processor = LangGraphReasoningProcessor(
        endpoint_snapshot=_snapshot(cancellation_declared=True),
        gateway=gateway,
        state_factory=lambda _context: _reasoning_state(),
    )
    pushed = []
    processor.push_frame = AsyncMock(side_effect=lambda frame, *_args: pushed.append(frame))
    processor.start_processing_metrics = AsyncMock()
    processor.stop_processing_metrics = AsyncMock()
    processor.start_ttfb_metrics = AsyncMock()
    processor.stop_ttfb_metrics = AsyncMock()
    return processor, pushed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("frame", "reason"),
    [
        (InterruptionFrame(), "caller_barge_in"),
        (CancelFrame(reason="user_hangup"), "hangup"),
        (CancelFrame(reason="worker_shutdown"), "platform_shutdown"),
    ],
)
async def test_pipecat_signals_cancel_once_and_suppress_late_speech(frame, reason):
    gateway = _CancellableGateway()
    processor, pushed = _cancellable_processor(gateway)
    if isinstance(frame, InterruptionFrame):
        processor._start_interruption = AsyncMock()

    invocation = asyncio.create_task(processor._process_context(LLMContext()))
    await asyncio.wait_for(gateway.started.wait(), timeout=1)
    accepted_at = time.monotonic()

    await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
    await asyncio.wait_for(invocation, timeout=1)

    assert [item[1] for item in gateway.cancellations] == [reason]
    assert gateway.cancellations[0][2] - accepted_at < 0.25
    assert gateway.cancellation_state.reason == reason
    assert [item.text for item in pushed if isinstance(item, LLMTextFrame)] == [
        "before cancellation"
    ]
    assert sum(isinstance(item, LLMFullResponseEndFrame) for item in pushed) == 1
    assert frame in pushed
    suppression = gateway.metrics.timings_ms[
        ("cancellation_suppression_latency", "registration-1", "1.1")
    ]
    assert len(suppression) == 1
    assert suppression[0] < 250


@pytest.mark.asyncio
async def test_cancellation_race_dispatches_once_and_keeps_terminal_state():
    gateway = _CancellableGateway()
    processor, pushed = _cancellable_processor(gateway)
    invocation = asyncio.create_task(processor._process_context(LLMContext()))
    await asyncio.wait_for(gateway.started.wait(), timeout=1)

    results = await asyncio.gather(
        processor.cancel_active_invocation("caller_barge_in"),
        processor.cancel_active_invocation("platform_shutdown"),
    )
    await asyncio.wait_for(invocation, timeout=1)

    assert sorted(results) == [False, True]
    assert len(gateway.cancellations) == 1
    assert sum(isinstance(item, LLMFullResponseStartFrame) for item in pushed) == 1
    assert sum(isinstance(item, LLMFullResponseEndFrame) for item in pushed) == 1


@pytest.mark.asyncio
async def test_processor_cleanup_cancels_active_invocation_as_shutdown():
    gateway = _CancellableGateway()
    processor, _pushed = _cancellable_processor(gateway)
    invocation = asyncio.create_task(processor._process_context(LLMContext()))
    await asyncio.wait_for(gateway.started.wait(), timeout=1)

    await processor.cleanup()
    await asyncio.wait_for(invocation, timeout=1)

    assert [item[1] for item in gateway.cancellations] == ["platform_shutdown"]


@pytest.mark.asyncio
async def test_node_change_cancels_remote_invocation_before_switch(simple_workflow):
    llm = SimpleNamespace(cancel_active_invocation=AsyncMock(return_value=True))
    engine = PipecatEngine(
        llm=llm,
        context=LLMContext(),
        workflow=simple_workflow,
        call_context_vars={},
    )
    start = simple_workflow.nodes[simple_workflow.start_node_id]
    target = next(node for node in simple_workflow.nodes.values() if node.id != start.id)
    engine._current_node = start
    engine._handle_start_node = AsyncMock()
    engine._handle_agent_node = AsyncMock()
    engine._handle_end_node = AsyncMock()

    await engine.set_node(target.id)

    llm.cancel_active_invocation.assert_awaited_once_with("node_change")
    assert engine._current_node.id == target.id


def test_non_endpoint_reasoner_never_instantiates_gateway(monkeypatch):
    local_llm = object()
    local_factory = Mock(return_value=local_llm)
    remote_factory = Mock()
    monkeypatch.setattr(
        "api.services.pipecat.run_pipeline.create_llm_service", local_factory
    )
    monkeypatch.setattr(
        "api.services.pipecat.run_pipeline.create_langgraph_reasoning_processor",
        remote_factory,
    )

    reasoner, inference_llm = _create_non_realtime_reasoner(
        binding=None,
        user_config=object(),
        correlation_id=None,
        organization_id=7,
        state_factory=Mock(),
    )

    assert reasoner is local_llm
    assert inference_llm is None
    remote_factory.assert_not_called()


def test_pinned_endpoint_reasoner_uses_remote_processor(monkeypatch):
    remote_llm = object()
    remote_factory = Mock(return_value=remote_llm)
    monkeypatch.setattr(
        "api.services.pipecat.run_pipeline.create_llm_service", Mock(return_value=object())
    )
    monkeypatch.setattr(
        "api.services.pipecat.run_pipeline.create_langgraph_reasoning_processor",
        remote_factory,
    )

    reasoner, inference_llm = _create_non_realtime_reasoner(
        binding=_binding(),
        user_config=object(),
        correlation_id="correlation",
        organization_id=7,
        state_factory=Mock(),
    )

    assert reasoner is remote_llm
    assert inference_llm is not None
    remote_factory.assert_called_once()


@pytest.mark.asyncio
async def test_feature_disabled_binding_fails_before_reasoner_creation(monkeypatch):
    monkeypatch.setattr(
        "api.services.langgraph_integration.configuration.get_langgraph_feature_configuration",
        AsyncMock(return_value=LangGraphFeatureConfiguration(enabled=False)),
    )

    with pytest.raises(FeatureDisabledError):
        await _resolve_live_langgraph_binding(
            run_configs={"langgraph_endpoint": _binding().model_dump(mode="json")},
            organization_id=7,
            is_realtime=False,
        )


@pytest.mark.asyncio
async def test_non_endpoint_binding_skips_feature_lookup(monkeypatch):
    feature_lookup = AsyncMock()
    monkeypatch.setattr(
        "api.services.langgraph_integration.configuration.get_langgraph_feature_configuration",
        feature_lookup,
    )

    binding = await _resolve_live_langgraph_binding(
        run_configs={}, organization_id=7, is_realtime=False
    )

    assert binding is None
    feature_lookup.assert_not_awaited()
