"""Register direct OpenEMR gateway tools in SpinSci.

The gateway handles OpenEMR OAuth. These are ordinary reusable ``http_api``
tools, so their LLM function names are the stable raw operation names rather
than MCP namespaces.

Usage:
    venv/bin/python integrations/openemr/register_http_tools.py \
      --api-key "$SPINSCI_ORG2_API_KEY"

The script creates an organization-owned API-key credential containing the
SpinSci API key, then creates or reuses the 11 gateway tools. It writes the
mapping to ``integrations/openemr/.http_tool_uuids.json`` (gitignored).
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MAPPING_PATH = REPO_ROOT / "integrations/openemr/.http_tool_uuids.json"
DEFAULT_ENDPOINT = "http://localhost:8000"
GATEWAY_BASE = "/api/v1/integrations/openemr"
CREDENTIAL_NAME = "OpenEMR gateway API authentication"


TOOLS = [
    {
        "name": "identify_patient_by_phone",
        "description": "Look up the patient chart by phone number. Call this first after the caller confirms a phone number. Returns patient_id, name, age, and is_pediatric from OpenEMR.",
        "path": "/patient/lookup",
        "parameters": [{"name": "phone", "type": "string", "description": "The patient's phone number, including digits or spoken digit text.", "required": True}],
    },
    {
        "name": "check_nutrition_eligibility",
        "description": "Check the selected patient's OpenEMR problem list against nutrition clinic eligibility and refer-out rules.",
        "path": "/patient/eligibility",
        "parameters": [{"name": "patient_id", "type": "string", "description": "The numeric patient_id returned by identify_patient_by_phone.", "required": True}],
    },
    {
        "name": "check_gdm_referral",
        "description": "Verify whether the selected patient's gestational diabetes referral came from Summit Health.",
        "path": "/patient/gdm-referral",
        "parameters": [{"name": "patient_id", "type": "string", "description": "The numeric patient_id returned by identify_patient_by_phone.", "required": True}],
    },
    {
        "name": "route_pediatric_patient",
        "description": "Route a pediatric patient to Alexa Bacino and store the provider assignment in OpenEMR.",
        "path": "/patient/route-pediatric",
        "parameters": [{"name": "patient_id", "type": "string", "description": "The numeric patient_id returned by identify_patient_by_phone.", "required": True}],
    },
    {
        "name": "check_nutrition_coverage",
        "description": "Check active insurance coverage for the selected patient in OpenEMR.",
        "path": "/patient/coverage",
        "parameters": [{"name": "patient_id", "type": "string", "description": "The numeric patient_id returned by identify_patient_by_phone.", "required": True}],
    },
    {
        "name": "get_patient_instructions",
        "description": "Get pre-visit instructions for the selected patient from the nutrition workflow.",
        "path": "/patient/instructions",
        "parameters": [
            {"name": "patient_id", "type": "string", "description": "The numeric patient_id returned by identify_patient_by_phone.", "required": True},
            {"name": "tests_blood_sugar_at_home", "type": "boolean", "description": "Whether the patient tests blood sugar at home.", "required": False},
        ],
    },
    {
        "name": "find_available_slots",
        "description": "Find available nutrition appointment slots for the selected patient. Pass patient_id so adult and pediatric providers are filtered correctly.",
        "path": "/appointments/slots",
        "parameters": [
            {"name": "patient_id", "type": "string", "description": "The numeric patient_id returned by identify_patient_by_phone.", "required": True},
            {"name": "visit_type", "type": "string", "description": "Use Nutrition Follow Up unless the caller explicitly requests a new-patient or telehealth visit.", "required": False},
            {"name": "provider_name", "type": "string", "description": "Optional provider full name; normally leave empty and let the patient context filter providers.", "required": False},
            {"name": "days_ahead", "type": "number", "description": "Number of days forward to search; use 3 for GDM.", "required": False},
            {"name": "max_results", "type": "number", "description": "Maximum number of slots to return.", "required": False},
        ],
    },
    {
        "name": "validate_slot_policy",
        "description": "Validate the exact selected slot_id from find_available_slots. Never replace slot_id with only a visit type.",
        "path": "/appointments/slot-policy",
        "parameters": [
            {"name": "slot_id", "type": "string", "description": "The exact slot_id returned by find_available_slots and selected by the caller.", "required": True},
            {"name": "wants_virtual", "type": "boolean", "description": "Whether the caller requested a virtual visit.", "required": False},
        ],
    },
    {
        "name": "book_nutrition_appointment",
        "description": "Book the exact selected slot in OpenEMR without changing its visit type.",
        "path": "/appointments/book",
        "parameters": [
            {"name": "patient_id", "type": "string", "description": "The numeric patient_id returned by identify_patient_by_phone.", "required": True},
            {"name": "slot_id", "type": "string", "description": "The exact slot_id selected by the caller.", "required": True},
            {"name": "reason", "type": "string", "description": "Short reason for the visit.", "required": False},
        ],
    },
    {
        "name": "get_patient_appointments",
        "description": "List the selected patient's appointments from OpenEMR for confirmation.",
        "path": "/appointments/list",
        "parameters": [{"name": "patient_id", "type": "string", "description": "The numeric patient_id returned by identify_patient_by_phone.", "required": True}],
    },
    {
        "name": "escalate_gdm_scheduling",
        "description": "Record and escalate a GDM scheduling failure when no slot is available within 72 hours.",
        "path": "/appointments/gdm-escalate",
        "parameters": [
            {"name": "patient_id", "type": "string", "description": "The numeric patient_id returned by identify_patient_by_phone.", "required": True},
            {"name": "reason", "type": "string", "description": "Reason for the escalation.", "required": False},
        ],
    },
]


def api_call(endpoint: str, api_key: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"X-API-Key": api_key}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"{method} {path} failed ({exc.code}): {exc.read().decode(errors='replace')}"
        ) from exc


def create_credential(endpoint: str, api_key: str) -> str:
    result = api_call(
        endpoint,
        api_key,
        "POST",
        "/api/v1/credentials/",
        {
            "name": CREDENTIAL_NAME,
            "description": "SpinSci API key used by direct OpenEMR gateway tools.",
            "credential_type": "api_key",
            "credential_data": {"header_name": "X-API-Key", "api_key": api_key},
        },
    )
    return result["uuid"]


def tool_request(endpoint: str, credential_uuid: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": spec["name"],
        "description": spec["description"],
        "category": "http_api",
        "definition": {
            "schema_version": 1,
            "type": "http_api",
            "config": {
                "method": "POST",
                "url": f"{endpoint.rstrip('/')}{GATEWAY_BASE}{spec['path']}",
                "credential_uuid": credential_uuid,
                "parameters": spec["parameters"],
                "timeout_ms": 20000,
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key", default=os.environ.get("SPINSCI_API_TOKEN"), required=False)
    parser.add_argument("--api-endpoint", default=os.environ.get("SPINSCI_API_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--credential-uuid", default=None)
    args = parser.parse_args()
    if not args.api_key:
        raise SystemExit("--api-key or SPINSCI_API_TOKEN is required")

    credential_uuid = args.credential_uuid or create_credential(args.api_endpoint, args.api_key)
    mapping: dict[str, str] = {}
    for spec in TOOLS:
        response = api_call(
            args.api_endpoint,
            args.api_key,
            "POST",
            "/api/v1/tools/",
            tool_request(args.api_endpoint, credential_uuid, spec),
        )
        mapping[spec["name"]] = response["tool_uuid"]
        print(f"{spec['name']}: {response['tool_uuid']}")

    MAPPING_PATH.write_text(
        json.dumps({"credential_uuid": credential_uuid, "tools": mapping}, indent=2) + "\n"
    )
    print(f"credential_uuid: {credential_uuid}")
    print(f"wrote: {MAPPING_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
