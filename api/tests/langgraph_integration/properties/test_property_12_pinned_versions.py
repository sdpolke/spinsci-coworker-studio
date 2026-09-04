from copy import deepcopy

from hypothesis import given
from hypothesis import strategies as st

from api.schemas.langgraph_integration import v1_0, v1_1
from api.schemas.langgraph_integration.examples import EXECUTABLE_EXAMPLES
from api.services.langgraph_integration.contract import serialize_pinned_request


valid_locales = st.from_regex(
    r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", fullmatch=True
).filter(lambda locale: len(locale) <= 35)


# Feature: langgraph-voice-integration, Property 12: Pinned versions remain wire-authoritative
@given(st.sampled_from(["1.0", "1.1"]), st.one_of(st.none(), valid_locales))
def test_property_12_pinned_wire_version_is_authoritative(pinned_version, locale):
    payload = deepcopy(EXECUTABLE_EXAMPLES["1.0"]["invocation"])
    payload["contract_version"] = "9.9"
    if pinned_version == "1.1" and locale is not None:
        payload["locale"] = locale
    serialized = serialize_pinned_request(pinned_version=pinned_version, payload=payload)
    assert serialized["contract_version"] == pinned_version


@given(st.booleans())
def test_property_12_optional_minor_fields_preserve_prior_payloads(include_optional):
    prior = deepcopy(EXECUTABLE_EXAMPLES["1.0"]["invocation"])
    v1_0.InvocationRequest.model_validate(prior)
    upgraded = prior | {"contract_version": "1.1"}
    if include_optional:
        upgraded["locale"] = "en-US"
    assert v1_1.InvocationRequest.model_validate(upgraded)
