import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlencode

import pytest
from starlette.requests import Request

from api.enums import TelephonyCallStatus
from api.services.telephony.providers.exotel.provider import (
    ExotelProvider,
    build_inbound_voicebot_url,
)
from api.services.telephony.providers.exotel.routes import (
    handle_exotel_status_callback,
    handle_exotel_voicebot,
)
from api.services.telephony.providers.twilio.provider import TwilioProvider

INBOUND_SECRET = "exotel-inbound-token"


def _provider(**overrides) -> ExotelProvider:
    config = {
        "api_key": "exotel-api-key",
        "api_token": "exotel-api-token",
        "account_sid": "acme1a",
        "subdomain": "api.in.exotel.com",
        "inbound_secret": INBOUND_SECRET,
        "from_numbers": ["+918043071383"],
    }
    config.update(overrides)
    return ExotelProvider(config)


def _request(
    *,
    path: str,
    method: str = "POST",
    query: dict[str, str] | None = None,
    body: bytes = b"",
    content_type: str | None = None,
) -> Request:
    headers = []
    if content_type:
        headers.append((b"content-type", content_type.encode("ascii")))
        headers.append((b"content-length", str(len(body)).encode("ascii")))

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "scheme": "https",
            "server": ("example.test", 443),
            "path": path,
            "query_string": urlencode(query or {}).encode("utf-8"),
            "headers": headers,
        },
        receive,
    )


# ---------------------------------------------------------------- outbound


@pytest.mark.asyncio
async def test_initiate_call_dials_connect_voice_ai_with_inline_stream_url():
    provider = _provider()
    captured: dict = {}

    class _Response:
        status = 200

        async def text(self):
            return json.dumps({"Call": {"Sid": "call-sid-1", "Status": "in-progress"}})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class _Session:
        def post(self, url, data=None, headers=None, auth=None):
            captured["url"] = url
            captured["fields"] = parse_qs(data.decode("utf-8"))
            captured["auth"] = auth
            return _Response()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    with (
        patch(
            "api.services.telephony.providers.exotel.provider.get_backend_endpoints",
            AsyncMock(
                return_value=("https://api.example.test", "wss://api.example.test")
            ),
        ),
        patch("aiohttp.ClientSession", lambda *a, **k: _Session()),
    ):
        result = await provider.initiate_call(
            to_number="+919876543210",
            webhook_url="ignored",
            workflow_run_id=42,
            workflow_id=7,
            organization_id=3,
        )

    assert captured["url"] == (
        "https://api.in.exotel.com/v1/Accounts/acme1a/Calls/connect.json"
    )
    fields = captured["fields"]
    # Exotel inverts the usual naming: From is the callee, CallerId the ExoPhone.
    assert fields["From"] == ["+919876543210"]
    assert fields["CallerId"] == ["+918043071383"]
    assert fields["StreamType"] == ["bidirectional"]
    assert fields["StreamUrl"] == [
        "wss://api.example.test/api/v1/telephony/ws/7/3/42?sample-rate=8000"
    ]
    assert fields["StatusCallback"] == [
        f"https://api.example.test/api/v1/telephony/exotel/status/42?token={INBOUND_SECRET}"
    ]
    assert set(fields["StatusCallbackEvents[]"]) == {"answered", "terminal"}
    assert fields["CustomField"] == ["workflow_run_id=42"]

    assert result.call_id == "call-sid-1"
    assert result.caller_number == "+918043071383"
    assert result.provider_metadata["call_id"] == "call-sid-1"


@pytest.mark.asyncio
async def test_initiate_call_requires_a_caller_id():
    provider = _provider(from_numbers=[])
    with pytest.raises(ValueError, match="CallerId"):
        await provider.initiate_call(
            to_number="+919876543210", webhook_url="ignored", workflow_run_id=1
        )


def test_validate_config_requires_credentials():
    assert _provider().validate_config() is True
    assert _provider(api_token="").validate_config() is False
    assert _provider(account_sid="").validate_config() is False


# ---------------------------------------------------------------- status mapping


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"Status": "completed"}, TelephonyCallStatus.COMPLETED),
        ({"Status": "no-answer"}, TelephonyCallStatus.NO_ANSWER),
        ({"Status": "busy"}, TelephonyCallStatus.BUSY),
        ({"Status": "failed"}, TelephonyCallStatus.FAILED),
        ({"Status": "in-progress"}, TelephonyCallStatus.IN_PROGRESS),
        ({"EventType": "answered"}, TelephonyCallStatus.ANSWERED),
    ],
)
def test_parse_status_callback_maps_exotel_statuses(payload, expected):
    parsed = _provider().parse_status_callback(
        {"CallSid": "call-sid-1", "ConversationDuration": 31, **payload}
    )
    assert parsed["status"] == expected
    assert parsed["call_id"] == "call-sid-1"
    assert parsed["duration"] == "31"


# ---------------------------------------------------------------- inbound parsing


def test_can_handle_webhook_recognises_exotel_applet_payload():
    assert ExotelProvider.can_handle_webhook(
        {"CallSid": "c1", "CallFrom": "09876543210", "CallTo": "08043071383"}, {}
    )
    assert ExotelProvider.can_handle_webhook(
        {"CallSid": "c1", "account_sid": "acme1a"}, {}
    )


def test_exotel_and_twilio_webhooks_do_not_cross_detect():
    twilio_payload = {
        "CallSid": "CA123",
        "AccountSid": "AC123",
        "ApiVersion": "2010-04-01",
        "From": "+15551230001",
        "To": "+15551230002",
        "Direction": "inbound",
    }
    exotel_payload = {
        "CallSid": "c1",
        "CallFrom": "09876543210",
        "CallTo": "08043071383",
        "account_sid": "acme1a",
    }
    assert TwilioProvider.can_handle_webhook(twilio_payload, {}) is True
    assert ExotelProvider.can_handle_webhook(twilio_payload, {}) is False
    assert TwilioProvider.can_handle_webhook(exotel_payload, {}) is False
    assert ExotelProvider.can_handle_webhook(exotel_payload, {}) is True


def test_parse_inbound_webhook_normalizes_indian_local_numbers():
    normalized = ExotelProvider.parse_inbound_webhook(
        {
            "CallSid": "c1",
            "CallFrom": "09876543210",
            "CallTo": "08043071383",
            "Direction": "incoming",
            "account_sid": "acme1a",
        }
    )
    assert normalized.provider == "exotel"
    assert normalized.direction == "inbound"
    assert normalized.from_number == "+919876543210"
    assert normalized.to_number == "+918043071383"
    assert normalized.account_id == "acme1a"


def test_validate_account_id_rejects_missing_or_mismatched_sid():
    config = {"account_sid": "acme1a"}
    assert ExotelProvider.validate_account_id(config, "acme1a") is True
    assert ExotelProvider.validate_account_id(config, "other2b") is False
    assert ExotelProvider.validate_account_id(config, "") is False


# ---------------------------------------------------------------- inbound auth


@pytest.mark.asyncio
async def test_verify_inbound_signature_checks_the_shared_token():
    provider = _provider()
    url = "https://api.example.test/api/v1/telephony/exotel/voicebot"

    assert await provider.verify_inbound_signature(
        f"{url}?token={INBOUND_SECRET}", {}, {}
    )
    assert await provider.verify_inbound_signature(url, {"token": INBOUND_SECRET}, {})
    assert not await provider.verify_inbound_signature(f"{url}?token=wrong", {}, {})
    assert not await provider.verify_inbound_signature(url, {}, {})


@pytest.mark.asyncio
async def test_verify_inbound_signature_allows_when_no_token_is_configured():
    provider = _provider(inbound_secret=None)
    assert await provider.verify_inbound_signature("https://x/y", {}, {})


# ---------------------------------------------------------------- inbound stream


@pytest.mark.asyncio
async def test_start_inbound_stream_returns_voicebot_url_json():
    provider = _provider()
    response = await provider.start_inbound_stream(
        websocket_url="wss://api.example.test/api/v1/telephony/ws/7/3/42",
        workflow_run_id=42,
        normalized_data=SimpleNamespace(call_id="c1"),
        backend_endpoint="https://api.example.test",
    )
    assert response == {
        "url": "wss://api.example.test/api/v1/telephony/ws/7/3/42?sample-rate=8000"
    }


@pytest.mark.asyncio
async def test_configure_inbound_reports_the_manual_app_bazaar_step():
    provider = _provider()
    with patch(
        "api.services.telephony.providers.exotel.provider.get_backend_endpoints",
        AsyncMock(return_value=("https://api.example.test", "wss://api.example.test")),
    ):
        result = await provider.configure_inbound(
            "+918043071383", "https://api.example.test/api/v1/telephony/inbound/run"
        )
    assert result.ok is False
    assert (
        build_inbound_voicebot_url("https://api.example.test", "acme1a", INBOUND_SECRET)
        in result.message
    )


# ---------------------------------------------------------------- transfers


def test_transfers_are_reported_unsupported():
    provider = _provider()
    assert provider.supports_transfers() is False


@pytest.mark.asyncio
async def test_transfer_call_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        await _provider().transfer_call("+919876543210", "t1", "conf-1")


# ---------------------------------------------------------------- routes


@pytest.mark.asyncio
async def test_voicebot_route_forwards_get_query_params_to_shared_dispatcher():
    captured: dict = {}

    async def fake_handle_inbound_run(request):
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["payload"] = await request.json()
        return {"url": "wss://api.example.test/media"}

    request = _request(
        path="/api/v1/telephony/exotel/voicebot",
        method="GET",
        query={
            "account_sid": "acme1a",
            "token": INBOUND_SECRET,
            "CallSid": "c1",
            "CallFrom": "09876543210",
            "CallTo": "08043071383",
            "Direction": "incoming",
        },
    )

    with patch(
        "api.routes.telephony.handle_inbound_run",
        AsyncMock(side_effect=fake_handle_inbound_run),
    ):
        response = await handle_exotel_voicebot(request)

    assert response == {"url": "wss://api.example.test/media"}
    # Rewritten so the POST-only dispatcher can read it, with the original URL
    # (and therefore the token) preserved for the signature check.
    assert captured["method"] == "POST"
    assert f"token={INBOUND_SECRET}" in captured["url"]
    assert captured["payload"]["CallSid"] == "c1"
    assert captured["payload"]["account_sid"] == "acme1a"


@pytest.mark.asyncio
async def test_status_route_processes_update_when_token_matches():
    provider = _provider()
    body = json.dumps(
        {"CallSid": "c1", "Status": "completed", "Duration": "31"}
    ).encode()
    request = _request(
        path="/api/v1/telephony/exotel/status/42",
        query={"token": INBOUND_SECRET},
        body=body,
        content_type="application/json",
    )

    process = AsyncMock()
    with (
        patch(
            "api.services.telephony.providers.exotel.routes.db_client.get_workflow_run_by_id",
            AsyncMock(return_value=SimpleNamespace(id=42, workflow_id=7)),
        ),
        patch(
            "api.services.telephony.providers.exotel.routes.db_client.get_workflow_by_id",
            AsyncMock(return_value=SimpleNamespace(id=7, organization_id=3)),
        ),
        patch(
            "api.services.telephony.providers.exotel.routes.get_telephony_provider_for_run",
            AsyncMock(return_value=provider),
        ),
        patch(
            "api.services.telephony.providers.exotel.routes._process_status_update",
            process,
        ),
    ):
        response = await handle_exotel_status_callback(request, 42)

    assert response == {"status": "success"}
    status_update = process.await_args.args[1]
    assert status_update.call_id == "c1"
    assert status_update.status == TelephonyCallStatus.COMPLETED


@pytest.mark.asyncio
async def test_status_route_rejects_a_bad_token_with_401():
    from fastapi import HTTPException

    provider = _provider()
    request = _request(
        path="/api/v1/telephony/exotel/status/42",
        query={"token": "forged"},
        body=json.dumps({"CallSid": "c1", "Status": "completed"}).encode(),
        content_type="application/json",
    )

    process = AsyncMock()
    with (
        patch(
            "api.services.telephony.providers.exotel.routes.db_client.get_workflow_run_by_id",
            AsyncMock(return_value=SimpleNamespace(id=42, workflow_id=7)),
        ),
        patch(
            "api.services.telephony.providers.exotel.routes.db_client.get_workflow_by_id",
            AsyncMock(return_value=SimpleNamespace(id=7, organization_id=3)),
        ),
        patch(
            "api.services.telephony.providers.exotel.routes.get_telephony_provider_for_run",
            AsyncMock(return_value=provider),
        ),
        patch(
            "api.services.telephony.providers.exotel.routes._process_status_update",
            process,
        ),
        pytest.raises(HTTPException) as excinfo,
    ):
        await handle_exotel_status_callback(request, 42)

    assert excinfo.value.status_code == 401
    process.assert_not_awaited()
