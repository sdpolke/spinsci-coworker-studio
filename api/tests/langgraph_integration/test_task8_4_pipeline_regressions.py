from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pipecat.frames.frames import (
    LLMFullResponseEndFrame,
    LLMTextFrame,
    TTSAudioRawFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from api.services.langgraph_integration.conformance import (
    FIXTURES_BY_ID,
    ScriptedEndpointSimulator,
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
from api.services.pipecat.pipeline_builder import build_pipeline, build_realtime_pipeline
from api.services.workflow.langgraph_adapter import PinnedReasoningState
from api.services.workflow.langgraph_binding import parse_langgraph_binding
from api.services.workflow.reasoning import ReasoningMessage
from api.services.workflow_run_artifacts import upload_workflow_run_artifacts


class _PassThrough(FrameProcessor):
    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


class _Transport:
    def __init__(self):
        self.input_processor = _PassThrough()
        self.output_processor = _PassThrough()

    def input(self):
        return self.input_processor

    def output(self):
        return self.output_processor


class _VoicemailDetector:
    def __init__(self):
        self.detector_processor = _PassThrough()
        self.gate_processor = _PassThrough()

    def detector(self):
        return self.detector_processor

    def llm_gate(self):
        return self.gate_processor


def _pipeline_processors(pipeline) -> list[FrameProcessor]:
    # Pipecat wraps every declared processor with an internal source and sink.
    return list(pipeline._processors[1:-1])


def test_non_endpoint_standard_voice_pipeline_preserves_owned_processor_order():
    """The remote integration must not alter the approved local voice baseline."""
    transport = _Transport()
    stt = _PassThrough()
    audio_buffer = _PassThrough()
    local_llm = _PassThrough()
    callback = _PassThrough()
    recording_router = _PassThrough()
    tts = _PassThrough()
    user_aggregator = _PassThrough()
    assistant_aggregator = _PassThrough()
    metrics = _PassThrough()
    voicemail = _VoicemailDetector()

    pipeline = build_pipeline(
        transport,
        stt,
        audio_buffer,
        local_llm,
        tts,
        user_aggregator,
        assistant_aggregator,
        callback,
        metrics,
        voicemail_detector=voicemail,
        recording_router=recording_router,
    )

    assert parse_langgraph_binding({}) is None
    assert _pipeline_processors(pipeline) == [
        transport.input_processor,
        stt,
        voicemail.detector_processor,
        user_aggregator,
        voicemail.gate_processor,
        local_llm,
        callback,
        recording_router,
        tts,
        transport.output_processor,
        audio_buffer,
        assistant_aggregator,
        metrics,
    ]


def test_non_endpoint_webrtc_realtime_pipeline_preserves_media_ownership():
    """Realtime WebRTC remains STS-owned and never gains a gateway processor."""
    transport = _Transport()
    user_aggregator = _PassThrough()
    realtime_llm = _PassThrough()
    callback = _PassThrough()
    output_audio_buffer = _PassThrough()
    assistant_aggregator = _PassThrough()
    metrics = _PassThrough()
    voicemail = _VoicemailDetector()

    pipeline = build_realtime_pipeline(
        transport,
        realtime_llm,
        output_audio_buffer,
        user_aggregator,
        assistant_aggregator,
        callback,
        metrics,
        voicemail_detector=voicemail,
    )

    assert _pipeline_processors(pipeline) == [
        transport.input_processor,
        user_aggregator,
        realtime_llm,
        voicemail.detector_processor,
        callback,
        transport.output_processor,
        output_audio_buffer,
        assistant_aggregator,
        metrics,
    ]
    assert not any(
        isinstance(processor, LangGraphReasoningProcessor)
        for processor in _pipeline_processors(pipeline)
    )


@pytest.mark.asyncio
async def test_recording_and_post_call_artifacts_keep_existing_persistence_contract(
    monkeypatch,
):
    uploads: list[tuple[str, bytes]] = []
    updates: list[dict] = []

    async def create_file(storage_key: str, data: bytes) -> bool:
        uploads.append((storage_key, data))
        return True

    monkeypatch.setattr(
        "api.services.workflow_run_artifacts.get_current_storage_backend",
        lambda: SimpleNamespace(name="TEST", value="test"),
    )
    monkeypatch.setattr(
        "api.services.workflow_run_artifacts.storage_fs.acreate_file_from_bytes",
        create_file,
    )
    monkeypatch.setattr(
        "api.services.workflow_run_artifacts.db_client.update_workflow_run",
        AsyncMock(side_effect=lambda **kwargs: updates.append(kwargs)),
    )

    await upload_workflow_run_artifacts(
        42,
        mixed_audio_wav=b"mixed-wav",
        user_audio_wav=b"user-wav",
        bot_audio_wav=b"bot-wav",
        transcript_text="user: hello\nassistant: hi",
    )

    assert [key for key, _data in uploads] == [
        "recordings/42.wav",
        "recordings/42/user.wav",
        "recordings/42/bot.wav",
        "transcripts/42.txt",
    ]
    assert uploads[-1][1] == b"user: hello\nassistant: hi"
    assert any(update.get("recording_url") == "recordings/42.wav" for update in updates)
    assert any(update.get("transcript_url") == "transcripts/42.txt" for update in updates)
    recordings = next(update["extra"]["recordings"] for update in updates if "extra" in update)
    assert set(recordings) == {"mixed", "user", "bot"}


class _LiveSmokeGateway:
    def __init__(self, events: list[str]):
        self.events = events
        self.metrics = GatewayMetrics()
        self.simulator = ScriptedEndpointSimulator(
            FIXTURES_BY_ID["chat.valid.fragmented_text"]
        )
        self.first_event_seen = asyncio.Event()
        self.release_after_cancel = asyncio.Event()
        self.cancel_reasons: list[str] = []

    async def invoke_stream(self, _snapshot, _request, **_kwargs):
        self.events.append("dispatch")
        for step in self.simulator.steps():
            event_type = step["type"]
            text = step["data"].get("text") if event_type == "text_delta" else None
            if not self.first_event_seen.is_set():
                self.events.append("first_accepted_event")
                self.first_event_seen.set()
            yield AcceptedRuntimeEvent(
                event=SimpleNamespace(**step),
                disposition=ReductionDisposition.ACCEPTED,
                speakable_text=text,
            )
            if step["sequence"] == 0:
                await self.release_after_cancel.wait()

    async def cancel(self, _snapshot, *, invocation_id, reason, trace_context):
        assert invocation_id
        assert trace_context.invocation_id == invocation_id
        self.cancel_reasons.append(reason)
        self.events.append("cancellation")
        self.release_after_cancel.set()
        return SimpleNamespace(status="cancelled")


def _smoke_snapshot() -> RuntimeEndpointSnapshot:
    return RuntimeEndpointSnapshot(
        organization_id=7,
        registration_id="registration-smoke",
        endpoint_url="https://agent.example.com",
        credential_reference="credential-smoke",
        contract_version="1.0",
        invocation_modes=frozenset({"streaming"}),
        operations={
            "invoke": "/v1/invocations",
            "cancel": "/v1/invocations/{invocation_id}/cancel",
        },
        request_bytes=1_048_576,
        response_bytes=2_097_152,
        event_bytes=65_536,
        tool_argument_bytes=262_144,
        cancellation_declared=True,
    )


def _smoke_state() -> PinnedReasoningState:
    return PinnedReasoningState(
        organization_id=7,
        voice_run_id="voice-run-smoke",
        workflow_version_id="workflow-version-smoke",
        registration_id="registration-smoke",
        contract_version="1.0",
        active_node_id="agent",
        node_prompt="Help the caller",
        history=(ReasoningMessage("user", "Hello"),),
        tools=(),
        context={},
    )


@pytest.mark.asyncio
async def test_simulator_backed_live_pipeline_smoke_records_causal_order(
    monkeypatch,
):
    """Exercise transcript -> endpoint -> TTS -> barge-in -> finalization order."""
    events = ["transcript_completion"]
    gateway = _LiveSmokeGateway(events)
    processor = LangGraphReasoningProcessor(
        endpoint_snapshot=_smoke_snapshot(),
        gateway=gateway,
        state_factory=lambda _context: _smoke_state(),
    )
    emitted_frames = []

    async def emit_frame(frame, *_args):
        emitted_frames.append(frame)
        if isinstance(frame, LLMTextFrame):
            # A deterministic TTS boundary: accepted text produces actual audio
            # before the caller barge-in is accepted.
            emitted_frames.append(
                TTSAudioRawFrame(audio=b"pcm", sample_rate=16_000, num_channels=1)
            )
            if "first_synthesized_audio" not in events:
                events.append("first_synthesized_audio")

    processor.push_frame = AsyncMock(side_effect=emit_frame)
    processor.start_processing_metrics = AsyncMock()
    processor.stop_processing_metrics = AsyncMock()
    processor.start_ttfb_metrics = AsyncMock()
    processor.stop_ttfb_metrics = AsyncMock()

    invocation = asyncio.create_task(processor._process_context(LLMContext()))
    await asyncio.wait_for(gateway.first_event_seen.wait(), timeout=1)
    while "first_synthesized_audio" not in events:
        await asyncio.sleep(0)

    assert await processor.cancel_active_invocation("caller_barge_in") is True
    await asyncio.wait_for(invocation, timeout=1)
    events.append("terminal_call_state")

    async def create_file(_storage_key: str, _data: bytes) -> bool:
        return True

    monkeypatch.setattr(
        "api.services.workflow_run_artifacts.get_current_storage_backend",
        lambda: SimpleNamespace(name="TEST", value="test"),
    )
    monkeypatch.setattr(
        "api.services.workflow_run_artifacts.storage_fs.acreate_file_from_bytes",
        create_file,
    )
    monkeypatch.setattr(
        "api.services.workflow_run_artifacts.db_client.update_workflow_run",
        AsyncMock(),
    )
    await upload_workflow_run_artifacts(
        42,
        bot_audio_wav=b"synthesized-audio",
        transcript_text="user: Hello\nassistant: Hello",
    )
    events.append("recording_finalization")

    assert events == [
        "transcript_completion",
        "dispatch",
        "first_accepted_event",
        "first_synthesized_audio",
        "cancellation",
        "terminal_call_state",
        "recording_finalization",
    ]
    assert gateway.cancel_reasons == ["caller_barge_in"]
    assert gateway.simulator.observe().terminal_outcome == {"status": "completed"}
    assert [frame.text for frame in emitted_frames if isinstance(frame, LLMTextFrame)] == [
        "Hello"
    ]
    assert sum(isinstance(frame, TTSAudioRawFrame) for frame in emitted_frames) == 1
    assert sum(isinstance(frame, LLMFullResponseEndFrame) for frame in emitted_frames) == 1
