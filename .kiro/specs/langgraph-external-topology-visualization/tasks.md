# Implementation Plan

## Overview

The completed work established the external LangGraph topology contract, secure proxy and pinned snapshots, isolated read-only viewer, generated API client, and baseline compatibility coverage. The follow-up adds stale endpoint-evidence detection, an explicit and atomic Current_Draft binding update plus topology refresh, actionable draft-only UI controls, focused regression coverage, and a separate Mintlify user guide. Topology remains a manifest operation at `operations.topology`; it is not a Selected_Capability.

## Tasks

- [x] 1. Define and implement the versioned endpoint topology contract
  - Add the manifest topology operation and validated topology request/response DTOs.
  - Implement authenticated `GET /v1/topology` with collapsed and expanded views in the example LangGraph endpoint.
  - Add focused contract tests for valid, unsupported, and invalid topology responses.
  - _Requirements: 2_

- [x] 2. Add SpinSci's secure topology proxy and pinned snapshot support
  - Add the `IntegrationGateway` operation, backend service, and authenticated SpinSci API route.
  - Validate/normalize the external response; reuse current tenant, credential, audit, timeout, and SSRF/private-network controls.
  - Store a digest and immutable topology snapshot with the endpoint binding/version, and return graceful unavailable states.
  - Add focused backend tests, including historical-version snapshot retrieval.
  - _Requirements: 2, 3_

- [x] 3. Build the isolated read-only endpoint topology view
  - Add topology-specific React Flow types, components, mapper, and generic Dagre layout helper.
  - Add an entry point from endpoint configuration or the workflow editor, with loading, unsupported, empty, and error states.
  - Keep all elements out of the SpinSci workflow store and disable all graph editing interactions.
  - Add focused mapper/layout/component tests.
  - _Requirements: 1, 4, 5_

- [x] 4. Verify compatibility and deliver the API client update
  - Generate/update the frontend API client for the SpinSci topology route.
  - Run focused endpoint, backend, and UI tests, plus the existing workflow-editor regression suite.
  - Verify workflows whose endpoint manifest has no topology operation and existing SpinSci-owned workflows render and execute without changed canvas, persistence, or runtime highlighting behavior.
  - _Requirements: 1, 2, 3, 4, 5_

- [x] 5. Add binding status and safe candidate-rebind foundations
  - [x] 5.1 Extend topology API schemas with draft binding status, action availability, lifecycle stages, and stable reason codes
    - Keep existing `ExternalTopologyResponse` fields backward compatible and expose only non-secret evidence identifiers.
    - Represent current, stale, revalidation-required, failed, genuinely unsupported, immutable, and unavailable states distinctly.
    - Keep `operations.topology` out of Selected_Capability models and comparisons.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 9.1, 9.2, 9.3_

  - [x] 5.2 Implement read-only binding classification and an allowlisted candidate binding builder
    - Compare the draft's report/snapshot identities and digests with same-tenant current passing activation evidence.
    - Check current manifest operation support before labeling evidence stale, so true non-support remains `topology_unsupported`.
    - Build candidate bindings from one current passing report/snapshot set while preserving registration, endpoint URL, credentials, exact profile and Selected_Capabilities, modes, region, policy, timeout, and failure-action fields.
    - Reject profile or Selected_Capability mismatch with an actionable compatibility error; do not add topology to Selected_Capabilities.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.2, 7.3, 7.4, 7.5_

  - [x] 5.3 Add a tenant-scoped conditional workflow-definition configuration update
    - Add or extend a DB client operation that updates only the selected Current_Draft when the expected binding revision still matches.
    - Make the binding plus Topology_Snapshot write atomic and return a conflict when a concurrent draft save wins.
    - Reject published and historical definitions before mutation and keep every lookup constrained by `organization_id`.
    - _Requirements: 3.4, 3.5, 7.6, 7.7, 8.4, 8.5, 8.8_

  - [ ]* 5.4 Add unit tests for classification and candidate binding construction
    - Cover stale old evidence with current topology support, matching current evidence, genuinely unsupported current evidence, missing/failed evidence, and exact profile/capability incompatibility.
    - Assert the update allowlist and preservation of credentials, endpoint URL, modes, region, policies, timeout/failure behavior, and Selected_Capabilities.
    - Assert read-only classification performs no writes.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.3, 7.4, 7.5_

- [x] 6. Implement the explicit draft binding update and topology lifecycle
  - [x] 6.1 Implement atomic stale-binding recovery and current-binding refresh in the topology service
    - Load the Current_Draft and current activation evidence within the active tenant, choose the existing or candidate binding, and fetch collapsed topology through `IntegrationGateway`.
    - Validate the response, compute the digest, and atomically persist the chosen binding plus a Topology_Snapshot whose revision matches the chosen Capability_Snapshot.
    - Preserve the old binding and snapshot on unsupported, authentication, network, schema, or concurrency failure.
    - Keep refresh behavior for already-current bindings from changing validation or capability evidence.
    - _Requirements: 3.1, 3.2, 3.3, 6.2, 6.3, 6.4, 7.2, 7.3, 7.4, 8.2, 8.3, 8.4, 8.5, 8.8_

  - [x] 6.2 Add the explicit update-binding route and enrich the existing GET/refresh routes
    - Add a draft-only `POST .../langgraph-topology/update-binding` route; do not initiate endpoint validation or mutate a binding from GET.
    - Return binding status from draft GET/refresh, preserve immutable GET behavior, and return `binding_stale` instead of `topology_unsupported` for recoverable old evidence.
    - Enforce existing endpoint-validation and workflow-update permissions at the appropriate actions and return tenant-safe responses.
    - Keep the current endpoint `POST .../validate` and `POST .../activate` operations as the explicit evidence and lifecycle steps.
    - _Requirements: 6.1, 6.6, 7.1, 7.2, 7.6, 7.7, 7.8, 8.1, 8.2, 8.7_

  - [ ]* 6.3 Add focused backend service and API tests for the complete lifecycle
    - Recover an old draft snapshot/binding from current passing evidence that advertises `operations.topology` and verify the new snapshot revision.
    - Refresh a current binding without replacing evidence; return true unsupported status when current evidence omits the operation.
    - Cover immutable published/history rejection, version-local snapshot retention, cross-tenant workflow/definition/registration isolation, permission failures, read non-mutation, optimistic conflicts, and auth/network/schema rollback.
    - Retain workflow execution, SpinSci canvas, runtime highlighting, and non-topology endpoint regressions.
    - _Requirements: 1.1, 1.2, 1.4, 3.5, 5.1, 6.2, 6.3, 6.4, 6.6, 7.6, 7.7, 7.8, 8.2, 8.4, 8.5, 8.8, 9.4, 9.5, 9.6_

- [x] 7. Add the draft-only topology recovery UI
  - [x] 7.1 Regenerate the frontend API client for the final topology status and update-binding contract
    - Regenerate types and SDK calls from the backend OpenAPI schema after routes and response models stabilize.
    - Verify generated calls expose both `{ data, error }` handling and the new draft update action.
    - _Requirements: 8.1, 8.2, 8.6, 9.1, 9.2, 9.3_

  - [x] 7.2 Wire endpoint revalidation, explicit binding update, and current refresh into workflow configuration
    - Add an authorized Current_Draft action that requests endpoint revalidation when needed, reports validation progress, activates passing evidence when required, and invokes update-binding only after the registration has current passing evidence.
    - Offer refresh without evidence replacement for a current binding and require a new draft before any mutation from a published or historical version.
    - Check generated-client `response.error` values and normalize messages with `detailFromError`.
    - _Requirements: 7.1, 7.2, 7.7, 7.8, 8.1, 8.2, 8.6, 8.7_

  - [x] 7.3 Extend the topology viewer with distinct snapshot and lifecycle states
    - Continue rendering a valid pinned graph while labeling stale evidence and offering the explicit update action.
    - Add actionable text for `snapshot_unavailable`, `binding_stale`, `topology_unsupported`, validation, authentication, network, schema, and concurrency states.
    - Display per-stage validation, binding update, topology retrieval, and snapshot pinning outcomes without exposing credentials or unredacted diagnostics.
    - Keep the React Flow instance read-only and isolated from the SpinSci workflow store and runtime state.
    - _Requirements: 4.3, 4.6, 5.1, 8.1, 8.6, 8.7, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [x]* 7.4 Add focused UI tests for stale recovery, current refresh, errors, and immutable versions
    - Cover stale status plus update action, current refresh, true unsupported guidance, revalidation progress/failure, successful action chaining, and retained pinned topology after failure.
    - Cover auth/network/schema messages, generated-client error normalization, immutable action hiding/disablement, and workflow-store/runtime regression behavior.
    - _Requirements: 1.1, 1.2, 4.3, 4.6, 5.1, 6.2, 6.3, 6.4, 8.1, 8.2, 8.6, 8.7, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

- [x] 8. Checkpoint - Ensure all backend and UI tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Add the Mintlify LangGraph topology user guide after behavior stabilizes
  - [x] 9.1 Create `docs/integrations/langgraph-topology.mdx` with validated end-to-end instructions
    - Add valid YAML frontmatter and second-person instructions for prerequisites, starting/restarting the Endpoint, and authenticated discovery verification of `operations.topology`.
    - Cover validation/activation in **LangGraph Endpoints**, opening or creating a Current_Draft, updating the Endpoint_Binding, refreshing topology, and viewing the pinned graph.
    - Troubleshoot `snapshot_unavailable`, `topology_unsupported`, authentication, network, and schema failures.
    - Use placeholders for every secret and execute each shell or `curl` example against the implemented contract before retaining it.
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 9.2 Add the guide to Mintlify navigation and validate the documentation build
    - Add `docs/integrations/langgraph-topology` to the appropriate `docs/docs.json` navigation group.
    - Run repository documentation/MDX validation and verify the guide consistently describes topology as a manifest operation rather than a Selected_Capability.
    - _Requirements: 10.1, 10.5, 10.6_

- [ ] 10. Final checkpoint - Ensure all tests and documentation checks pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks 1-4 are completed baseline work and remain checked.
- Tasks marked with `*` are optional test tasks in the task runner, but they define the requested focused regression coverage and should be completed before release.
- Endpoint validation, workflow draft rebinding, and topology refresh are explicit actions; GET requests remain side-effect free.
- The binding update and Topology_Snapshot pin commit together only after the topology response validates.
- Published and historical workflow versions retain version-local bindings and snapshots and are never rebound.
- `operations.topology` is a manifest operation, not a Selected_Capability.
- Task 9 creates the separate Mintlify guide only after backend and UI behavior stabilizes; this planning update does not create the page.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["5.1", "5.3"] },
    { "id": 1, "tasks": ["5.2"] },
    { "id": 2, "tasks": ["5.4", "6.1"] },
    { "id": 3, "tasks": ["6.2"] },
    { "id": 4, "tasks": ["6.3", "7.1"] },
    { "id": 5, "tasks": ["7.2", "7.3"] },
    { "id": 6, "tasks": ["7.4"] },
    { "id": 7, "tasks": ["9.1"] },
    { "id": 8, "tasks": ["9.2"] }
  ]
}
```
