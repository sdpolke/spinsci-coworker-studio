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

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from api.db.models import UserModel
from api.services.auth.depends import get_user_with_selected_organization
from api.services.observability import langfuse_metrics
from api.services.observability.conventions import CallChannel

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
    channel: CallChannel | None = Query(
        None,
        description=(
            "Restrict every panel to one channel. All channels when absent. "
            "The channel is derived from the transport the call arrived on, so "
            "browser covers WebRTC and telephony covers every carrier."
        ),
    ),
    user: UserModel = Depends(get_user_with_selected_organization),
) -> dict:
    """Every dashboard panel for one time window.

    Panels are gathered independently: one that fails comes back empty rather
    than failing the request, because four panels and a gap are more useful to
    someone debugging than a single error.
    """
    snapshot = langfuse_metrics.build_snapshot(
        window_hours=window_hours,
        channel=str(channel) if channel else None,
    )
    payload = asdict(snapshot)
    payload["generated_at"] = snapshot.generated_at.isoformat()
    return payload


@router.get("/calls/{trace_id}")
async def call_detail(
    trace_id: str = Path(..., description="Langfuse trace id, as the per-call table reports it."),
    user: UserModel = Depends(get_user_with_selected_organization),
) -> dict:
    """Everything one call did, in order.

    The drill-down behind a row of the per-call table: each span with its
    offset from the start of the call, its duration and its time to first
    byte, so a slow or failed step can be found without leaving the platform
    for the raw trace viewer.
    """
    detail = langfuse_metrics.call_detail(trace_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="No trace with that id")
    return detail


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
