# Implementation Plan: LangGraph Validate Endpoint No-Op Bugfix

## Overview

This plan fixes `request_validation()` in `api/services/langgraph_integration/endpoint_registration.py` so it
actually dispatches validation work (discovery → negotiation → conformance) and persists a `Validation_Report`,
instead of only flipping `lifecycle_status`. Exploration and preservation tests are written and run against the
current (unfixed) code first, then the fix is implemented, then both test groups are re-run to confirm the bug is
resolved with no regressions.

## Tasks

- [x] 1. Write bug condition exploration test — validate dispatches nothing today
  - **Property 1: Bug Condition** - Validate Action Never Dispatches Validation Work Or Persists A Report
  - **IMPORTANT**: Write this test BEFORE implementing the fix, and run it against the current UNFIXED
    `request_validation()`.
  - **GOAL**: Surface counterexamples proving `request_validation()` never enqueues a job and never creates a
    `Validation_Report`, for both lifecycle branches.
  - Extend `api/tests/langgraph_integration/test_endpoint_lifecycle.py`. Mock
    `db_client.get_langgraph_endpoint`, `db_client.compare_and_set_langgraph_lifecycle`, and
    `db_client.insert_langgraph_validation_report`, and spy/mock `api.tasks.arq.enqueue_job`.
  - Test case (a) — endpoint starts in `validation_only`: call `request_validation`; assert
    `enqueue_job` was never awaited and `insert_langgraph_validation_report` was never awaited (per bugfix.md
    1.1, isBugCondition holds unconditionally per design.md's Bug Condition spec).
  - Test case (b) — endpoint starts in `pending_validation`: call `request_validation` again; assert the same
    zero-dispatch outcome (per bugfix.md 1.2).
  - Run both tests on the current unfixed code. **EXPECTED OUTCOME**: both tests PASS today (the absence of a
    dispatch call is exactly the counterexample that demonstrates the bug — the "failure" being proven is the
    missing behavior itself, not a test failure). Document this observation in the task/PR notes so it is clear
    these two tests currently encode the *defect*, and will be repurposed as fix-checking assertions (task 6)
    once behavior changes.
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Permission, Feature-Flag, Lifecycle, And Activation-Evidence-Evaluation
    Behavior Unchanged
  - **IMPORTANT**: Follow observation-first methodology — observe behavior on UNFIXED code, then encode it as
    property-based tests.
  - Observe on unfixed code: a role without `LangGraphPermission.VALIDATE` calling `request_validation` raises
    `LangGraphAuthorizationError` and performs zero DB/enqueue calls (bugfix.md 3.1).
  - Observe on unfixed code: `require_feature_enabled` raising `FeatureDisabledError` short-circuits before any
    lifecycle or dispatch work (bugfix.md 3.2).
  - Write a property-based test over all `(LangGraphRole, target_status)` pairs asserting `can_transition`
    results match `EXPECTED_TRANSITIONS` (already defined in `test_endpoint_lifecycle.py`) exactly, and that
    `require_transition` raises `InvalidLifecycleTransition` for every disallowed pair (bugfix.md 3.3).
  - Write a test that a lost `compare_and_set_langgraph_lifecycle` race (mocked to return `False`) still raises
    `InvalidLifecycleTransition` from `transition_endpoint` (bugfix.md 3.4).
  - Add these as new tests in `api/tests/langgraph_integration/test_endpoint_lifecycle.py`, reusing
    `EXPECTED_TRANSITIONS` and the existing `_user`/mocking patterns in that file. Use Hypothesis
    (`st.sampled_from(list(LangGraphRole))` / `st.sampled_from(sorted(EndpointLifecycle))`) since this test
    module's sibling `api/tests/langgraph_integration/properties/` package already depends on and uses Hypothesis
    for role/permission and transition-table style properties (see `test_property_24_denied_authorization.py`
    and `test_property_1_live_voice_eligibility.py`).
  - Confirm the existing `test_activation_requires_current_passing_snapshot_evidence` and
    `test_degraded_reactivation_requires_current_health` tests in the same file still pass unmodified on unfixed
    code (bugfix.md 3.5, 3.6) — no code change needed here, just re-run them as a baseline.
  - Run all of the above on the current UNFIXED code. **EXPECTED OUTCOME**: all tests PASS (this confirms the
    baseline behavior to preserve through the fix).
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 3. Add the new ARQ job name to `FunctionNames`
  - In `api/tasks/function_names.py`, add `VALIDATE_LANGGRAPH_ENDPOINT = "validate_langgraph_endpoint"` to the
    `FunctionNames` class (design.md "Fix Implementation" step 3).
  - Verify by importing `FunctionNames.VALIDATE_LANGGRAPH_ENDPOINT` in a quick Python check / existing test
    collection (no dedicated test needed for a plain string constant; covered by task 4's tests importing it).
  - _Requirements: 2.1, 2.2_

- [x] 4. Implement `validate_langgraph_endpoint` job in `api/tasks/langgraph_validation.py`
  - Create new file `api/tasks/langgraph_validation.py` with
    `async def validate_langgraph_endpoint(ctx, organization_id: int, endpoint_uuid: str) -> None:` per
    design.md's "Fix Implementation" step 4.
  - Load the endpoint via `db_client.get_langgraph_endpoint(organization_id=organization_id,
    endpoint_uuid=endpoint_uuid)`; if `None`, log and return without writing a report (endpoint deleted/retired
    since enqueue).
  - Resolve the endpoint's credential: look up the `ExternalCredentialModel` row scoped by
    `id == endpoint.credential_id AND organization_id == organization_id` (following the same pattern already
    used in `create_endpoint` / `get_langgraph_endpoint_management_view`), then build auth headers with
    `api.utils.credential_auth.build_auth_header`.
  - Call `gateway.discover_manifest(endpoint_url=endpoint.endpoint_url, auth_headers=auth_headers,
    feature_configuration=<org's LangGraphFeatureConfiguration>)`.
    - On `DiscoveryTimeoutError` / `InvalidManifestError` / `UnsafeDestinationError` (or other `DiscoveryError`):
      skip negotiation/conformance and persist a failing `Validation_Report`
      (`capability_snapshot_id=None`, `status="failed"`, `completed_at` set, `evidence` describing the error
      class name and a safe message, no raw exception internals or credential data) via
      `db_client.insert_langgraph_validation_report`.
  - On successful discovery: call `discovery.record_capability_snapshot(store=db_client,
    organization_id=organization_id, registration_id=endpoint.id, manifest=discovery_result.manifest)` to persist
    the capability snapshot.
  - Load the current compatibility matrix via `db_client.list_langgraph_compatibility_matrices()` and take
    index `0` (matching the `current=index==0` convention in `routes/langgraph_endpoints.py`), and build the
    `MatrixVersion` used by negotiation from that row's `matrix` JSON column.
  - Call `discovery.negotiate_capabilities(manifest=discovery_result.manifest, matrix=<matrix>,
    selected_profile=endpoint.selected_profile, selected_invocation_modes=..., selected_state_mode=...,
    selected_features=...)`.
    - On `CapabilitySelectionError`: persist a failing `Validation_Report` with the already-recorded snapshot id,
      `status="failed"`, `evidence={"negotiation_failed": True, "reasons": [...]}`, skipping the conformance
      suite.
  - On successful negotiation: call `conformance.runner.run_suite()` and persist the resulting
    `Validation_Report` using `suite_result.report_evidence()` for `evidence`,
    `suite_result.persistence_results()` for `results`, `status` = `"passed"` if `suite_result.passed` else
    `"failed"`, `report_digest` from `conformance.runner.deterministic_digest` over the evidence+results
    payload, `started_at`/`completed_at` bracketing the job run, `capability_snapshot_id` from the recorded
    snapshot, `compatibility_matrix_id` from the loaded matrix row, `contract_version` from the negotiated
    result, `selected_profile` from the endpoint.
  - Ensure every branch (discovery failure, negotiation failure, and the success path) calls
    `db_client.insert_langgraph_validation_report` before returning, per design.md step 5. Let unexpected
    exceptions (e.g. a DB error while loading the endpoint) propagate uncaught rather than being swallowed into
    a synthetic report.
  - Write unit tests in a new `api/tests/langgraph_integration/test_langgraph_validation_job.py` covering:
    - endpoint-not-found returns early with no report insert;
    - `DiscoveryTimeoutError` / `InvalidManifestError` / `UnsafeDestinationError` each persist a failing report
      with `capability_snapshot_id=None` and `status="failed"`;
    - `CapabilitySelectionError` from negotiation persists a failing report referencing the recorded snapshot;
    - a passing `ConformanceSuiteResult` persists a `status="passed"` report with the expected digest/evidence
      fields; a failing one persists `status="failed"`.
  - Run the new unit tests and confirm they pass.
  - _Requirements: 2.3_

- [x] 5. Register `validate_langgraph_endpoint` in the ARQ worker
  - In `api/tasks/arq.py`, import `validate_langgraph_endpoint` from `api.tasks.langgraph_validation` and add it
    to `WorkerSettings.functions` alongside the existing `sweep_langgraph_retention` entry. Do not add it to
    `cron_jobs` — it is on-demand, not scheduled (design.md step 7).
  - Add/extend a test (e.g. in `api/tests/langgraph_integration/test_langgraph_validation_job.py` or an existing
    ARQ registration test if one exists) asserting `validate_langgraph_endpoint` is present in
    `WorkerSettings.functions` and that `sweep_langgraph_retention` and the other pre-existing entries are still
    present and unchanged (bugfix.md 3.7).
  - Run the test and confirm it passes.
  - _Requirements: 2.1, 2.2, 3.7_

- [x] 6. Implement `_dispatch_validation` and wire it into `request_validation`
  - In `api/services/langgraph_integration/endpoint_registration.py`, add a new helper:
    ```python
    async def _dispatch_validation(organization_id: int, endpoint_uuid: str) -> None:
        from api.tasks.arq import enqueue_job
        from api.tasks.function_names import FunctionNames

        await enqueue_job(
            FunctionNames.VALIDATE_LANGGRAPH_ENDPOINT,
            organization_id,
            endpoint_uuid,
            _job_id=f"langgraph_validate:{endpoint_uuid}",
        )
    ```
    using a lazy import to avoid the circular import `arq.py` → task modules → back to this module (matching the
    existing pattern in `run_integrations.py`), per design.md step 2.
  - Modify `request_validation()` so both branches call `_dispatch_validation` after permission/feature-flag
    checks succeed and after any lifecycle transition attempt: remove the early-return no-op for the
    already-`pending_validation` case, and call `_dispatch_validation(organization_id, endpoint_uuid)` at the end
    of both that branch and the `transition_endpoint(...)` branch. A transition failure
    (`InvalidLifecycleTransition`) must still propagate and must NOT call `_dispatch_validation` (design.md
    step 1, bugfix.md 2.1, 2.2).
  - Write unit tests in `api/tests/langgraph_integration/test_endpoint_lifecycle.py` (or a new focused test
    module) asserting: `_dispatch_validation` enqueues with job id exactly `f"langgraph_validate:{endpoint_uuid}"`;
    `request_validation` calls `_dispatch_validation` in both the transition-needed and already-`pending_validation`
    branches; `request_validation` does NOT call `_dispatch_validation` when `require_permission`,
    `require_feature_enabled`, or `require_transition` raise.
  - Run the new tests and confirm they pass against the now-fixed `request_validation`.
  - _Requirements: 2.1, 2.2_

- [x] 7. Re-run exploration tests from task 1 as fix-checking tests
  - **Property 1: Expected Behavior** - Validate Action Dispatches Validation Work And Persists A Report
  - **IMPORTANT**: Re-purpose the SAME two test cases from task 1 (do not write new scenarios) — invert their
    assertions to match the fixed behavior, per design.md's "Fix Checking" pseudocode.
  - Test case (a): endpoint starts in `validation_only`; call the fixed `request_validation`; assert
    `enqueue_job` was awaited once with job id `f"langgraph_validate:{endpoint_uuid}"`.
  - Test case (b): endpoint starts in `pending_validation`; call the fixed `request_validation` again; assert
    `enqueue_job` is awaited again with the same deterministic job id (per bugfix.md 2.2, re-dispatch on retry).
  - Add an integration-style test that runs the enqueued job function directly (simulating ARQ execution) against
    a mocked `db_client`/`gateway`/`discovery`/`conformance.runner`, and asserts
    `db_client.insert_langgraph_validation_report` is awaited, i.e. a `Validation_Report` now exists for the
    endpoint (bugfix.md 2.3).
  - Run these tests against the fixed code. **EXPECTED OUTCOME**: all PASS, confirming the bug is resolved.
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [x] 8. Verify preservation tests from task 2 still pass after the fix
  - **Property 2: Preservation** - Permission, Feature-Flag, Lifecycle, And Activation-Evidence-Evaluation
    Behavior Unchanged
  - **IMPORTANT**: Re-run the SAME tests written in task 2 — do not write new tests.
  - Re-run: permission-denial test, feature-disabled test, the `EXPECTED_TRANSITIONS` property test, the lost
    compare-and-set-race test, and the two pre-existing `test_activation_requires_current_passing_snapshot_evidence`
    / `test_degraded_reactivation_requires_current_health` tests.
  - **EXPECTED OUTCOME**: all PASS unchanged, confirming no regression in permission, feature-flag, lifecycle
    transition, concurrency, or activation-evidence-evaluation behavior (bugfix.md 3.1–3.6).
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 9. Add remaining unit tests for job failure branches and idempotent dispatch
  - In `api/tests/langgraph_integration/test_langgraph_validation_job.py` (created in task 4), add any failure
    branch coverage not already added in task 4:
    - endpoint-not-found early return (no report insert) — if not already covered in task 4, add it here.
    - Assert a `DiscoveryTimeoutError`/`InvalidManifestError`/`UnsafeDestinationError` always results in
      `completed_at` being set (never `None`) on the persisted report, so `activate_endpoint` reports "not
      passing" rather than "evidence is required" (bugfix.md 1.3, 2.3, 2.4).
  - In `api/tests/langgraph_integration/test_endpoint_lifecycle.py`, add the idempotent duplicate dispatch test:
    two rapid `request_validation` calls for the same endpoint each call `enqueue_job` with the identical
    deterministic job id `f"langgraph_validate:{endpoint_uuid}"`; assert the job id equality (ARQ's own
    duplicate-job-id collapsing behavior is not exercised here since ARQ itself is not run in these unit tests —
    only that the fixed code always passes the same job id, per design.md's Non-Goals section on idempotency).
  - Run all new tests and confirm they pass.
  - _Requirements: 2.2, 3.7_

- [x] 10. Add property-based tests for authorization, transition table, and discovery-failure reporting
  - Check `api/tests/langgraph_integration/properties/` for existing Hypothesis strategies/conftest fixtures
    (confirmed present: `hypothesis` is already a pinned dependency used extensively in that directory, e.g.
    `test_property_24_denied_authorization.py` and `test_property_1_live_voice_eligibility.py`).
  - Add a new property test module `api/tests/langgraph_integration/properties/test_langgraph_validate_dispatch.py`
    (or extend an existing lifecycle-focused property test file) with:
    - A property over all `(LangGraphRole, LangGraphPermission.VALIDATE)` combinations asserting
      `request_validation` calls `_dispatch_validation` if and only if `is_langgraph_authorized` returns true
      and the feature is enabled — matching pre-fix authorization outcomes exactly (design.md Property-Based
      Tests, bullet 1).
    - A property over all pairs of `(current lifecycle_status, target_status="pending_validation")` asserting
      `can_transition` results used by `request_validation` match `EXPECTED_TRANSITIONS` exactly, unaffected by
      the added dispatch call (design.md Property-Based Tests, bullet 2).
    - A property over randomly generated discovery failure types (`DiscoveryTimeoutError`, `InvalidManifestError`,
      `UnsafeDestinationError`) asserting the persisted report always has `status != "passed"` and
      `completed_at` is never `None` (design.md Property-Based Tests, bullet 3).
  - Follow this codebase's existing property test comment convention: `# Feature: langgraph-validate-endpoint-noop,
    Property {N}: {property title}`.
  - Run the new property tests and confirm they pass.
  - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3_

- [x] 11. Add end-to-end integration tests for validate → job → activate
  - In `api/tests/langgraph_integration/test_endpoint_registration_api.py` (or a new integration test module),
    add:
    - A passing-manifest scenario: call the `/validate` route, run the enqueued job inline against the test
      harness (mocked `gateway.discover_manifest` returning a valid manifest, mocked `conformance.runner.run_suite`
      returning a passing result), then call `/activate` and assert it now succeeds (subject to existing
      snapshot/profile match checks).
    - A failing-discovery scenario: same flow but `gateway.discover_manifest` raises a `DiscoveryTimeoutError`;
      assert the subsequent `/activate` call fails with `ActivationEvidenceError` matching "not passing" rather
      than "evidence is required".
    - A re-validate scenario: an endpoint already in `pending_validation` is validated a second time (simulating
      a retry after fixing the endpoint's manifest); assert a new `Validation_Report` is created reflecting the
      corrected manifest (bugfix.md 2.2).
  - Run the new integration tests and confirm they pass.
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [x] 12. Checkpoint — run the full LangGraph test suite and project linters
  - Run the complete `api/tests/langgraph_integration/` suite (not just the new/modified tests) to confirm no
    regressions across discovery, negotiation, conformance, lifecycle, and endpoint registration API tests.
  - Run the project's configured linters/type-checks for the touched files
    (`api/services/langgraph_integration/endpoint_registration.py`, `api/tasks/langgraph_validation.py`,
    `api/tasks/function_names.py`, `api/tasks/arq.py`, and the new/modified test files), per the repository's
    standard lint/type-check commands.
  - Ensure all tests pass; ask the user if questions or unexpected failures arise.
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

## Notes

- Tasks 1 and 2 must be run against the current unfixed code before any implementation task (3-6) begins; they
  encode the bug condition and the preservation baseline respectively, per the bug condition methodology.
- Tasks 7 and 8 re-run/re-purpose the exact same test cases from tasks 1 and 2 rather than introducing new
  scenarios, so the same assertions can be checked against both unfixed and fixed code.
- No property test uses live network, database, or ARQ/Redis calls; `db_client`, `gateway.discover_manifest`,
  and `conformance.runner.run_suite` are mocked throughout, consistent with the rest of
  `api/tests/langgraph_integration/`.
- Backend pytest must use the project-local `venv` and source `api/.env.test`, per repository convention.
