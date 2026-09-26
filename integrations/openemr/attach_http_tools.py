"""Attach registered direct OpenEMR HTTP tools to the nutrition workflow.

The generator remains the source of the graph/prompt structure. This adapter
replaces each node's MCP binding with the corresponding ordinary ``http_api``
tool UUID and rewrites MCP-namespaced tool references to the stable raw HTTP
tool function names.

Usage:
    python integrations/openemr/attach_http_tools.py \
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
WORKFLOW_FILE = REPO_ROOT / "docs/json_workflows_samples/generated_nutrition_voice_workflow.json"
MAPPING_FILE = REPO_ROOT / "integrations/openemr/.http_tool_uuids.json"
DEFAULT_ENDPOINT = "http://localhost:8000"


def put_json(endpoint: str, api_key: str, path: str, body: dict) -> dict:
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"PUT {path} failed ({exc.code}): {exc.read().decode(errors='replace')}") from exc


def post(endpoint: str, api_key: str, path: str) -> dict:
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}{path}",
        data=b"",
        headers={"X-API-Key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"POST {path} failed ({exc.code}): {exc.read().decode(errors='replace')}") from exc


def build_definition() -> dict:
    payload = json.loads(WORKFLOW_FILE.read_text())
    mapping = json.loads(MAPPING_FILE.read_text())["tools"]
    definition = payload["workflow_definition"]

    for node in definition["nodes"]:
        data = node.get("data") or {}
        filters = data.get("mcp_tool_filters") or {}
        raw_tools = [raw for names in filters.values() for raw in names]
        # Keep the generator's tool names for direct HTTP nodes too. This is
        # intentionally a raw-name function contract, not an MCP namespace.
        if raw_tools:
            missing = [raw for raw in raw_tools if raw not in mapping]
            if missing:
                raise SystemExit(f"No direct HTTP tool UUID for {missing} on node {node['id']}")
            data["tool_uuids"] = [mapping[raw] for raw in raw_tools]
            data["mcp_tool_filters"] = None
            prompt = data.get("prompt") or ""
            for raw in raw_tools:
                prompt = prompt.replace(f"mcp__openemr_nutrition__{raw}", raw)
            data["prompt"] = prompt
            node["data"] = data

    return definition


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key", default=os.environ.get("SPINSCI_API_TOKEN"))
    parser.add_argument("--api-endpoint", default=os.environ.get("SPINSCI_API_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--workflow-id", type=int, default=16)
    args = parser.parse_args()
    if not args.api_key:
        raise SystemExit("--api-key or SPINSCI_API_TOKEN is required")

    definition = build_definition()
    payload = json.loads(WORKFLOW_FILE.read_text())
    payload["workflow_definition"] = definition
    WORKFLOW_FILE.write_text(json.dumps(payload, indent=2) + "\n")

    result = put_json(
        args.api_endpoint,
        args.api_key,
        f"/api/v1/workflow/{args.workflow_id}",
        {"name": payload["name"], "workflow_definition": definition},
    )
    print(f"updated workflow {result.get('id')} status={result.get('status')}")
    validation = post(args.api_endpoint, args.api_key, f"/api/v1/workflow/{args.workflow_id}/validate")
    print(f"validation: {validation}")
    published = post(args.api_endpoint, args.api_key, f"/api/v1/workflow/{args.workflow_id}/publish")
    print(f"published: {published}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
