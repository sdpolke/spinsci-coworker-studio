# Bugfix Requirements Document

## Introduction

The LangGraph endpoint "Validate" action (`POST /api/v1/langgraph-endpoints/{endpoint_uuid}/validate`) is intended to
run discovery and the conformance suite against a registered LangGraph endpoint and persist the result as a
`Validation_Report`, so that the endpoint can later be activated against that evidence.

In the current implementation, `request_validation()` in
`api/services/langgraph_integration/endpoint_registration.py` only flips `lifecycle_status` to
`pending_validation` (or short-circuits if it's already there). It never calls `discovery.py`, never calls
`conformance/runner.py::run_suite`, never enqueues an ARQ job to do so out of band, and never writes a
`Validation_Report` row. `api/tasks/arq.py` has no registered job for onboarding validation at all — only
`sweep_langgraph_retention` is registered for LangGraph.

Because no `Validation_Report` is ever created, `activate_endpoint()` always fails its evidence check
(`db_client.get_current_langgraph_activation_evidence` returns a `report=None`), raising
`ActivationEvidenceError("current validation evidence is required")`, surfaced to callers as HTTP 409. This makes
it impossible to activate any LangGraph endpoint through the intended validate → activate flow.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN a caller with VALIDATE permission calls `POST /langgraph-endpoints/{endpoint_uuid}/validate` on an
    endpoint whose `lifecycle_status` is not already `pending_validation` THEN the system transitions
    `lifecycle_status` to `pending_validation` and returns 200 without dispatching discovery or the conformance
    suite, and without creating any `Validation_Report`.

1.2 WHEN a caller calls `POST /langgraph-endpoints/{endpoint_uuid}/validate` on an endpoint whose
    `lifecycle_status` is already `pending_validation` THEN the system returns 200 immediately (no-op) without
    dispatching discovery or the conformance suite, and without creating any `Validation_Report`.

1.3 WHEN a caller subsequently calls `POST /langgraph-endpoints/{endpoint_uuid}/activate` on that endpoint THEN
    the system always raises `ActivationEvidenceError("current validation evidence is required")` (HTTP 409),
    because `get_current_langgraph_activation_evidence` never finds a report, regardless of whether the
    endpoint's manifest and runtime would actually pass conformance.

### Expected Behavior (Correct)

2.1 WHEN a caller with VALIDATE permission calls `POST /langgraph-endpoints/{endpoint_uuid}/validate` on an
    endpoint whose `lifecycle_status` is not already `pending_validation` THEN the system SHALL transition
    `lifecycle_status` to `pending_validation` AND SHALL dispatch validation work (discovery followed by the
    conformance suite via `run_suite`) for that endpoint, either synchronously or via an ARQ job enqueued
    against the endpoint's current capability snapshot.

2.2 WHEN a caller calls `POST /langgraph-endpoints/{endpoint_uuid}/validate` on an endpoint whose
    `lifecycle_status` is already `pending_validation` THEN the system SHALL (re-)dispatch validation work for
    that endpoint rather than silently no-op'ing, so that a stuck or previously-failed validation can be retried.

2.3 WHEN validation work completes for an endpoint THEN the system SHALL persist a `Validation_Report` (with
    `capability_snapshot_id`, `selected_profile`, `status`, `completed_at`, and `evidence` populated per the
    conformance suite result) that `get_current_langgraph_activation_evidence` can retrieve.

2.4 WHEN a caller calls `POST /langgraph-endpoints/{endpoint_uuid}/activate` on an endpoint for which validation
    has completed with a passing report against the endpoint's current capability snapshot and selected profile
    THEN the system SHALL NOT raise `ActivationEvidenceError("current validation evidence is required")` on the
    basis of a missing report, and SHALL proceed to the remaining activation checks (report status, snapshot
    match, profile match).

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a caller lacking VALIDATE permission calls the validate endpoint THEN the system SHALL CONTINUE TO
    reject the request via `require_permission` before any lifecycle or validation work occurs.

3.2 WHEN the LangGraph feature is not enabled for the organization THEN the system SHALL CONTINUE TO reject
    validate and activate calls via `require_feature_enabled`.

3.3 WHEN `transition_endpoint` is called with a `target_status` that is not a valid transition from the
    endpoint's current `lifecycle_status` THEN the system SHALL CONTINUE TO raise `InvalidLifecycleTransition`
    via `require_transition`, unchanged from today.

3.4 WHEN two concurrent requests race to change the same endpoint's lifecycle status THEN the system SHALL
    CONTINUE TO use the compare-and-set semantics in `compare_and_set_langgraph_lifecycle` and raise
    `InvalidLifecycleTransition` on a lost race, unchanged from today.

3.5 WHEN `activate_endpoint` is called and a `Validation_Report` exists but is not passing, or does not cover the
    endpoint's current capability snapshot, or does not cover the endpoint's `selected_profile` THEN the system
    SHALL CONTINUE TO raise the corresponding `ActivationEvidenceError` exactly as it does today.

3.6 WHEN `activate_endpoint` is called on an endpoint in the `degraded` lifecycle state without current healthy
    health evidence THEN the system SHALL CONTINUE TO raise `ActivationEvidenceError("current successful health
    evidence is required")`, unchanged from today.

3.7 WHEN `sweep_langgraph_retention` and other existing registered ARQ jobs run THEN the system SHALL CONTINUE TO
    execute on their existing schedules, unaffected by any newly added validation job.

## Bug Condition (for reference)

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type ValidateRequest
  OUTPUT: boolean

  // True for every call to request_validation, regardless of endpoint state,
  // because no code path ever dispatches discovery/conformance or writes a report.
  RETURN true
END FUNCTION
```

```pascal
// Property: Fix Checking
FOR ALL X WHERE isBugCondition(X) DO
  result ← request_validation'(X)
  ASSERT validation_report_created_for(X.endpoint_uuid)
         AND (discovery_was_invoked(X.endpoint_uuid) OR job_enqueued(X.endpoint_uuid))
END FOR
```

```pascal
// Property: Preservation
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT request_validation(X) = request_validation'(X)
END FOR
```

Note: because the bug condition is unconditionally true for the validate action itself (every call is affected),
preservation checking for this bugfix focuses on the surrounding permission checks, feature-flag checks, lifecycle
transition rules, and `activate_endpoint`'s existing evidence checks (3.1–3.7 above) — i.e. behavior in the same
module and adjacent flows that must not regress while the validate action is fixed to actually dispatch validation.
