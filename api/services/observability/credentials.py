"""Which Langfuse an organisation's telemetry is read from.

The pipeline already writes per organisation: an org that has saved its own
credentials gets its spans exported to its own project, and everything else
falls back to the deployment's environment variables. The dashboard did not
read the same way -- it read the environment and nothing else.

That mismatch has a sharp edge. The moment an organisation configures its own
Langfuse, its spans stop arriving in the shared project while its dashboard
keeps querying the shared project, so the org sees an empty page on the day it
turns the feature on. Resolving credentials the same way on both sides is what
makes "configure it from the app" actually work.

Resolution is async because it reads configuration, so it happens in the route
and the resolved credentials are handed to the read layer as an argument. The
read layer stays synchronous and has no opinion about where its credentials
came from, which is also what makes it testable without a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from loguru import logger

from api.constants import (
    LANGFUSE_HOST,
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
)
from api.db import db_client
from api.enums import OrganizationConfigurationKey


class CredentialSource(StrEnum):
    """Where a set of credentials came from.

    Reported to the dashboard so an empty page can say which Langfuse it
    looked in. "No calls" and "no calls *in your project*" are different
    answers and only one of them is a reason to check the configuration.
    """

    ORGANIZATION = "organization"
    ENVIRONMENT = "environment"


@dataclass(frozen=True)
class LangfuseCredentials:
    """One Langfuse project to read from."""

    host: str
    public_key: str
    secret_key: str
    source: CredentialSource
    #: Set only for an organisation's own project, for display.
    project_id: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.host and self.public_key and self.secret_key)


def _from_environment() -> LangfuseCredentials:
    return LangfuseCredentials(
        host=str(LANGFUSE_HOST or ""),
        public_key=str(LANGFUSE_PUBLIC_KEY or ""),
        secret_key=str(LANGFUSE_SECRET_KEY or ""),
        source=CredentialSource.ENVIRONMENT,
    )


async def resolve(organization_id: int | str | None) -> LangfuseCredentials:
    """The Langfuse this organisation's telemetry lives in.

    Its own project where it has configured one, the deployment's otherwise --
    the same order the exporter uses when deciding where to write, so reads and
    writes cannot disagree about which project holds an organisation's calls.

    A partially filled configuration (a host with no keys, say) is treated as
    absent rather than attempted. Half a credential cannot authenticate, and
    failing over to the environment shows the org an empty page rather than an
    error, so the gap is logged loudly instead.
    """
    if organization_id is None:
        return _from_environment()

    try:
        stored = await db_client.get_configuration_value(
            organization_id,
            OrganizationConfigurationKey.LANGFUSE_CREDENTIALS.value,
        )
    except Exception as exc:  # noqa: BLE001 - a telemetry read is not worth a 500
        logger.warning(
            f"Could not read Langfuse configuration for organisation "
            f"{organization_id}: {exc}. Falling back to the environment."
        )
        return _from_environment()

    if not isinstance(stored, dict) or not stored:
        return _from_environment()

    candidate = LangfuseCredentials(
        host=str(stored.get("host") or ""),
        public_key=str(stored.get("public_key") or ""),
        secret_key=str(stored.get("secret_key") or ""),
        source=CredentialSource.ORGANIZATION,
        project_id=str(stored.get("project_id") or "") or None,
    )
    if candidate.configured:
        return candidate

    missing = [
        name
        for name, value in (
            ("host", candidate.host),
            ("public_key", candidate.public_key),
            ("secret_key", candidate.secret_key),
        )
        if not value
    ]
    logger.warning(
        f"Organisation {organization_id} has an incomplete Langfuse "
        f"configuration (missing {', '.join(missing)}); reading from the "
        "environment instead. Its calls will not appear until it is completed."
    )
    return _from_environment()
