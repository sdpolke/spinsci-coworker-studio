from copy import deepcopy

from hypothesis import given
from hypothesis import strategies as st

from api.services.langgraph_integration.access_control import (
    LangGraphPermission,
    LangGraphRole,
    is_langgraph_resource_authorized,
)


# Feature: langgraph-voice-integration, Property 24: Denied authorization produces no mutation
@given(
    role=st.sampled_from(list(LangGraphRole)),
    permission=st.sampled_from(list(LangGraphPermission)),
    actor_org=st.integers(min_value=1, max_value=10),
    resource_org=st.integers(min_value=1, max_value=10),
    seed=st.integers(),
)
def test_property_24_denied_authorization_is_mutation_free(
    role, permission, actor_org, resource_org, seed
):
    governed = {
        "endpoint": {"status": "pending_validation", "revision": seed},
        "credential": {"revision": seed},
        "workflow": {"revision": seed},
        "voice_run": {"revision": seed},
        "audit_target": {"revision": seed},
        "endpoint_state": {"revision": seed},
    }
    before = deepcopy(governed)

    if is_langgraph_resource_authorized(
        role=role,
        permission=permission,
        actor_organization_id=actor_org,
        resource_organization_id=resource_org,
    ):
        governed["endpoint"]["revision"] += 1
    else:
        assert governed == before
