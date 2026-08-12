"""Exotel telephony routes (Voicebot applet URL, status callbacks).

Mounted under ``/api/v1/telephony`` by ``api.routes.telephony`` via the
provider registry.

Two endpoints, for the two things Exotel calls back about:

* ``/exotel/voicebot`` — the URL an operator configures on the Voicebot applet
  of an App Bazaar flow. Exotel fetches it per inbound call and expects
  ``{"url": "wss://..."}`` in return. App Bazaar applet URLs are fetched with
  ``GET`` and call details arrive as query parameters, so this accepts both
  verbs and folds the query string into the payload before handing off to the
  shared inbound dispatcher — the dispatcher owns config matching, quota,
  concurrency and run creation for every provider, and Exotel should not fork
  any of it.
* ``/exotel/status/{workflow_run_id}`` — outbound ``StatusCallback`` target.
"""

import json

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pipecat.utils.run_context import set_current_run_id

from api.db import db_client
from api.services.telephony.factory import get_telephony_provider_for_run
from api.services.telephony.status_processor import (
    StatusCallbackRequest,
    _process_status_update,
)
from api.utils.telephony_helper import parse_webhook_request

router = APIRouter()


def _rebuild_as_json_post(request: Request, payload: dict) -> Request:
    """Re-present ``request`` as a JSON POST carrying ``payload``.

    The shared dispatcher is a POST handler that reads the body; Exotel's
    applet fetch is a GET with query parameters. Rewriting the scope keeps the
    dispatcher untouched while preserving the original URL, which is what the
    provider's token check reads.
    """
    body = json.dumps(payload).encode("utf-8")
    scope = dict(request.scope)
    scope["method"] = "POST"
    scope["headers"] = [
        (name, value)
        for name, value in request.scope.get("headers", [])
        if name not in (b"content-type", b"content-length")
    ] + [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]

    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


@router.get("/exotel/voicebot", operation_id="exotel_voicebot_get")
@router.post("/exotel/voicebot", operation_id="exotel_voicebot_post")
async def handle_exotel_voicebot(request: Request):
    """Resolve an inbound Exotel call and return its media WebSocket URL."""
    # Imported lazily: api.routes.telephony imports this module at the bottom
    # of its own definition, so a module-level import would be circular.
    from api.routes.telephony import handle_inbound_run

    payload: dict = dict(request.query_params)
    if request.method == "POST":
        try:
            body_data, _ = await parse_webhook_request(request)
        except ValueError:
            body_data = {}
        if isinstance(body_data, dict):
            payload.update(body_data)

    logger.info(
        f"Exotel voicebot callback: call_sid={payload.get('CallSid')} "
        f"from={payload.get('CallFrom')} to={payload.get('CallTo')}"
    )

    return await handle_inbound_run(_rebuild_as_json_post(request, payload))


@router.get(
    "/exotel/status/{workflow_run_id}", operation_id="exotel_status_callback_get"
)
@router.post(
    "/exotel/status/{workflow_run_id}", operation_id="exotel_status_callback_post"
)
async def handle_exotel_status_callback(request: Request, workflow_run_id: int):
    """Handle Exotel ``StatusCallback`` events for a run.

    Exotel posts JSON for Connect Voice AI calls but form-encodes App Bazaar
    callbacks, and sends nothing at all in the body when the URL is fetched by
    an applet — accept all three shapes.
    """
    set_current_run_id(workflow_run_id)

    raw_body = (await request.body()).decode("utf-8", errors="replace")
    data: dict = dict(request.query_params)
    try:
        body_data, _ = await parse_webhook_request(request)
    except ValueError:
        body_data = {}
    if isinstance(body_data, dict):
        data.update(body_data)

    workflow_run = await db_client.get_workflow_run_by_id(workflow_run_id)
    if not workflow_run:
        logger.warning(f"Workflow run {workflow_run_id} not found for Exotel status")
        raise HTTPException(status_code=404, detail="Workflow run not found")

    workflow = await db_client.get_workflow_by_id(workflow_run.workflow_id)
    if not workflow:
        logger.warning(f"Workflow {workflow_run.workflow_id} not found")
        raise HTTPException(status_code=404, detail="Workflow not found")

    provider = await get_telephony_provider_for_run(
        workflow_run, workflow.organization_id
    )

    # Exotel signs nothing, so this is the shared-token check against the
    # ``token`` parameter we put on the StatusCallback URL at dial time.
    if not await provider.verify_inbound_signature(
        str(request.url), data, dict(request.headers), raw_body
    ):
        logger.warning(
            f"[run {workflow_run_id}] Rejecting Exotel status callback: invalid token"
        )
        raise HTTPException(status_code=401, detail="Invalid callback token")

    parsed = provider.parse_status_callback(data)
    logger.info(
        f"[run {workflow_run_id}] Exotel status callback: status={parsed['status']} "
        f"call_id={parsed['call_id']}"
    )

    await _process_status_update(
        workflow_run_id,
        StatusCallbackRequest(
            call_id=parsed["call_id"],
            status=parsed["status"],
            from_number=parsed.get("from_number"),
            to_number=parsed.get("to_number"),
            direction=parsed.get("direction"),
            duration=parsed.get("duration"),
            extra=parsed.get("extra", {}),
        ),
    )

    return {"status": "success"}
