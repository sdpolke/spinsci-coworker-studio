"""Which Langfuse an organisation's dashboard reads from.

The failure this guards against is quiet rather than loud: an organisation
configures its own Langfuse, its spans start going to its own project, and its
dashboard keeps querying the deployment's. Nothing errors. The page is simply
empty, on the day the feature was turned on, and reads as "no calls".
"""

from __future__ import annotations

import pytest

from api.services.observability import credentials as module
from api.services.observability.credentials import (
    CredentialSource,
    LangfuseCredentials,
    resolve,
)

COMPLETE = {
    "host": "https://langfuse.theirs.example",
    "public_key": "pk-theirs",
    "secret_key": "sk-theirs",
    "project_id": "their-project",
}


@pytest.fixture
def stored(monkeypatch):
    """Stand in for the organisation's saved configuration."""

    def install(value, raises: Exception | None = None):
        async def fake(organization_id, key):
            if raises is not None:
                raise raises
            return value

        monkeypatch.setattr(module.db_client, "get_configuration_value", fake)

    return install


@pytest.fixture(autouse=True)
def deployment_credentials(monkeypatch):
    monkeypatch.setattr(module, "LANGFUSE_HOST", "https://langfuse.ours.example")
    monkeypatch.setattr(module, "LANGFUSE_PUBLIC_KEY", "pk-ours")
    monkeypatch.setattr(module, "LANGFUSE_SECRET_KEY", "sk-ours")


async def test_an_organisation_with_its_own_project_is_read_from_it(stored):
    """The whole point: reads follow writes."""
    stored(COMPLETE)
    creds = await resolve(7)

    assert creds.source is CredentialSource.ORGANIZATION
    assert creds.host == "https://langfuse.theirs.example"
    assert creds.public_key == "pk-theirs"
    assert creds.project_id == "their-project"
    assert creds.configured


async def test_an_organisation_without_one_falls_back_to_the_deployment(stored):
    """What every organisation does today, and must keep doing."""
    stored(None)
    creds = await resolve(7)

    assert creds.source is CredentialSource.ENVIRONMENT
    assert creds.host == "https://langfuse.ours.example"
    assert creds.configured


@pytest.mark.parametrize("missing", ["host", "public_key", "secret_key"])
async def test_a_half_filled_configuration_is_not_attempted(stored, missing):
    """Half a credential cannot authenticate. Attempting it produces an
    authentication failure that surfaces as an empty dashboard, which is the
    same thing a quiet system looks like."""
    stored({**COMPLETE, missing: ""})
    creds = await resolve(7)

    assert creds.source is CredentialSource.ENVIRONMENT
    assert creds.configured


@pytest.mark.parametrize("stored_value", [{}, None, "not-a-mapping", 42])
async def test_junk_configuration_falls_back_rather_than_raising(stored, stored_value):
    stored(stored_value)
    creds = await resolve(7)
    assert creds.source is CredentialSource.ENVIRONMENT


async def test_a_database_failure_does_not_fail_the_dashboard(stored):
    """A telemetry read is not worth a 500."""
    stored(None, raises=RuntimeError("connection pool exhausted"))
    creds = await resolve(7)
    assert creds.source is CredentialSource.ENVIRONMENT


async def test_no_organisation_reads_the_deployment(stored):
    stored(COMPLETE)
    creds = await resolve(None)
    assert creds.source is CredentialSource.ENVIRONMENT


async def test_an_unconfigured_deployment_is_reported_not_guessed(stored, monkeypatch):
    """With neither source set the dashboard must say so, rather than render
    zeroes that look like a quiet system."""
    monkeypatch.setattr(module, "LANGFUSE_HOST", "")
    monkeypatch.setattr(module, "LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setattr(module, "LANGFUSE_SECRET_KEY", "")
    stored(None)

    creds = await resolve(7)
    assert not creds.configured


async def test_the_organisation_project_is_never_mixed_with_the_deployment(stored):
    """A partially overridden set would read one project with another's key."""
    stored({"host": "https://langfuse.theirs.example", "public_key": "pk-theirs",
            "secret_key": "sk-theirs"})
    creds = await resolve(7)

    assert creds.host == "https://langfuse.theirs.example"
    assert creds.secret_key == "sk-theirs"
    # Nothing from the deployment leaked into the organisation's set.
    assert "ours" not in creds.host and "ours" not in creds.secret_key


def test_credentials_without_a_host_are_not_configured():
    assert not LangfuseCredentials(
        host="", public_key="pk", secret_key="sk", source=CredentialSource.ENVIRONMENT
    ).configured
