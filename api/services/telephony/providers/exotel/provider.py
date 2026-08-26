"""Exotel implementation of the TelephonyProvider interface.

Outbound uses Exotel's *Connect Voice AI* API
(``POST /v1/Accounts/{sid}/Calls/connect.json`` with ``StreamType=bidirectional``
and a per-call ``StreamUrl``), which is the same shape Telnyx uses: the media
WebSocket URL is handed to the carrier at dial time, so no markup response and
no App Bazaar flow are involved. Docs:
https://docs.exotel.com/exotel-agentstream/connect-voice-ai-api

Inbound goes the other way round: an ExoPhone is bound to an App Bazaar flow
containing a **Voicebot applet** whose URL points at
``/api/v1/telephony/exotel/voicebot``. Exotel fetches that URL per call and
expects ``{"url": "wss://..."}`` back, which is what
:meth:`ExotelProvider.start_inbound_stream` returns.

Media is 16-bit linear PCM (little-endian), mono, 8 kHz by default — *not*
mu-law. Closing the WebSocket ends the call; Exotel has no separate hangup
command on the stream.
"""

import hmac
import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp
from fastapi import HTTPException, WebSocketDisconnect
from loguru import logger

from api.enums import TelephonyCallStatus, WorkflowRunMode
from api.services.telephony import ws_auth
from api.services.telephony.base import (
    CallInitiationResult,
    NormalizedInboundData,
    ProviderSyncResult,
    TelephonyProvider,
)
from api.utils.common import get_backend_endpoints
from api.utils.telephony_address import normalize_telephony_address

if TYPE_CHECKING:
    from fastapi import WebSocket

# Wire-format rate Exotel streams by default. Also declared on the
# ProviderSpec so pipecat derives the matching AudioConfig, and appended to
# the StreamUrl so the two can never silently disagree.
EXOTEL_STREAM_SAMPLE_RATE = 8000

# Exotel is an India-first carrier and its App Bazaar callbacks carry local
# formats (leading-0 trunk prefix, bare 10-digit mobiles) with no country
# field to disambiguate them. Same reasoning as the Vobiz provider. E.164
# inputs ignore the hint, so Singapore-DC accounts using +65 numbers are
# unaffected.
EXOTEL_COUNTRY_HINT = "IN"

# The Voicebot applet reaches this path; the account SID and the shared token
# ride along as custom parameters because Exotel neither signs its callbacks
# nor reliably stamps the account on them.
INBOUND_VOICEBOT_PATH = "/api/v1/telephony/exotel/voicebot"


def build_inbound_voicebot_url(
    backend_endpoint: str, account_sid: str, inbound_secret: Optional[str]
) -> str:
    """The URL an operator pastes into the Exotel Voicebot applet.

    ``account_sid`` is what lets the shared inbound dispatcher match the call
    to the right telephony configuration (see
    ``ProviderSpec.account_id_credential_field``); ``token`` is what
    authenticates the request, since Exotel signs nothing.
    """
    params = {"account_sid": account_sid}
    if inbound_secret:
        params["token"] = inbound_secret
    return f"{backend_endpoint.rstrip('/')}{INBOUND_VOICEBOT_PATH}?{urlencode(params)}"


class ExotelProvider(TelephonyProvider):
    """Exotel implementation of TelephonyProvider (AgentStream / Voicebot)."""

    PROVIDER_NAME = WorkflowRunMode.EXOTEL.value
    WEBHOOK_ENDPOINT = "exotel/voicebot"

    def __init__(self, config: Dict[str, Any]):
        self.api_key = config.get("api_key")
        self.api_token = config.get("api_token")
        self.account_sid = config.get("account_sid")
        self.subdomain = (config.get("subdomain") or "api.in.exotel.com").strip("/")
        self.inbound_secret = config.get("inbound_secret")
        self.from_numbers = config.get("from_numbers", [])
        self.default_from_number = config.get("default_from_number")

        if isinstance(self.from_numbers, str):
            self.from_numbers = [self.from_numbers]

    @property
    def base_url(self) -> str:
        return f"https://{self.subdomain}/v1/Accounts/{self.account_sid}"

    def _auth(self) -> aiohttp.BasicAuth:
        """Exotel uses HTTP Basic with API key as user and API token as password."""
        return aiohttp.BasicAuth(self.api_key or "", self.api_token or "")

    @staticmethod
    def _form_body(fields: List[tuple[str, str]]) -> bytes:
        """Encode form fields, preserving repeats (``StatusCallbackEvents[]``)."""
        return urlencode(fields).encode("utf-8")

    @staticmethod
    def _form_headers() -> Dict[str, str]:
        return {"Content-Type": "application/x-www-form-urlencoded"}

    # ======== OUTBOUND ========

    async def initiate_call(
        self,
        to_number: str,
        webhook_url: str,
        workflow_run_id: Optional[int] = None,
        from_number: Optional[str] = None,
        **kwargs: Any,
    ) -> CallInitiationResult:
        """Dial out with Exotel's Connect Voice AI API.

        ``webhook_url`` is ignored: Exotel does not fetch an answer URL on this
        path. The media socket is named inline via ``StreamUrl`` and status
        events go to a run-scoped ``StatusCallback`` we build here.

        Note Exotel's parameter naming — ``From`` is the party Exotel dials
        (the callee) and ``CallerId`` is the ExoPhone shown to them. That is
        the inverse of most carriers.
        """
        if not self.validate_config():
            raise ValueError("Exotel provider not properly configured")

        caller_id = self.select_from_number(from_number)
        if not caller_id:
            raise ValueError(
                "Exotel requires a CallerId (ExoPhone); no phone number is "
                "configured on this telephony configuration"
            )

        backend_endpoint, wss_backend_endpoint = await get_backend_endpoints()

        workflow_id = kwargs.get("workflow_id")
        organization_id = kwargs.get("organization_id")
        stream_url = self._build_stream_url(
            wss_backend_endpoint, workflow_id, organization_id, workflow_run_id
        )
        status_callback = self._build_status_callback_url(
            backend_endpoint, workflow_run_id
        )

        fields: List[tuple[str, str]] = [
            ("From", to_number),
            ("CallerId", caller_id),
            ("StreamUrl", stream_url),
            ("StreamType", "bidirectional"),
            ("StatusCallback", status_callback),
            ("StatusCallbackEvents[]", "answered"),
            ("StatusCallbackEvents[]", "terminal"),
        ]
        if workflow_run_id is not None:
            fields.append(("CustomField", f"workflow_run_id={workflow_run_id}"))

        # Logged as pairs, not a dict: StatusCallbackEvents[] repeats and a dict
        # would silently drop all but the last one. StreamUrl is omitted because
        # it carries the media-socket capability token.
        logger.info(
            "Exotel dial payload: "
            + ws_auth.redact_token(
                json.dumps([[k, v] for k, v in fields if k != "StreamUrl"])
            )
            + f" stream_url_len={len(stream_url)}"
        )

        endpoint = f"{self.base_url}/Calls/connect.json"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint,
                data=self._form_body(fields),
                headers=self._form_headers(),
                auth=self._auth(),
            ) as response:
                body = await response.text()
                if response.status not in (200, 201, 202):
                    logger.error(
                        f"Exotel connect failed: HTTP {response.status} body={body}"
                    )
                    raise HTTPException(status_code=response.status, detail=body)
                try:
                    response_data = json.loads(body)
                except json.JSONDecodeError as e:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Exotel returned a non-JSON connect response: {body}",
                    ) from e

        call = response_data.get("Call") or {}
        call_sid = call.get("Sid", "")
        if not call_sid:
            logger.error(f"Exotel connect response missing Call.Sid: {response_data}")
            raise HTTPException(
                status_code=502,
                detail=f"Exotel connect response missing Call.Sid: {response_data}",
            )

        logger.info(
            f"Exotel call initiated: sid={call_sid} status={call.get('Status')}"
        )

        return CallInitiationResult(
            call_id=call_sid,
            status=call.get("Status") or "initiated",
            caller_number=caller_id,
            provider_metadata={"call_id": call_sid, "call_sid": call_sid},
            raw_response=response_data,
        )

    def _build_status_callback_url(
        self, backend_endpoint: str, workflow_run_id: Optional[int]
    ) -> str:
        """Run-scoped StatusCallback target, carrying the shared token.

        The run id alone would be a guessable bearer capability for forging
        call outcomes, so the same token that authenticates inbound callbacks
        is appended here and checked by the status route.
        """
        url = (
            f"{backend_endpoint.rstrip('/')}/api/v1/telephony/exotel/status/"
            f"{workflow_run_id}"
        )
        if self.inbound_secret:
            url = f"{url}?{urlencode({'token': self.inbound_secret})}"
        return url

    @staticmethod
    def _build_stream_url(
        wss_backend_endpoint: str,
        workflow_id: Optional[int],
        organization_id: Optional[int],
        workflow_run_id: Optional[int],
    ) -> str:
        """Media WS URL plus the sample-rate Exotel should stream at.

        Exotel reads the rate from ``?sample-rate=`` on the stream URL and
        defaults to 8 kHz when it is absent. Stating it explicitly keeps the
        wire format pinned to ``ProviderSpec.transport_sample_rate``.
        """
        url = ws_auth.build_media_ws_url(
            wss_backend_endpoint, workflow_id, organization_id, workflow_run_id
        )
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}sample-rate={EXOTEL_STREAM_SAMPLE_RATE}"

    async def get_call_status(self, call_id: str) -> Dict[str, Any]:
        """Fetch call details from Exotel."""
        endpoint = f"{self.base_url}/Calls/{call_id}.json"
        async with aiohttp.ClientSession() as session:
            async with session.get(endpoint, auth=self._auth()) as response:
                body = await response.text()
                if response.status != 200:
                    raise Exception(
                        f"Failed to get Exotel call status: "
                        f"HTTP {response.status} {body}"
                    )
                return json.loads(body)

    async def get_available_phone_numbers(self) -> List[str]:
        return self.from_numbers

    def validate_config(self) -> bool:
        return bool(
            self.api_key and self.api_token and self.account_sid and self.subdomain
        )

    async def get_call_cost(self, call_id: str) -> Dict[str, Any]:
        """Report duration only.

        Exotel's call-details response carries ``Price`` in the account
        currency (INR for the Mumbai DC) with no exchange rate, so there is no
        honest way to fill ``cost_usd`` here. Duration is still useful to
        callers, so return that and leave cost at zero.
        """
        try:
            details = await self.get_call_status(call_id)
        except Exception as e:
            logger.warning(f"Failed to fetch Exotel call details for {call_id}: {e}")
            return {
                "cost_usd": 0.0,
                "duration": 0,
                "status": "unknown",
                "raw_response": {},
            }

        call = details.get("Call") or {}
        try:
            duration = int(call.get("Duration") or 0)
        except (TypeError, ValueError):
            duration = 0

        return {
            "cost_usd": 0.0,
            "duration": duration,
            "status": call.get("Status") or "unknown",
            "raw_response": details,
        }

    def parse_status_callback(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize an Exotel status callback.

        Exotel's ``Status`` values already line up with the platform's
        vocabulary (``completed``/``failed``/``busy``/``no-answer``); the
        in-flight ones need mapping.
        """
        status_map = {
            "in-progress": TelephonyCallStatus.IN_PROGRESS,
            "in_progress": TelephonyCallStatus.IN_PROGRESS,
            "ringing": TelephonyCallStatus.RINGING,
            "answered": TelephonyCallStatus.ANSWERED,
            "completed": TelephonyCallStatus.COMPLETED,
            "failed": TelephonyCallStatus.FAILED,
            "busy": TelephonyCallStatus.BUSY,
            "no-answer": TelephonyCallStatus.NO_ANSWER,
            "no_answer": TelephonyCallStatus.NO_ANSWER,
            "canceled": TelephonyCallStatus.CANCELED,
            "cancelled": TelephonyCallStatus.CANCELED,
        }

        raw_status = str(data.get("Status") or data.get("CallStatus") or "").lower()
        # ``EventType: answered`` can arrive while Status is still empty.
        if not raw_status and str(data.get("EventType") or "").lower() == "answered":
            raw_status = "answered"

        duration = (
            data.get("ConversationDuration")
            or data.get("Duration")
            or data.get("DialCallDuration")
        )

        return {
            "call_id": data.get("CallSid") or data.get("Sid") or "",
            "status": status_map.get(raw_status, raw_status),
            "from_number": data.get("From") or data.get("CallFrom"),
            "to_number": data.get("To") or data.get("CallTo"),
            "direction": data.get("Direction"),
            "duration": str(duration) if duration not in (None, "") else None,
            "extra": data,
        }

    async def verify_webhook_signature(
        self, url: str, params: Dict[str, Any], signature: str
    ) -> bool:
        """Exotel does not sign webhooks; see :meth:`verify_inbound_signature`."""
        return True

    async def get_webhook_response(
        self, workflow_id: int, organization_id: int, workflow_run_id: int
    ) -> str:
        """Unused — Exotel learns the stream URL from the dial request or from
        :meth:`start_inbound_stream`, never from a markup response."""
        return ""

    # ======== MEDIA WEBSOCKET ========

    async def handle_websocket(
        self,
        websocket: "WebSocket",
        workflow_id: int,
        organization_id: int,
        workflow_run_id: int,
    ) -> None:
        """Read Exotel's handshake, then hand the socket to the pipeline.

        Exotel sends ``connected`` and then ``start``, but its own sample
        bridges tolerate the first being absent and the identifiers arriving
        in either snake_case (``stream_sid``, as documented) or camelCase
        (``streamSid``, as the Connect Voice AI path emits). Accept all of
        that rather than pinning one shape.
        """
        from api.services.pipecat.run_pipeline import run_pipeline_telephony

        try:
            start_msg = await self._read_start_message(websocket, workflow_run_id)
        except WebSocketDisconnect as e:
            logger.info(
                f"[run {workflow_run_id}] Exotel WebSocket closed before the start "
                f"event: code={e.code}, reason={e.reason!r}"
            )
            return

        if start_msg is None:
            return

        start_data = start_msg.get("start") or {}
        stream_sid = (
            start_data.get("stream_sid")
            or start_data.get("streamSid")
            or start_msg.get("stream_sid")
            or start_msg.get("streamSid")
            or ""
        )
        call_sid = (
            start_data.get("call_sid")
            or start_data.get("callSid")
            or start_msg.get("call_sid")
            or start_msg.get("callSid")
            or ""
        )

        if not stream_sid:
            logger.error(
                f"[run {workflow_run_id}] Exotel start event missing stream sid: "
                f"{start_msg}"
            )
            await websocket.close(code=4400, reason="Missing stream_sid")
            return

        logger.info(
            f"[run {workflow_run_id}] Exotel stream started: stream_sid={stream_sid} "
            f"call_sid={call_sid} media_format={start_data.get('media_format')}"
        )

        await run_pipeline_telephony(
            websocket,
            provider_name=self.PROVIDER_NAME,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
            organization_id=organization_id,
            call_id=call_sid,
            transport_kwargs={"stream_sid": stream_sid, "call_sid": call_sid},
        )

    @staticmethod
    async def _read_start_message(
        websocket: "WebSocket", workflow_run_id: int
    ) -> Optional[Dict[str, Any]]:
        """Consume pre-``start`` frames and return the ``start`` payload.

        Bounded so a peer that connects and then goes quiet cannot hold the
        org's concurrency slot: only a handful of control frames are allowed
        before ``start``, and audio arriving first is treated as a protocol
        error rather than silently dropped.
        """
        max_preamble_frames = 4
        for _ in range(max_preamble_frames):
            message = json.loads(await websocket.receive_text())
            event = message.get("event")
            if event == "start":
                return message
            if event == "connected":
                logger.debug(f"[run {workflow_run_id}] Exotel WebSocket connected")
                continue
            logger.warning(
                f"[run {workflow_run_id}] Exotel sent '{event}' before 'start'; "
                f"ignoring"
            )

        logger.error(
            f"[run {workflow_run_id}] Exotel did not send a 'start' event within "
            f"{max_preamble_frames} frames"
        )
        await websocket.close(code=4400, reason="Expected start event")
        return None

    # ======== INBOUND ========

    @classmethod
    def can_handle_webhook(
        cls, webhook_data: Dict[str, Any], headers: Dict[str, str]
    ) -> bool:
        """Detect an Exotel App Bazaar callback.

        ``CallFrom``/``CallTo`` are Exotel's own field names and are what
        separate it from Twilio, which shares ``CallSid``/``AccountSid`` but
        always sends ``From``/``To`` plus ``ApiVersion``. The
        ``account_sid`` custom parameter we ask operators to put on the
        Voicebot applet URL is a second, unambiguous marker.
        """
        if webhook_data.get("account_sid") and webhook_data.get("CallSid"):
            return True
        return bool(
            webhook_data.get("CallSid")
            and (webhook_data.get("CallFrom") or webhook_data.get("CallTo"))
        )

    @staticmethod
    def parse_inbound_webhook(webhook_data: Dict[str, Any]) -> NormalizedInboundData:
        """Parse an Exotel Voicebot-applet callback into normalized form."""
        from_raw = webhook_data.get("CallFrom") or webhook_data.get("From") or ""
        # For an inbound leg ``CallTo`` is the ExoPhone that was dialed, while
        # ``To`` may already be the onward destination once the flow connects.
        to_raw = webhook_data.get("CallTo") or webhook_data.get("To") or ""

        direction = str(webhook_data.get("Direction") or "").lower()
        if direction in ("", "incoming", "inbound", "call-attempt"):
            direction = "inbound"

        return NormalizedInboundData(
            provider=ExotelProvider.PROVIDER_NAME,
            call_id=webhook_data.get("CallSid") or "",
            from_number=(
                normalize_telephony_address(
                    from_raw, country_hint=EXOTEL_COUNTRY_HINT
                ).canonical
                if from_raw
                else ""
            ),
            to_number=(
                normalize_telephony_address(
                    to_raw, country_hint=EXOTEL_COUNTRY_HINT
                ).canonical
                if to_raw
                else ""
            ),
            direction=direction,
            call_status=webhook_data.get("CallStatus") or "ringing",
            account_id=webhook_data.get("account_sid")
            or webhook_data.get("AccountSid"),
            to_country=EXOTEL_COUNTRY_HINT,
            raw_data=webhook_data,
        )

    @staticmethod
    def validate_account_id(config_data: dict, webhook_account_id: str) -> bool:
        if not webhook_account_id:
            return False
        return config_data.get("account_sid") == webhook_account_id

    async def verify_inbound_signature(
        self,
        url: str,
        webhook_data: Dict[str, Any],
        headers: Dict[str, str],
        body: str = "",
    ) -> bool:
        """Authenticate the inbound callback with the configured shared token.

        Exotel offers no webhook signing for App Bazaar callbacks — its own
        guidance is IP whitelisting — so this compares the ``token`` custom
        parameter on the Voicebot applet URL against ``inbound_secret``.
        Configurations saved through the normal path always have a token
        (one is generated on save); when none is stored there is nothing to
        check and the request is allowed, which is the pre-existing behaviour
        for unsigned providers. Whitelist Exotel's egress ranges at the edge
        if you rely on that path.
        """
        if not self.inbound_secret:
            logger.warning(
                "Exotel inbound webhook accepted without verification: no "
                "inbound_secret is set on this telephony configuration. Set one "
                "and add it as the 'token' parameter on the Voicebot applet URL."
            )
            return True

        presented = webhook_data.get("token") or ""
        if not presented:
            query = parse_qs(urlparse(url).query)
            presented = (query.get("token") or [""])[0]

        if not presented:
            logger.warning("Exotel inbound webhook missing the 'token' parameter")
            return False

        if not hmac.compare_digest(
            self.inbound_secret.encode("utf-8"), presented.encode("utf-8")
        ):
            logger.warning("Exotel inbound webhook presented an invalid token")
            return False
        return True

    async def start_inbound_stream(
        self,
        *,
        websocket_url: str,
        workflow_run_id: int,
        normalized_data: NormalizedInboundData,
        backend_endpoint: str,
    ) -> Any:
        """Hand the per-call media socket back to the Voicebot applet.

        A Voicebot applet pointed at an ``https://`` URL expects a JSON body
        with a single ``url`` key holding the ``wss://`` endpoint to dial.
        """
        separator = "&" if "?" in websocket_url else "?"
        stream_url = (
            f"{websocket_url}{separator}sample-rate={EXOTEL_STREAM_SAMPLE_RATE}"
        )
        logger.info(
            f"[run {workflow_run_id}] Returning Exotel stream URL for call "
            f"{normalized_data.call_id}"
        )
        return {"url": stream_url}

    async def configure_inbound(
        self, address: str, webhook_url: Optional[str]
    ) -> ProviderSyncResult:
        """Report the manual App Bazaar step; Exotel has no API for it.

        Inbound routing lives in the Exotel console: an ExoPhone is bound to a
        custom App, and the Voicebot applet inside that App holds the URL. No
        public API sets an applet's URL, so instead of silently succeeding we
        return the exact URL to paste, which the caller surfaces as a
        non-fatal warning.
        """
        if webhook_url is None:
            return ProviderSyncResult(
                ok=False,
                message=(
                    f"Inbound was detached from {address} in SpinSci, but Exotel "
                    f"routing is console-side: remove or repoint the Voicebot "
                    f"applet on the App Bazaar flow bound to this ExoPhone."
                ),
            )

        backend_endpoint, _ = await get_backend_endpoints()
        voicebot_url = build_inbound_voicebot_url(
            backend_endpoint, self.account_sid or "", self.inbound_secret
        )
        return ProviderSyncResult(
            ok=False,
            message=(
                f"Exotel inbound routing must be set in App Bazaar. Point the "
                f"Voicebot applet on the flow bound to {address} at: "
                f"{voicebot_url}"
            ),
        )

    async def validate_phone_number(self, address: str) -> ProviderSyncResult:
        """Accept the address without an ownership lookup.

        Exotel's ExoPhone inventory API is ``v2_beta`` and its response shape
        is not stable enough to treat as an ownership oracle — a wrong guess
        here would reject numbers the account really owns. Dialing with a
        ``CallerId`` the account does not own fails fast at Exotel instead,
        which is the safer failure mode. Revisit when the ExoPhones API
        leaves beta.
        """
        return ProviderSyncResult(ok=True)

    @staticmethod
    def generate_error_response(error_type: str, message: str):
        from fastapi import Response

        return Response(
            content=json.dumps({"error": error_type, "message": message}),
            media_type="application/json",
            status_code=200,
        )

    @staticmethod
    def generate_validation_error_response(error_type):
        from fastapi import Response

        from api.errors.telephony_errors import TELEPHONY_ERROR_MESSAGES, TelephonyError

        message = TELEPHONY_ERROR_MESSAGES.get(
            error_type, TELEPHONY_ERROR_MESSAGES[TelephonyError.GENERAL_AUTH_FAILED]
        )
        # Returned to Exotel, which only looks for a "url" key. Omitting it
        # makes the applet fall through to the next applet in the flow instead
        # of hanging the caller on a silent socket.
        return Response(
            content=json.dumps({"error": str(error_type), "message": message}),
            media_type="application/json",
            status_code=200,
        )

    # ======== CALL TRANSFER ========

    def supports_transfers(self) -> bool:
        """Exotel exposes no conference/bridge primitive on the stream leg.

        A transfer would have to be modelled as a fresh ``Calls/connect`` to
        the destination, which drops the caller instead of bridging them.
        Reporting False keeps the transfer tool off Exotel runs rather than
        offering one that silently loses the call.
        """
        return False

    async def transfer_call(
        self,
        destination: str,
        transfer_id: str,
        conference_name: str,
        timeout: int = 30,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        raise NotImplementedError(
            "Exotel call transfer is not supported: the Voicebot/AgentStream leg "
            "has no conference or bridge primitive to hand the caller off with."
        )
