"""Thin async client for the OpenEMR standard REST API.

Owns the OAuth2 password-grant lifecycle so callers never see tokens: the
first request fetches one, subsequent requests reuse it until shortly before
expiry, and a 401 triggers exactly one forced refresh + retry (OpenEMR also
invalidates tokens server-side on restart, which looks identical to expiry).

Scope is deliberately narrow: transport, auth, and unwrapping OpenEMR's
``{validationErrors, internalErrors, data, links}`` envelope. All nutrition
domain logic lives in ``server.py``.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Mapping

import httpx

ENV_PATH = Path(__file__).resolve().parent.parent / ".env.openemr"

# Refresh a little early so a token can't expire mid-flight.
_EXPIRY_SKEW_SECONDS = 60


class OpenEMRError(RuntimeError):
    """An OpenEMR request failed. Message is safe to surface to the agent."""


def load_env(path: Path = ENV_PATH) -> dict[str, str]:
    """Read the dotenv written by setup_api_client.py, with os.environ winning.

    Kept dependency-free (no python-dotenv) so the MCP server can run outside
    the API virtualenv.
    """
    values: dict[str, str] = {}
    if path.exists():
        for raw_line in path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()

    for key in list(values) + [
        "OPENEMR_BASE_URL",
        "OPENEMR_CLIENT_ID",
        "OPENEMR_CLIENT_SECRET",
        "OPENEMR_USERNAME",
        "OPENEMR_PASSWORD",
        "OPENEMR_SCOPES",
        "OPENEMR_VERIFY_SSL",
    ]:
        override = os.environ.get(key)
        if override is not None:
            values[key] = override
    return values


class OpenEMRClient:
    """Authenticated access to ``{base_url}/apis/default/api``."""

    def __init__(
        self,
        *,
        base_url: str,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
        scopes: str,
        verify_ssl: bool = True,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._username = username
        self._password = password
        self._scopes = scopes
        self._api_root = f"{self._base_url}/apis/default/api"

        self._http = httpx.AsyncClient(verify=verify_ssl, timeout=timeout_seconds)
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        # Serialise refreshes so concurrent tool calls don't stampede the
        # token endpoint (and invalidate each other's tokens).
        self._token_lock = asyncio.Lock()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "OpenEMRClient":
        env = dict(env if env is not None else load_env())
        missing = [
            key
            for key in (
                "OPENEMR_BASE_URL",
                "OPENEMR_CLIENT_ID",
                "OPENEMR_CLIENT_SECRET",
                "OPENEMR_USERNAME",
                "OPENEMR_PASSWORD",
            )
            if not env.get(key)
        ]
        if missing:
            raise OpenEMRError(
                "Missing OpenEMR configuration: "
                + ", ".join(missing)
                + ". Run: python integrations/openemr/setup_api_client.py"
            )
        verify = env.get("OPENEMR_VERIFY_SSL", "true").strip().lower() not in {
            "false",
            "0",
            "no",
        }
        return cls(
            base_url=env["OPENEMR_BASE_URL"],
            client_id=env["OPENEMR_CLIENT_ID"],
            client_secret=env["OPENEMR_CLIENT_SECRET"],
            username=env["OPENEMR_USERNAME"],
            password=env["OPENEMR_PASSWORD"],
            scopes=env.get("OPENEMR_SCOPES", "openid offline_access api:oemr"),
            verify_ssl=verify,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # ---------------------------------------------------------------- auth

    async def _token(self, *, force_refresh: bool = False) -> str:
        async with self._token_lock:
            if (
                not force_refresh
                and self._access_token
                and time.monotonic() < self._expires_at
            ):
                return self._access_token

            response = await self._http.post(
                f"{self._base_url}/oauth2/default/token",
                data={
                    "grant_type": "password",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "scope": self._scopes,
                    "user_role": "users",
                    "username": self._username,
                    "password": self._password,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if response.status_code != 200:
                raise OpenEMRError(
                    f"OpenEMR token request failed ({response.status_code}): "
                    f"{response.text[:300]}"
                )
            payload = response.json()
            token = payload.get("access_token")
            if not token:
                raise OpenEMRError(f"OpenEMR token response had no access_token: {payload}")

            self._access_token = token
            self._expires_at = (
                time.monotonic() + float(payload.get("expires_in", 3600)) - _EXPIRY_SKEW_SECONDS
            )
            return token

    # ------------------------------------------------------------ requests

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> Any:
        """Call the standard API and return the unwrapped ``data`` payload."""
        url = f"{self._api_root}{path}"
        clean_params = (
            {k: v for k, v in params.items() if v not in (None, "")} if params else None
        )

        response = await self._send(method, url, clean_params, json_body, token_refreshed=False)

        if response.status_code == 404:
            # OpenEMR returns a bare 404 for "no such route" and for some
            # empty collections. Treat it as an empty result and let the
            # caller decide what to say.
            return None
        if response.status_code >= 400:
            raise OpenEMRError(
                f"OpenEMR {method} {path} failed ({response.status_code}): "
                f"{response.text[:300]}"
            )

        if not response.content:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None

        if isinstance(payload, dict):
            validation = payload.get("validationErrors")
            internal = payload.get("internalErrors")
            if validation:
                raise OpenEMRError(f"OpenEMR rejected the request: {validation}")
            if internal:
                raise OpenEMRError(f"OpenEMR internal error: {internal}")
            if "data" in payload:
                return payload["data"]
        return payload

    async def _send(
        self,
        method: str,
        url: str,
        params: Mapping[str, Any] | None,
        json_body: Mapping[str, Any] | None,
        *,
        token_refreshed: bool,
    ) -> httpx.Response:
        token = await self._token(force_refresh=token_refreshed)
        try:
            response = await self._http.request(
                method,
                url,
                params=params,
                json=json_body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            raise OpenEMRError(f"Could not reach OpenEMR at {url}: {exc}") from exc

        if response.status_code == 401 and not token_refreshed:
            # Token rejected — refresh once and retry before giving up.
            return await self._send(method, url, params, json_body, token_refreshed=True)
        return response

    async def get(self, path: str, **params: Any) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, body: Mapping[str, Any]) -> Any:
        return await self.request("POST", path, json_body=body)

    async def put(self, path: str, body: Mapping[str, Any]) -> Any:
        return await self.request("PUT", path, json_body=body)
