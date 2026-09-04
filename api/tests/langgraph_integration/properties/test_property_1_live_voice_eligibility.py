from hypothesis import given
from hypothesis import strategies as st

from api.services.langgraph_integration.lifecycle import evaluate_live_voice_eligibility

versions = st.sets(
    st.builds(lambda major, minor: f"{major}.{minor}", st.integers(1, 2), st.integers(0, 3)),
    min_size=1,
    max_size=4,
)
profiles = st.sets(st.sampled_from(["chat", "stateful_run"]), min_size=1)
modes = st.sets(
    st.sampled_from(["synchronous", "streaming", "asynchronous"]), min_size=1
)


# Feature: langgraph-voice-integration, Property 1: Eligibility follows the matrix, profile, mode, tests, and lifecycle
@given(
    matrix_versions=versions,
    matrix_profiles=profiles,
    manifest_versions=versions,
    manifest_profiles=profiles,
    declared_modes=modes,
    selected_modes=modes,
    selected_profile=st.sampled_from(["chat", "stateful_run"]),
    required_results=st.lists(st.booleans(), min_size=1, max_size=8),
    latency_passed=st.booleans(),
    lifecycle_status=st.sampled_from(
        [
            "pending_validation",
            "validation_only",
            "active",
            "degraded",
            "disabled",
            "incompatible",
            "retired",
        ]
    ),
)
def test_property_1_live_voice_eligibility(
    matrix_versions,
    matrix_profiles,
    manifest_versions,
    manifest_profiles,
    declared_modes,
    selected_modes,
    selected_profile,
    required_results,
    latency_passed,
    lifecycle_status,
):
    decision = evaluate_live_voice_eligibility(
        matrix_versions=matrix_versions,
        matrix_profiles=matrix_profiles,
        manifest_versions=manifest_versions,
        manifest_profiles=manifest_profiles,
        declared_modes=declared_modes,
        selected_modes=selected_modes,
        selected_profile=selected_profile,
        required_non_latency_results=required_results,
        latency_passed=latency_passed,
        lifecycle_status=lifecycle_status,
    )
    contract_and_profile_supported = bool(matrix_versions & manifest_versions) and (
        selected_profile in matrix_profiles
        and selected_profile in manifest_profiles
    )
    required_pass = all(required_results)
    modes_declared = selected_modes <= declared_modes
    streaming_selected = "streaming" in selected_modes
    expected_live = (
        contract_and_profile_supported
        and required_pass
        and modes_declared
        and streaming_selected
        and latency_passed
        and lifecycle_status == "active"
    )
    assert decision.live_voice_selectable is expected_live

    if not contract_and_profile_supported or not required_pass:
        assert decision.classification == "incompatible"
    elif not modes_declared or not streaming_selected or not latency_passed:
        assert decision.classification == "validation_only"
    else:
        assert decision.classification == "supported"
