"""Create and publish a new Nutrition workflow using direct HTTP tools.

Unlike ``attach_http_tools.py`` this never updates workflow 16. It reads the
already-prepared direct-tool artifact and creates a new workflow version under
the authenticated user's organization.

Usage:
    venv/bin/python integrations/openemr/create_direct_nutrition_workflow.py \
      --api-key "$SPINSCI_ORG2_API_KEY"
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = REPO_ROOT / "docs/json_workflows_samples/generated_nutrition_voice_workflow.json"
DEFAULT_ENDPOINT = "http://localhost:8000"
DEFAULT_NAME = "Nutrition Scheduling Agent - Direct OpenEMR API"


def call(endpoint: str, api_key: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else b""
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}{path}",
        data=data,
        headers={"X-API-Key": api_key, "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"{method} {path} failed ({exc.code}): {exc.read().decode(errors='replace')}"
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key", default=os.environ.get("SPINSCI_API_TOKEN"))
    parser.add_argument("--api-endpoint", default=os.environ.get("SPINSCI_API_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--name", default=DEFAULT_NAME)
    parser.add_argument("--workflow-id", type=int, default=None, help="Only for verification; never modified.")
    args = parser.parse_args()
    if not args.api_key:
        raise SystemExit("--api-key or SPINSCI_API_TOKEN is required")

    payload = json.loads(ARTIFACT.read_text())
    definition = payload["workflow_definition"]
    tool_nodes = [n for n in definition["nodes"] if (n.get("data") or {}).get("tool_uuids")]
    if len(tool_nodes) != 11:
        raise SystemExit(f"Expected 11 direct-tool nodes, found {len(tool_nodes)}")
    if any((n.get("data") or {}).get("mcp_tool_filters") for n in definition["nodes"]):
        raise SystemExit("Artifact still contains MCP filters; refusing to create a mixed workflow")
    if any("mcp__openemr_nutrition__" in ((n.get("data") or {}).get("prompt") or "") for n in tool_nodes):
        raise SystemExit("Artifact still contains MCP tool names; refusing to create a mixed workflow")

    created = call(
        args.api_endpoint,
        args.api_key,
        "POST",
        "/api/v1/workflow/create/definition",
        {"name": args.name, "workflow_definition": definition},
    )
    workflow_id = created["id"]
    print(f"created workflow_id={workflow_id} status={created.get('status')}")

    validation = call(args.api_endpoint, args.api_key, "POST", f"/api/v1/workflow/{workflow_id}/validate")
    print(f"validation={validation}")
    if not validation.get("is_valid"):
        raise SystemExit("Created workflow failed validation; not publishing")

    call(args.api_endpoint, args.api_key, "POST", f"/api/v1/workflow/{workflow_id}/create-draft")
    published = call(args.api_endpoint, args.api_key, "POST", f"/api/v1/workflow/{workflow_id}/publish")
    print(f"published={published}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
