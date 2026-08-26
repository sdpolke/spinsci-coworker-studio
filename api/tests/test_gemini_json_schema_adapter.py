from unittest.mock import patch

from google.genai.types import GenerateContentConfig, LiveConnectConfig
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.adapters.services.gemini_live_adapter import GeminiLiveLLMAdapter

from api.services.configuration.registry import ServiceProviders
from api.services.pipecat.gemini_json_schema_adapter import (
    SpinSciGeminiJSONSchemaAdapter,
    SpinSciGeminiLiveJSONSchemaAdapter,
)
from api.services.pipecat.realtime.gemini_live import SpinSciGeminiLiveLLMService
from api.services.pipecat.realtime.gemini_live_vertex import (
    SpinSciGeminiLiveVertexLLMService,
)
from api.services.pipecat.service_factory import (
    SpinSciGoogleLLMService,
    SpinSciGoogleVertexLLMService,
    create_llm_service_from_provider,
)


def test_gemini_tools_use_json_schema_parameters_for_external_schemas():
    function_schema = FunctionSchema(
        name="customer_lookup",
        description="Look up a customer by email.",
        properties={
            "customerEmail": {
                "description": "Customer email address",
                "anyOf": [
                    {"anyOf": [{"not": {}}]},
                    {"const": ""},
                ],
            },
            "metadata": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
        },
        required=["customerEmail"],
    )

    tools = SpinSciGeminiJSONSchemaAdapter().to_provider_tools_format(
        ToolsSchema(standard_tools=[function_schema])
    )

    declaration = tools[0]["function_declarations"][0]
    assert "parameters" not in declaration
    assert (
        declaration["parameters_json_schema"]["properties"]["customerEmail"]["anyOf"][
            0
        ]["anyOf"][0]["not"]
        == {}
    )
    assert (
        declaration["parameters_json_schema"]["properties"]["customerEmail"]["anyOf"][
            1
        ]["const"]
        == ""
    )
    assert declaration["parameters_json_schema"]["properties"]["metadata"][
        "additionalProperties"
    ] == {"type": "string"}

    GenerateContentConfig(tools=tools)


def test_gemini_tools_use_json_schema_parameters_for_no_argument_tools():
    function_schema = FunctionSchema(
        name="refresh_context",
        description="Refresh the current context.",
        properties={},
        required=[],
    )

    tools = SpinSciGeminiJSONSchemaAdapter().to_provider_tools_format(
        ToolsSchema(standard_tools=[function_schema])
    )

    declaration = tools[0]["function_declarations"][0]
    assert "parameters" not in declaration
    assert declaration["parameters_json_schema"] == {
        "type": "object",
        "properties": {},
        "required": [],
    }

    GenerateContentConfig(tools=tools)


def test_google_service_classes_use_spinsci_gemini_adapter_class():
    assert SpinSciGoogleLLMService.adapter_class is SpinSciGeminiJSONSchemaAdapter
    assert SpinSciGoogleVertexLLMService.adapter_class is SpinSciGeminiJSONSchemaAdapter


def test_google_llm_service_factory_uses_spinsci_service_class():
    with patch(
        "api.services.pipecat.service_factory.SpinSciGoogleLLMService",
    ) as mock_service:
        result = create_llm_service_from_provider(
            provider=ServiceProviders.GOOGLE.value,
            model="gemini-3.5-flash",
            api_key="test-api-key",
        )

    assert result is mock_service.return_value
    assert mock_service.call_args.kwargs["api_key"] == "test-api-key"
    assert mock_service.call_args.kwargs["settings"].model == "gemini-3.5-flash"


def test_google_vertex_llm_service_factory_uses_spinsci_service_class():
    with patch(
        "api.services.pipecat.service_factory.SpinSciGoogleVertexLLMService",
    ) as mock_service:
        result = create_llm_service_from_provider(
            provider=ServiceProviders.GOOGLE_VERTEX.value,
            model="gemini-2.5-pro",
            api_key=None,
            project_id="demo-project",
            location="us-central1",
            credentials='{"type":"service_account"}',
        )

    assert result is mock_service.return_value
    assert mock_service.call_args.kwargs["project_id"] == "demo-project"
    assert mock_service.call_args.kwargs["location"] == "us-central1"
    assert mock_service.call_args.kwargs["settings"].model == "gemini-2.5-pro"


def test_gemini_live_service_classes_use_spinsci_gemini_adapter_class():
    assert SpinSciGeminiLiveLLMService.adapter_class is SpinSciGeminiLiveJSONSchemaAdapter
    # Vertex Live inherits adapter_class from SpinSciGeminiLiveLLMService via MRO.
    assert (
        SpinSciGeminiLiveVertexLLMService.adapter_class
        is SpinSciGeminiLiveJSONSchemaAdapter
    )
    # The Live adapter must keep upstream's tool-call-to-text conversion for
    # seeded contexts (GeminiLiveLLMAdapter) alongside the JSON Schema fix.
    assert issubclass(SpinSciGeminiLiveJSONSchemaAdapter, GeminiLiveLLMAdapter)
    assert issubclass(SpinSciGeminiLiveJSONSchemaAdapter, SpinSciGeminiJSONSchemaAdapter)
    assert (
        SpinSciGeminiLiveJSONSchemaAdapter.to_provider_tools_format
        is SpinSciGeminiJSONSchemaAdapter.to_provider_tools_format
    )


def test_vertex_live_inherits_spinsci_node_transition_lifecycle():
    assert (
        SpinSciGeminiLiveVertexLLMService._requires_node_transition_context_aggregation
        is SpinSciGeminiLiveLLMService._requires_node_transition_context_aggregation
    )
    assert (
        SpinSciGeminiLiveVertexLLMService._run_or_defer_function_calls
        is SpinSciGeminiLiveLLMService._run_or_defer_function_calls
    )
    assert (
        SpinSciGeminiLiveVertexLLMService._reconnect_for_node_transition
        is SpinSciGeminiLiveLLMService._reconnect_for_node_transition
    )


def test_gemini_live_config_accepts_json_schema_tools():
    function_schema = FunctionSchema(
        name="customer_lookup",
        description="Look up a customer by email.",
        properties={
            "customerEmail": {
                "description": "Customer email address",
                "anyOf": [{"not": {}}, {"const": ""}],
            },
        },
        required=["customerEmail"],
    )

    tools = SpinSciGeminiJSONSchemaAdapter().to_provider_tools_format(
        ToolsSchema(standard_tools=[function_schema])
    )

    declaration = tools[0]["function_declarations"][0]
    assert "parameters" not in declaration
    assert "parameters_json_schema" in declaration

    # Gemini Live validates tools through LiveConnectConfig rather than
    # GenerateContentConfig; it must also accept the raw JSON Schema payload.
    LiveConnectConfig(tools=tools)
