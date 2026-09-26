"""OpenEMR API gateway integration.

The gateway exposes the existing OAuth-aware OpenEMR domain operations as
ordinary authenticated HTTP endpoints. SpinSci reusable ``http_api`` tools
call these endpoints; OpenEMR client secrets remain server-side.
"""

from api.services.integrations.base import IntegrationPackageSpec
from api.services.integrations.registry import register_package
from api.services.integrations.openemr.routes import router

PACKAGE = register_package(
    IntegrationPackageSpec(
        name="openemr",
        routers=(router,),
    )
)

__all__ = ["PACKAGE"]
