from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pipecat.processors.aggregators.llm_context import LLMContext

from api.schemas.workflow_configurations import LangGraphEndpointBinding
from api.services.pipecat.langgraph_reasoning_processor import (
    LangGraphReasoningProcessor,
)
from api.services.pipecat.run_pipeline import (
    _create_pinned_non_conversational_reasoner,
)
from api.services.workflow.langgraph_adapter import (
    DataSharingPolicy,
    PinnedReasoningState,
)
from api.services.workflow.langgraph_binding import (
    LangGraphWorkflowBindingError,
    parse_langgraph_binding,
    validate_langgraph_runtime_path,
)
from api.services.workflow.reasoning import ReasoningMessage
from api.services.workflow.run_creation import prepare_workflow_run_inputs


def _binding(**changes) -> LangGraphEndpointBinding:
    values = {
        "registration_uuid": "registration-1",
        "validation_report_uuid": "report-1",
        "validation_report_digest": "report-digest",
        "contract_version": "1.1",
        "compatibility_profile": "chat",
        "state_mode": "mural_authoritative",
        "live_invocation_mode": "streaming",
        "non_conversational_modes": {},
        "selected_capabilities": ["streaming", "synchronous"],
        "capability_snapshot_uuid": "snapshot-1",
        "capability_snapshot_digest": "snapshot-digest",
        "capability_snapshot": {
            "features": {},
            "invocation_modes": ["streaming", "synchronous"],
        },
        "data_sharing_policy": {"context_fields": ["locale"]},
        "data_region": "us-east",
        "first_event_deadline_ms": 1500,
        "first_event_action": "fallback_message",
        "terminal_failure_action": "transfer",
        "evidence": {
            "text_session_conformance": True,
            "accepted_transition": True,
            "cancellation_verified": True,
            "recording_verified": True,
        },
        "endpoint_url": "https://agent.example.com",
        "credential_reference": "credential-1",
        "operations": {"invoke": "/v1/invocations"},
        "limits": {},
    }
    values.update(changes)
    return LangGraphEndpointBinding.model_validate(values)


@pytest.mark.parametrize("operation", ["amd", "variable_extraction"])
def test_explicitly_pinned_non_conversational_operation_uses_sync_endpoint(
    monkeypatch, operation
):
    remote = object()
    factory = Mock(return_value=remote)
    monkeypatch.setattr(
        "api.services.pipecat.run_pipeline.create_langgraph_reasoning_processor",
        factory,
    )

    result = _create_pinned_non_conversational_reasoner(
        operation=operation,
        binding=_binding(non_conversational_modes={operation: "synchronous"}),
        organization_id=7,
        state_factory=Mock(),
    )

    assert result is remote
    assert factory.call_args.kwargs["invocation_mode"] == "synchronous"


@pytest.mark.parametrize("operation", ["amd", "variable_extraction"])
def test_unpinned_non_conversational_operation_retains_provider_path(
    monkeypatch, operation
):
    factory = Mock()
    monkeypatch.setattr(
        "api.services.pipecat.run_pipeline.create_langgraph_reasoning_processor",
        factory,
    )

    result = _create_pinned_non_conversational_reasoner(
        operation=operation,
        binding=_binding(non_conversational_modes={}),
        organization_id=7,
        state_factory=Mock(),
    )

    assert result is None
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_synchronous_inference_sends_text_only_and_returns_assistant_text():
    gateway = SimpleNamespace(
        invoke_sync=AsyncMock(
            return_value=SimpleNamespace(
                result=SimpleNamespace(
                    type="assistant",
                    message=SimpleNamespace(
                        content=[SimpleNamespace(type="text", text='{"answer": true}')]
                    ),
                )
            )
        )
    )
    state = PinnedReasoningState(
        organization_id=7,
        voice_run_id="42",
        workflow_version_id="9",
        registration_id="registration-1",
        contract_version="1.1",
        active_node_id="agent",
        node_prompt="normal conversation prompt",
        history=(ReasoningMessage("user", "classify this"),),
        tools=(),
        context={"locale": "en-US", "raw_audio": b"never-send", "processor": object()},
    )
    snapshot = SimpleNamespace(
        organization_id=7,
        registration_id="registration-1",
    )
    processor = LangGraphReasoningProcessor(
        endpoint_snapshot=snapshot,
        gateway=gateway,
        state_factory=lambda _context: state,
        sharing_policy=DataSharingPolicy(context_fields=frozenset({"locale"})),
        invocation_mode="synchronous",
    )

    result = await processor.run_inference(
        LLMContext(), system_instruction="Return JSON only"
    )

    assert result == '{"answer": true}'
    request = gateway.invoke_sync.await_args.args[1]
    assert request["mode"] == "synchronous"
    assert request["context"] == {"locale": "en-US"}
    assert "raw_audio" not in repr(request)
    assert "processor" not in repr(request)


@pytest.mark.asyncio
async def test_realtime_endpoint_attachment_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "api.services.configuration.ai_model_configuration.get_effective_ai_model_configuration_for_workflow",
        AsyncMock(return_value=SimpleNamespace(is_realtime=True, realtime=object())),
    )

    with pytest.raises(LangGraphWorkflowBindingError, match="realtime speech-to-speech"):
        await validate_langgraph_runtime_path(
            workflow_configurations={
                "langgraph_endpoint": _binding().model_dump(mode="json")
            },
            organization_id=7,
        )


@pytest.mark.asyncio
async def test_realtime_endpoint_run_is_rejected_before_inputs_are_created(monkeypatch):
    monkeypatch.setattr(
        "api.services.configuration.ai_model_configuration.get_effective_ai_model_configuration_for_workflow",
        AsyncMock(return_value=SimpleNamespace(is_realtime=True, realtime=object())),
    )
    definition = SimpleNamespace(
        id=9,
        workflow_configurations={
            "langgraph_endpoint": _binding().model_dump(mode="json")
        },
    )
    workflow = SimpleNamespace(
        id=3,
        organization_id=7,
        released_definition=definition,
        current_definition=None,
    )

    with pytest.raises(LangGraphWorkflowBindingError, match="realtime speech-to-speech"):
        await prepare_workflow_run_inputs(SimpleNamespace(), workflow)


@pytest.mark.parametrize(
    "changes",
    [
        {"selected_capabilities": ["streaming", "direct_audio"]},
        {"data_sharing_policy": {"context_fields": ["raw_audio"]}},
        {"ownership": {"pipecat_processor": "endpoint"}},
    ],
)
def test_direct_media_or_processor_requests_are_rejected(changes):
    binding = _binding(**changes)

    with pytest.raises(LangGraphWorkflowBindingError, match="cannot request raw audio"):
        parse_langgraph_binding(
            {"langgraph_endpoint": binding.model_dump(mode="json")}
        )
