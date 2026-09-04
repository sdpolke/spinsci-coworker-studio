from copy import deepcopy

from hypothesis import given
from hypothesis import strategies as st

from api.services.langgraph_integration.lifecycle import (
    capabilities_changed,
    capability_digest,
)


@st.composite
def capability_manifests(draw):
    return {
        "contract_versions": draw(
            st.sets(st.sampled_from(["1.0", "1.1", "2.0"]), min_size=1)
        ),
        "compatibility_profiles": draw(
            st.sets(st.sampled_from(["chat", "stateful_run"]), min_size=1)
        ),
        "invocation_modes": draw(
            st.sets(
                st.sampled_from(["synchronous", "streaming", "asynchronous"]),
                min_size=1,
            )
        ),
        "state_modes": draw(
            st.sets(
                st.sampled_from(["mural_authoritative", "endpoint_checkpointed"]),
                min_size=1,
            )
        ),
        "features": {
            "interrupts": draw(st.booleans()),
            "idempotent_invocations": draw(st.booleans()),
            "cancellation": draw(st.booleans()),
        },
        "limits": {
            "request_bytes": draw(st.integers(1, 2_000_000)),
            "response_bytes": draw(st.integers(1, 3_000_000)),
            "event_bytes": draw(st.integers(1, 100_000)),
            "tool_argument_bytes": draw(st.integers(1, 500_000)),
        },
    }


# Feature: langgraph-voice-integration, Property 29: Capability change detection is complete
@given(capability_manifests())
def test_property_29_ordering_only_changes_do_not_change_digest(manifest):
    reordered = deepcopy(manifest)
    for field in (
        "contract_versions",
        "compatibility_profiles",
        "invocation_modes",
        "state_modes",
    ):
        reordered[field] = sorted(manifest[field], reverse=True)
    reordered["features"] = dict(reversed(list(manifest["features"].items())))
    reordered["limits"] = dict(reversed(list(manifest["limits"].items())))

    assert capability_digest(manifest) == capability_digest(reordered)
    assert not capabilities_changed(manifest, reordered)


# Feature: langgraph-voice-integration, Property 29: Capability change detection is complete
@given(
    manifest=capability_manifests(),
    field=st.sampled_from(
        [
            "contract_versions",
            "compatibility_profiles",
            "invocation_modes",
            "state_modes",
            "features",
            "limits",
        ]
    ),
)
def test_property_29_every_semantic_capability_change_changes_digest(manifest, field):
    changed = deepcopy(manifest)
    if field in {
        "contract_versions",
        "compatibility_profiles",
        "invocation_modes",
        "state_modes",
    }:
        changed[field] = set(changed[field]) | {f"changed-{field}"}
    elif field == "features":
        changed[field]["new_feature"] = True
    else:
        changed[field]["new_limit"] = 1

    assert capability_digest(manifest) != capability_digest(changed)
    assert capabilities_changed(manifest, changed)
