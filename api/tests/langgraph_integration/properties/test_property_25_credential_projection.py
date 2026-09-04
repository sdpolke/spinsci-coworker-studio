import base64
import json
from datetime import UTC, datetime
from types import SimpleNamespace

from hypothesis import assume, given
from hypothesis import strategies as st

from api.services.langgraph_integration.privacy import project_credential


# Feature: langgraph-voice-integration, Property 25: Credential responses are non-secret projections
@given(
    secret=st.text(min_size=8, max_size=80),
    credential_type=st.sampled_from(["api_key", "bearer_token", "basic_auth", "custom_header"]),
    reference_id=st.uuids().map(str),
)
def test_property_25_credential_projection_contains_no_secret_or_reversible_derivative(
    secret, credential_type, reference_id
):
    assume(secret not in credential_type)
    assume(secret not in reference_id)
    credential = SimpleNamespace(
        credential_type=credential_type,
        credential_uuid=reference_id,
        updated_at=datetime.now(UTC),
        credential_data={"secret": secret},
    )

    projection = project_credential(credential)
    serialized = json.dumps(
        {
            "credential_type": projection.credential_type,
            "reference_id": projection.reference_id,
            "last_updated_at": projection.last_updated_at.isoformat(),
        }
    )
    assert set(projection.__dict__) == {
        "credential_type",
        "reference_id",
        "last_updated_at",
    }
    assert secret not in serialized
    assert base64.b64encode(secret.encode()).decode() not in serialized
