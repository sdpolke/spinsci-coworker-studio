# OpenEMR nutrition agent integration

Turns the nutrition workflow diagram in
`docs/json_workflows_samples/nutrition_agent_workflow.json` into a running
SpinSci voice agent whose tool calls hit a real OpenEMR EHR.

Three pieces:

| Piece | What it is |
| --- | --- |
| `docker-compose.yml` | Local OpenEMR 8.4 + MariaDB |
| `mcp_server/` | Optional MCP surface exposing the same OpenEMR operations over streamable HTTP |
| `api/services/integrations/openemr/` | Authenticated FastAPI gateway used by direct SpinSci HTTP tools |
| `register_http_tools.py` | Registers ordinary `http_api` tools for the gateway |
| `attach_http_tools.py` | Rebinds workflow 16 from MCP tools to direct HTTP tools |
| `generate_nutrition_workflow.py` | Compiles the spec diagram into a SpinSci `workflow_definition` |

Everything here is **dev-only**. Credentials are local placeholders and the
OpenEMR container uses a self-signed certificate.

## Setup

```bash
# 1. Start OpenEMR (first boot runs the installer; takes a few minutes)
docker compose -f integrations/openemr/docker-compose.yml up -d
docker compose -f integrations/openemr/docker-compose.yml logs -f openemr

# 2. Register + enable an OAuth2 API client, then verify the password grant
python integrations/openemr/setup_api_client.py

# 3. Seed nutrition-clinic demo data (idempotent)
python integrations/openemr/seed_data.py

# 4. Run the MCP server only if you want the optional MCP surface
OPENEMR_MCP_API_KEY=spinsci-openemr-dev-key \
    python integrations/openemr/mcp_server/server.py

# 5. Verify the domain operations against live OpenEMR
python integrations/openemr/test_mcp_tools.py

# 6. Register direct HTTP tools and attach them to workflow 16
python integrations/openemr/register_http_tools.py \
    --api-key "$SPINSCI_API_TOKEN"
python integrations/openemr/attach_http_tools.py \
    --api-key "$SPINSCI_API_TOKEN"
```

OpenEMR UI: <https://localhost:9390/> — `admin` / `SpinSciDev123`.
The `OE_PASS` in the compose file overrides OpenEMR's default `pass`.

`setup_api_client.py` writes `.env.openemr` (gitignored) with the client
credentials the MCP server reads. Re-run it if you recreate the containers.

## Wiring it into SpinSci

```bash
python integrations/openemr/generate_nutrition_workflow.py \
    --create --validate \
    --api-endpoint http://localhost:8000 \
    --api-key "$SPINSCI_API_TOKEN" \
    --mcp-url http://127.0.0.1:8765/mcp \
    --credential-uuid "$MCP_CREDENTIAL_UUID"
```

This registers ordinary `http_api` tools whose URLs point to the authenticated
FastAPI gateway. The gateway calls OpenEMR using the server-side OAuth-aware
client, so SpinSci never receives the OpenEMR client secret or an expiring
OpenEMR token. `register_http_tools.py` writes the direct tool UUID mapping to
the gitignored `.http_tool_uuids.json`; `attach_http_tools.py` updates and
publishes workflow 16. The direct tool function names are stable raw names such
as `identify_patient_by_phone` and `find_available_slots` — there is no MCP
namespace in the agent's tool list.

The gateway requires the SpinSci API key in `X-API-Key` and is organization
scoped through the normal auth dependency. It is intended for this local
single-OpenEMR development setup; a multi-tenant deployment needs an
organization-specific OpenEMR credential boundary.

The older `generate_nutrition_workflow.py --create` path registers the optional
MCP tool and creates a new workflow. Use the direct-tool scripts above for the
published workflow 16.

Without `--create` the generator just writes
`docs/json_workflows_samples/generated_nutrition_voice_workflow.json`, and
`--validate` alone runs the backend's own DTO and graph validators offline.

## How the spec maps to the workflow

Node types translate mechanically, so editing the spec regenerates the agent:

| Spec `data.type` | SpinSci node | Behaviour |
| --- | --- | --- |
| `start` | `startCall` | Greeting, then capture patient + intent |
| `api_request` | `agentNode` | Calls the bound direct HTTP or MCP tool, speaks its `spoken_summary` |
| `branch` | `agentNode` | Silent routing turn, no speech |
| `conversation` | `agentNode` | Speaks a clinic rule and waits |
| `transfer` | `agentNode` | Escalates via tool, reads back number and option |
| `end` | `endCall` | Short close |
| — | `globalNode` | Synthesised persona + voice/safety rules |

Each node's `detailLines` are carried into the generated prompt verbatim as
clinic rules, so the policy text in the diagram reaches the model rather than
being paraphrased. The `MCP: Name1, Name2` suffix on a detail line is what
binds tools to that node, through `SPEC_TOOL_MAP`.

Edges become transitions: the label is derived from the target node name (made
unique per source, since SpinSci turns labels into LLM function names), and the
condition comes from `CONDITION_TEXT`, keyed on the diagram's edge expression.
An unmapped expression is a hard error rather than a silently vague condition.

The generator can produce MCP-namespaced prompts when used with the optional
MCP tool. Workflow 16 is currently bound to direct HTTP tools, so its prompts
use stable raw names such as `identify_patient_by_phone`. If you switch back to
MCP, regenerate with the MCP workflow path so the namespace matches the MCP
runtime.

`VAPI_Call_GetDetails` and `Call_GetData` are call-platform context rather than
EHR lookups, so they are intentionally unbound and reported as warnings.

## Tools

Each returns a `spoken_summary` for the agent to read plus structured fields
for the workflow's branch conditions. Failures return `{"status": "error"}`
rather than raising, so an unreachable EHR degrades the call instead of
dropping it.

Patient identification is mandatory and is enforced by the workflow runtime:
after the caller confirms the phone number, the `begin_phone_lookup` transition
enters the lookup node and the engine automatically executes
`identify_patient_by_phone` using the confirmed number from conversation history.
The LLM cannot skip this call or replace it with an invented patient. The real
MCP result is attached to the transition result, then the workflow continues to
its age router and condition screening.

Structured MCP results are retained for the internal age, GDM-status, and
72-hour-capacity routers. Those decisions use returned fields rather than
conversational guessing, so a non-GDM patient cannot be sent to GDM escalation
because the model misread a branch condition.

| Tool | OpenEMR data |
| --- | --- |
| `identify_patient_by_phone` | `GET /patient` by cell/home/business phone; derives age |
| `check_nutrition_eligibility` | Problem list; approve vs refer-out classification |
| `check_gdm_referral` | Patient `referrer` field vs the Summit Health rule |
| `route_pediatric_patient` | Writes `providerID` to the chart |
| `find_available_slots` | `GET /appointment`; uses `patient_id` to keep pediatric patients with Alexa Bacino and adult patients with adult nutrition providers |
| `validate_slot_policy` | Validates the exact selected `slot_id`, so the visit type cannot change between nodes |
| `check_nutrition_coverage` | Patient insurance, active-date filtered |
| `book_nutrition_appointment` | `POST /patient/{pid}/appointment` |
| `get_patient_appointments` | Appointment read-back for confirmation |
| `get_patient_instructions` | New-patient / glucose-log instructions |
| `escalate_gdm_scheduling` | Records a chart message, returns escalation number |

Scheduling rules live in `mcp_server/nutrition_policy.py`, which is pure and
has no OpenEMR imports. Every constant traces back to a `detailLines` entry in
the spec.

## Notes on the OpenEMR API

Things that cost time and are easy to get wrong:

- Appointment routes use the **numeric `pid`**; problem-list, insurance and
  patient-update routes use the **`uuid`**.
- `GET /practitioner` only returns users that have an NPI **and** either a
  username or an `abook_type` of `ord_lab`/`spe`/`external_provider`.
  `abook_type` is not in the REST controller's field whitelist, so seeded
  providers get a `username`.
- Insurance `POST` requires `date_end` once `date`, `pid` and `type` are all
  present.
- A newly registered OAuth2 client is created disabled; it must be enabled
  (Administration → System → API Clients, or the `UPDATE` that
  `setup_api_client.py` runs).
- FHIR uses a separate capitalised scope namespace (`user/Patient.read`) and
  has no `Slot` resource in this version, which is why availability is computed
  from the calendar instead.

## Security

- The MCP server reads and writes patient data. With `OPENEMR_MCP_API_KEY`
  unset it starts **unauthenticated** and prints a warning; it binds to
  loopback by default. Always set the key if you change `OPENEMR_MCP_HOST`.
- `.env.openemr` holds the OpenEMR client secret and admin password and is
  gitignored. Don't point `setup_api_client.py` at a real deployment.
- TLS verification is disabled against the container's self-signed certificate
  via `OPENEMR_VERIFY_SSL=false`. Set it to `true` for any real server.
