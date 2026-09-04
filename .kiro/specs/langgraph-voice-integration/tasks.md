# Implementation Plan: LangGraph Voice Integration

## Overview

This plan delivers an internal experimental **Mural Chat Compatibility** release first, preserving the existing Pipecat voice boundary, then isolates Stateful Run/checkpoint/HITL work as an optional expansion. Tasks are ordered so each code-generation step builds on tested contract, persistence, gateway, adapter, and preflight foundations before live voice wiring. Security, tenant isolation, compatibility, non-regression, and release-gate work is required; only the post-Chat Stateful Run/HITL expansion is marked optional.

## Tasks

- [x] 1. Establish the versioned contract and test foundation
  - [x] 1.1 Implement contract schemas, compatibility profiles, and immutable matrix definitions
    - Create versioned Pydantic schemas under `api/schemas/langgraph_integration/` for discovery, invocation, synchronous/asynchronous results, SSE Runtime Events, errors, health, cancellation, and resume.
    - Add normalized capability/profile/mode models and matrix version selection under `api/services/langgraph_integration/contract/`, including bounded payload/identifier limits and executable schema examples.
    - Add schema tests for representative valid/invalid v1.0 and v1.1 payloads and explicit major/minor compatibility behavior.
    - _Requirements: 1.1, 1.4, 1.8, 1.9, 6.1, 6.4, 6.6, 6.7, 19.1, 19.2, 19.4_

  - [x] 1.2 Implement integration threat-model enforcement primitives
    - Add pure classifiers for unsupported agent requirements, untrusted endpoint output, payload-size bounds, secret-bearing continuation data, and Mural-versus-endpoint ownership declarations.
    - Extend `api/utils/url_security.py` with reusable destination policy hooks needed for initial URL, redirect, and connection-time validation without sending credentials before validation.
    - Add focused tests for direct-audio/in-process/package rejection, control-instruction non-authority, secret rejection, and boundary sizes.
    - _Requirements: 1.6, 10.5, 10.11, 12.10, 12.11, 12.12, 13.12, 14.1, 14.9, 14.10_

  - [x] 1.3 Add the pinned property-based testing dependency and harness
    - Add Hypothesis at an exact version in `api/pyproject.toml` and update the repository lock/dependency artifacts using the existing package workflow.
    - Create `api/tests/langgraph_integration/properties/` strategies for semantic versions, manifests, histories, graphs, JSON fragments, Runtime Events, tools, tenant scopes, retry states, IP classes, policies, health windows, rollout windows, and traces.
    - Configure at least 100 examples per property and enforce the design comment format `Feature: langgraph-voice-integration, Property {number}: {property title}`.
    - _Requirements: 17.1, 17.3_

  - [x] 1.4 Write the property test for unsupported integration classification
    - **Property 2: Unsupported integration requirements are rejected deterministically**
    - Generate combinations of direct audio, in-process objects, executable packages, and undocumented payload requirements; assert all applicable reasons are returned.
    - **Validates: Requirements 1.6**

  - [x] 1.5 Write the property test for manifest validation and version negotiation
    - **Property 5: Discovery validation and version negotiation are exact**
    - Assert complete schema-violation reporting, selected-capability subset rules, highest mutually supported compatible minor selection, and no-common-major rejection.
    - **Validates: Requirements 2.6, 2.7, 2.9, 6.2, 6.5**

  - [x] 1.6 Write the property test for pinned contract-version authority
    - **Property 12: Pinned versions remain wire-authoritative**
    - Assert every request uses the workflow-pinned version and compatible optional minor fields preserve prior valid payloads.
    - **Validates: Requirements 6.3, 6.7**

- [x] 2. Add tenant-scoped persistence, DB clients, feature flags, and permissions
  - [x] 2.1 Create additive database models and Alembic migrations
    - Extend `api/db/models.py` and add migrations under `api/alembic/versions/` for endpoint registrations, capability snapshots, compatibility matrices, validation reports/results, run bindings, invocations/attempts/events/tool effects, security events, retention policies, and rollout state.
    - Add organization-scoped indexes, immutable-record constraints, lifecycle checks, nullable rollout-safe foreign keys, and exactly-once uniqueness guards.
    - Add migration upgrade tests proving existing workflows/runs need no backfill and remain non-endpoint workflows.
    - _Requirements: 1.9, 2.11, 2.12, 3.5, 5.7, 6.8, 6.9, 9.9, 9.10, 12.1, 13.6, 15.1, 15.12, 15.13, 16.4, 17.13_

  - [x] 2.2 Implement organization-scoped DB clients and immutable ledgers
    - Add `api/db/langgraph_endpoint_client.py` and include it in `DBClient`; require `organization_id` on every tenant-owned query/mutation.
    - Implement compare-and-set lifecycle changes, immutable report/snapshot insertion, invocation/attempt/event/effect recording, reference-aware retirement, and transaction-safe deduplication.
    - Add two-organization and concurrent-write tests proving no cross-tenant reads/mutations and exactly-once ledger behavior.
    - _Requirements: 2.3, 2.11, 5.7, 5.10, 9.9, 9.10, 11.5, 11.6, 12.1, 12.3, 12.9, 15.12, 15.13, 17.9, 17.10_

  - [x] 2.3 Implement experimental feature configuration, acknowledgment, and RBAC
    - Add organization configuration for feature enablement, experimental acknowledgment, rollout stage, and self-hosted private-network decision with disabled defaults.
    - Define separately testable endpoint lifecycle and interrupt-review permissions in existing authorization code; use `WorkerSyncManager` for cross-worker invalidation where configuration/credential state is cached.
    - Add route/service authorization tests asserting denied actions perform no endpoint, credential, workflow, Voice Run, or audit-target mutation.
    - _Requirements: 12.2, 12.5, 12.6, 12.13, 12.14, 18.1, 18.2, 18.3, 18.4_

  - [x] 2.4 Write the property test for mutation-free denied authorization
    - **Property 24: Denied authorization produces no mutation**
    - Generate role/action/resource combinations and assert authorization errors leave every governed snapshot unchanged.
    - **Validates: Requirements 12.6**

  - [x] 2.5 Write the property test for non-secret credential projections
    - **Property 25: Credential responses are non-secret projections**
    - Assert endpoint responses contain only credential type, reference ID, and last-updated metadata, with no secret or reversible derivative.
    - **Validates: Requirements 12.8**

  - [x] 2.6 Write the property test for bounded retention and disabled capture
    - **Property 27: Retention and capture policies cannot broaden storage**
    - Assert invalid retention requests preserve active policy and capture-off persistence excludes all governed payload content.
    - **Validates: Requirements 13.7, 13.9**

- [x] 3. Implement endpoint registration APIs and lifecycle controls
  - [x] 3.1 Implement endpoint CRUD and tenant-safe response schemas
    - Add `api/routes/langgraph_endpoints.py`, route registration, request/response schemas, and service orchestration under `api/services/langgraph_integration/`.
    - Validate the 2,048-character URL bound, same-tenant credential ownership, selected capabilities, masked credential projection, list/detail scoping, and feature flag before mutation.
    - Add API tests for create/list/detail/update/delete, exact URL bounds, foreign credentials, masked secrets, and disabled-feature behavior.
    - _Requirements: 2.1, 2.2, 2.3, 2.8, 2.9, 2.13, 12.2, 12.3, 12.7, 12.8, 18.1, 18.3_

  - [x] 3.2 Implement lifecycle, validation-history, matrix, activation, and retirement APIs
    - Implement explicit lifecycle transition rules, immutable report history, current/prior matrix retrieval, active/degraded/disabled/incompatible/retired selection gates, and reference-aware delete-versus-retire behavior.
    - Preserve published workflow snapshots across revalidation and registration changes; require current passing evidence and authorized activation/reactivation.
    - Add transition-table and API tests for valid/invalid transitions, immutable history, changed snapshots, referenced retirement, and new-run blocking.
    - _Requirements: 1.8, 1.9, 2.10, 2.11, 2.12, 3.8, 15.1, 15.2, 15.3, 15.4, 15.5, 15.8, 15.9, 15.11, 15.12, 15.13_

  - [x] 3.3 Write the property test for live-voice eligibility
    - **Property 1: Eligibility follows the matrix, profile, mode, tests, and lifecycle**
    - Assert exact supported/incompatible/validation-only/live-selectable outcomes across generated matrices, manifests, validation results, modes, and lifecycle states.
    - **Validates: Requirements 1.1, 1.2, 1.7, 3.6, 3.7, 7.8, 15.2**

  - [x] 3.4 Write the property test for complete capability-change detection
    - **Property 29: Capability change detection is complete**
    - Assert semantic capability changes alter the normalized digest and ordering-only changes do not.
    - **Validates: Requirements 15.4**

- [x] 4. Build discovery, SSRF hardening, conformance, and background validation
  - [x] 4.1 Implement authenticated discovery with redirect and connection-time SSRF enforcement
    - Implement `GET /.well-known/mural-langgraph` through the gateway-only network boundary with a five-second complete-manifest deadline.
    - Validate initial URL, every redirect, DNS results, and actual connection destination; keep self-hosted private access disabled unless audited deployment configuration enables it.
    - Add deterministic tests for public/private IPv4/IPv6, DNS rebinding, redirects, timeout, malformed manifests, and credential non-disclosure before destination approval.
    - _Requirements: 2.4, 2.5, 2.6, 12.4, 12.10, 12.11, 12.12, 12.13, 12.14_

  - [x] 4.2 Implement capability selection and contract negotiation
    - Parse and normalize manifests, validate selected capability subsets, negotiate the highest mutually supported minor, record changed snapshots, and expose incompatibility details.
    - Ensure only selected declared behavior can be enabled and streaming remains mandatory for live voice.
    - Add negotiation tests for multi-major/minor offers, no-common-major, undeclared selections, data-region absence, and operational-limit changes.
    - _Requirements: 1.1, 1.5, 1.7, 2.7, 2.9, 6.2, 6.4, 6.5, 13.10, 13.11, 15.4, 15.5_

  - [x] 4.3 Implement deterministic conformance simulators and fixture runner
    - Create `api/services/langgraph_integration/conformance/` with versioned valid/malformed fixtures for text, fragmented text/JSON, tools, errors, retries, cancellation, terminal/post-terminal data, authentication, timeouts, disconnects, and oversized payloads.
    - Compare observed events, effects, terminal outcomes, and state mutations with fixture oracles; persist suite version and deterministic digests.
    - Add fixture-runner tests covering all baseline Chat Compatibility required tests.
    - _Requirements: 3.1, 3.3, 3.4, 17.1, 17.2, 17.3, 17.4, 17.13, 17.14_

  - [x] 4.4 Implement validation reports, ARQ scheduling, latency harness, and health sampling
    - Register idempotent onboarding, daily revalidation, latency, and health jobs in `api/tasks/arq.py`; store immutable reports/results and scheduled-failure windows.
    - Measure at least 100 fixed streaming first-event and tool-free completion requests, classify latency-only failures as `validation_only`, block after three scheduled failures in 15 minutes, and apply the 60-second degradation policy.
    - Add job idempotency, report immutability, daily schedule, p95 calculation, degraded recovery, and alert tests.
    - _Requirements: 3.2, 3.5, 3.6, 3.7, 3.8, 3.9, 11.9, 11.10, 15.6, 15.7, 15.8, 15.9, 17.13, 17.14_

  - [x] 4.5 Write the property test for hosted address classification
    - **Property 26: Hosted address classification blocks non-public destinations**
    - Generate IPv4/IPv6 addresses and assert every prohibited address class is blocked while public destinations remain eligible.
    - **Validates: Requirements 12.10**

  - [x] 4.6 Write the property test for health degradation windows
    - **Property 30: Health degradation follows the complete sample window**
    - Assert degradation occurs exactly at window end iff every due sample fails and the status-change alert emits once.
    - **Validates: Requirements 15.7**

  - [x] 4.7 Write the property test for conformance-oracle equality
    - **Property 34: Conformance results equal their declared oracle**
    - Generate valid and malformed fixtures and assert pass/fail exactly matches event, outcome, mutation, error, and unauthorized-effect expectations.
    - **Validates: Requirements 17.2, 17.4**

- [x] 5. Implement the Integration Gateway protocol engine
  - [x] 5.1 Implement bounded synchronous, streaming, and asynchronous clients
    - Create `api/services/langgraph_integration/gateway.py` as the only endpoint network client, with credential resolution, pinned-version serialization, authenticated operations, deadlines, and bounded incremental JSON/SSE parsing.
    - Enforce exact synchronous/asynchronous result cardinality, authenticated status polling, one terminal event, selected invocation modes, and structured error mapping.
    - Add simulator-backed tests for sync/stream/async success and all schema/cardinality/deadline failures.
    - _Requirements: 6.3, 6.10, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.8, 7.9, 7.12, 9.11, 12.4_

  - [x] 5.2 Implement Runtime Event reduction and durable accepted-event/effect ledgers
    - Add sequence/event reducers for contiguous ordering, exact duplicate suppression, fragment assembly, first-terminal closure, post-terminal recording without mutation, and checkpoint/event capability checks.
    - Persist accepted events and terminal/tool effects before forwarding effectful output; fail closed if durable guards cannot be written.
    - Add concurrent duplicate, sequence gap, multiple-terminal, post-terminal, oversized-event, and replay tests.
    - _Requirements: 7.3, 7.10, 7.11, 9.9, 9.10, 10.6, 10.7, 11.1, 11.2, 11.3, 11.4, 14.10_

  - [x] 5.3 Implement invocation identity, retry, cancellation, and idempotency coordination
    - Create one Invocation ID per logical invocation and one Attempt ID per attempt; implement the pure retry decision table and durable terminal-action guard.
    - Suppress forwarding and dispatch declared cancellation within 250 ms for barge-in, hangup, node change, operator action, and shutdown; never retry after an accepted event.
    - Add deterministic race tests for retry-before-event, insufficient time, consumed retry, disconnect-after-event, cancellation, repeated terminal results, and repeated Tool Call IDs.
    - _Requirements: 3.2, 3.3, 3.4, 7.7, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 9.10, 9.12, 9.13_

  - [x] 5.4 Add gateway trace propagation, redacted metrics, and protocol/security errors
    - Integrate with `api/services/pipecat/tracing_config.py`; originate protected Mural tenant scope, continue only valid trace headers, and ignore malformed endpoint headers with warnings.
    - Emit bounded request/active/retry/error/tool/health counts and latency timings without sensitive payloads.
    - Add tests for every operation’s Trace Context, malformed headers, tenant-claim rejection, and redacted error/metric attributes.
    - _Requirements: 12.9, 13.5, 14.5, 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8, 16.9, 16.17, 16.18_

  - [x] 5.5 Write the property test for negotiated output progression
    - **Property 4: Only negotiated output semantics can progress state**
    - Assert undefined, wrong-cardinality, or semantically invalid output produces a Protocol Error and no history/node mutation.
    - **Validates: Requirements 1.4, 6.10, 7.2**

  - [x] 5.6 Write the property test for streaming terminal history
    - **Property 13: Streaming accepts one ordered terminal history**
    - Assert contiguous accepted order, first-terminal authority, and mutation-free post-terminal data.
    - **Validates: Requirements 7.3, 7.10, 7.11**

  - [x] 5.7 Write the property test for invocation-mode cardinality
    - **Property 14: Synchronous and asynchronous cardinality is exact**
    - Assert exactly one assistant-or-error for sync and one non-empty External Run ID for async, with no progression otherwise.
    - **Validates: Requirements 7.1, 7.4**

  - [x] 5.8 Write the property test for asynchronous deadline outcomes
    - **Property 15: Asynchronous deadlines produce one pinned outcome**
    - Assert cancellation precedes the single timeout effect whenever cancellation is declared.
    - **Validates: Requirements 7.6, 7.7**

  - [x] 5.9 Write the property test for retry identity and event boundaries
    - **Property 17: Retry decisions preserve logical identity and obey the event boundary**
    - Assert one logical ID, unique attempt IDs, and exactly the permitted retry count across generated failures/deadlines/event states.
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.6**

  - [x] 5.10 Write the property test for terminal idempotency
    - **Property 18: Terminal outcomes and failure actions are idempotent**
    - Assert terminal replay returns the recorded outcome, executes at most one failure action, and never changes endpoint selection.
    - **Validates: Requirements 9.9, 9.12, 9.13**

  - [x] 5.11 Write the property test for Tool Call fragmentation
    - **Property 19: Tool Call fragmentation round-trips**
    - Generate JSON objects and fragment boundaries; assert exact assembly and rejection of reused IDs with changed name/arguments.
    - **Validates: Requirements 11.1, 11.2, 11.3, 11.4**

  - [x] 5.12 Write the property test for exactly-once speakable text
    - **Property 22: Speakable text is forwarded exactly once**
    - Assert each unique non-empty text sequence is forwarded once, including text before tools, and duplicates are suppressed.
    - **Validates: Requirements 10.6, 10.7, 11.14**

- [x] 6. Implement the Workflow Adapter and authorized tool boundary
  - [x] 6.1 Implement prompt, canonical history, policy projection, and redaction mapping
    - Add `api/services/workflow/langgraph_adapter.py` and shared reasoning interfaces; refactor prompt/tool composition from `pipecat_engine.py::_setup_llm_context` without changing the local-model path.
    - Put the current node prompt first, preserve accepted history order, send complete history in Mural-authoritative mode, apply data-sharing allowlists and redaction, and exclude raw audio/media/processor handles.
    - Add adapter tests for ordering, ownership labels, policy minimization, redaction, and unchanged existing model composition.
    - _Requirements: 4.2, 5.1, 5.2, 5.3, 5.4, 5.5, 10.4, 10.11, 13.1, 13.2, 13.3, 13.4_

  - [x] 6.2 Implement stable transition mapping and node progression
    - Reuse `api/services/workflow/workflow_graph.py` transition naming to produce a stable edge-to-tool bijection and reject normalized-name collisions at publication.
    - Execute only the current node’s authorized schema-valid transition once; preserve the node for text, unknown tools, or invalid arguments; build the next request from target-node state.
    - Add graph and adapter tests for duplicate entry notifications, stable names, collisions, successful transitions, and no-progression cases.
    - _Requirements: 4.1, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9_

  - [x] 6.3 Implement Platform Tool authorization and exactly-once execution
    - Add exact-name/node/version/tenant/run/registration enablement, JSON-schema, argument-size, resource ownership, and high-impact confirmation checks before existing tool handlers.
    - Persist accepted `(invocation_id, tool_call_id)` before execution, return cached Tool Results on duplicates, append Tool Call/Result before reinvocation, and emit security events on violations.
    - Add tests covering transition/custom/knowledge/HTTP/MCP/call-control tools, schema errors, disabled/foreign/oversized calls, confirmation, duplicate execution, and endpoint-internal ownership boundaries.
    - _Requirements: 9.10, 11.5, 11.6, 11.7, 11.8, 12.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 14.8, 14.11, 14.12_

  - [x] 6.4 Implement Mural-authoritative state reconciliation and protocol conflict handling
    - Persist opaque endpoint identifiers only after tenant/run validation, compare endpoint claims with canonical history/active node, and stop progression on conflicts.
    - Ensure output text cannot alter pinned prompts, credentials, tool allowlists, organization scope, or contract controls.
    - Add state-conflict, foreign identifier, stale claim, control-injection, secret detection, and no-mutation tests.
    - _Requirements: 5.6, 5.7, 5.9, 5.10, 13.12, 14.9_

  - [x] 6.5 Write the property test for canonical message order
    - **Property 3: Canonical message order is preserved**
    - Assert prompt-first ordering, relative message order, and exactly-once full history in Mural-authoritative mode.
    - **Validates: Requirements 1.3, 5.2, 5.3, 5.5**

  - [x] 6.6 Write the property test for transition bijection
    - **Property 6: Workflow edges and Transition Tools form a stable bijection**
    - Assert one-to-one edge mapping, namespace uniqueness, and stable names for immutable versions.
    - **Validates: Requirements 4.3, 4.4**

  - [x] 6.7 Write the property test for one invocation per node entry
    - **Property 7: Node entry creates one initial invocation**
    - Assert duplicate notifications and unrelated events cannot create additional initial invocations.
    - **Validates: Requirements 4.1**

  - [x] 6.8 Write the property test for minimal authorized outbound requests
    - **Property 8: Outbound requests are minimal, authorized, and redacted**
    - Assert required/allowlisted fields only, current prompt/history/tools, redaction, and absence of media/process handles.
    - **Validates: Requirements 4.2, 10.4, 10.11, 13.2, 13.3, 13.4, 13.5**

  - [x] 6.9 Write the property test for endpoint-controlled progression boundaries
    - **Property 9: Endpoint output cannot bypass node progression rules**
    - Assert only an authorized valid Transition Tool changes node once and the next request uses target-node pinned state.
    - **Validates: Requirements 4.5, 4.6, 4.7, 4.8, 4.9**

  - [x] 6.10 Write the property test for Mural-authoritative conflict resolution
    - **Property 10: Mural state wins every conflict**
    - Assert all endpoint state conflicts preserve Mural state and emit a state-conflict Protocol Error.
    - **Validates: Requirements 5.9**

  - [x] 6.11 Write the property test for authorized exactly-once Platform Tool effects
    - **Property 20: Platform Tool effects are authorized and exactly once**
    - Assert execution iff every authorization/schema/size/tenant/confirmation condition passes and duplicates return cached results.
    - **Validates: Requirements 9.10, 11.5, 11.6, 11.8, 14.2, 14.3, 14.4, 14.6, 14.7, 14.11, 14.12**

  - [x] 6.12 Write the property test for tool-history causality
    - **Property 21: Tool history causality is preserved**
    - Assert matching Tool Call and Tool Result are appended in order before every subsequent invocation.
    - **Validates: Requirements 11.7**

  - [x] 6.13 Write the property test for immutable controls and secret rejection
    - **Property 28: Endpoint content cannot alter pinned controls or persist detected secrets**
    - Assert control-like text has no authority, detected continuation secrets are not persisted, and every configured size bound applies before effects.
    - **Validates: Requirements 13.12, 14.9, 14.10**

- [x] 7. Add text preflight and immutable workflow publication gates
  - [x] 7.1 Wire the adapter and gateway into text-session preflight
    - Update `api/services/workflow/text_chat_runner.py` and `text_chat_session_service.py` to use the same endpoint snapshot, adapter, gateway, transition, tool, and state rules as live voice.
    - Report Invocation ID, requested transition, source/target nodes, and observed node change; preserve existing non-endpoint text sessions.
    - Add integration tests for text, Tool Call, transition, failure, cancellation, and two-tenant isolation paths.
    - _Requirements: 17.6, 17.7, 18.11, 18.12_

  - [x] 7.2 Implement workflow binding, immutable snapshot, and publication validation
    - Extend workflow configuration schemas and `api/routes/workflow.py::_validate_workflow_definition`/`publish_workflow` with same-tenant registration, current report, exact capability/profile/version/mode/state/policy, streaming, region, deadline/action, evidence, and feature-flag checks.
    - Copy the full binding into `WorkflowDefinitionModel.workflow_configurations`; create run bindings from pinned snapshots without consulting mutable registration behavior.
    - Add workflow-version tests proving attachment changes create a new version, revalidation cannot mutate published versions/active runs, invalid capabilities block publication, and feature-off requests are mutation-free.
    - _Requirements: 2.10, 4.10, 4.11, 6.8, 6.9, 7.8, 7.12, 11.11, 11.12, 11.15, 13.10, 13.11, 15.3, 18.3, 18.6, 18.11, 18.12_

  - [x] 7.3 Implement first-event and terminal-failure policy validation/effects
    - Validate 500–3,000 ms first-event deadlines and one allowed action; execute each first-event or terminal action exactly once using durable guards.
    - Cancel/suppress late streams before caller action and never silently switch to an unpinned model/endpoint.
    - Add boundary, late-event race, timeout metric, retry-prompt, fallback, transfer, end-call, and replay tests.
    - _Requirements: 9.11, 9.12, 9.13, 11.11, 11.12, 11.13_

  - [x] 7.4 Write the property test for first-event deadline policy
    - **Property 23: First-event deadlines are bounded and idempotent**
    - Assert valid bounds/actions and exactly one action plus timeout metric when no accepted first event arrives.
    - **Validates: Requirements 11.11, 11.12, 11.13**

  - [x] 7.5 Write the property test for feature-off mutation safety
    - **Property 35: Feature-off requests are mutation-free**
    - Assert create, attach, publish, and invoke requests return feature-disabled errors with no integration changes.
    - **Validates: Requirements 18.3**

  - [x] 7.6 Write the property test for complete live-eligibility evidence
    - **Property 38: Live eligibility evidence is complete**
    - Assert eligibility requires passing text conformance, one accepted transition, cancellation verification, and recording verification.
    - **Validates: Requirements 18.12**

- [x] 8. Integrate the non-realtime Pipecat voice path without changing media ownership
  - [x] 8.1 Implement the contract-backed reasoning processor in the standard pipeline
    - Update `api/services/pipecat/pipeline_builder.py`, `run_pipeline.py`, and `api/services/workflow/pipecat_engine.py` to select the remote reasoner only for pinned, eligible, non-realtime runs.
    - Convert accepted text to ordinary Pipecat frames while leaving STT, TTS, VAD, endpointing, turn-taking, telephony, transport, transfer, recording, transcript assembly, and post-call finalization in existing processors.
    - Add component tests proving feature-disabled/non-endpoint pipelines do not instantiate or dispatch the gateway.
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.6, 10.12, 10.13, 18.2, 18.3_

  - [x] 8.2 Wire barge-in, hangup, node-change, and shutdown cancellation
    - Connect existing interruption and lifecycle signals to gateway cancellation while preserving immediate TTS interruption and call finalization.
    - Measure/suppress forwarding and dispatch declared cancellation within 250 ms; protect against late events and duplicate speech.
    - Add deterministic Pipecat tests for barge-in replacement, hangup, node change, shutdown, cancellation races, and terminal call state.
    - _Requirements: 9.7, 9.8, 10.7, 10.8, 10.9, 16.9, 17.11, 17.12_

  - [x] 8.3 Implement synchronous non-conversational routing and realtime rejection
    - Route AMD/variable extraction synchronously only when explicitly pinned; otherwise retain existing provider paths.
    - Reject endpoint attachment/publication/run creation for realtime speech-to-speech paths and any direct audio/processor request.
    - Add tests for pinned/unpinned AMD and extraction, unsupported realtime publication/run creation, and no raw-audio transmission.
    - _Requirements: 7.9, 7.12, 10.5, 10.10, 19.9, 19.10_

  - [x] 8.4 Add required non-LangGraph and live-pipeline regression tests
    - Extend `api/tests/` Pipecat/telephony/text/recording suites with approved baseline assertions for non-endpoint voice, WebRTC, text, AMD, interruption, transfer, recording, and post-call behavior.
    - Add a simulator-backed live smoke test recording transcript completion, dispatch, first accepted event, first synthesized audio, cancellation, terminal call state, and recording finalization in causal order.
    - _Requirements: 10.12, 10.13, 17.8, 17.11, 17.12, 18.11, 18.12_

- [x] 9. Checkpoint — internal Chat runtime
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Build the frontend endpoint, workflow, and Chat diagnostics surfaces
  - [x] 10.1 Generate the typed API client and implement endpoint registry pages
    - Regenerate `ui/src/client` from stabilized FastAPI OpenAPI and add feature-flagged App Router list/create/detail/edit/validate/activate/deactivate/retire surfaces.
    - Display identity, profile/version/modes/state, capabilities, region, lifecycle, immutable report history, latency eligibility, masked credentials, experimental status, and limitations.
    - Add Vitest/React Testing Library tests for visibility, authorization/error states, masking, validation history, and lifecycle controls.
    - _Requirements: 2.8, 12.8, 13.1, 13.11, 15.1, 18.2, 18.15_

  - [x] 10.2 Implement workflow endpoint configuration, ownership, and publication feedback
    - Extend `ui/src/app/workflow/[workflowId]`, `ui/src/components/flow`, and the workflow Zustand store with endpoint binding in `ConfigurationsDialog` rather than a new node type.
    - Show Mural/endpoint ownership, capability-dependent controls, transition-name collisions, data-sharing fields, realtime rejection, and warnings for latency/tool silence/endpoint-internal tools.
    - Add component tests for capability blocking, ownership badges, immutable version edits, warnings, and structured publication errors.
    - _Requirements: 4.10, 4.11, 11.15, 13.1, 14.8, 18.6, 18.15_

  - [x] 10.3 Implement tenant-scoped Chat run diagnostics
    - Add run views that merge Pipecat events, endpoint attempts, accepted sequences, Tool Calls, transitions, errors, trace links, and external identifiers in recorded order.
    - Enforce tenant-scoped API queries and non-enumerating authorization errors; apply observability redaction before rendering.
    - Add API/UI tests for causal ordering, redaction, trace links, and cross-organization denial.
    - _Requirements: 16.13, 16.14, 16.15, 16.16, 16.19, 16.20_

- [x] 11. Complete observability, privacy, retention, and security operations
  - [x] 11.1 Implement causal event metrics, bounded alerts, and run-log correlation
    - Record monotonic user-turn, dispatch, Runtime Event, synthesized-audio, terminal, and cancellation observations with millisecond timestamps and run/invocation IDs.
    - Add deployment-bounded threshold configuration and redacted alert payloads for latency/error/health/security conditions.
    - Add reducer/timing tests for counts, latency calculations, order, bounds, evaluation intervals, and alert fields.
    - _Requirements: 14.5, 16.5, 16.6, 16.7, 16.8, 16.9, 16.10, 16.11, 16.12, 16.13, 16.14, 16.15, 16.16_

  - [x] 11.2 Implement privacy policy compilation, governed capture, and retention jobs
    - Compile Workflow-Version-pinned data-sharing/redaction policies; apply redaction before endpoint serialization and all log/trace/report/error persistence.
    - Add bounded tenant retention configuration and idempotent ARQ deletion/irreversible-anonymization within 24 hours of expiration, while preserving allowed operational metadata when capture is disabled.
    - Add tests for allowlist omission, redaction, bounds, capture-off storage, expiration, report/audit handling, and tenant isolation.
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9, 19.3_

  - [x] 11.3 Implement per-run external identifier and security-event diagnostics
    - Associate external run/thread/checkpoint identifiers with protected Trace Context, expose only bounded opaque/redacted values, and query through organization-scoped DB clients.
    - Surface tool-security enforcement decisions without endpoint payloads or secrets.
    - Add API tests for same-tenant retrieval, cross-tenant non-enumeration, malformed trace headers, and sensitive-field exclusion.
    - _Requirements: 12.1, 14.5, 16.4, 16.17, 16.18, 16.19, 16.20_

  - [x] 11.4 Write the property test for causal trace and metric projections
    - **Property 31: Trace and metric projections are causally correct**
    - Assert required context fields, reference count reductions, latency differences, monotonic order, text-before-audio, and dispatch/events-before-terminal.
    - **Validates: Requirements 16.2, 16.3, 16.5, 16.6, 16.7, 16.8, 16.9, 16.14, 16.15, 16.16**

  - [x] 11.5 Write the property test for bounded redacted alerts
    - **Property 32: Alerts are bounded, complete, and redacted**
    - Assert interval-end emission iff violated and complete tenant-safe fields without unredacted sensitive data.
    - **Validates: Requirements 16.10, 16.11, 16.12**

  - [x] 11.6 Write the property test for malformed trace-header isolation
    - **Property 33: Malformed trace headers cannot replace Mural trace identity**
    - Assert malformed endpoint headers are ignored while the Mural trace/tenant scope remains and a warning is recorded.
    - **Validates: Requirements 16.18**

- [x] 12. Implement rollout, rollback, release automation, and evidence
  - [x] 12.1 Implement ordered rollout stages, kill-switch propagation, and evaluation windows
    - Add internal/allowlist/percentage/general-experimental stage transitions, tenant selection, continuous 15-minute qualification windows, expansion halts, and operator alerts.
    - Enforce feature disablement for new runs within 60 seconds while allowing pinned active runs to finish.
    - Add deterministic stage, rolling-window, kill-switch, active-run, and alert tests.
    - _Requirements: 18.5, 18.7, 18.8, 18.9, 18.10_

  - [x] 12.2 Implement prior-version rollback selection
    - Add authorized selection of a previously published non-LangGraph Workflow Version for new runs within 60 seconds without mutating active/completed runs or endpoint snapshots.
    - Add rollback timing, authorization, non-LangGraph isolation, and record-preservation tests.
    - _Requirements: 18.9, 18.10, 18.13, 18.14_

  - [x] 12.3 Write the property test for rollout-stage ordering
    - **Property 36: Rollout stages advance only in order**
    - Assert the only forward transition is to the immediate next declared stage.
    - **Validates: Requirements 18.5**

  - [x] 12.4 Write the property test for qualifying rollout gates
    - **Property 37: Rollout gates use every qualifying evaluation point**
    - Assert expansion halts iff every evaluation point qualifies and either failure-rate or p95 latency threshold is exceeded.
    - **Validates: Requirements 18.7, 18.8**

  - [x] 12.5 Implement generated contract reference and executable example validation
    - Build code that generates versioned contract/profile/operation/schema/auth/timeout/retry/cancellation/error/ownership inventories from canonical schemas and matrix data.
    - Add executable sync/stream/async/tool/error/cancel examples with claimed-version metadata; block generated artifact publication when any claimed version fails.
    - Add CI tests for inventory completeness, retained prior versions, version associations, example execution, and observable-result metadata.
    - _Requirements: 15.10, 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7, 19.8, 19.9, 19.10, 19.11, 19.12_

  - [x] 12.6 Write the property test for executable example publication
    - **Property 39: Documentation examples publish only for passing versions**
    - Assert an example/version association is publishable iff execution passes for that contract version.
    - **Validates: Requirements 19.6**

- [x] 13. Validate and package the internal experimental Chat Compatibility release
  - [x] 13.1 Add full-stack conformance, tenant-isolation, and security integration suites
    - Exercise registration through activation, text preflight, publication, run binding, gateway invocation, tools/transitions, disablement, retirement, callbacks/status operations, and diagnostics against local simulators.
    - Include cross-organization endpoint, credential, external identifier, callback, trace, diagnostic, and tool attempts plus redirect/connect-time SSRF attacks.
    - Require zero target-tenant mutation/data disclosure and preserve all approved non-LangGraph baselines.
    - _Requirements: 3.1, 12.9, 17.5, 17.8, 17.9, 17.10, 18.11, 18.12_

  - [x] 13.2 Add fixed-environment load, latency, cancellation, and capacity tests
    - Create non-watch test commands/harnesses for warmed fixed payloads at documented concurrency, at least 100 required requests, active streams, event-loop lag, first-event/completion p95, and cancellation suppression/dispatch.
    - Persist environment metadata and fail live eligibility/release gates when required limits or headroom checks fail.
    - _Requirements: 3.2, 11.9, 11.10, 16.6, 16.7, 16.8, 16.9, 17.11, 17.12, 18.7, 18.8_

  - [x] 13.3 Add internal-release CI gates and immutable evidence assembly
    - Add targeted backend/frontend/property/conformance/migration/non-regression jobs and assemble Validation Report evidence for text conformance, accepted transition, cancellation, recording, fixture digest, contract/matrix/suite versions, and live smoke.
    - Ensure the internal release remains feature-disabled by default and can advance only when required evidence passes.
    - _Requirements: 3.5, 17.13, 17.14, 18.1, 18.4, 18.11, 18.12, 18.15_

- [x] 14. Checkpoint — internal experimental Chat Compatibility release
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 15. Add optional Stateful Run, checkpoints, interrupts, and HITL expansion
  - [ ]* 15.1 Add tenant/run-scoped stateful persistence and DB clients
    - Add checkpoint/thread/external-run fields to run bindings plus interrupt and immutable human-review audit tables/clients, with bounded opaque values and expiration-effect uniqueness.
    - Add migration, cross-tenant, latest-checkpoint, stale-checkpoint, and append-only audit tests.
    - _Requirements: 1.5, 5.6, 5.7, 5.8, 5.10, 8.1, 8.10, 8.12, 12.1_

  - [ ]* 15.2 Implement stateful async status, checkpoint acceptance, and resume
    - Extend the gateway/adapter with authenticated status monitoring, selected checkpoint capability, latest same-tenant/same-run resume, Voice Run correlation, and a new Invocation ID.
    - Add tests for status terminal/deadline/cancel behavior, stale/foreign checkpoints, conflicts, and retry/idempotency boundaries.
    - _Requirements: 5.8, 7.4, 7.5, 7.6, 7.7, 8.8, 12.4_

  - [ ]* 15.3 Implement interrupt lifecycle and live/text HITL policies
    - Add interrupt validation, `awaiting_human_review`, allowed-decision checks, 10–300 second speak-and-wait, transfer/end-call actions within two seconds, expiration, resume, and immutable audits.
    - Wire policies to text sessions and existing Pipecat disclosure/transfer/end-call handlers without transferring media ownership.
    - Add deterministic expiry/decision/race/action/audit tests and conformance fixtures.
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 8.12, 17.5_

  - [ ]* 15.4 Implement interrupt review APIs and frontend HITL/diagnostic UI
    - Add tenant- and permission-scoped decision APIs plus UI for reason, allowed decisions, expiry, status, reviewer outcome, and resulting resume invocation.
    - Reject non-allowed, expired, foreign-tenant, and unauthorized decisions without rewriting interrupt/audit records.
    - Add API/component tests for text/live states, race outcomes, non-enumeration, audit display, and feature/profile gating.
    - _Requirements: 8.2, 8.8, 8.9, 8.10, 8.12, 12.2, 12.5, 12.6, 16.19, 16.20_

  - [ ]* 15.5 Write the property test for scoped latest-checkpoint resume
    - **Property 11: Resume uses only the latest scoped checkpoint**
    - Assert selection of only the latest same-organization/same-run checkpoint with Voice Run correlation, rejecting foreign or stale selected values.
    - **Validates: Requirements 5.8, 8.8**

  - [ ]* 15.6 Write the property test for closed interrupt transitions
    - **Property 16: Interrupt state transitions are closed and irreversible**
    - Assert profile/capability/field requirements, new resume IDs, decision constraints, one expiration effect, and permanent post-expiry rejection.
    - **Validates: Requirements 8.1, 8.7, 8.8, 8.9, 8.10, 8.11**

- [x] 16. Final checkpoint — full Chat plus optional Stateful profile
  - Ensure all tests pass, ask the user if questions arise.

- [x] 17. Add required authoritative Platform Settings enablement follow-up
  - [x] 17.1 Implement the organization feature-settings mutation API and authorization boundary
    - Extend LangGraph feature request/response schemas and `api/routes/langgraph_endpoints.py` with admin-authorized `PATCH /api/v1/langgraph-feature`; resolve only the authenticated selected organization, expose UI-safe configuration capability, and delegate updates through `update_langgraph_feature_configuration`.
    - Preserve omitted rollout/cohort/halt values, require explicit experimental acknowledgment for every enable request, preserve records on disable, enforce separate audited self-hosted private-network acknowledgment, reject SaaS private-network enablement, and retain cross-worker configuration broadcasts.
    - Add backend route/service tests for authorized enable/disable, missing acknowledgment, denied role, missing/foreign organization context, non-enumerating mutation-free failures, safe defaults, omitted-field preservation, audit identity/timestamp, worker sync, and unchanged SSRF/tenant/lifecycle/publication/runtime gates.
    - _Requirements: 12.2, 12.5, 12.6, 12.13, 12.14, 18.1, 18.2, 18.3, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7, 20.8, 20.15, 20.16, 20.17, 20.18, 20.19, 20.20, 20.23, 20.24_

  - [x] 17.2 Implement the authoritative Platform Settings card and immediate context refresh
    - Regenerate `ui/src/client` with `npm run generate-client` after the API schema stabilizes; consume generated feature status and PATCH types without hand-editing generated files.
    - Add `LangGraphFeatureSettingsCard` at `/settings#langgraph-integration` with current enabled/acknowledged/experimental/rollout status, compatibility/latency/data-sharing warning, admin and read-only variants, explicit enable acknowledgment, and self-hosted-only separate private-network risk controls.
    - Implement accessible loading, saving, normalized API error, and success states; prevent duplicate submissions, preserve last confirmed status on error, and await `OrgConfigContext.refreshConfig()` after success.
    - Add component tests for administrator/read-only behavior, acknowledgment enforcement, deployment-mode private-network gating, API errors, save states, success refresh, and sidebar/workflow Reasoning endpoint visibility changes without reload.
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.9, 20.10, 20.11, 20.12, 20.13, 20.14, 20.17, 20.18, 20.19, 20.20, 20.23_

  - [x] 17.3 Update disabled endpoint guidance and add feature-disable preservation regressions
    - Update disabled `/langgraph-endpoints` rendering to link authorized configuration users to `/settings#langgraph-integration`, show explanatory read-only copy without the link for other users, and keep the settings form out of the registry page.
    - Add frontend tests for permission-gated settings navigation, absence of onboarding calls while disabled, refreshed sidebar/workflow visibility, and no embedded mutation controls.
    - Add backend integration regressions proving disablement preserves registrations, immutable reports, published workflow history, retained runs, and diagnostics while onboarding, attachment, publication, and new dispatch remain blocked by existing gates.
    - _Requirements: 2.10, 10.12, 15.2, 15.3, 18.2, 18.3, 18.9, 18.10, 20.1, 20.14, 20.15, 20.16, 20.21, 20.22, 20.24_

  - [x] 17.4 Reuse endpoint credential selection with inline credential creation
    - Reuse or safely generalize `CredentialSelector` and `CreateCredentialDialog` in `LangGraphEndpointForm`; wait for authentication readiness, load only the authenticated selected organization's credentials through the existing organization-scoped API, and render accessible loading, normalized API error, and clear empty states.
    - Allow inline credential creation, refresh the scoped credential list after success, automatically select the newly created credential, and require a selected credential UUID before endpoint submission; keep credential secrets masked and ensure the logged-in user's access token is never used as or forwarded in the external LangGraph endpoint credential.
    - Add focused component tests for existing credential selection, empty results, inline creation with refresh and automatic selection, loading/error states, delayed auth readiness, secret non-exposure, and submission of the selected credential UUID.
    - _Requirements: 2.1, 2.2, 2.3, 12.1, 12.3, 12.4, 12.7, 12.8, 18.2_

## Notes

- Tasks marked with `*` are optional and belong to the post-Chat Stateful Run/HITL expansion; the internal Chat Compatibility release does not depend on them.
- Task group 17 is a required Chat-release follow-up and does not depend on optional task group 15.
- All security, SSRF, tenant isolation, compatibility, feature-gate, non-regression, property, conformance, internal release-evidence, and Platform Settings follow-up tasks are required.
- Property tests use Python/Hypothesis; backend implementation uses Python/FastAPI/SQLAlchemy/ARQ; frontend implementation uses TypeScript/Next.js/React.
- Backend pytest must use the project-local `venv` and source `api/.env.test`; it must never use development database credentials.
- Every leaf task is designed as an incremental code-generation prompt and concludes with targeted automated validation; no deployment or manual user-acceptance tasks are included.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["1.4", "1.5", "1.6"] },
    { "id": 2, "tasks": ["2.1"] },
    { "id": 3, "tasks": ["2.2", "2.3"] },
    { "id": 4, "tasks": ["2.4", "2.5", "2.6"] },
    { "id": 5, "tasks": ["3.1"] },
    { "id": 6, "tasks": ["3.2"] },
    { "id": 7, "tasks": ["3.3", "3.4"] },
    { "id": 8, "tasks": ["4.1", "4.2"] },
    { "id": 9, "tasks": ["4.3", "4.4"] },
    { "id": 10, "tasks": ["4.5", "4.6", "4.7"] },
    { "id": 11, "tasks": ["5.1"] },
    { "id": 12, "tasks": ["5.2"] },
    { "id": 13, "tasks": ["5.3", "5.4"] },
    { "id": 14, "tasks": ["5.5", "5.6", "5.7", "5.8", "5.9", "5.10", "5.11", "5.12"] },
    { "id": 15, "tasks": ["6.1"] },
    { "id": 16, "tasks": ["6.2", "6.3", "6.4"] },
    { "id": 17, "tasks": ["6.5", "6.6", "6.7", "6.8", "6.9", "6.10", "6.11", "6.12", "6.13"] },
    { "id": 18, "tasks": ["7.1"] },
    { "id": 19, "tasks": ["7.2", "7.3"] },
    { "id": 20, "tasks": ["7.4", "7.5", "7.6"] },
    { "id": 21, "tasks": ["8.1"] },
    { "id": 22, "tasks": ["8.2", "8.3"] },
    { "id": 23, "tasks": ["8.4"] },
    { "id": 24, "tasks": ["10.1"] },
    { "id": 25, "tasks": ["10.2", "10.3"] },
    { "id": 26, "tasks": ["11.1", "11.2", "11.3"] },
    { "id": 27, "tasks": ["11.4", "11.5", "11.6"] },
    { "id": 28, "tasks": ["12.1", "12.2", "12.5"] },
    { "id": 29, "tasks": ["12.3", "12.4", "12.6"] },
    { "id": 30, "tasks": ["13.1"] },
    { "id": 31, "tasks": ["13.2"] },
    { "id": 32, "tasks": ["13.3"] },
    { "id": 33, "tasks": ["17.1"] },
    { "id": 34, "tasks": ["17.2"] },
    { "id": 35, "tasks": ["17.3"] },
    { "id": 36, "tasks": ["17.4"] },
    { "id": 37, "tasks": ["15.1"] },
    { "id": 38, "tasks": ["15.2"] },
    { "id": 39, "tasks": ["15.3"] },
    { "id": 40, "tasks": ["15.4", "15.5", "15.6"] }
  ]
}
```
