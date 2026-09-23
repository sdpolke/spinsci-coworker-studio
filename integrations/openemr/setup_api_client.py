"""Register (and enable) an OpenEMR OAuth2 API client for the MCP server.

OpenEMR exposes dynamic client registration, but a freshly registered client
lands with ``is_enabled = 0`` and normally needs an admin to approve it in
Administration -> System -> API Clients. This script does both steps: it
registers the client over HTTPS, then flips ``is_enabled`` directly in the
MariaDB container (the same thing the admin UI does).

It finishes by running the password grant once, so a non-zero exit means the
credentials it wrote are known-bad rather than merely untested.

Usage:
    python integrations/openemr/setup_api_client.py

Writes ``integrations/openemr/.env.openemr`` (gitignored) containing the
client id/secret the MCP server reads at startup.

Dev-only: the OpenEMR instance uses a self-signed certificate, so TLS
verification is disabled against localhost, and the admin password is written
to a local dotenv. Do not point this at a real OpenEMR deployment.
"""

from __future__ import annotations

import json
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OPENEMR_BASE = "https://localhost:9390"
DB_CONTAINER = "openemr-db"
DB_NAME = "openemr"
DB_ROOT_PASSWORD = "openemr_root_pw"

OPENEMR_USER = "admin"
OPENEMR_PASSWORD = "SpinSciDev123"

CLIENT_NAME = "SpinSci Nutrition Voice Agent"
REDIRECT_URI = f"{OPENEMR_BASE}/swagger/oauth2-redirect.html"

ENV_PATH = Path(__file__).parent / ".env.openemr"

# Standard-API ("lowercase") scopes only. OpenEMR keeps FHIR scopes in a
# separate capitalised namespace (user/Patient.read); the MCP server talks to
# /apis/default/api, so requesting the FHIR set would just be noise.
# Authoritative list: GET /oauth2/default/.well-known/openid-configuration.
SCOPES = [
    "openid",
    "offline_access",
    "api:oemr",
    "user/patient.read",
    "user/patient.write",
    "user/appointment.read",
    "user/appointment.write",
    "user/practitioner.read",
    "user/practitioner.write",
    "user/facility.read",
    "user/facility.write",
    "user/insurance.read",
    "user/insurance.write",
    "user/insurance_company.read",
    "user/insurance_company.write",
    "user/insurance_type.read",
    "user/medical_problem.read",
    "user/medical_problem.write",
    "user/encounter.read",
    "user/encounter.write",
    "user/list.read",
    "user/user.read",
    "user/version.read",
]

# Self-signed localhost certificate.
_SSL_CONTEXT = ssl.create_default_context()
_SSL_CONTEXT.check_hostname = False
_SSL_CONTEXT.verify_mode = ssl.CERT_NONE


def _post(url: str, *, json_body: dict | None = None, form: dict | None = None) -> dict:
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers = {"Content-Type": "application/json"}
    else:
        data = urllib.parse.urlencode(form or {}).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, context=_SSL_CONTEXT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise SystemExit(f"POST {url} failed ({exc.code}): {body}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"POST {url} failed: {exc.reason}. Is OpenEMR running? "
            f"(docker compose -f integrations/openemr/docker-compose.yml ps)"
        ) from exc


def register_client() -> dict:
    print(f"Registering OAuth2 client {CLIENT_NAME!r} ...")
    registration = _post(
        f"{OPENEMR_BASE}/oauth2/default/registration",
        json_body={
            "application_type": "private",
            "client_name": CLIENT_NAME,
            "token_endpoint_auth_method": "client_secret_post",
            "redirect_uris": [REDIRECT_URI],
            "post_logout_redirect_uris": [REDIRECT_URI],
            "contacts": ["dev@spinsci.local"],
            "scope": " ".join(SCOPES),
        },
    )
    client_id = registration.get("client_id")
    if not client_id:
        raise SystemExit(f"Registration returned no client_id: {registration}")
    print(f"  client_id = {client_id}")
    return registration


def enable_client(client_id: str) -> None:
    """Approve the client, equivalent to the admin API Clients screen."""
    print("Enabling client (admin approval) ...")
    # client_id is quoted inside the SQL string; it is a server-generated
    # base64url token, but pass it via argv rather than a shell string so a
    # value containing quotes can't break out of the statement.
    statement = "UPDATE oauth_clients SET is_enabled = 1 WHERE client_id = %s;"
    escaped = client_id.replace("\\", "\\\\").replace("'", "\\'")
    result = subprocess.run(
        [
            "docker",
            "exec",
            DB_CONTAINER,
            "mariadb",
            f"-uroot",
            f"-p{DB_ROOT_PASSWORD}",
            "-D",
            DB_NAME,
            "-e",
            statement % f"'{escaped}'",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"Failed to enable client: {result.stderr.strip()}")
    print("  is_enabled = 1")


def fetch_token(client_id: str, client_secret: str) -> dict:
    """Run the password grant once to prove the credentials work."""
    print("Requesting an access token (password grant) ...")
    token = _post(
        f"{OPENEMR_BASE}/oauth2/default/token",
        form={
            "grant_type": "password",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": " ".join(SCOPES),
            "user_role": "users",
            "username": OPENEMR_USER,
            "password": OPENEMR_PASSWORD,
        },
    )
    if "access_token" not in token:
        raise SystemExit(f"Token request returned no access_token: {token}")
    print(f"  access_token acquired (expires_in={token.get('expires_in')}s)")
    return token


def write_env(client_id: str, client_secret: str) -> None:
    ENV_PATH.write_text(
        "\n".join(
            [
                "# Generated by integrations/openemr/setup_api_client.py",
                "# Dev-only credentials for the local OpenEMR container.",
                f"OPENEMR_BASE_URL={OPENEMR_BASE}",
                f"OPENEMR_CLIENT_ID={client_id}",
                f"OPENEMR_CLIENT_SECRET={client_secret}",
                f"OPENEMR_USERNAME={OPENEMR_USER}",
                f"OPENEMR_PASSWORD={OPENEMR_PASSWORD}",
                f"OPENEMR_SCOPES={' '.join(SCOPES)}",
                "OPENEMR_VERIFY_SSL=false",
                "",
            ]
        )
    )
    print(f"Wrote {ENV_PATH}")


def main() -> int:
    registration = register_client()
    client_id = registration["client_id"]
    client_secret = registration["client_secret"]

    enable_client(client_id)
    fetch_token(client_id, client_secret)
    write_env(client_id, client_secret)

    print("\nOpenEMR API client is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
