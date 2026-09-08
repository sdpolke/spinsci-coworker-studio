# Requirements Document

## Introduction

SpinSci, the SpinSci workflow application, displays the static topology of a LangGraph workflow owned and implemented by a configured reasoning endpoint. The display is an optional, read-only inspection surface and does not alter SpinSci's workflow canvas, persisted workflow definition, or runtime-node visualization.

This follow-up addresses endpoint registrations whose current validation evidence advertises the topology manifest operation while an existing workflow draft remains bound to an older capability snapshot that does not. SpinSci must distinguish stale draft evidence from genuine endpoint non-support, allow an authorized user to explicitly revalidate and rebind only the current draft, and pin topology at an explicit lifecycle point without mutating published or historical versions.

## Glossary

- **SpinSci**: The SpinSci workflow application that stores workflow definitions, endpoint bindings, and version-local topology snapshots.
- **Endpoint**: An externally hosted LangGraph-compatible reasoning service registered with SpinSci.
- **Endpoint_Registration**: The tenant-scoped SpinSci control-plane record for an Endpoint, including selected compatibility settings, credentials, lifecycle state, and current validation evidence.
- **Discovery_Manifest**: The authenticated, versioned document returned by an Endpoint during discovery.
- **Topology_Operation**: The `operations.topology` entry in a Discovery_Manifest. The Topology_Operation is a manifest operation and is not a Selected_Capability.
- **Selected_Capability**: A capability explicitly selected on an Endpoint_Registration and validated for compatibility. Topology support is not represented as a Selected_Capability.
- **Capability_Snapshot**: An immutable, normalized copy of a Discovery_Manifest retained by SpinSci after endpoint discovery.
- **Validation_Report**: An immutable record of endpoint compatibility validation against one Capability_Snapshot.
- **Passing_Validation_Report**: The current Validation_Report whose status permits activation and whose covered Capability_Snapshot is current for the Endpoint_Registration.
- **Endpoint_Binding**: The immutable-by-version copy of endpoint identity, validation evidence, manifest-derived operation data, credentials, compatibility choices, and policy fields stored in a workflow version.
- **Current_Draft**: The mutable draft workflow definition selected for editing within one tenant.
- **Immutable_Version**: A published or historical workflow definition that cannot be rebound or have its topology snapshot replaced.
- **Stale_Binding**: A Current_Draft Endpoint_Binding whose Validation_Report or Capability_Snapshot no longer matches the Endpoint_Registration's current passing evidence.
- **Topology_Snapshot**: A validated Endpoint topology payload, digest, and Endpoint_Binding revision pinned to one workflow version.
- **Binding_Status_Classifier**: SpinSci backend logic that distinguishes current binding evidence, stale binding evidence, unsupported topology, and unavailable validation evidence.
- **Authorized_User**: A tenant member whose role grants the permissions required for endpoint validation and workflow draft updates.
- **IntegrationGateway**: The SpinSci backend boundary that applies endpoint credentials, tenant context, audit, timeout, and network protections to external calls.

## Requirements

### Requirement 1: Preserve the SpinSci workflow canvas

**User Story:** As a workflow author, I want endpoint-owned graph topology to remain separate from my SpinSci workflow, so that existing workflows and editing behavior remain reliable.

#### Acceptance Criteria

1. WHEN a workflow is opened, THE SpinSci workflow canvas SHALL render only nodes and edges from the persisted `workflow_definition`.
2. THE SpinSci topology integration SHALL keep endpoint topology nodes and edges outside the workflow store, undo history, validation state, persistence model, and runtime-node transition state.
3. THE SpinSci workflow canvas SHALL retain the mandatory `startCall` node as a media and lifecycle shell without a visual connection to the Endpoint graph's `__start__` node.
4. WHEN a workflow has no Endpoint_Binding with a supported Topology_Operation, THE SpinSci workflow canvas SHALL retain the existing editor and runtime behavior.

### Requirement 2: Retrieve an explicit, versioned endpoint topology

**User Story:** As an endpoint integrator, I want to expose a stable graph topology contract, so that SpinSci can safely render the graph.

#### Acceptance Criteria

1. WHEN a Discovery_Manifest advertises `operations.topology`, THE Endpoint SHALL expose the authenticated, versioned Topology_Operation at the advertised path.
2. WHEN the Endpoint returns topology, THE Endpoint SHALL include a schema version, `graph_id`, `revision`, requested view, node collection, and edge collection.
3. WHEN the Endpoint returns a topology node, THE Endpoint SHALL include a stable endpoint-local `id` and display label.
4. WHEN the Endpoint returns a topology edge, THE Endpoint SHALL include source and target endpoint-local node IDs.
5. THE Topology_Operation SHALL support `collapsed` and `expanded` views.
6. WHEN SpinSci requests topology without an explicit view, THE SpinSci topology service SHALL request the `collapsed` view.
7. IF the current Discovery_Manifest omits `operations.topology` or the Endpoint returns the contract-defined unsupported response, THEN THE SpinSci topology service SHALL return an unsupported status without invalidating the Endpoint_Registration.

### Requirement 3: Securely proxy and pin topology through SpinSci

**User Story:** As an organization administrator, I want endpoint topology access to use the same tenant, credential, and network protections as endpoint invocation, so that topology inspection does not bypass integration security.

#### Acceptance Criteria

1. WHEN SpinSci retrieves Endpoint topology, THE SpinSci topology service SHALL invoke the Topology_Operation through IntegrationGateway.
2. WHEN IntegrationGateway invokes the Topology_Operation, THE IntegrationGateway SHALL apply endpoint authentication, tenant isolation, credential resolution, audit, timeout, and SSRF and private-network controls.
3. WHEN SpinSci receives a topology response, THE SpinSci topology service SHALL validate the response against the versioned topology DTO before exposing the response to the browser.
4. WHEN SpinSci pins topology to a workflow version, THE SpinSci topology service SHALL store the Topology_Snapshot and digest with the Endpoint_Binding revision.
5. WHEN SpinSci displays an Immutable_Version, THE SpinSci topology service SHALL return the version's pinned Topology_Snapshot without consulting mutable registration evidence.
6. THE SpinSci topology integration SHALL keep endpoint credentials and direct Endpoint network access outside the browser.

### Requirement 4: Render a separate read-only React Flow view

**User Story:** As a workflow author, I want to inspect the endpoint-owned LangGraph separately, so that I cannot accidentally change either graph.

#### Acceptance Criteria

1. WHEN a workflow contains an Endpoint_Binding, THE SpinSci workflow UI SHALL provide a separate topology pane, sheet, drawer, or tab reachable from endpoint configuration or the workflow editor.
2. WHEN the topology view renders a Topology_Snapshot, THE topology view SHALL use a dedicated React Flow instance with topology-specific node types, edge types, and endpoint-ID namespacing.
3. WHILE the topology view is open, THE topology view SHALL disable node dragging, connection, edit selection, deletion, and edge reconnection.
4. WHEN the topology view lays out a graph, THE topology view SHALL use a generic graph layout helper independent of SpinSci workflow node semantics.
5. WHEN the topology view receives topology nodes, THE topology view SHALL fit the topology into the viewport.
6. WHEN the topology view is not ready to render a graph, THE topology view SHALL present a distinct loading, empty, unsupported, stale, unavailable, or retrieval-error state.

### Requirement 5: Keep endpoint runtime state out of the initial scope

**User Story:** As an operator, I want static topology delivered safely before endpoint-internal runtime highlighting is considered, so that topology inspection remains independent of runtime event mapping.

#### Acceptance Criteria

1. WHEN the topology view renders Endpoint nodes, THE SpinSci runtime visualization SHALL keep Endpoint node IDs outside `WorkflowRuntimeNodeTransition` events and `activeRuntimeNodeId`.
2. WHERE a future endpoint runtime-status extension is enabled, THE endpoint runtime-status event SHALL use a separate event namespace and include the topology `revision` and endpoint-local `node_id`.
3. WHEN an Endpoint emits no runtime node status, THE topology view SHALL remain available for a pinned static Topology_Snapshot.

### Requirement 6: Distinguish stale binding evidence from unsupported topology

**User Story:** As a workflow author, I want SpinSci to identify outdated draft evidence separately from endpoint non-support, so that I can recover a draft after an Endpoint adds the Topology_Operation.

#### Acceptance Criteria

1. WHEN SpinSci evaluates topology availability for a Current_Draft, THE Binding_Status_Classifier SHALL compare the Endpoint_Binding's Validation_Report and Capability_Snapshot identities and digests with the Endpoint_Registration's current passing evidence within the same tenant.
2. WHEN the Endpoint_Binding evidence differs from current passing registration evidence and the current Capability_Snapshot advertises `operations.topology`, THE Binding_Status_Classifier SHALL return a stale-binding status with an explicit update action.
3. WHEN current passing registration evidence matches the Endpoint_Binding and the Capability_Snapshot advertises `operations.topology`, THE Binding_Status_Classifier SHALL return a current-and-supported status.
4. WHEN the current Capability_Snapshot omits `operations.topology`, THE Binding_Status_Classifier SHALL return `topology_unsupported` rather than stale-binding status.
5. IF the Endpoint_Registration has no current Passing_Validation_Report covering its current Capability_Snapshot, THEN THE Binding_Status_Classifier SHALL return a revalidation-required or validation-failed status that identifies the next action.
6. WHEN a user reads a Topology_Snapshot or binding status, THE SpinSci backend SHALL leave the Endpoint_Binding and Topology_Snapshot unchanged.

### Requirement 7: Revalidate and explicitly rebind only the current draft

**User Story:** As an Authorized_User, I want to update a stale draft binding from current passing endpoint evidence, so that I can adopt the Endpoint's advertised Topology_Operation without changing immutable workflow versions.

#### Acceptance Criteria

1. WHEN an Authorized_User requests endpoint revalidation, THE Endpoint_Registration service SHALL perform authenticated discovery and validation under the existing tenant and permission controls and retain the resulting Validation_Report and Capability_Snapshot.
2. WHEN an Authorized_User explicitly requests a Current_Draft rebind after validation passes, THE SpinSci binding service SHALL bind the Current_Draft to the Endpoint_Registration's current Passing_Validation_Report and covered Capability_Snapshot.
3. WHEN the SpinSci binding service rebinds a Current_Draft, THE SpinSci binding service SHALL update the validation report identity and digest, capability snapshot identity, digest, and payload, contract version, manifest operations, limits, ownership, and validation evidence from the same passing evidence set.
4. WHEN the SpinSci binding service rebinds a Current_Draft, THE SpinSci binding service SHALL preserve the registration identity, endpoint URL, credential reference, compatibility profile, state and invocation modes, Selected_Capabilities, data region, data-sharing policy, redaction policy, compiled policy versions, timeout actions, and failure actions.
5. IF the Endpoint_Registration's selected compatibility profile or Selected_Capabilities differ from the Current_Draft Endpoint_Binding, THEN THE SpinSci binding service SHALL reject the rebind with an actionable compatibility error.
6. IF the Endpoint_Registration, Validation_Report, Capability_Snapshot, workflow, or Current_Draft belongs to another tenant, THEN THE SpinSci binding service SHALL return a tenant-safe not-found or authorization response without changing either tenant's data.
7. IF the target workflow definition is an Immutable_Version, THEN THE SpinSci binding service SHALL reject revalidation-linked rebinding and topology replacement without changing the Immutable_Version.
8. WHEN an Authorized_User requests a Current_Draft rebind, THE SpinSci binding service SHALL require the existing endpoint-management and workflow-update permissions before changing the Endpoint_Binding.

### Requirement 8: Refresh and pin topology through an explicit draft lifecycle action

**User Story:** As a workflow author, I want a draft-only action that updates stale endpoint evidence and pins current topology, so that the displayed graph is version-local and reproducible.

#### Acceptance Criteria

1. WHEN an Authorized_User invokes the draft topology update action for a Stale_Binding, THE SpinSci workflow UI SHALL guide the Authorized_User through endpoint revalidation and activation when required, explicit draft rebinding, and topology refresh.
2. WHEN an Authorized_User invokes the draft topology update action for a current Endpoint_Binding, THE SpinSci topology service SHALL refresh topology without replacing current binding evidence.
3. WHEN a Current_Draft is rebound successfully, THE SpinSci topology service SHALL fetch the `collapsed` Topology_Operation through IntegrationGateway and pin the resulting Topology_Snapshot to the rebound Capability_Snapshot identity.
4. WHEN an Authorized_User explicitly refreshes a supported Current_Draft topology, THE SpinSci topology service SHALL atomically replace only that Current_Draft's Topology_Snapshot after response validation succeeds.
5. IF topology retrieval, authentication, network access, or schema validation fails, THEN THE SpinSci topology service SHALL preserve the Current_Draft's existing Topology_Snapshot and return an actionable failure status.
6. WHEN the topology update action completes, THE SpinSci workflow UI SHALL show whether endpoint validation, draft rebinding, topology retrieval, and snapshot pinning succeeded or identify the failed stage.
7. WHILE an Immutable_Version is displayed, THE SpinSci workflow UI SHALL hide or disable revalidation, rebinding, and topology refresh actions and SHALL display only the version-local Topology_Snapshot status.
8. WHEN a workflow draft is published or copied into history, THE SpinSci workflow versioning service SHALL retain the draft's Endpoint_Binding and Topology_Snapshot as version-local immutable data.

### Requirement 9: Provide actionable topology status and errors

**User Story:** As a workflow author, I want clear topology status and recovery guidance, so that I can resolve stale evidence and endpoint failures without guessing.

#### Acceptance Criteria

1. WHEN a Topology_Snapshot is absent, THE SpinSci workflow UI SHALL display `snapshot_unavailable` guidance that directs an Authorized_User to update and refresh the Current_Draft.
2. WHEN current passing endpoint evidence omits the Topology_Operation, THE SpinSci workflow UI SHALL display `topology_unsupported` guidance that directs the user to inspect authenticated discovery and restart or update the Endpoint.
3. WHEN the Binding_Status_Classifier reports a Stale_Binding, THE SpinSci workflow UI SHALL state that the draft uses older endpoint evidence and offer the draft-only update action.
4. IF endpoint authentication fails, THEN THE SpinSci workflow UI SHALL display credential-oriented recovery guidance without exposing secret values.
5. IF endpoint network access fails, THEN THE SpinSci workflow UI SHALL display endpoint availability and network-policy recovery guidance.
6. IF endpoint discovery or topology schema validation fails, THEN THE SpinSci workflow UI SHALL display schema-oriented recovery guidance with a redacted diagnostic.

### Requirement 10: Document the end-to-end user workflow

**User Story:** As a SpinSci user, I want a LangGraph topology guide, so that I can configure, refresh, view, and troubleshoot endpoint topology.

#### Acceptance Criteria

1. WHEN the follow-up implementation is ready for documentation, THE SpinSci documentation set SHALL include `docs/integrations/langgraph-topology.mdx` with valid YAML frontmatter and second-person instructions.
2. THE LangGraph topology guide SHALL describe prerequisites, Endpoint start or restart, and authenticated verification that the Discovery_Manifest contains `operations.topology`.
3. THE LangGraph topology guide SHALL describe endpoint validation and activation in LangGraph Endpoints, opening or creating a Current_Draft, explicitly updating the Endpoint_Binding, refreshing topology, and viewing the pinned topology.
4. THE LangGraph topology guide SHALL troubleshoot `snapshot_unavailable`, `topology_unsupported`, authentication failures, network failures, and schema failures.
5. WHEN the LangGraph topology guide includes a shell or `curl` example, THE documentation implementation SHALL use placeholders for secret values and validate the command against the implemented endpoint contract.
6. WHEN the LangGraph topology guide is created, THE SpinSci documentation navigation SHALL include the guide in `docs/docs.json`.
