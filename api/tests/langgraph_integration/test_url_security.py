import pytest

from api.utils.url_security import (
    validate_connection_destination,
    validate_initial_destination,
    validate_redirect_destination,
)


def test_initial_redirect_and_connection_hooks_block_private_destinations(monkeypatch):
    monkeypatch.setattr("api.utils.url_security.DEPLOYMENT_MODE", "saas")
    for validator in (validate_initial_destination, validate_redirect_destination):
        with pytest.raises(ValueError):
            validator("http://127.0.0.1/resource")
    with pytest.raises(ValueError):
        validate_connection_destination("10.0.0.1")


def test_credentials_can_be_attached_only_after_public_destination_approval(monkeypatch):
    monkeypatch.setattr("api.utils.url_security.DEPLOYMENT_MODE", "saas")
    monkeypatch.setattr("api.utils.url_security._resolve_hostname_ips", lambda *_: [__import__("ipaddress").ip_address("8.8.8.8")])
    approved = validate_initial_destination("https://example.com")
    assert tuple(map(str, approved)) == ("8.8.8.8",)


def test_self_hosted_private_access_requires_explicit_enablement(monkeypatch):
    monkeypatch.setattr("api.utils.url_security.DEPLOYMENT_MODE", "oss")
    with pytest.raises(ValueError):
        validate_initial_destination("http://10.0.0.1")
    assert validate_initial_destination("http://10.0.0.1", allow_self_hosted_private_network=True)
