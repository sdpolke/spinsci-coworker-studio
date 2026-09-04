# Requirements Document

## Feature Metadata

- **Feature Name:** `langgraph-voice-integration`
- **Feature Type:** New feature
- **Selected Workflow:** Requirements-first
- **Initial Release Status:** Experimental and additive

## Introduction

This feature enables a Mural frontend workflow to use an externally supplied LangGraph chat agent as a voice conversation reasoning endpoint while preserving Mural's existing Pipecat voice pipeline. Mural continues to own speech recognition, speech synthesis, voice activity detection, endpointing, turn-taking, barge-in, telephony lifecycle, answering-machine detection, and recording. The external agent receives a versioned chat-oriented runtime contract and returns text, tool calls, run status, or declared interrupt information.

Compatibility is contract-based rather than framework-internal. The feature supports LangGraph deployments that expose the required endpoint operations, authentication behavior, message semantics, and latency characteristics. The feature does not promise compatibility with arbitrary Python objects, arbitrary LangGraph application code, undocumented custom APIs, media-native agents, or agents that cannot externalize the state and control signals required by a declared capability profile.

The first release is feature-flagged and experimental. Existing Mural agents, Pipecat processors, provider integrations, and published workflow runs remain unchanged unless an authorized user explicitly selects a validated LangGraph workflow endpoint for a new workflow version.

## Glossary

- **Mural_Platform**: The multi-tenant product containing the frontend workflow builder, FastAPI control plane, Pipecat runtime, data stores, and asynchronous workers.
- **Frontend_Workflow**: A versioned directed graph authored in Mural whose nodes contain prompts, tools, settings, and outgoing transition edges.
- **Workflow_Version**: An immutable published definition of a Frontend_Workflow that is pinned to each Voice_Run.
- **LangGraph_Workflow_Endpoint**: An externally deployed chat-agent service that implements a supported LangGraph_Workflow_Contract version.
- **LangGraph_Workflow_Contract**: The versioned request, response, authentication, capability, error, streaming, state, and lifecycle contract between Mural and a LangGraph_Workflow_Endpoint.
- **Capability_Manifest**: Machine-readable metadata that declares endpoint identity, contract versions, Invocation_Modes, State_Modes, interrupt support, cancellation support, health operations, and operational limits.
- **Compatibility_Profile**: A named, testable subset of LangGraph_Workflow_Contract capabilities that an endpoint must satisfy for a stated Mural use case.
- **Chat_Compatibility_Profile**: The baseline Compatibility_Profile that accepts ordered chat messages and supplied Tool_Definitions and returns assistant text or Tool_Calls.
- **Stateful_Run_Profile**: An optional Compatibility_Profile that externalizes LangGraph thread, run, checkpoint, interrupt, and cancellation semantics.
- **Compatibility_Matrix**: The versioned Mural record of supported contract versions, Compatibility_Profiles, Invocation_Modes, State_Modes, and limitations.
- **Supported_Endpoint**: A LangGraph_Workflow_Endpoint that passes every required test for at least Chat_Compatibility_Profile under a contract version listed in the current Compatibility_Matrix.
- **Unsupported_Agent**: An agent that requires in-process Python loading, direct object invocation, arbitrary undocumented payloads, direct audio access, or undeclared semantics outside the supported Compatibility_Profiles.
- **Endpoint_Registration**: The tenant-scoped Mural record containing endpoint URL, selected Compatibility_Profile, credential reference, declared capabilities, validation status, and lifecycle status.
- **Integration_Gateway**: The Mural backend component that validates, invokes, cancels, authenticates to, and observes LangGraph_Workflow_Endpoints.
- **Workflow_Adapter**: The runtime mapping between one Frontend_Workflow node invocation and one LangGraph_Workflow_Endpoint invocation.
- **Voice_Pipeline**: The existing Pipecat processing path that handles audio input, speech recognition, conversation timing, model invocation, speech synthesis, and audio output.
- **Voice_Run**: One Mural voice, WebRTC, or text conversation pinned to a Workflow_Version.
- **Voice_Run_ID**: The Mural-generated identifier for a Voice_Run and the primary correlation identifier within Mural.
- **Invocation_ID**: A unique Mural-generated identifier for one logical endpoint invocation, retained across eligible retry attempts.
- **Attempt_ID**: A unique identifier for one network attempt belonging to an Invocation_ID.
- **External_Run_ID**: An optional endpoint-generated identifier for a LangGraph execution.
- **Thread_ID**: An identifier used by a Stateful_Run_Profile endpoint to group related LangGraph state.
- **Checkpoint_Reference**: An opaque endpoint-issued reference to resumable LangGraph state.
- **Conversation_History**: The ordered system, user, assistant, Tool_Call, and Tool_Result messages accepted as authoritative for a Voice_Run.
- **State_Mode**: A declared ownership mode for conversation state: `Mural_authoritative` or `endpoint_checkpointed`.
- **Invocation_Mode**: A declared execution mode: `synchronous`, `streaming`, or `asynchronous`.
- **Tool_Definition**: A name, description, JSON input schema, ownership label, and authorization policy supplied for a Frontend_Workflow node.
- **Tool_Call**: A structured request from the endpoint to execute one supplied Tool_Definition.
- **Transition_Tool**: A Tool_Definition generated from an outgoing Frontend_Workflow edge and executed by Mural to change the active node.
- **Platform_Tool**: A Mural-managed tool, including knowledge retrieval, HTTP, MCP, transfer, and call-control tools.
- **Endpoint_Internal_Tool**: A tool executed entirely by the external endpoint and not represented as a Mural Tool_Call.
- **Tool_Result**: The structured result associated with a Tool_Call identifier.
- **Runtime_Event**: A versioned endpoint event carrying an Invocation_ID, sequence position, and text, Tool_Call fragment, usage, status, interrupt, completion, or error data.
- **Endpoint_Interrupt**: A declared pause from a Stateful_Run_Profile endpoint that requires input or approval before execution can continue.
- **Human_Review**: An authorized user decision that resumes, rejects, edits, or terminates an Endpoint_Interrupt.
- **Conformance_Suite**: Automated contract tests and simulators that determine Compatibility_Profile eligibility.
- **Validation_Report**: A versioned record of discovery, security, schema, behavior, latency, and Conformance_Suite results.
- **Experimental_Feature_Flag**: A tenant-scoped control that enables creation and execution of Endpoint_Registrations.
- **Trace_Context**: Correlation metadata containing Voice_Run_ID, Invocation_ID, Attempt_ID, Workflow_Version, endpoint registration identifier, and standards-compatible trace identifiers.
- **Sensitive_Data**: Credentials, personal data, call audio, transcripts, prompt content, tool arguments, tool results, and checkpoint data governed by access and retention policies.
- **Redaction_Policy**: A tenant-configurable policy that removes or masks selected Sensitive_Data fields before storage, logs, traces, or endpoint transmission.
- **Data_Sharing_Policy**: The Workflow_Version-pinned allowlist of runtime fields that Mural may transmit to a LangGraph_Workflow_Endpoint.
- **Conformance_Environment**: A documented test environment with fixed request fixtures, network conditions, and measurement procedures used to compare endpoint behavior.
- **Protocol_Error**: A structured integration error recorded when endpoint behavior violates the negotiated LangGraph_Workflow_Contract without authorizing Mural state progression.

## Requirements

### Requirement 1: Contract-Based Compatibility Boundaries

**User Story:** As a workflow author, I want explicit compatibility rules, so that I know which external LangGraph agents can become voice-enabled without relying on undocumented behavior.

#### Acceptance Criteria

1. WHEN a LangGraph_Workflow_Endpoint offers a contract version listed in the current Compatibility_Matrix and passes every required test for a selected Compatibility_Profile, THE Mural_Platform SHALL classify the endpoint as a Supported_Endpoint for that contract version and Compatibility_Profile.
2. IF a LangGraph_Workflow_Endpoint fails any required Chat_Compatibility_Profile test, THEN THE Mural_Platform SHALL withhold Supported_Endpoint classification and record each failed test in the Validation_Report.
3. THE Chat_Compatibility_Profile SHALL preserve the submitted order of system, user, assistant, Tool_Call, and Tool_Result messages across each endpoint invocation.
4. THE Chat_Compatibility_Profile SHALL accept only contract-defined assistant text, Tool_Calls, completion status, and structured errors as endpoint outputs.
5. WHERE a LangGraph_Workflow_Endpoint declares Stateful_Run_Profile, THE Integration_Gateway SHALL validate Thread_ID, External_Run_ID, Checkpoint_Reference, Endpoint_Interrupt, resume, and cancellation semantics before assigning that profile.
6. IF an agent requires direct audio frames, an in-process Python object, an uploaded executable package, or an undocumented payload, THEN THE Mural_Platform SHALL classify the agent as an Unsupported_Agent and record the applicable incompatibility reason.
7. IF a LangGraph_Workflow_Endpoint omits streaming Invocation_Mode, THEN THE Mural_Platform SHALL make the Endpoint_Registration ineligible for live voice and permit only validation and supported non-conversational operations.
8. THE Mural_Platform SHALL publish a Compatibility_Matrix that identifies each supported contract version, Compatibility_Profile, Invocation_Mode, State_Mode, and known limitation.
9. WHEN the Compatibility_Matrix changes, THE Mural_Platform SHALL create a new immutable matrix version containing an effective date and Mural release version while retaining every prior matrix version.

### Requirement 2: Endpoint Discovery and Onboarding

**User Story:** As an organization administrator, I want to register and inspect an external endpoint, so that I can onboard a compatible agent before attaching the agent to a workflow.

#### Acceptance Criteria

1. WHEN an organization administrator submits an endpoint URL containing no more than 2,048 characters and a credential reference owned by the same organization, THE Mural_Platform SHALL create a tenant-scoped Endpoint_Registration in `pending_validation` status.
2. IF an endpoint URL contains more than 2,048 characters, THEN THE Mural_Platform SHALL reject the registration with a URL-length validation error and create no Endpoint_Registration.
3. IF a credential reference belongs to a different organization, THEN THE Mural_Platform SHALL reject the registration with an authorization error and create no Endpoint_Registration.
4. WHEN the Integration_Gateway dispatches the discovery request, THE Integration_Gateway SHALL receive, parse, and schema-validate a complete Capability_Manifest within 5 seconds of dispatch.
5. IF the discovery interval exceeds 5 seconds before a complete Capability_Manifest is received, THEN THE Integration_Gateway SHALL set the Endpoint_Registration validation outcome to `discovery_timeout`.
6. IF discovery returns a payload that fails the Capability_Manifest schema, THEN THE Integration_Gateway SHALL set the Endpoint_Registration validation outcome to `invalid_manifest` and record each schema violation.
7. IF a valid Capability_Manifest offers no contract version listed in the current Compatibility_Matrix, THEN THE Integration_Gateway SHALL set the Endpoint_Registration to `incompatible` and record the offered and supported versions.
8. THE Mural_Platform SHALL display endpoint identity, selected Compatibility_Profile, declared capabilities, negotiated contract version, validation timestamp, lifecycle status, and Validation_Report summary.
9. WHEN an authorized user selects a declared capability set, THE Mural_Platform SHALL validate exactly the selected set without enabling undeclared endpoint behavior.
10. IF endpoint validation fails, THEN THE Mural_Platform SHALL prevent publication of a new Workflow_Version that references the failed Endpoint_Registration.
11. WHEN an authorized user revalidates an Endpoint_Registration, THE Mural_Platform SHALL create a new immutable Validation_Report and retain every earlier Validation_Report.
12. WHEN an Endpoint_Registration is revalidated, THE Mural_Platform SHALL preserve every previously published Workflow_Version without changing the pinned endpoint, contract, profile, or capability snapshot.
13. THE Mural_Platform SHALL complete onboarding without receiving endpoint source code, Python packages, or LangGraph graph objects.

### Requirement 3: Validation and Production Eligibility

**User Story:** As a platform operator, I want endpoint validation to exercise real contract behavior, so that incompatible agents fail before a live call.

#### Acceptance Criteria

1. THE Conformance_Suite SHALL test authentication, request schema, response schema, streaming framing, Tool_Call assembly, Tool_Result handling, error mapping, timeout behavior, and every state capability required by the selected Compatibility_Profile.
2. WHERE an endpoint declares cancellation, WHEN the Conformance_Suite dispatches a cancellation request, THE Conformance_Suite SHALL verify a terminal `cancelled` state no later than 2 seconds after cancellation dispatch.
3. WHERE an endpoint declares idempotent invocation handling, WHEN the Conformance_Suite submits the same Invocation_ID at least twice, THE Conformance_Suite SHALL verify exactly one logical terminal result for that Invocation_ID.
4. WHERE an endpoint declares idempotent invocation handling, WHEN the Conformance_Suite submits the same Invocation_ID at least twice, THE Conformance_Suite SHALL verify at most one externally visible execution for each Tool_Call identifier.
5. WHEN validation completes, THE Integration_Gateway SHALL create an immutable Validation_Report containing each test result, warning, measured latency, tested contract version, and selected Compatibility_Profile.
6. IF any required Chat_Compatibility_Profile test other than a live-voice latency test fails, THEN THE Mural_Platform SHALL mark the Endpoint_Registration as `incompatible`.
7. IF every required non-latency Chat_Compatibility_Profile test passes and a Requirement 11 live-voice latency limit fails, THEN THE Mural_Platform SHALL mark the Endpoint_Registration as `validation_only` rather than `live_voice_eligible`.
8. WHEN three scheduled health-validation failures for an Endpoint_Registration occur within any rolling 15-minute interval, THE Mural_Platform SHALL prevent new Voice_Runs from selecting the endpoint.
9. THE Integration_Gateway SHALL execute scheduled contract revalidation at least once every 24 hours for each live-voice-eligible Endpoint_Registration.

### Requirement 4: Frontend Workflow Mapping and Semantics

**User Story:** As a workflow author, I want Mural graph concepts mapped predictably to an external chat agent, so that the visual workflow remains understandable and testable.

#### Acceptance Criteria

1. WHEN a Voice_Run enters a Frontend_Workflow node configured for a Supported_Endpoint, THE Workflow_Adapter SHALL create exactly one initial endpoint invocation for that node entry.
2. WHEN the Workflow_Adapter creates an endpoint invocation, THE Workflow_Adapter SHALL include the current node prompt, ordered Conversation_History, current node Tool_Definitions, and only runtime context fields allowed by the Workflow_Version-pinned Data_Sharing_Policy.
3. THE Workflow_Adapter SHALL map each outgoing Frontend_Workflow edge to exactly one Transition_Tool in the Workflow_Version.
4. THE Workflow_Adapter SHALL assign each Transition_Tool a name that is unique within the Workflow_Version and stable for the lifetime of that Workflow_Version.
5. WHEN the endpoint returns a Transition_Tool call authorized for the current node with arguments valid under the pinned JSON schema, THE Mural_Platform SHALL execute exactly the one outgoing edge mapped to that Transition_Tool.
6. IF the endpoint returns text without an accepted Transition_Tool call, THEN THE Mural_Platform SHALL keep the current Frontend_Workflow node active.
7. IF the endpoint returns a Tool_Call whose name is absent from the current node Tool_Definitions, THEN THE Mural_Platform SHALL reject the Tool_Call as unauthorized and keep the current node active.
8. IF a Transition_Tool call fails its pinned JSON schema, THEN THE Mural_Platform SHALL return a structured Tool_Result error and keep the current node active.
9. WHEN a node transition completes, THE Workflow_Adapter SHALL create the next invocation with the target node prompt, target node Tool_Definitions, ordered Conversation_History, and pinned Data_Sharing_Policy.
10. THE Mural_Platform SHALL display whether each prompt, tool, transition, and state field is owned by Mural or by the endpoint before workflow publication.
11. WHERE a frontend feature has no mapping in the selected Compatibility_Profile, THE Mural_Platform SHALL block that feature selection and display the missing endpoint capability.

### Requirement 5: Ownership of Prompts, History, State, and Identifiers

**User Story:** As a workflow author, I want one declared owner for each state category, so that Mural and the external endpoint do not diverge during a conversation.

#### Acceptance Criteria

1. THE Mural_Platform SHALL own Voice_Run_ID, Workflow_Version selection, active Frontend_Workflow node, node prompts, supplied Tool_Definitions, Tool_Results, and canonical transcript.
2. WHEN the Workflow_Adapter constructs an invocation, THE Workflow_Adapter SHALL place the current Mural node prompt as the authoritative system instruction before the ordered Conversation_History.
3. WHEN Mural accepts a user message, assistant message, Tool_Call, or Tool_Result, THE Mural_Platform SHALL append the accepted message to Conversation_History in acceptance order.
4. THE Mural_Platform SHALL use Conversation_History as the authoritative record of wire-visible system, user, assistant, Tool_Call, and Tool_Result messages.
5. WHERE State_Mode is `Mural_authoritative`, THE Workflow_Adapter SHALL send the complete available Conversation_History on every invocation without requiring endpoint persistence.
6. WHERE State_Mode is `endpoint_checkpointed`, THE LangGraph_Workflow_Endpoint SHALL own internal LangGraph graph state and checkpoint contents.
7. WHERE State_Mode is `endpoint_checkpointed`, THE Mural_Platform SHALL persist endpoint-issued Thread_ID, External_Run_ID, and Checkpoint_Reference values as opaque records scoped to the Voice_Run organization.
8. WHEN a Stateful_Run_Profile invocation resumes, THE Workflow_Adapter SHALL send the latest persisted Checkpoint_Reference owned by the same organization and Voice_Run together with Voice_Run_ID correlation context.
9. IF endpoint state conflicts with Mural Conversation_History or active-node state, THEN THE Mural_Platform SHALL preserve the current Mural state, stop automatic progression, and record a state-conflict Protocol_Error.
10. IF a request uses a Thread_ID or Checkpoint_Reference owned by another organization, THEN THE Mural_Platform SHALL reject the request with an authorization error and perform no Voice_Run, workflow, or endpoint-state mutation.

### Requirement 6: Versioned Backend and Runtime Contract

**User Story:** As an endpoint developer, I want a stable, versioned contract, so that Mural upgrades do not silently break my deployed LangGraph agent.

#### Acceptance Criteria

1. THE LangGraph_Workflow_Contract SHALL assign an explicit version to discovery, invocation, Runtime_Event, error, cancellation, resume, and health schemas.
2. WHEN Mural and an endpoint offer multiple versions under a common supported major version, THE Integration_Gateway SHALL negotiate the highest mutually supported compatible minor version listed in the current Compatibility_Matrix.
3. WHEN invoking an endpoint, THE Integration_Gateway SHALL send the Workflow_Version-pinned negotiated contract version.
4. THE Mural_Platform SHALL support the two most recent mutually compatible minor contract versions within each supported major version.
5. IF Mural and an endpoint have no common supported major contract version, THEN THE Integration_Gateway SHALL reject activation with a version-incompatibility error.
6. WHEN a contract change removes or changes existing semantics, THE Mural_Platform SHALL publish the change under a new major contract version.
7. WHEN a contract change adds optional backward-compatible fields, THE Mural_Platform SHALL publish the change under a new minor contract version.
8. WHEN a Workflow_Version is published, THE Mural_Platform SHALL pin the Endpoint_Registration identifier, negotiated contract version, Compatibility_Profile, State_Mode, Invocation_Modes, Data_Sharing_Policy, and immutable capability snapshot.
9. WHILE a Voice_Run is active, THE Mural_Platform SHALL preserve the contract version and immutable capability snapshot pinned at Voice_Run creation.
10. IF an endpoint response violates required semantics of the pinned contract version, THEN THE Integration_Gateway SHALL record a Protocol_Error, preserve Conversation_History and active-node state, and prevent state progression from that response.

### Requirement 7: Synchronous, Streaming, and Asynchronous Invocation

**User Story:** As an endpoint developer, I want declared invocation modes, so that Mural invokes my agent using semantics the deployment actually supports.

#### Acceptance Criteria

1. WHERE Invocation_Mode is `synchronous`, THE Integration_Gateway SHALL accept exactly one complete response containing exactly one assistant message or exactly one structured error.
2. IF a synchronous response contains zero results or more than one assistant-or-error result, THEN THE Integration_Gateway SHALL record a Protocol_Error and perform no state progression from that response.
3. WHERE Invocation_Mode is `streaming`, THE Integration_Gateway SHALL consume Runtime_Events in declared sequence order until exactly one terminal completion or error event arrives.
4. WHERE Invocation_Mode is `asynchronous`, THE Integration_Gateway SHALL accept exactly one non-empty External_Run_ID for the accepted invocation.
5. WHERE Invocation_Mode is `asynchronous`, THE Integration_Gateway SHALL monitor the External_Run_ID through the contract-defined authenticated status or callback operation until one terminal result or the Workflow_Version voice-turn deadline occurs.
6. IF an asynchronous invocation reaches the Workflow_Version voice-turn deadline without a terminal result, THEN THE Integration_Gateway SHALL apply the configured timeout policy.
7. WHERE an asynchronous endpoint declares cancellation, IF the asynchronous invocation reaches the Workflow_Version voice-turn deadline without a terminal result, THEN THE Integration_Gateway SHALL dispatch a cancellation request before applying the configured timeout policy.
8. THE Mural_Platform SHALL require `streaming` Invocation_Mode for live voice eligibility.
9. WHEN the Voice_Pipeline performs non-conversational extraction or answering-machine classification through the endpoint, THE Workflow_Adapter SHALL request a synchronous non-streaming result.
10. IF a Runtime_Event sequence contains more than one terminal event, THEN THE Integration_Gateway SHALL classify every terminal event after the first as post-terminal protocol data and ignore the additional terminal event.
11. IF a Runtime_Event arrives after the first terminal event, THEN THE Integration_Gateway SHALL record a Protocol_Error and perform no transcript, tool, transition, checkpoint, or Voice_Run state mutation from the post-terminal event.
12. WHERE an endpoint declares multiple Invocation_Modes, THE Workflow_Version SHALL pin the mode used for live turns and the mode used for each non-conversational operation.

### Requirement 8: Interrupts, Human Review, and Resume

**User Story:** As a workflow operator, I want declared interrupt behavior, so that an agent requiring approval does not leave a live caller in an undefined state.

#### Acceptance Criteria

1. WHERE Stateful_Run_Profile declares interrupts, THE Integration_Gateway SHALL accept an Endpoint_Interrupt containing interrupt type, human-readable reason, allowed decisions, expiration time, and Checkpoint_Reference.
2. WHEN an Endpoint_Interrupt occurs during a text or preview session, THE Mural_Platform SHALL place the Voice_Run in `awaiting_human_review` and expose the interrupt to authorized reviewers.
3. WHEN an Endpoint_Interrupt occurs during a live voice call, THE Voice_Pipeline SHALL start the Workflow_Version-pinned interrupt policy within 2 seconds after accepting the interrupt.
4. WHERE the interrupt policy is `speak_and_wait`, THE Voice_Pipeline SHALL play the configured disclosure audio and wait for Human_Review for the configured duration between 10 and 300 seconds.
5. WHERE the interrupt policy is `transfer`, THE Voice_Pipeline SHALL initiate the Workflow_Version-pinned transfer action within 2 seconds after accepting the interrupt.
6. WHERE the interrupt policy is `end_call`, THE Voice_Pipeline SHALL initiate the Workflow_Version-pinned call-ending action within 2 seconds after accepting the interrupt.
7. IF a `speak_and_wait` duration expires without an accepted Human_Review decision, THEN THE Mural_Platform SHALL execute the Workflow_Version-pinned expiration action exactly once.
8. WHEN an authorized reviewer submits a decision listed in the Endpoint_Interrupt allowed decisions before expiration, THE Integration_Gateway SHALL resume from the stored same-tenant Checkpoint_Reference using a new Invocation_ID.
9. IF a reviewer submits a decision absent from the Endpoint_Interrupt allowed decisions, THEN THE Mural_Platform SHALL reject the decision and preserve the `awaiting_human_review` state.
10. IF an Endpoint_Interrupt expires without an accepted Human_Review decision, THEN THE Mural_Platform SHALL mark the interrupt expired and reject every later decision without changing the expired interrupt record.
11. IF the selected Compatibility_Profile does not declare interrupts, THEN THE Integration_Gateway SHALL treat an interrupt event as a Protocol_Error and perform no state progression.
12. WHEN Mural accepts or rejects a Human_Review action, THE Mural_Platform SHALL record reviewer identity, submitted decision, outcome, timestamp, Voice_Run_ID, and Checkpoint_Reference in an immutable audit record.

### Requirement 9: Errors, Retries, Idempotency, and Cancellation

**User Story:** As a caller, I want endpoint failures handled predictably, so that retries do not duplicate speech, tools, or external side effects.

#### Acceptance Criteria

1. THE Integration_Gateway SHALL assign exactly one Invocation_ID to each logical invocation and exactly one new Attempt_ID to each network attempt.
2. WHEN retrying an eligible invocation, THE Integration_Gateway SHALL reuse the Invocation_ID and generate a new Attempt_ID.
3. IF a connection failure, timeout, HTTP 408, HTTP 425, HTTP 429, HTTP 502, HTTP 503, or HTTP 504 occurs before any Runtime_Event is accepted and the remaining turn deadline permits another attempt, THEN THE Integration_Gateway SHALL perform exactly one retry for that Invocation_ID.
4. IF a listed pre-event retry condition occurs and the remaining turn deadline does not permit another attempt, THEN THE Integration_Gateway SHALL perform zero retries and classify the invocation as a terminal failure.
5. IF a listed pre-event retry condition recurs after the one permitted retry, THEN THE Integration_Gateway SHALL perform no additional retry for that Invocation_ID.
6. IF any text, Tool_Call fragment, interrupt, or terminal Runtime_Event has been accepted, THEN THE Integration_Gateway SHALL perform zero automatic retries for that Invocation_ID.
7. WHEN Mural accepts cancellation caused by hangup, barge-in replacement, node change, operator action, or platform shutdown, THE Integration_Gateway SHALL stop forwarding later Runtime_Events for the cancelled Invocation_ID within 250 milliseconds.
8. WHERE the endpoint declares cancellation, WHEN Mural accepts cancellation of an active invocation, THE Integration_Gateway SHALL dispatch the contract-defined cancellation request within 250 milliseconds.
9. IF an endpoint repeats a terminal result for a completed Invocation_ID, THEN THE Integration_Gateway SHALL return the recorded logical outcome without forwarding or persisting the repeated result.
10. IF an endpoint repeats a Tool_Call identifier for a completed Invocation_ID, THEN THE Integration_Gateway SHALL suppress tool re-execution and return the recorded Tool_Result.
11. WHEN an invocation fails terminally, THE Mural_Platform SHALL record the structured error category, retry count, elapsed time, and configured caller-facing action.
12. WHEN an invocation reaches a terminal failure, THE Mural_Platform SHALL execute exactly one Workflow_Version-pinned terminal-failure action of `retry_prompt`, `fallback_message`, `transfer`, or `end_call`.
13. IF an invocation reaches a terminal failure, THEN THE Mural_Platform SHALL preserve the Workflow_Version-pinned endpoint selection without switching to an unpinned model endpoint.

### Requirement 10: Voice Pipeline Responsibility Boundary

**User Story:** As a platform operator, I want the existing voice pipeline boundary preserved, so that adding LangGraph support does not regress established call behavior.

#### Acceptance Criteria

1. THE Voice_Pipeline SHALL retain ownership of speech-to-text processing, text-to-speech processing, voice activity detection, endpointing, turn-taking, and interruption handling.
2. THE Voice_Pipeline SHALL retain ownership of telephony signaling, call admission, media transport, call transfer, hangup, and provider event normalization.
3. THE Voice_Pipeline SHALL retain ownership of answering-machine detection, recording, transcript assembly, and post-call artifact finalization.
4. WHEN speech-to-text produces a completed user turn, THE Workflow_Adapter SHALL send transcript text and Data_Sharing_Policy-authorized context to the endpoint without raw audio.
5. IF an endpoint requests raw audio, telephony media sockets, or direct Pipecat processor access, THEN THE Mural_Platform SHALL reject the request as outside the selected Compatibility_Profile.
6. WHEN the Integration_Gateway accepts a non-empty text Runtime_Event, THE Voice_Pipeline SHALL forward that event exactly once to text-to-speech according to Runtime_Event sequence position.
7. IF the Integration_Gateway receives a duplicate text Runtime_Event sequence position for an Invocation_ID, THEN THE Voice_Pipeline SHALL suppress duplicate text-to-speech forwarding.
8. WHEN caller barge-in occurs, THE Voice_Pipeline SHALL interrupt current synthesized speech and accept cancellation of the superseded invocation within 250 milliseconds.
9. WHEN caller barge-in cancels an invocation, THE Integration_Gateway SHALL apply the cancellation behavior in Requirement 9.
10. IF a workflow uses a realtime speech-to-speech model, THEN THE Mural_Platform SHALL classify the LangGraph_Workflow_Endpoint as unavailable for that conversational path.
11. THE LangGraph_Workflow_Endpoint SHALL receive normalized call context rather than direct control of telephony media sockets or Pipecat processors.
12. WHILE the Experimental_Feature_Flag is disabled, THE Voice_Pipeline SHALL execute existing workflows without dispatching a LangGraph integration request.
13. WHILE the Experimental_Feature_Flag is disabled, THE Voice_Pipeline SHALL preserve existing non-LangGraph Pipecat behavior and provider integrations.

### Requirement 11: Tool Calls, Transitions, and Latency

**User Story:** As a caller, I want responsive and correct tool behavior, so that the conversation advances without unexplained silence or duplicated actions.

#### Acceptance Criteria

1. WHEN streaming a Tool_Call, THE LangGraph_Workflow_Endpoint SHALL use one Tool_Call identifier that remains unchanged across every fragment of that Tool_Call.
2. THE LangGraph_Workflow_Endpoint SHALL keep each Tool_Call identifier unique within an Invocation_ID.
3. WHEN a streamed Tool_Call completes, THE Integration_Gateway SHALL assemble the ordered JSON argument fragments into exactly one argument object that validates against the pinned Tool_Definition schema.
4. IF a Tool_Call identifier is reused within an Invocation_ID for a different tool name or different assembled arguments, THEN THE Integration_Gateway SHALL reject the reused identifier as a Protocol_Error.
5. WHEN a Tool_Call passes authorization and schema validation, THE Mural_Platform SHALL execute the Tool_Call exactly once for the Invocation_ID and Tool_Call identifier pair.
6. IF Mural receives a duplicate accepted Tool_Call identifier for the same Invocation_ID, THEN THE Mural_Platform SHALL return the cached Tool_Result without re-executing the tool.
7. WHEN a Tool_Result becomes available, THE Workflow_Adapter SHALL append the Tool_Call and Tool_Result to Conversation_History before the next endpoint invocation.
8. IF a Tool_Call fails schema validation, THEN THE Mural_Platform SHALL return a structured Tool_Result error without executing the tool.
9. THE Conformance_Suite SHALL require the elapsed time from request dispatch to the first accepted non-empty text or Tool_Call Runtime_Event to be no more than 1,500 milliseconds at the 95th percentile across at least 100 fixed streaming requests in the Conformance_Environment.
10. THE Conformance_Suite SHALL require the elapsed time from request dispatch to terminal completion to be no more than 10 seconds at the 95th percentile across at least 100 fixed requests that invoke no external tool in the Conformance_Environment.
11. THE Workflow_Version SHALL pin a first-event deadline between 500 and 3,000 milliseconds inclusive.
12. THE Workflow_Version SHALL pin exactly one first-event latency action of `fallback_message`, `transfer`, or `end_call`.
13. IF a live invocation produces no first accepted text or Tool_Call Runtime_Event by the pinned first-event deadline, THEN THE Voice_Pipeline SHALL execute the pinned first-event latency action exactly once and record a timeout metric.
14. WHEN an endpoint emits text before a Tool_Call in the same invocation, THE Voice_Pipeline SHALL treat each accepted text event as speakable caller-facing content.
15. THE Mural_Platform SHALL display a warning before publication that Tool_Call turns can create caller silence until tool completion and a subsequent text event.

### Requirement 12: Tenant Isolation, Authentication, Authorization, and Secrets

**User Story:** As an organization administrator, I want endpoint access isolated and authenticated, so that one tenant cannot use another tenant's agent, credentials, or state.

#### Acceptance Criteria

1. THE Mural_Platform SHALL scope every Endpoint_Registration, credential reference, Validation_Report, Thread_ID, Checkpoint_Reference, trace, invocation record, and audit record by organization identifier.
2. WHEN a user creates, reads, updates, deletes, lists, validates, activates, deactivates, or retires Endpoint_Registrations, THE Mural_Platform SHALL restrict the operation and returned records to the user's authorized organization.
3. WHEN resolving an Endpoint_Registration for a Workflow_Version, THE Mural_Platform SHALL verify that both records belong to the same organization before returning endpoint metadata.
4. THE Integration_Gateway SHALL authenticate every discovery, invocation, status, resume, cancellation, health, and callback request using the credential mechanism pinned by Endpoint_Registration.
5. THE Mural_Platform SHALL authorize endpoint creation, credential replacement, validation, activation, deactivation, deletion, retirement, and listing through separately testable tenant-role permissions.
6. IF a tenant-role authorization check fails, THEN THE Mural_Platform SHALL return an authorization error and perform no endpoint, credential, workflow, Voice_Run, or audit-target state mutation.
7. THE Mural_Platform SHALL store endpoint credentials through the existing encrypted credential reference mechanism without placing credential values in workflow definitions, logs, traces, or client responses.
8. WHEN displaying an Endpoint_Registration, THE Mural_Platform SHALL mask credential values and expose only credential type, reference identifier, and last-updated metadata.
9. IF an authenticated endpoint callback references a Voice_Run_ID, External_Run_ID, Endpoint_Registration, or organization identifier outside the callback registration's organization, THEN THE Integration_Gateway SHALL reject the callback with an authorization error and perform no state mutation.
10. WHERE Mural runs in hosted mode, THE Integration_Gateway SHALL reject an initial endpoint URL that resolves to a loopback, private, link-local, multicast, reserved, unspecified, or carrier-grade NAT address.
11. WHERE Mural runs in hosted mode, WHEN an endpoint request follows a redirect, THE Integration_Gateway SHALL apply the same URL validation and address-range restrictions to every redirect target before dispatch.
12. WHERE Mural runs in hosted mode, WHEN the Integration_Gateway opens an endpoint connection, THE Integration_Gateway SHALL validate the resolved destination address against the hosted address-range restrictions at connection time.
13. WHERE Mural runs in self-hosted mode, THE Mural_Platform SHALL keep private-network endpoint access disabled by default.
14. WHERE Mural runs in self-hosted mode, WHEN an administrator enables private-network endpoint access, THE Mural_Platform SHALL record the administrator identity, timestamp, and deployment-level decision.

### Requirement 13: Privacy, Data Minimization, and Redaction

**User Story:** As a privacy administrator, I want control over data sent to and retained for external agents, so that voice integration follows organizational data policy.

#### Acceptance Criteria

1. THE Mural_Platform SHALL display each prompt, transcript, context, Tool_Definition, tool-argument, tool-result, and identifier field eligible for endpoint transmission before activation.
2. WHEN the Workflow_Adapter constructs an outbound request, THE Workflow_Adapter SHALL include only fields required by the pinned Compatibility_Profile and explicitly allowed by the Workflow_Version Data_Sharing_Policy.
3. IF an outbound field is absent from the Data_Sharing_Policy allowlist, THEN THE Workflow_Adapter SHALL omit the field from endpoint transmission.
4. WHERE a Redaction_Policy is configured for endpoint transmission, THE Workflow_Adapter SHALL apply the policy before constructing the outbound request.
5. WHERE a Redaction_Policy is configured for observability, THE Mural_Platform SHALL apply the policy before persisting logs, traces, Validation_Reports, or error payloads.
6. THE Mural_Platform SHALL allow a tenant to configure retention periods within the deployment-configured minimum and maximum retention bounds for invocation metadata, external identifiers, checkpoint references, and captured endpoint payloads.
7. IF a requested retention period is outside the displayed deployment-configured bounds, THEN THE Mural_Platform SHALL reject the retention configuration without changing the active policy.
8. WHEN a governed record reaches its configured retention expiration, THE Mural_Platform SHALL delete or irreversibly anonymize the governed integration data in tenant-accessible storage within 24 hours.
9. IF payload capture is disabled, THEN THE Mural_Platform SHALL retain operational metadata without retaining prompt text, transcript text, tool arguments, tool results, or checkpoint contents.
10. THE Mural_Platform SHALL require endpoint data-region metadata before an Endpoint_Registration can become active.
11. THE Mural_Platform SHALL display endpoint data-region metadata before an Endpoint_Registration becomes active.
12. IF an endpoint response contains a secret that Mural would need to persist to continue a Voice_Run, THEN THE Integration_Gateway SHALL reject the response as a Protocol_Error, persist no secret value, and preserve the current Voice_Run state.

### Requirement 14: Prompt-Injection and Tool Safety

**User Story:** As a security administrator, I want external agent output treated as untrusted, so that prompt injection cannot expand tool or tenant permissions.

#### Acceptance Criteria

1. THE Mural_Platform SHALL treat endpoint text, Tool_Calls, Tool_Call arguments, checkpoint references, callback payloads, and error details as untrusted input.
2. WHEN an endpoint requests a Platform_Tool, THE Mural_Platform SHALL authorize the exact tool name against the Tool_Definition pinned to the current node, Workflow_Version, organization, and Voice_Run.
3. WHEN an endpoint requests a Platform_Tool, THE Mural_Platform SHALL validate the assembled Tool_Call arguments against the pinned Tool_Definition JSON schema and configured argument-size limit before execution.
4. IF an endpoint invents a tool, changes a tool schema, requests another tenant's resource, or exceeds a declared argument-size limit, THEN THE Mural_Platform SHALL reject the Tool_Call without executing the tool.
5. WHEN Mural rejects a Tool_Call for a security violation, THE Mural_Platform SHALL record a security event containing timestamp, organization identifier, Endpoint_Registration identifier, Voice_Run_ID, Invocation_ID, Tool_Call identifier, tool name, violation category, enforcement decision, and trace identifier.
6. WHERE a Platform_Tool is classified as high impact, THE Mural_Platform SHALL require the Workflow_Version-pinned explicit confirmation or Human_Review decision before executing the tool.
7. IF required confirmation for a high-impact Platform_Tool is absent, expired, or rejected, THEN THE Mural_Platform SHALL return a structured Tool_Result denial without executing the tool.
8. THE Mural_Platform SHALL keep Endpoint_Internal_Tools outside Mural's authorization guarantee and display that ownership boundary during onboarding.
9. IF endpoint-generated text attempts to alter system instructions, credentials, tool allowlists, organization scope, or contract controls, THEN THE Mural_Platform SHALL preserve the pinned controls and process the text only as model output.
10. THE Integration_Gateway SHALL enforce configured request, response, Runtime_Event, Tool_Call argument, and callback size limits with structured rejection errors.
11. WHEN an organization administrator disables a Platform_Tool for an Endpoint_Registration, THE Workflow_Adapter SHALL omit that Platform_Tool from subsequent endpoint Tool_Definitions.
12. IF an endpoint requests a Platform_Tool disabled for the Endpoint_Registration, THEN THE Mural_Platform SHALL reject the Tool_Call without executing the tool and record a security event.

### Requirement 15: Deployment, Lifecycle, and Version Compatibility

**User Story:** As a platform operator, I want endpoint lifecycle controls, so that deployments and upgrades do not unpredictably affect active calls.

#### Acceptance Criteria

1. THE Endpoint_Registration SHALL support lifecycle statuses `pending_validation`, `validation_only`, `active`, `degraded`, `disabled`, `incompatible`, and `retired`.
2. WHEN an Endpoint_Registration becomes `disabled`, `incompatible`, or `retired`, THE Mural_Platform SHALL prevent new Voice_Runs from selecting the endpoint.
3. WHILE a Voice_Run is active, THE Mural_Platform SHALL preserve the endpoint and contract snapshot pinned at Voice_Run creation.
4. WHEN an endpoint advertises a Capability_Manifest whose contract versions, profiles, modes, or operational limits differ from the last validated capability snapshot, THE Mural_Platform SHALL record the manifest as a changed capability snapshot requiring revalidation.
5. WHILE a changed capability snapshot has not passed required revalidation, THE Mural_Platform SHALL prevent a new Workflow_Version from pinning the changed capabilities.
6. WHEN an endpoint health operation first fails, THE Mural_Platform SHALL sample endpoint health at the configured health-sampling interval throughout the next 60 seconds.
7. IF every configured endpoint health sample due during the 60 seconds after the first failure also fails, THEN THE Mural_Platform SHALL set the Endpoint_Registration to `degraded` at the end of the 60-second interval and emit an operator alert with the status change.
8. WHEN endpoint health recovers, THE Mural_Platform SHALL require a successful current health operation and every required contract validation before reactivation.
9. WHEN reactivation prerequisites pass, THE Mural_Platform SHALL permit only an authorized operator to return the Endpoint_Registration to `active`.
10. THE Mural_Platform SHALL document supported LangGraph deployment shapes by contract behavior rather than by a guarantee for every LangGraph library, server, cloud, or application version.
11. WHEN Mural schedules removal of a compatible minor contract version, THE Mural_Platform SHALL expose a deprecation notice at least one Mural minor release before removal.
12. WHEN an authorized user deletes an unreferenced Endpoint_Registration, THE Mural_Platform SHALL delete the registration according to its retention policy.
13. WHEN an authorized user deletes an Endpoint_Registration referenced by a Workflow_Version or retained Voice_Run, THE Mural_Platform SHALL convert the registration to `retired`, block new-run selection, and retain referential metadata.

### Requirement 16: Observability and Trace Correlation

**User Story:** As an operator, I want correlated traces across voice and LangGraph execution, so that I can diagnose latency, errors, and state transitions end to end.

#### Acceptance Criteria

1. THE Integration_Gateway SHALL associate one Trace_Context with every discovery, invocation, status, resume, cancellation, health, and callback exchange.
2. WHEN an exchange belongs to a Voice_Run, THE Trace_Context SHALL contain Voice_Run_ID, Invocation_ID, Attempt_ID, Workflow_Version identifier, Endpoint_Registration identifier, negotiated contract version, organization scope, and standards-compatible trace identifiers.
3. WHEN an exchange does not belong to a Voice_Run, THE Trace_Context SHALL contain the applicable operation identifier, Endpoint_Registration identifier, negotiated contract version, organization scope, and standards-compatible trace identifiers.
4. WHEN an endpoint returns External_Run_ID, Thread_ID, or Checkpoint_Reference, THE Mural_Platform SHALL associate each value with the originating Trace_Context and organization scope.
5. THE Mural_Platform SHALL measure request count, active invocation count, retry count, error count, Tool_Call count, interrupt count, and endpoint-health result as integer counts grouped by tenant-safe dimensions.
6. THE Mural_Platform SHALL measure first-event latency from endpoint request dispatch to first accepted non-empty text or Tool_Call Runtime_Event in milliseconds.
7. THE Mural_Platform SHALL measure completion latency from endpoint request dispatch to accepted terminal Runtime_Event in milliseconds.
8. THE Mural_Platform SHALL measure stream duration from first accepted Runtime_Event to accepted terminal Runtime_Event in milliseconds.
9. THE Mural_Platform SHALL measure cancellation latency from Mural cancellation acceptance to event-forwarding suppression and cancellation-request dispatch in milliseconds.
10. THE Mural_Platform SHALL restrict configurable latency and error alert thresholds to the displayed deployment-configured minimum and maximum bounds.
11. IF a metric violates its configured threshold for the configured evaluation interval, THEN THE Mural_Platform SHALL emit an alert at the end of that evaluation interval.
12. WHEN Mural emits a latency or error alert, THE Mural_Platform SHALL include organization-safe endpoint identifier, contract version, metric name, measured value, unit, threshold, evaluation interval, and trace link without unredacted Sensitive_Data.
13. WHEN a node transition or Tool_Call occurs, THE Mural_Platform SHALL record the related Invocation_ID and Voice_Run_ID in the existing run log.
14. WHEN Mural observes user-turn completion, endpoint request dispatch, first Runtime_Event, first synthesized audio, terminal event, or cancellation, THE Mural_Platform SHALL record the observation using a monotonic event order and millisecond-resolution timestamp.
15. WHEN first synthesized audio exists for an invocation, THE Mural_Platform SHALL record the first-synthesized-audio event after the text Runtime_Event that produced the audio.
16. WHEN a terminal event exists for an invocation, THE Mural_Platform SHALL record the terminal event after endpoint request dispatch and every earlier Runtime_Event sequence position.
17. WHERE the endpoint supports distributed tracing, WHEN the endpoint supplies valid standards-compatible trace headers, THE Integration_Gateway SHALL continue the trace without accepting endpoint-supplied tenant identity.
18. WHERE the endpoint supports distributed tracing, IF the endpoint supplies malformed trace headers, THEN THE Integration_Gateway SHALL ignore the malformed headers, continue the Mural-originated trace, and record a protocol warning.
19. WHEN an authorized user opens a per-Voice_Run diagnostic view, THE Mural_Platform SHALL display tenant-scoped Pipecat events, endpoint attempts, Tool_Calls, transitions, errors, and external run identifiers in recorded event order.
20. IF a user requests a diagnostic view for a Voice_Run outside the user's organization, THEN THE Mural_Platform SHALL return an authorization error without revealing whether the Voice_Run or related trace data exists.

### Requirement 17: Test and Conformance Strategy

**User Story:** As a release engineer, I want repeatable conformance and end-to-end tests, so that contract changes and voice regressions are detected before rollout.

#### Acceptance Criteria

1. THE Conformance_Suite SHALL provide deterministic fixtures with declared input, expected Runtime_Event sequence, expected terminal outcome, and expected state mutation for plain text, fragmented text, single Tool_Call, multiple Tool_Calls, fragmented JSON arguments, Tool_Results, usage, structured errors, retries, cancellation, and terminal events.
2. WHEN an endpoint processes a valid deterministic fixture, THE Conformance_Suite SHALL pass the fixture only if observed events, terminal outcome, Tool_Calls, and state mutations equal the fixture's declared expectations.
3. THE Conformance_Suite SHALL provide malformed fixtures for invalid schemas, unknown events, duplicate events, reordered fragments, oversized payloads, authentication failures, timeouts, disconnects, and post-terminal data.
4. WHEN an endpoint processes a malformed fixture, THE Conformance_Suite SHALL pass the fixture only if Mural produces the expected structured error, performs no unauthorized state mutation, and executes no unauthorized Tool_Call.
5. WHERE Stateful_Run_Profile is selected, THE Conformance_Suite SHALL provide deterministic fixtures for Thread_ID isolation, checkpoint resume, stale checkpoints, Endpoint_Interrupt expiration, Human_Review decisions, and cancellation races.
6. THE Mural_Platform SHALL provide a text-session or simulation path that exercises the same Workflow_Adapter, prompts, Tool_Definitions, transitions, and state rules used by live voice.
7. WHEN a workflow author runs a preflight conversation, THE Mural_Platform SHALL report the Invocation_ID, requested Transition_Tool, source node, target node, and whether the active node changed as expected.
8. WHEN testing existing non-LangGraph voice, WebRTC, text, answering-machine detection, interruption, transfer, recording, and post-call flows, THE Conformance_Suite SHALL require observed outputs and state transitions to match the approved non-LangGraph baseline.
9. THE Conformance_Suite SHALL include cross-organization attempts for endpoint, credential, Thread_ID, Checkpoint_Reference, callback, trace, diagnostic-view, and tool access.
10. WHEN executing a cross-organization fixture, THE Conformance_Suite SHALL pass the fixture only if Mural returns an authorization error, performs no target-tenant state mutation, and reveals no target-tenant data.
11. THE Conformance_Suite SHALL include a live-pipeline smoke test that records completed transcript input, endpoint request dispatch, first accepted endpoint event, first synthesized output, barge-in cancellation, terminal call state, and recording finalization.
12. WHEN executing the live-pipeline smoke test, THE Conformance_Suite SHALL require recorded events to follow the applicable Requirement 16 event order and the barge-in cancellation boundaries in Requirements 9 and 10.
13. WHEN creating a Validation_Report, THE Mural_Platform SHALL retain Conformance_Suite version, contract version, endpoint capability snapshot, deterministic fixture result digest, and live-smoke result when required.
14. WHEN a Conformance_Suite version adds a required test, THE Mural_Platform SHALL revalidate active Endpoint_Registrations before treating the new test as an activation gate.

### Requirement 18: Additive Migration and Experimental Rollout

**User Story:** As a product owner, I want a controlled additive rollout, so that the integration can be evaluated without disrupting existing customers or Pipecat behavior.

#### Acceptance Criteria

1. THE Mural_Platform SHALL gate Endpoint_Registration creation, workflow attachment, and runtime invocation behind Experimental_Feature_Flag.
2. WHILE Experimental_Feature_Flag is disabled for an organization, THE Mural_Platform SHALL hide LangGraph onboarding controls and preserve existing workflow execution behavior.
3. IF a user or runtime requests Endpoint_Registration creation, workflow attachment, or LangGraph invocation while Experimental_Feature_Flag is disabled for the organization, THEN THE Mural_Platform SHALL reject the request with a feature-disabled error and perform no integration state mutation.
4. WHEN enabling the feature for an organization, THE Mural_Platform SHALL require explicit administrator acknowledgment of experimental status, external latency responsibility, data-sharing scope, and compatibility boundaries.
5. THE Mural_Platform SHALL implement rollout stages in the order `internal_test_tenant`, `selected_tenant_allowlist`, `percentage_cohort`, and `general_experimental_availability`.
6. WHEN an authorized user attaches or changes an Endpoint_Registration, THE Mural_Platform SHALL create a new Workflow_Version instead of mutating a published Workflow_Version.
7. WHEN each configured evaluation point in a continuous 15-minute interval contains at least 100 endpoint-attributable turns in the then-current rolling window and an endpoint-attributable turn-failure rate above 5 percent, THE Mural_Platform SHALL halt expansion to the next rollout stage and alert operators.
8. WHEN each configured evaluation point in a continuous 15-minute interval contains at least 100 endpoint-attributable turns in the then-current rolling window and a 95th-percentile first-event latency above 2,000 milliseconds, THE Mural_Platform SHALL halt expansion to the next rollout stage and alert operators.
9. WHEN an operator disables Experimental_Feature_Flag, THE Mural_Platform SHALL prevent new LangGraph-backed Voice_Runs within 60 seconds without changing non-LangGraph workflows.
10. WHILE LangGraph-backed Voice_Runs remain active after feature disablement, THE Mural_Platform SHALL allow each Voice_Run to finish under the Workflow_Version pinned at Voice_Run creation.
11. WHEN a workflow becomes live-voice eligible, THE Mural_Platform SHALL retain evidence of successful text-session conformance, one accepted Transition_Tool transition, cancellation verification, and recording verification in the eligibility Validation_Report.
12. IF any required eligibility evidence is absent or failed, THEN THE Mural_Platform SHALL prevent the workflow from becoming live-voice eligible.
13. WHEN an operator initiates rollback, THE Mural_Platform SHALL restore new-run selection to the selected previously published non-LangGraph Workflow_Version within 60 seconds.
14. WHEN rollback changes new-run selection, THE Mural_Platform SHALL preserve every completed or active Voice_Run record without mutation.
15. THE Mural_Platform SHALL label the integration as experimental in onboarding, workflow configuration, Validation_Report, and operator documentation until product governance removes the label.

### Requirement 19: Documentation and Operational Readiness

**User Story:** As an endpoint developer and operator, I want complete integration documentation, so that I can implement, validate, deploy, and support a compatible endpoint.

#### Acceptance Criteria

1. THE Mural_Platform SHALL publish a versioned documentation inventory for every supported Compatibility_Profile, contract operation, schema, authentication method, timeout, retry condition, cancellation rule, error category, and Compatibility_Matrix version.
2. WHEN a documentation version is published, THE Mural_Platform SHALL associate the documentation version with each applicable LangGraph_Workflow_Contract version and Mural release version.
3. THE Mural_Platform SHALL publish an ownership matrix covering prompts, Conversation_History, Frontend_Workflow state, LangGraph state, checkpoints, Thread_ID, External_Run_ID, Tool_Definitions, Tool_Calls, Tool_Results, telephony controls, and recordings.
4. THE Mural_Platform SHALL provide executable request and response examples for synchronous, streaming, asynchronous, Tool_Call, Tool_Result, Endpoint_Interrupt, resume, error, and cancellation flows.
5. WHEN a contract example is proposed for publication, THE Mural_Platform SHALL execute the example against each contract version identified by the example.
6. IF a contract example fails execution against an identified contract version, THEN THE Mural_Platform SHALL prevent publication of that example for the failing version.
7. WHEN a contract example passes validation, THE Mural_Platform SHALL publish the example with the validated contract version, validation timestamp, and expected observable result.
8. THE Mural_Platform SHALL provide an operator checklist covering endpoint reachability, credentials, tenant authorization, privacy policy, data region, latency, health, conformance, rollout, and rollback.
9. THE Mural_Platform SHALL document that the endpoint receives chat-oriented requests rather than phone calls, raw telephony events, or direct Pipecat processor access.
10. THE Mural_Platform SHALL document that realtime speech-to-speech workflows bypass the LangGraph chat integration.
11. THE Mural_Platform SHALL document caller-visible consequences of slow first events, long-running Tool_Calls, asynchronous waits, endpoint errors, and Human_Review pauses.
12. WHEN versioned documentation changes, THE Mural_Platform SHALL retain the prior published version and its contract-version associations.

### Requirement 20: Authoritative Organization Feature Settings

**User Story:** As an organization administrator, I want to manage LangGraph enablement from Platform Settings, so that experimental access, deployment-specific network risk, and organization-wide visibility remain explicit and controlled.

#### Acceptance Criteria

1. THE Mural_Platform SHALL designate Platform Settings as the authoritative user interface for organization-level Experimental_Feature_Flag configuration.
2. THE Mural_Platform SHALL expose the current enabled, experimental-acknowledgment, experimental label, rollout-stage, and deployment-appropriate private-network configuration status to Platform Settings.
3. WHEN an authorized organization administrator submits `PATCH /api/v1/langgraph-feature` with enablement requested and explicit experimental acknowledgment accepted, THE Mural_Platform SHALL update the Experimental_Feature_Flag for the selected organization.
4. IF enablement is requested without explicit experimental acknowledgment, THEN THE Mural_Platform SHALL return an acknowledgment-required validation error without changing the organization configuration.
5. WHEN an authorized organization administrator submits `PATCH /api/v1/langgraph-feature` with disablement requested, THE Mural_Platform SHALL disable the Experimental_Feature_Flag for the selected organization.
6. IF a user without organization feature-configuration permission submits a feature-settings mutation, THEN THE Mural_Platform SHALL return an authorization error without changing organization configuration.
7. IF a feature-settings mutation has no selected organization context, THEN THE Mural_Platform SHALL return an organization-context error without changing organization configuration.
8. IF a feature-settings mutation targets an organization outside the authenticated selected organization context, THEN THE Mural_Platform SHALL return a non-enumerating authorization or not-found response without changing either organization configuration.
9. WHEN Platform Settings displays the LangGraph integration card, THE Mural_Platform SHALL display current enabled, acknowledged, experimental, and rollout-stage status.
10. THE Mural_Platform SHALL display a compatibility, external-latency, and data-sharing warning adjacent to the LangGraph enablement control.
11. WHEN the LangGraph integration card is loading current status, THE Mural_Platform SHALL display a loading state and disable feature-settings mutation controls.
12. WHILE a LangGraph feature-settings mutation is in progress, THE Mural_Platform SHALL display a saving state and prevent a duplicate mutation submission.
13. IF a LangGraph feature-settings mutation fails, THEN THE Mural_Platform SHALL display the normalized API error and preserve the last confirmed feature status.
14. WHEN a LangGraph feature-settings mutation succeeds, THE Mural_Platform SHALL display a success state and refresh organization configuration before updating LangGraph-dependent navigation and workflow controls.
15. WHEN the Experimental_Feature_Flag is disabled, THE Mural_Platform SHALL preserve Endpoint_Registrations, immutable Validation_Reports, published Workflow_Versions, retained Voice_Run records, and tenant-scoped diagnostics.
16. WHILE the Experimental_Feature_Flag is disabled, THE Mural_Platform SHALL block endpoint onboarding, workflow attachment, workflow publication, and new LangGraph endpoint dispatch through the existing feature gates.
17. WHERE Mural runs in self-hosted mode, THE Mural_Platform SHALL display private-network endpoint access as a separate Platform Settings option that defaults to disabled.
18. WHERE Mural runs in self-hosted mode, IF private-network endpoint access is requested without a distinct audited risk acknowledgment, THEN THE Mural_Platform SHALL reject the private-network setting without changing the active private-network policy.
19. WHERE Mural runs in self-hosted mode, WHEN an authorized organization administrator accepts the distinct private-network risk decision, THE Mural_Platform SHALL record administrator identity, decision timestamp, and the resulting private-network setting.
20. WHERE Mural runs in hosted mode, THE Mural_Platform SHALL omit the private-network option from Platform Settings and reject requests that attempt to enable private-network endpoint access.
21. IF an authorized configuration user opens the disabled `/langgraph-endpoints` page, THEN THE Mural_Platform SHALL display a control linking to the LangGraph card in Platform Settings.
22. IF a user without feature-configuration permission opens the disabled `/langgraph-endpoints` page, THEN THE Mural_Platform SHALL display explanatory read-only guidance without a feature-settings navigation control.
23. THE Mural_Platform SHALL keep the Experimental_Feature_Flag and private-network endpoint access disabled by default.
24. WHEN organization feature settings change, THE Mural_Platform SHALL preserve existing SSRF validation, tenant isolation, endpoint lifecycle, workflow publication, and runtime eligibility enforcement.
