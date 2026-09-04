from __future__ import annotations

import ipaddress
import json
from itertools import pairwise
from typing import Any

from hypothesis import strategies as st

from api.schemas.langgraph_integration.common import MAX_EVENT_BYTES

identifier = st.text(alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")), min_size=1, max_size=24)
semantic_versions = st.builds(lambda major, minor: f"{major}.{minor}", st.integers(0, 4), st.integers(0, 20))
version_sets = st.sets(semantic_versions, min_size=1, max_size=8)

json_scalars = st.one_of(st.none(), st.booleans(), st.integers(-10_000, 10_000), st.text(max_size=30))
json_values: st.SearchStrategy[Any] = st.recursive(
    json_scalars,
    lambda children: st.one_of(st.lists(children, max_size=5), st.dictionaries(identifier, children, max_size=5)),
    max_leaves=20,
)
json_objects = st.dictionaries(identifier, json_values, max_size=6)

manifests = st.builds(
    lambda versions, modes, profile: {
        "schema_version": "1.0",
        "endpoint_id": "endpoint",
        "display_name": "Endpoint",
        "data_regions": ["us-east"],
        "contract_versions": sorted(versions),
        "compatibility_profiles": [profile],
        "invocation_modes": sorted(modes),
        "state_modes": ["mural_authoritative"],
        "operations": {
            "invoke": "/v1/invocations",
            "health": "/v1/health",
            **({"status": "/v1/status"} if "asynchronous" in modes else {}),
        },
    },
    versions=version_sets,
    modes=st.sets(st.sampled_from(["synchronous", "streaming", "asynchronous"]), min_size=1),
    profile=st.sampled_from(["chat", "stateful_run"]),
)

histories = st.lists(
    st.fixed_dictionaries({
        "role": st.sampled_from(["system", "user", "assistant", "tool_call", "tool_result"]),
        "text": st.text(min_size=1, max_size=80),
    }),
    max_size=30,
)

graphs = st.builds(
    lambda nodes, edges: {"nodes": nodes, "edges": edges},
    nodes=st.lists(identifier, min_size=1, max_size=8, unique=True),
    edges=st.lists(st.tuples(identifier, identifier, identifier), max_size=12),
)

@st.composite
def json_fragments(draw):
    value = draw(json_objects)
    serialized = json.dumps(value, separators=(",", ":"), sort_keys=True)
    cuts = draw(st.lists(st.integers(0, len(serialized)), unique=True).map(sorted))
    points = [0, *cuts, len(serialized)]
    return value, [serialized[a:b] for a, b in pairwise(points) if a != b]

runtime_events = st.builds(
    lambda sequence, text: {
        "contract_version": "1.0", "invocation_id": "inv", "sequence": sequence,
        "event_id": f"evt_{sequence}", "type": "text_delta", "data": {"text": text},
    },
    sequence=st.integers(0, 1000),
    text=st.text(min_size=1, max_size=min(100, MAX_EVENT_BYTES)),
)

tools = st.builds(
    lambda name, owner, schema: {"name": name, "owner": owner, "input_schema": schema},
    name=identifier,
    owner=st.sampled_from(["mural_transition", "mural_platform", "endpoint_internal"]),
    schema=json_objects,
)

tenant_scopes = st.tuples(identifier, identifier).map(lambda pair: {"actor_org": pair[0], "resource_org": pair[1]})
retry_states = st.fixed_dictionaries({
    "attempts": st.integers(0, 2),
    "accepted_event": st.booleans(),
    "remaining_ms": st.integers(0, 30_000),
    "status": st.sampled_from([408, 425, 429, 500, 502, 503, 504]),
})

ip_classes = st.one_of(
    st.ip_addresses(v=4), st.ip_addresses(v=6),
    st.sampled_from([ipaddress.ip_address("100.64.0.1"), ipaddress.ip_address("127.0.0.1"), ipaddress.ip_address("::1")]),
)
policies = st.fixed_dictionaries({
    "allowlist": st.sets(identifier, max_size=12),
    "redacted": st.sets(identifier, max_size=12),
    "capture": st.booleans(),
})
@st.composite
def health_windows(draw):
    """Complete configured sample windows beginning with the first failure."""
    sampling_interval_seconds = draw(st.integers(min_value=1, max_value=60))
    offsets = tuple(range(0, 61, sampling_interval_seconds))
    later_results = draw(
        st.lists(
            st.booleans(),
            min_size=len(offsets) - 1,
            max_size=len(offsets) - 1,
        )
    )
    return {
        "sampling_interval_seconds": sampling_interval_seconds,
        "samples": tuple(zip(offsets, (False, *later_results), strict=True)),
    }


rollout_windows = st.lists(
    st.tuples(st.integers(0, 1000), st.floats(0, 1, allow_nan=False), st.integers(0, 10_000)),
    min_size=1,
    max_size=30,
)
traces = st.lists(
    st.fixed_dictionaries({"kind": identifier, "timestamp_ms": st.integers(0, 10**12)}),
    max_size=30,
)
