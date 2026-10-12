"""Admin-facing call telemetry.

Reads the spans the voice pipeline already writes to Langfuse and returns them
shaped for the dashboard. Nothing is stored here -- Langfuse is the record, and
a second copy would be one more thing to disagree with it.

Access is organisation-scoped through the normal auth dependency. When admin
controls land this becomes the natural place to require the admin role; the
shape of the endpoint does not change.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query

from api.db.models import UserModel
from api.services.auth.depends import get_user_with_selected_organization
from api.services.observability import langfuse_metrics

router = APIRouter(prefix="/observability", tags=["observability"])

# A week is the ceiling on purpose. An unbounded window lets one dashboard
# load scan an arbitrary span of history on the Langfuse side, which is slow
# for the person waiting and unkind to a shared instance.
MAX_WINDOW_HOURS = 168


@router.get("/calls/summary")
async def call_summary(
    window_hours: int = Query(
        24,
        ge=1,
        le=MAX_WINDOW_HOURS,
        description="How far back to aggregate, in hours. One week maximum.",
    ),
    channel: str | None = Query(
        None,
        description="Restrict to one channel, e.g. browser or telephony. All channels when absent.",
    ),
    user: UserModel = Depends(get_user_with_selected_organization),
) -> dict:
    """Every dashboard panel for one time window.

    Panels are gathered independently: one that fails comes back empty rather
    than failing the request, because four panels and a gap are more useful to
    someone debugging than a single error.
    """
    snapshot = langfuse_metrics.build_snapshot(
        window_hours=window_hours, channel=channel
    )
    payload = asdict(snapshot)
    payload["generated_at"] = snapshot.generated_at.isoformat()
    return payload


@router.get("/status")
async def status(
    user: UserModel = Depends(get_user_with_selected_organization),
) -> dict:
    """Whether telemetry is available, and why not when it is not.

    Lets the dashboard distinguish a quiet system from an unconfigured one.
    Without it, both render as zeroes and the difference only surfaces when
    somebody asks why there are no calls.
    """
    configured = langfuse_metrics.is_configured()
    return {
        "configured": configured,
        "message": (
            None
            if configured
            else (
                "Langfuse is not configured. Set LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY "
                "and LANGFUSE_SECRET_KEY to enable call telemetry."
            )
        ),
    }
