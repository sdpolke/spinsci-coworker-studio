# LangGraph Validate Endpoint No-Op Bugfix Design

## Overview

`request_validation()` in `endpoint_registration.py` only performs the `lifecycle_status` transition to
`pending_validation` (or an early-return no-op if already there). It never runs discovery
(`gateway.discover_manifest` + `discovery.record_capability_snapshot`), never runs the conformance suite
(`conformance/runner.run_suite`), and never calls `db_client.insert_langgraph_validation_report`. Because no
`Validation_Report` row is ever created, `activate_endpoint()`'s evidence check
(`db_client.get_current_langgraph_activation_evidence`) always resolves `report=None`, and activation always fails
with `ActivationEvidenceError("current validation evidence is required")` — independent of whether the endpoint
would actually pass conformance (bugfix.md 1.1–1.3).

The fix dispatches an idempotent ARQ background job (`validate_langgraph_endpoint`, new file
`api/tasks/langgraph_validation.py`) from `request_validation()` — for both the "not yet pending_validation" and
"already pending_validation" cases (bugfix.md 2.1, 2.2) — that runs discovery then the conformance suite and
persists a `Validation_Report` on every outcome, success or failure (bugfix.md 2.3). `activate_endpoint()`'s
existing evidence-matching logic is not touched (bugfix.md 2.4, 3.5, 3.6): this bugfix only ensures a report
exists to evaluate; it does not change how that report is evaluated.

## Glossary

- **Bug_Condition (C)**: Every call to `request_validation()` — no code path ever dispatches discovery/conformance
  or persists a `Validation_Report`, regardless of the endpoint's current `lifecycle_status`.
- **Property (P)**: After the fixed `request_validation()` runs, a validation job for that endpoint has been
  enqueued and, once executed, a `Validation_Report` row exists that `get_current_langgraph_activation_evidence`
  can retrieve — on both a passing and a failing validation run.
- **Preservation**: The permission checks, feature-flag checks, lifecycle transition rules, concurrent
  compare-and-set semantics, and `activate_endpoint`'s existing evidence-matching checks (bugfix.md 3.1–3.7) must
  behave exactly as they do today.
- **discover_manifest**: Existing function in `api/services/langgraph_integration/gateway.py` that performs the
  authenticated, SSRF-checked GET against `{endpoint_url}/.well-known/mural-langgraph` and returns a
  `DiscoveryResult(manifest, final_url, redirects, peer_address)`.
- **record_capability_snapshot**: Existing function in `api/services/langgraph_integration/discovery.py` that
  normalizes an already-fetched manifest and persists it via `db_client.insert_langgraph_capability_snapshot`.
- **run_suite**: Existing function in `api/services/langgraph_integration/conformance/runner.py` that executes the
  `CHAT_BASELINE_FIXTURES` deterministic fixture set and returns a `ConformanceSuiteResult`.
- **validate_langgraph_endpoint**: New ARQ job function (this bugfix) that orchestrates discovery, negotiation,
  the conformance suite, and `Validation_Report` persistence for one endpoint.

## Bug Details

### Bug Condition

The bug manifests on every call to `request_validation()`. The function transitions (or no-ops on) lifecycle
status but never invokes discovery, negotiation, or the conformance suite, and never writes a
`Validation_Report`.

**Formal Specification:**
```
FUNCTION isBugCondition(X)
  INPUT: X of type ValidateRequest
  OUTPUT: boolean

  // True for every call to request_validation, regardless of endpoint state,
  // because no code path ever dispatches discovery/conformance or writes a report.
  RETURN true
END FUNCTION
```

### Examples

- Endpoint in `validation_only` calls `POST .../validate` → transitions to `pending_validation`, returns 200, but
  no `LangGraphCapabilitySnapshotModel` or `LangGraphValidationReportModel` row is ever created. A subsequent
  `POST .../activate` call fails with `ActivationEvidenceError("current validation evidence is required")` even
  if the endpoint's manifest and runtime are fully conformant.
- Endpoint already in `pending_validation` calls `POST .../validate` again (e.g. retrying after fixing the
  endpoint's manifest) → the early return in `request_validation()` re-checks permission/feature-flag and returns
  the endpoint unchanged. No new discovery attempt is made, so a previously broken endpoint that has since been
  fixed can never get a passing report without an operator manually invoking discovery/conformance out of band
  (which no route or job currently exposes).
- Edge case — endpoint's manifest is genuinely broken (invalid JSON, unreachable host): today this produces the
  exact same symptom as a healthy endpoint (missing report, HTTP 409 on activate), so an operator cannot
  distinguish "never validated" from "failed validation" from the API alone.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- `require_permission` continues to reject callers lacking `LangGraphPermission.VALIDATE` before any lifecycle or
  validation work occurs (bugfix.md 3.1).
- `require_feature_enabled` continues to reject validate/activate calls when the org's LangGraph feature is
  disabled (bugfix.md 3.2).
- `require_transition` continues to raise `InvalidLifecycleTransition` for disallowed `target_status` values
  (bugfix.md 3.3).
- `compare_and_set_langgraph_lifecycle`'s compare-and-set semantics continue to raise
  `InvalidLifecycleTransition` on a lost race between concurrent lifecycle changes (bugfix.md 3.4).
- `activate_endpoint`'s existing evidence checks (report status not passing, snapshot mismatch, profile
  mismatch, degraded-health) continue to raise their corresponding `ActivationEvidenceError` exactly as today
  (bugfix.md 3.5).
- `activate_endpoint`'s degraded-lifecycle health-evidence check is unchanged (bugfix.md 3.6).
- `sweep_langgraph_retention` and other existing registered ARQ jobs/cron entries continue to run on their
  existing schedules, unaffected by the newly registered validation job (bugfix.md 3.7).

**Scope:**
All behavior outside `request_validation()`'s dispatch of validation work is unaffected by this fix, including
`create_endpoint`, `update_endpoint`, `transition_endpoint`, `delete_or_retire_endpoint`, and every check inside
`activate_endpoint` after the evidence tuple is obtained.

## Hypothesized Root Cause

1. **Missing dispatch entirely**: `request_validation()` was implemented to only perform the lifecycle
   transition; the discovery → conformance → persist pipeline that the function's docstring/route name implies
   was never wired in.
2. **No ARQ job registered**: `api/tasks/arq.py`'s `WorkerSettings.functions` has no per-endpoint validation job —
   only `sweep_langgraph_retention` exists for LangGraph, and it is a retention sweep, not a validation runner.
3. **No manifest-fetch call site**: `discovery.record_capability_snapshot` takes an already-fetched manifest; the
   actual authenticated HTTP GET (`gateway.discover_manifest`) exists but is never invoked from any endpoint
   lifecycle code path — it is currently only exercised directly by gateway tests.
4. **Already-pending_validation short-circuit**: the `if endpoint.lifecycle_status == "pending_validation":
   ... return endpoint` branch was written to avoid an `InvalidLifecycleTransition` (transitioning to the same
   status), but as a side effect it also skips any and all validation dispatch on retry.

## Correctness Properties

Property 1: Bug Condition - Validate Action Dispatches Validation Work And Persists A Report

_For any_ call to `request_validation(organization_id, endpoint_uuid, role)` that passes permission and
feature-flag checks (i.e. `isBugCondition` holds for every such call today), the fixed function SHALL enqueue an
idempotent `validate_langgraph_endpoint` ARQ job for that endpoint uuid, and once that job runs to completion a
`Validation_Report` SHALL exist for the endpoint such that `get_current_langgraph_activation_evidence` returns a
non-`None` report — regardless of whether discovery/negotiation/conformance for that endpoint ultimately succeed
or fail, and regardless of whether the endpoint's `lifecycle_status` was already `pending_validation` before the
call.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation - Permission, Feature-Flag, Lifecycle, And Activation-Evidence-Evaluation Behavior Unchanged

_For any_ input to `request_validation`, `transition_endpoint`, or `activate_endpoint` that does NOT concern
whether validation work is dispatched or a report is created (i.e. permission denial, feature disabled, invalid
lifecycle transitions, concurrent lifecycle races, and `activate_endpoint`'s evaluation of an existing report's
status/snapshot/profile/health fields), the fixed code SHALL produce exactly the same outcome as the original
code.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**

## Fix Implementation

### Changes Required

**File**: `api/services/langgraph_integration/endpoint_registration.py`

**Function**: `request_validation`

**Specific Changes**:
1. Remove the early-return no-op for the already-`pending_validation` case. Both branches (transition needed,
   already `pending_validation`) SHALL end by calling a new helper, `_dispatch_validation(organization_id,
   endpoint_uuid)`, after permission/feature-flag checks succeed and after any lifecycle transition attempt
   (transition failures — `InvalidLifecycleTransition` — must still propagate and must NOT dispatch a job).
2. `_dispatch_validation` enqueues the ARQ job via `api.tasks.arq.enqueue_job` (lazy import, matching the existing
   pattern in `run_integrations.py` and `webhook_delivery.py`, to avoid a circular import since `arq.py` imports
   task modules at load time):
   ```python
   from api.tasks.arq import enqueue_job
   from api.tasks.function_names import FunctionNames

   await enqueue_job(
       FunctionNames.VALIDATE_LANGGRAPH_ENDPOINT,
       organization_id,
       endpoint_uuid,
       _job_id=f"langgraph_validate:{endpoint_uuid}",
   )
   ```
   The deterministic `_job_id` (endpoint-scoped, no per-call token) is what makes rapid duplicate "Validate"
   clicks idempotent: ARQ rejects/collapses a second enqueue with the same job id while the first job is queued
   or running, so only one validation run is in flight per endpoint at a time. This mirrors the existing
   `webhook-delivery-{id}-0` / `inactive-text-chat-completion-{run_id}-{revision}` deterministic-job-id pattern
   already used in `run_integrations.py` and `text_chat_inactivity.py`.

**File**: `api/tasks/function_names.py`

**Specific Changes**:
3. Add `VALIDATE_LANGGRAPH_ENDPOINT = "validate_langgraph_endpoint"` to `FunctionNames`.

**File**: `api/tasks/langgraph_validation.py` (new)

**Specific Changes**:
4. Add `async def validate_langgraph_endpoint(ctx, organization_id: int, endpoint_uuid: str) -> None:` that:
   - Loads the endpoint via `db_client.get_langgraph_endpoint(organization_id=organization_id,
     endpoint_uuid=endpoint_uuid)`. If `None`, log and return (endpoint deleted/retired since enqueue — no report
     to write).
   - Resolves the endpoint's credential auth headers. The endpoint row stores `credential_id` (an internal FK),
     not a `credential_uuid`, so `db_client.get_credential_by_uuid` does not apply here. A new small DB client
     method (or an inline session query following the same organization-scoped `ExternalCredentialModel` lookup
     already used in `create_endpoint` and `get_langgraph_endpoint_management_view`, i.e. filter by `id ==
     endpoint.credential_id AND organization_id == organization_id`) resolves the credential row; headers are
     then built with `api.utils.credential_auth.build_auth_header`.
   - Calls `gateway.discover_manifest(endpoint_url=endpoint.endpoint_url, auth_headers=auth_headers,
     feature_configuration=<org's LangGraphFeatureConfiguration>)`.
     - **On `DiscoveryTimeoutError` / `InvalidManifestError` / `UnsafeDestinationError` / other `DiscoveryError`**:
       skip negotiation and the conformance suite, and persist a **failing** `Validation_Report` (see step 6)
       with `capability_snapshot_id=None`, `status="failed"`, and `evidence` describing the discovery failure
       (error class name + safe message; no raw exception internals or credential data). This satisfies bugfix.md
       2.3 for the discovery-failure path — activate then fails with `ActivationEvidenceError("current
       validation report is not passing")`, a real "not passing" reason, instead of "evidence is required".
   - **On successful discovery**: calls `discovery.record_capability_snapshot(store=db_client,
     organization_id=organization_id, registration_id=endpoint.id, manifest=discovery_result.manifest)` to persist
     the snapshot (reuses the existing immutable-snapshot dedup-by-digest behavior).
   - Loads the current compatibility matrix via `db_client.list_langgraph_compatibility_matrices()` and takes
     index `0` (most recently effective), matching the existing "current" selection convention already used in
     `routes/langgraph_endpoints.py`'s `list_langgraph_compatibility_matrices` handler (`current=index==0`).
     Constructs the `MatrixVersion` used by `discovery.negotiate_capabilities` from that row's `matrix` JSON
     column (already shaped as a `MatrixVersion.model_dump()`-compatible payload per
     `contract/catalog.COMPATIBILITY_MATRICES`).
   - Calls `discovery.negotiate_capabilities(manifest=discovery_result.manifest, matrix=<matrix>,
     selected_profile=endpoint.selected_profile, selected_invocation_modes=endpoint.selected_capabilities ∩
     known invocation modes, selected_state_mode=<profile's allowed state mode>, selected_features=...)`.
     - **On `CapabilitySelectionError`**: persist a failing `Validation_Report` with the negotiated snapshot id
       (snapshot was already recorded) and `evidence={"negotiation_failed": True, "reasons": [...]}`,
       `status="failed"`. Skip the conformance suite (there's no meaningful profile/contract to run it against).
   - **On successful negotiation**: calls `conformance.runner.run_suite()` (the existing deterministic
     `CHAT_BASELINE_FIXTURES` set — see Non-Goals; this bugfix does not add live-endpoint-driven conformance).
   - Persists the `Validation_Report` (success or failure — see step 6 for the shared persistence call) using
     `suite_result.report_evidence()` for `evidence`, `suite_result.persistence_results()` for `results`,
     `status` derived from `suite_result.passed` (`"passed"` if true, `"failed"` if false — reusing
     `lifecycle.PASSING_REPORT_STATUSES` membership is not needed here since only the conformance-only outcomes
     `passed`/`failed` are produced by this job; `live_voice_eligible` remains produced elsewhere and is not
     claimed by this job — see Non-Goals), `report_digest` from `conformance.deterministic_digest` over the
     evidence+results payload (so retries with identical fixture results are idempotent against the report table's
     `uq_langgraph_report_registration_digest` unique constraint), `started_at`/`completed_at` bracketing the job
     run, `capability_snapshot_id` from the recorded snapshot, `compatibility_matrix_id` from the loaded matrix
     row, `contract_version` from the negotiated result, `selected_profile` from the endpoint.
5. All exception branches (discovery, negotiation, conformance, or unexpected) SHALL still call
   `db_client.insert_langgraph_validation_report` before returning, so **every** invocation of the job — success
   or failure — leaves a report behind (bugfix.md 2.3, satisfying the "meaningful not-passing report rather than
   missing evidence" requirement from the task description). An unexpected exception not anticipated above
   (e.g. a DB error while loading the endpoint) is logged and allowed to propagate so ARQ's normal failure/retry
   visibility applies; it is not swallowed into a synthetic report, since no attempt was actually made against
   the endpoint in that case.
6. `insert_langgraph_validation_report`'s existing side effects — setting
   `registration.current_validation_report_id` / `current_capability_snapshot_id` and flipping
   `lifecycle_status` to `incompatible` on failure or `validation_only` on a non-active passing/validation_only
   status — are reused as-is; this bugfix does not change that method.

**File**: `api/tasks/arq.py`

**Specific Changes**:
7. Import `validate_langgraph_endpoint` from `api.tasks.langgraph_validation` and add it to
   `WorkerSettings.functions` (alongside the existing `sweep_langgraph_retention` entry). No change to
   `cron_jobs` — this is an on-demand job, not scheduled.

## Testing Strategy

### Validation Approach

First, exploration tests on the current (unfixed) `request_validation()` demonstrate that no job is enqueued and
no report is ever created (Property 1 test), confirming bugfix.md 1.1–1.3. Then preservation tests capture
today's behavior of permission/feature/lifecycle/activation-evidence-evaluation checks so the fix does not
regress them (Property 2 test). The fix is implemented, then both test groups are re-run to confirm the bug is
resolved and nothing else changed.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that show `request_validation()` never dispatches validation work or persists a
report, for both the "needs transition" and "already pending_validation" cases.

**Test Plan**: Extend `api/tests/langgraph_integration/test_endpoint_lifecycle.py`. Mock
`db_client.get_langgraph_endpoint`, `db_client.compare_and_set_langgraph_lifecycle`, and (once the fix lands) spy
on `api.tasks.arq.enqueue_job`. On unfixed code, call `request_validation` for (a) an endpoint in
`validation_only` and (b) an endpoint already in `pending_validation`, and assert `enqueue_job` is never called
and `db_client.insert_langgraph_validation_report` is never called.

**Test Cases**:
1. **Not-yet-pending validate dispatches nothing**: endpoint starts in `validation_only`; call
   `request_validation`; assert no enqueue and no report insert (will fail — actually pass trivially — on unfixed
   code in the sense that the *absence* of a call is what's asserted; this is the counterexample demonstrating
   the bug).
2. **Already-pending validate dispatches nothing**: endpoint starts in `pending_validation`; call
   `request_validation` again; assert no enqueue and no report insert.

**Expected Counterexamples**:
- `enqueue_job` (or the eventual dispatch hook) is never invoked from `request_validation` in either case.
- No `Validation_Report` row is ever created, confirming the root cause: there is no code path from validate to
  discovery/conformance/persistence.

### Fix Checking

**Goal**: Verify that after the fix, every `request_validation` call (bug condition holds unconditionally) ends
with a dispatched job and — once that job runs — a persisted `Validation_Report`, for the success and failure
paths of discovery/negotiation/conformance.

**Pseudocode:**
```
FOR ALL X WHERE isBugCondition(X) DO
  request_validation'(X)
  ASSERT job_enqueued(X.endpoint_uuid, job_id = f"langgraph_validate:{X.endpoint_uuid}")
  run_enqueued_job(X.endpoint_uuid)
  ASSERT validation_report_created_for(X.endpoint_uuid)
END FOR
```

### Preservation Checking

**Goal**: Verify permission checks, feature-flag checks, lifecycle transition rules, concurrency semantics, and
`activate_endpoint`'s evidence-evaluation logic are byte-for-byte unchanged.

**Pseudocode:**
```
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT request_validation(X) = request_validation'(X)
END FOR
```
(As noted in bugfix.md, since the validate action's dispatch defect is universal, preservation here means: the
surrounding permission/feature/lifecycle/activation-evidence-evaluation code paths, which are a different concern
from "was validation work dispatched", are unaffected.)

**Testing Approach**: The existing `test_endpoint_lifecycle.py` tests already assert
`activation_requires_current_passing_snapshot_evidence` and `degraded_reactivation_requires_current_health`
against mocked evidence tuples — these are reused unmodified as regression tests (they exercise
`activate_endpoint` code this bugfix does not touch). New property-based tests are added for `request_validation`
permission/feature-flag denial and for `transition_endpoint`'s allowed/disallowed transition table (reusing
`EXPECTED_TRANSITIONS` already defined in that file) to confirm no change in behavior when validation dispatch is
added.

**Test Plan**: Observe on unfixed code that (a) a caller lacking `VALIDATE` gets `LangGraphAuthorizationError`
before any DB call, (b) a disabled feature gets `FeatureDisabledError`, (c) `can_transition`/`require_transition`
matches `EXPECTED_TRANSITIONS` exactly, (d) a lost compare-and-set race raises `InvalidLifecycleTransition`. Then
assert the same on fixed code.

**Test Cases**:
1. **Permission denial preserved**: role without `VALIDATE` calling `request_validation` still raises
   `LangGraphAuthorizationError` and performs zero DB/enqueue calls.
2. **Feature-disabled preserved**: `require_feature_enabled` raising `FeatureDisabledError` still short-circuits
   before any lifecycle or dispatch work.
3. **Lifecycle transition table preserved**: `test_lifecycle_transition_table_is_explicit_and_closed` (existing
   test) continues to pass unmodified.
4. **Concurrent lifecycle race preserved**: a lost `compare_and_set_langgraph_lifecycle` race still raises
   `InvalidLifecycleTransition` and — critically — does NOT enqueue a validation job for the losing caller.
5. **Activation evidence evaluation preserved**: `test_activation_requires_current_passing_snapshot_evidence` and
   `test_degraded_reactivation_requires_current_health` (existing tests) continue to pass unmodified.
6. **Idempotent duplicate dispatch**: two rapid `request_validation` calls for the same endpoint enqueue the job
   at most once (same deterministic `_job_id`); the second `enqueue_job` call either raises/no-ops per ARQ's
   duplicate-job-id behavior or is a harmless no-op, and in no case are two `validate_langgraph_endpoint` jobs
   observed running concurrently for the same endpoint.

### Unit Tests

- `_dispatch_validation` enqueues with the exact job id `f"langgraph_validate:{endpoint_uuid}"`.
- `request_validation` calls `_dispatch_validation` in both the transition and already-`pending_validation`
  branches, and does NOT call it when `require_permission`/`require_feature_enabled`/`require_transition` raise.
- `validate_langgraph_endpoint` persists a failing report (not a raised exception) on `DiscoveryTimeoutError`,
  `InvalidManifestError`, and `UnsafeDestinationError`.
- `validate_langgraph_endpoint` persists a failing report on `CapabilitySelectionError` from negotiation.
- `validate_langgraph_endpoint` persists a passing or failing report based on `ConformanceSuiteResult.passed`.
- `validate_langgraph_endpoint` returns early (no report) when the endpoint no longer exists.

### Property-Based Tests

- For all `LangGraphRole` × `LangGraphPermission.VALIDATE` combinations, `request_validation` dispatches a job if
  and only if `is_langgraph_authorized` returns true and the feature is enabled — matching pre-fix authorization
  outcomes exactly.
- For all pairs of (current `lifecycle_status`, `target_status="pending_validation"`), `can_transition` results
  used by `request_validation` match `EXPECTED_TRANSITIONS` exactly, unaffected by the added dispatch call.
- For randomly generated discovery failure types (timeout, invalid manifest, unsafe destination), the persisted
  report always has `status != "passed"` and `completed_at` is set (never `None`), so `activate_endpoint` reports
  "not passing" rather than "evidence is required".

### Integration Tests

- End-to-end: call the `/validate` route, run the enqueued ARQ job inline (test harness), then call `/activate` —
  for a manifest that would pass conformance, activation now succeeds (subject to the existing snapshot/profile
  match checks); for a manifest that fails discovery, activation now fails with "not passing" instead of
  "evidence is required".
- Re-validate a `pending_validation` endpoint a second time (simulating a "Validate" retry after fixing the
  endpoint) and confirm a new `Validation_Report` is created reflecting the corrected manifest.
- Rapid double-click of the `/validate` route enqueues the job once (dedup by job id verified against the ARQ
  test/fake redis harness already used, if any, or by asserting `enqueue_job` call count / job id equality in a
  mocked-redis unit test since ARQ itself is not exercised end-to-end in the existing test suite).

## Non-Goals / Known Limitations

- **This bugfix does not add real-endpoint-driven conformance.** `conformance/runner.run_suite()` executes the
  deterministic `CHAT_BASELINE_FIXTURES` script set entirely in-process (no network calls); it does not replay
  the discovered manifest's live behavior against those fixtures. The persisted `Validation_Report`'s conformance
  portion reflects deterministic fixture conformance against the pinned contract, not observed behavior of this
  specific endpoint's runtime beyond what discovery/negotiation already checked (declared capabilities,
  reachability, manifest validity). This matches today's `run_suite` capability and is not extended by this
  bugfix.
- **This bugfix does not change the conformance suite's fixture set** or add new fixtures.
- **This bugfix does not change `activate_endpoint`'s evidence-evaluation logic.** It only ensures a report
  exists for that logic to evaluate; report status, snapshot/profile matching, and degraded-health evidence
  checks are unchanged (bugfix.md 3.5, 3.6).
- **This bugfix does not add new lifecycle states.** `incompatible`/`validation_only`/etc. transitions triggered
  by `insert_langgraph_validation_report` reuse existing states and existing transition rules in `lifecycle.py`.
- **This bugfix does not implement synchronous (inline, non-ARQ) validation.** bugfix.md 2.1 permits either
  synchronous or ARQ-based dispatch; this design chooses ARQ exclusively (matching the existing webhook-delivery
  and text-chat-completion background-job patterns in this codebase) so the `/validate` HTTP call remains fast
  and does not block on a potentially slow (5s discovery timeout + conformance run) network round trip.
- **This bugfix does not change how discovery's HTTP fetch (`gateway.discover_manifest`) works** — it reuses the
  existing SSRF-checked, timeout-bounded implementation as-is; it only adds the first call site that actually
  invokes it as part of endpoint validation.
- **Idempotency is best-effort duplicate-suppression, not exactly-once.** The deterministic ARQ job id prevents
  two jobs from being queued for the same endpoint at the same time, but does not prevent two sequential
  validation runs (e.g. click "Validate", wait for completion, click "Validate" again) from producing two
  separate `Validation_Report` rows — that is the intended behavior for bugfix.md 2.2 (re-dispatching a stuck or
  previously-failed validation).
