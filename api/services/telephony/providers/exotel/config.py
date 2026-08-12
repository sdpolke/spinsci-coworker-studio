"""Exotel telephony configuration schemas."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# Exotel exposes one API host per data centre. These are the only two
# documented values; the base URL is
# ``https://<subdomain>/v1/Accounts/<account_sid>/``.
EXOTEL_SUBDOMAIN_MUMBAI = "api.in.exotel.com"
EXOTEL_SUBDOMAIN_SINGAPORE = "api.exotel.com"


class ExotelConfigurationRequest(BaseModel):
    """Request schema for Exotel configuration."""

    provider: Literal["exotel"] = Field(default="exotel")
    api_key: str = Field(..., description="Exotel API Key")
    api_token: str = Field(..., description="Exotel API Token")
    account_sid: str = Field(..., description="Exotel Account SID (e.g. mycompany1a)")
    subdomain: str = Field(
        default=EXOTEL_SUBDOMAIN_MUMBAI,
        description=(
            "Exotel API host for your data centre: api.in.exotel.com (Mumbai) "
            "or api.exotel.com (Singapore)."
        ),
    )
    inbound_secret: Optional[str] = Field(
        default=None,
        description=(
            "Shared token embedded in the Voicebot applet URL. Exotel does not "
            "sign App Bazaar callbacks, so this token is what authenticates "
            "inbound requests. Auto-generated on save when left blank."
        ),
    )
    # Phone numbers are managed via the dedicated phone-numbers endpoints; the
    # legacy /telephony-config POST shim still accepts them inline.
    from_numbers: List[str] = Field(
        default_factory=list, description="List of Exotel ExoPhone numbers"
    )


class ExotelConfigurationResponse(BaseModel):
    """Response schema for Exotel configuration with masked sensitive fields."""

    provider: Literal["exotel"] = Field(default="exotel")
    api_key: str  # Masked
    api_token: str  # Masked
    account_sid: str  # Masked
    subdomain: str = EXOTEL_SUBDOMAIN_MUMBAI
    inbound_secret: Optional[str] = None
    from_numbers: List[str]
