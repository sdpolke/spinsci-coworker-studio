"""Generate a SpinSci voice-agent workflow from the nutrition spec diagram.

Input is the design-time diagram at
``docs/json_workflows_samples/nutrition_agent_workflow.json`` — nodes carrying a
``label`` plus ``detailLines``, and a ``type`` of start / api_request / branch /
conversation / transfer / end. Output is a runtime
``workflow_definition`` in the shape SpinSci executes (the same shape as
``SpinSci Appointments PoC v10 - Structured Speech.json``).

The mapping is mechanical, so editing the spec regenerates the agent:

    spec type        -> SpinSci node type   tools
    start            -> startCall           (greeting + intent capture)
    api_request      -> agentNode           bound MCP tool(s)
    branch           -> agentNode           none (silent routing turn)
    conversation     -> agentNode           none (speaks a clinic rule)
    transfer         -> agentNode           escalation tool
    end              -> endCall             none
    (synthesised)    -> globalNode          shared persona + voice rules

Each node's ``detailLines`` are carried into the generated prompt verbatim as
clinic rules, so the policy text in the spec reaches the LLM rather than being
paraphrased away. The ``MCP: Name1, Name2`` suffix in a detail line is what
binds tools to that node, via SPEC_TOOL_MAP below.

Usage:
    # write the definition to disk
    python integrations/openemr/generate_nutrition_workflow.py

    # validate against the backend's own DTO + graph rules
    python integrations/openemr/generate_nutrition_workflow.py --validate

    # register the MCP tool + create the workflow in SpinSci
    python integrations/openemr/generate_nutrition_workflow.py --create \
        --api-endpoint http://localhost:8000 --api-key "$SPINSCI_API_TOKEN"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPEC = REPO_ROOT / "docs/json_workflows_samples/nutrition_agent_workflow.json"
DEFAULT_OUTPUT = (
    REPO_ROOT / "docs/json_workflows_samples/generated_nutrition_voice_workflow.json"
)

WORKFLOW_NAME = "Nutrition Scheduling Agent (OpenEMR)"

MCP_TOOL_NAME = "OpenEMR Nutrition"
DEFAULT_MCP_URL = "http://127.0.0.1:8765/mcp"

# Spec MCP identifiers -> tools actually exposed by the OpenEMR MCP server.
# Names present in the spec but absent here have no EHR equivalent and are
# reported by --validate rather than silently dropped.
SPEC_TOOL_MAP: dict[str, str] = {
    "Patient_IdentifyCaller": "identify_patient_by_phone",
    "Nutrition_Condition_CheckEligibility": "check_nutrition_eligibility",
    "Nutrition_GDM_CheckReferral": "check_gdm_referral",
    "Practicioner_RoutePatient": "route_pediatric_patient",
    "Slots_GetAvailable": "find_available_slots",
    "Nutrition_Slot_ValidatePolicy": "validate_slot_policy",
    "Nutrition_GDM_Escalate": "escalate_gdm_scheduling",
    "Coverage_CheckNutritionBenefit": "check_nutrition_coverage",
    "Appointments_Book": "book_nutrition_appointment",
    "Appointments_Get": "get_patient_appointments",
}

# Call-context lookups in the spec that are the voice platform's job, not the
# EHR's. Recorded so --validate can explain why they are unmapped.
NON_EHR_SPEC_TOOLS = {"VAPI_Call_GetDetails", "Call_GetData"}

# Nodes whose spec text implies a tool the diagram does not name.
EXTRA_NODE_TOOLS: dict[str, list[str]] = {
    "instructions": ["get_patient_instructions"],
}

# These nodes are internal routers, not conversational prompts. Avoid labels
# that sound like questions because the label is included in the node name and
# can override an instruction such as "do not ask a question".
INTERNAL_NODE_NAMES = {
    "age_check": "Route by returned patient age",
    "gdm_check": "Route by returned GDM status",
    "gdm_capacity": "Route by 72-hour slot capacity",
}

# Transition names are exposed to the LLM as functions. Avoid names that claim
# an EHR action already happened: `verify_patient_chart` caused the model to
# treat the graph handoff as the completed patient lookup and skip the MCP call.
EDGE_LABEL_OVERRIDES = {
    "start__identify_patient__0": "begin_phone_lookup",
    "identify_patient__age_check__1": "route_by_returned_patient_age",
    "age_check__route_pediatric__2": "route_to_alexa_bacino",
    "age_check__condition_check__3": "begin_condition_screening",
    "route_pediatric__pediatric_end__4": "complete_pediatric_routing",
    "condition_check__refer_out__5": "route_to_refer_out",
    "condition_check__gdm_check__6": "route_to_gdm_screening",
    "refer_out__refer_out_end__7": "complete_refer_out",
    "gdm_check__gdm_referral__8": "begin_gdm_referral_check",
    "gdm_check__find_slots__9": "begin_slot_search",
    "gdm_referral__outside_referral__10": "route_to_outside_referral",
    "gdm_referral__find_slots__11": "begin_slot_search",
    "outside_referral__outside_referral_end__12": "complete_external_referral",
    "find_slots__slot_policy__13": "begin_slot_policy_check",
    "slot_policy__gdm_capacity__14": "route_to_72_hour_check",
    "gdm_capacity__gdm_escalate__15": "route_to_gdm_escalation",
    "gdm_capacity__coverage_check__16": "begin_coverage_check",
    "gdm_escalate__gdm_escalated_end__17": "complete_gdm_escalation",
    "coverage_check__fee_notice__18": "begin_fee_notice",
    "fee_notice__book__19": "begin_booking",
    "book__instructions__20": "begin_patient_instructions",
    "instructions__confirm__21": "begin_appointment_confirmation",
    "confirm__booked_end__22": "complete_appointment",
}

# Spec edge expressions -> conditions phrased for the LLM. Keyed exactly on the
# diagram's edge labels so an unmapped expression fails loudly in _condition().
CONDITION_TEXT: dict[str, str] = {
    "patient_age < pediatric_age_limit": (
        "identify_patient_by_phone reported is_pediatric true for the selected "
        "patient, meaning the patient is under 18."
    ),
    "condition in [eating_disorder, adult_tube_feeding, nephrology]": (
        "check_nutrition_eligibility returned status refer_out, meaning the "
        "condition is an eating disorder, adult tube feeding, or nephrology."
    ),
    "condition_is_approved": (
        "check_nutrition_eligibility returned status approved."
    ),
    "condition == gestational_diabetes": (
        "check_nutrition_eligibility returned is_gestational_diabetes true."
    ),
    "referring_provider != Summit Health": (
        "check_gdm_referral returned status external, meaning the referral did "
        "not come from a Summit Health provider."
    ),
    "referring_provider == Summit Health": (
        "check_gdm_referral returned status internal, meaning the referral came "
        "from a Summit Health provider."
    ),
    "is_gdm and no_slot_within_72_hours": (
        "The patient has gestational diabetes and find_available_slots returned "
        "any_within_gdm_window false, so nothing is available inside 72 hours."
    ),
}

GLOBAL_PROMPT = """You are a scheduling assistant for a nutrition clinic, speaking with a caller on the phone.

VOICE OUTPUT RULES:
- Return plain spoken text only. Never use Markdown, bullets, headings, asterisks, brackets, stage directions, or JSON.
- Keep every turn short and conversational. Ask at most one question, then stop and wait for the caller.
- Never read a tool's raw output, field names, status values, ids, or slot_id strings aloud. When a tool returns spoken_summary, speak that wording.
- Speak dates naturally: say "Thursday, October ninth", never "2026-10-09".
- Speak times naturally: say "nine thirty A M", never "09:30:00".
- Read phone numbers back in short digit groups.

CLINICAL SAFETY:
- Never invent a patient, diagnosis, referral, appointment time, provider, or coverage detail. Only say what a tool returned.
- Never promise a booking until book_nutrition_appointment has confirmed it.
- You are scheduling only. Do not give medical, dietary, or dosing advice; if asked, say a dietitian will cover that at the visit.

- Never ask for the caller's name, the patient's full name, age, or adult/pediatric status before the phone lookup. The phone number is the identity input for this workflow.
- After the phone lookup returns a unique patient, treat its returned name, age, and is_pediatric fields as authoritative. Do not ask the caller to confirm facts the tool already returned.
- Internal routing nodes are silent. They must call one offered transition immediately and must not wait for, respond to, or ask the caller anything.

TURN RULES:
- Use at most one tool per turn. After a tool returns, either speak the result or make the single next workflow transition.
- Do not re-ask for information the caller already gave or a tool already returned.
- Workflow handoffs are silent. Never say "one moment", "let me transfer you", or narrate internal steps.

- Workflow transitions only move between workflow nodes; a transition result such as `{"status":"done"}` never means that an EHR lookup, eligibility check, availability search, or booking happened.
- After a transition into an API-request node, call that node's offered MCP tool before claiming any data was fetched.
- Do not claim that a chart, diagnosis, appointment, slot, or coverage was found unless the corresponding MCP tool returned it.

TOOL CALLING:
- Only ever call a tool whose name appears in the tools available to you this turn. Use the name exactly as given, including any `mcp__` prefix.
- Never invent, guess, shorten, or rename a tool. If the tool you expect is not offered, do not call anything; continue the conversation instead.
- The node prompt tells you the exact tool name to use at each step. Match it character for character."""


# --------------------------------------------------------------- spec parsing


def _detail_text(node_data: dict) -> str:
    return " ".join(line.strip() for line in node_data.get("detailLines") or [])


def _spec_tools(node_data: dict) -> list[str]:
    """Extract the spec MCP identifiers named in a node's detailLines."""
    found: list[str] = []
    for line in node_data.get("detailLines") or []:
        match = re.search(r"MCP:\s*(.+)$", line.strip())
        if not match:
            continue
        for raw in match.group(1).split(","):
            name = raw.strip().rstrip(".")
            if name:
                found.append(name)
    return found


def _rules(node_data: dict) -> list[str]:
    """detailLines with the trailing 'MCP: ...' binding stripped off."""
    out: list[str] = []
    for line in node_data.get("detailLines") or []:
        text = re.sub(r"\s*MCP:\s*.+$", "", line.strip()).strip()
        if text:
            out.append(text)
    return out


# ------------------------------------------------------------ prompt building


def _slugify(value: str) -> str:
    """Mirror api.services.workflow.tools.mcp_tool._slugify."""
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def namespaced_tool_name(tool_display_name: str, raw_tool: str) -> str:
    """LLM-visible name for an MCP tool: ``mcp__<slug>__<raw>``.

    Must match api.services.workflow.tools.mcp_tool.namespace_function_name, so
    prompts reference the exact name the runtime puts in request.tools. Getting
    this wrong is fatal at call time: the model calls the name from the prompt,
    and if it is not the namespaced one the LLM provider rejects the tool call
    ("tool ... which was not in request.tools").
    """
    slug = _slugify(tool_display_name) or "server"
    return f"mcp__{slug}__{raw_tool}"


def _tool_sentence(tools: list[str]) -> str:
    if not tools:
        return ""
    if len(tools) == 1:
        return f"Call the tool named exactly `{tools[0]}` for this step."
    listed = ", ".join(f"`{t}`" for t in tools[:-1]) + f" and `{tools[-1]}`"
    return f"Use {listed} for this step, one tool per turn."


def _exact_tool_rule(tools: list[str]) -> str:
    """A hard guard against tool-name hallucination.

    The model was inventing friendlier names (e.g. `get_nutrition_appointment_slots`
    instead of the real `mcp__..._find_available_slots`) and the LLM provider
    rejects any call whose name is not in the offered tool list. Restating the
    exact allowed name and forbidding substitution is what stops it.
    """
    allowed = ", ".join(f"`{t}`" for t in tools)
    return (
        "## Tool name (critical)\n"
        f"The only tool name you may call at this step is: {allowed}. "
        "Use that exact string. Do not shorten it, rename it, drop the "
        "`mcp__` prefix, or invent a different name. If you cannot see that "
        "exact tool available, do not guess a name."
    )


def _outgoing_labels(node_id: str, edges: list[dict]) -> list[str]:
    return [e["data"]["label"] for e in edges if e["source"] == node_id]


def _build_prompt(
    spec_node: dict,
    tools: list[str],
    out_labels: list[str],
    *,
    is_only_exit: bool,
    tool_display_name: str | None,
) -> str:
    data = spec_node["data"]
    label = INTERNAL_NODE_NAMES.get(
        spec_node["id"], data.get("label") or spec_node["id"]
    )
    kind = data.get("type")
    rules = _rules(data)

    # Prompts must name tools exactly as the runtime exposes them. When the
    # tools are attached as an MCP tool, that is the namespaced form; without a
    # binding (spec preview) fall back to the raw names.
    if tools and tool_display_name:
        prompt_tools = [namespaced_tool_name(tool_display_name, t) for t in tools]
    else:
        prompt_tools = list(tools)

    parts: list[str] = [f"# {label}"]

    if kind == "start":
        parts.append(
            "The configured greeting has already asked for the patient's phone "
            "number. This is a phone-first identity step. Do not ask who the "
            "appointment is for, the patient's name, the caller's reason, the "
            "patient's age, or whether the patient is adult or pediatric."
        )
        parts.append(
            "Ask exactly one question: 'Could you please provide the patient's "
            "phone number?' Wait for the complete number. Read the ten digits "
            "back in three groups and ask whether they are correct. If the caller "
            "says no, collect the phone number again. If the caller says yes, "
            "call the begin_phone_lookup transition immediately. This transition "
            "only moves to the lookup step; it does not verify or fetch a chart. "
            "Do not ask for a name before or after the phone confirmation."
        )
    elif kind == "api_request":
        parts.append(
            f"This step looks up information in the medical record. "
            f"{_tool_sentence(prompt_tools)} Do not speak before the tool call. "
            f"When it returns, read its spoken_summary aloud and say nothing else."
        )
        parts.append(_exact_tool_rule(prompt_tools))
        if spec_node["id"] == "identify_patient":
            parts.append(
                "## Phone verification behavior (critical)\n"
                "This tool accepts only the patient's phone number. Never ask for "
                "or use a full name as a substitute. For invalid_input or no_match, "
                "read the returned retry message and wait for a new phone number. "
                "For one unique match, read the returned spoken_summary exactly "
                "once, treat the returned patient_id, age, and is_pediatric as "
                "authoritative, and immediately call route_by_returned_patient_age. "
                "Do not ask 'is that you?', do not ask for age, and do not ask "
                "adult or pediatric. For multiple matches, ask only which listed "
                "patient to use, then continue after the caller selects one."
            )
        elif spec_node["id"] == "find_slots":
            parts.append(
                "## Slot search inputs (critical)\n"
                "Pass the patient_id returned by identify_patient_by_phone. Do "
                "not omit it. Use Nutrition Follow Up unless the caller explicitly "
                "requests a new-patient or telehealth visit. Do not invent a "
                "provider; let the tool filter providers using the patient chart."
            )
        elif spec_node["id"] == "slot_policy":
            parts.append(
                "## Selected slot (critical)\n"
                "Pass the exact slot_id from the slot the caller selected. Do "
                "not send only visit_type and do not change Nutrition Follow Up "
                "to Nutrition New Patient. If the caller has not selected a "
                "listed slot, ask one short question and wait."
            )
    elif kind == "branch":
        branch_instructions = {
            "age_check": (
                "Internal router only. Never speak to the caller, never ask a "
                "question, and never wait for caller input. Inspect the immediately "
                "preceding identify_patient_by_phone result. If its patients[0]."
                f"is_pediatric is true, call {out_labels[0]} now. Otherwise "
                f"call {out_labels[1]} now. Call exactly one transition and do not "
                "generate a conversational reply."
            ),
            "gdm_check": (
                "Internal router only. Never speak or ask whether the caller has "
                "gestational diabetes. Inspect the immediately preceding "
                "check_nutrition_eligibility result. If "
                f"is_gestational_diabetes is true, call {out_labels[0]}; "
                f"otherwise call {out_labels[1]}. Call exactly one transition "
                "now and do not wait for caller input."
            ),
            "gdm_capacity": (
                "Internal router only. Never speak or ask about slot capacity. "
                "Inspect the existing patient condition and the immediately "
                "preceding find_available_slots result. If the patient is GDM and "
                f"any_within_gdm_window is false, call {out_labels[0]}. "
                f"Otherwise call {out_labels[1]}. Call exactly one transition "
                "now and do not wait for caller input."
            ),
        }.get(
            spec_node["id"],
            "Internal router only. Never speak or ask a question. Use the "
            "information already gathered, call exactly one matching transition "
            "now, and do not wait for caller input.",
        )
        parts.append(branch_instructions)
    elif kind == "conversation":
        if spec_node["id"] == "fee_notice":
            parts.append(
                "The coverage result has already disclosed the possible fee. "
                "Do not repeat the dollar amount or explain insurance again. "
                "Ask one concise question: 'Would you like me to go ahead and "
                "book that time?' Wait for a clear yes before continuing to "
                "booking. If the caller declines, end politely without booking."
            )
        elif spec_node["id"] == "instructions":
            parts.append(
                "Call the instructions tool. If its instructions list is empty, "
                "say nothing about supplies or what to bring and immediately "
                "continue to appointment confirmation. If it returns instructions, "
                "read each instruction once in a concise sentence, then continue "
                "to appointment confirmation. Do not say 'there is nothing special "
                "to bring' unless the caller explicitly asks."
            )
        else:
            parts.append(
                "Tell the caller the following in one or two short sentences, then "
                "stop and wait for their reply."
            )
    elif kind == "transfer":
        parts.append(
            f"This call cannot be completed by scheduling alone. "
            f"{_tool_sentence(prompt_tools)} Then give the caller the phone "
            f"number and option exactly as the tool returned them."
        )
        parts.append(_exact_tool_rule(prompt_tools))
    elif kind == "end":
        parts.append(
            "Close the call warmly in one short sentence. Thank the caller and "
            "say goodbye. Do not repeat the appointment details or add anything "
            "else."
        )

    if rules:
        parts.append("## Clinic rules\n" + "\n".join(f"- {rule}" for rule in rules))

    if prompt_tools and kind not in {"api_request", "transfer"}:
        parts.append(f"## Tools\n{_tool_sentence(prompt_tools)}")

    if out_labels:
        if is_only_exit:
            parts.append(
                f"## Next\nWhen this step is done, call {out_labels[0]} to continue."
            )
        else:
            listed = "\n".join(f"- {name}" for name in out_labels)
            parts.append(
                "## Next\nChoose exactly one of these transitions once you know "
                f"which applies:\n{listed}"
            )

    return "\n\n".join(parts)


# -------------------------------------------------------------- edge building


def _edge_label(target_label: str, used: set[str]) -> str:
    """Human-readable, unique-per-source edge label.

    SpinSci turns the label into an LLM function name by lowercasing and
    replacing non-alphanumerics with underscores, and rejects duplicates on the
    same source node — so uniqueness is enforced on the normalised form.
    """
    base = re.sub(r"[^a-z0-9]+", " ", (target_label or "continue").lower()).strip()
    base = re.sub(r"\s+", "_", base) or "continue"
    candidate = base
    suffix = 2
    while re.sub(r"[^a-z0-9]", "_", candidate.lower()) in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(re.sub(r"[^a-z0-9]", "_", candidate.lower()))
    return candidate


def _condition(spec_edge: dict, *, is_sole_exit: bool, source_label: str) -> str:
    raw = (spec_edge.get("label") or "").strip()
    if raw:
        mapped = CONDITION_TEXT.get(raw)
        if mapped is None:
            raise SystemExit(
                f"Edge {spec_edge['id']!r} has expression {raw!r} with no entry in "
                f"CONDITION_TEXT. Add one so the generated condition is explicit."
            )
        return mapped
    if is_sole_exit:
        return f"The {source_label} step finished successfully."
    return (
        f"None of the other conditions leaving {source_label} apply, so this is "
        f"the default path."
    )


# ----------------------------------------------------------------- generation


def generate(
    spec: dict,
    *,
    tool_uuid: str | None = None,
    tool_display_name: str = MCP_TOOL_NAME,
) -> tuple[dict, list[str]]:
    """Build a workflow_definition. Returns (definition, warnings).

    ``tool_display_name`` must match the ``name`` the MCP tool is registered
    under in SpinSci, because prompts reference tools by their namespaced
    runtime name (``mcp__<slug-of-name>__<raw>``).
    """
    warnings: list[str] = []
    spec_nodes = spec["nodes"]
    spec_edges = spec["edges"]

    by_id = {node["id"]: node for node in spec_nodes}
    labels = {nid: (n["data"].get("label") or nid) for nid, n in by_id.items()}

    # --- resolve tools per node
    node_tools: dict[str, list[str]] = {}
    for node in spec_nodes:
        resolved: list[str] = []
        for spec_name in _spec_tools(node["data"]):
            if spec_name in NON_EHR_SPEC_TOOLS:
                warnings.append(
                    f"{node['id']}: spec tool {spec_name!r} is call-platform "
                    f"context, not an EHR call; no MCP tool bound."
                )
                continue
            mapped = SPEC_TOOL_MAP.get(spec_name)
            if mapped is None:
                warnings.append(
                    f"{node['id']}: spec tool {spec_name!r} has no entry in "
                    f"SPEC_TOOL_MAP; no MCP tool bound."
                )
                continue
            if mapped not in resolved:
                resolved.append(mapped)
        for extra in EXTRA_NODE_TOOLS.get(node["id"], []):
            if extra not in resolved:
                resolved.append(extra)
        node_tools[node["id"]] = resolved

    # --- build edges first: prompts reference the transition names
    out_edges: list[dict] = []
    used_labels: dict[str, set[str]] = {}
    outgoing_count = {
        nid: sum(1 for e in spec_edges if e["source"] == nid) for nid in by_id
    }

    for spec_edge in spec_edges:
        source = spec_edge["source"]
        target = spec_edge["target"]
        if source not in by_id or target not in by_id:
            raise SystemExit(f"Edge {spec_edge['id']!r} references an unknown node.")
        used = used_labels.setdefault(source, set())
        label = _edge_label(
            EDGE_LABEL_OVERRIDES.get(spec_edge["id"], labels[target]),
            used,
        )
        out_edges.append(
            {
                "id": spec_edge["id"],
                "source": source,
                "target": target,
                "data": {
                    "label": label,
                    "condition": _condition(
                        spec_edge,
                        is_sole_exit=outgoing_count[source] == 1,
                        source_label=labels[source],
                    ),
                    "transition_speech": None,
                    "transition_speech_type": None,
                    "transition_speech_recording_id": None,
                },
            }
        )

    labels_by_source: dict[str, list[str]] = {}
    for edge in out_edges:
        labels_by_source.setdefault(edge["source"], []).append(edge["data"]["label"])

    # --- build nodes
    out_nodes: list[dict] = []
    max_x = 0.0
    for spec_node in spec_nodes:
        nid = spec_node["id"]
        data = spec_node["data"]
        kind = data.get("type")
        tools = node_tools[nid]
        exits = labels_by_source.get(nid, [])
        position = {
            "x": float(spec_node["position"]["x"]),
            "y": float(spec_node["position"]["y"]),
        }
        max_x = max(max_x, position["x"])

        prompt = _build_prompt(
            spec_node,
            tools,
            exits,
            is_only_exit=outgoing_count[nid] == 1,
            tool_display_name=tool_display_name if tool_uuid else None,
        )

        if kind == "start":
            node_type = "startCall"
        elif kind == "end":
            node_type = "endCall"
        else:
            node_type = "agentNode"

        node_data: dict[str, Any] = {
            "name": INTERNAL_NODE_NAMES.get(nid, labels[nid])[:60],
            "prompt": prompt,
            "add_global_prompt": True,
            "is_start": node_type == "startCall",
            "is_end": node_type == "endCall",
        }

        if node_type == "endCall":
            # endCall has no tool/document refs and defaults to non-interruptible.
            node_data["extraction_enabled"] = False
        else:
            # Internal branch routers must not be interrupted while their
            # transition is pending. Conversational nodes keep their configured
            # interruption behavior.
            node_data["allow_interrupt"] = kind not in {"conversation", "branch"}
            node_data["extraction_enabled"] = False
            node_data["tool_uuids"] = [tool_uuid] if (tool_uuid and tools) else None
            node_data["document_uuids"] = None
            # Narrow each node to only the tools its spec step needs, so the
            # LLM is not offered the whole EHR surface on every turn.
            node_data["mcp_tool_filters"] = (
                {tool_uuid: tools} if (tool_uuid and tools) else None
            )

        if node_type == "startCall":
            node_data.update(
                {
                    "greeting": (
                        "Thank you for calling the nutrition clinic. This is the "
                        "scheduling assistant. To find the correct patient chart, "
                        "please provide the patient's phone number."
                    ),
                    "greeting_type": "text",
                    "greeting_recording_id": None,
                    "delayed_start": False,
                    "delayed_start_duration": None,
                    "pre_call_fetch_enabled": False,
                    "pre_call_fetch_url": None,
                    "pre_call_fetch_credential_uuid": None,
                }
            )

        out_nodes.append(
            {
                "id": nid,
                "type": node_type,
                "position": position,
                "data": node_data,
            }
        )

    # Global node: persona shared by every prompted node. It must carry no edges.
    out_nodes.append(
        {
            "id": "nutrition_global",
            "type": "globalNode",
            "position": {"x": max_x + 520.0, "y": 40.0},
            "data": {
                "name": "Nutrition Clinic Persona",
                "prompt": GLOBAL_PROMPT,
                "is_start": False,
                "is_end": False,
            },
        }
    )

    return (
        {
            "nodes": out_nodes,
            "edges": out_edges,
            "viewport": {"x": 0.0, "y": 0.0, "zoom": 0.5},
        },
        warnings,
    )


# ----------------------------------------------------------------- validation


def validate_locally(definition: dict) -> list[str]:
    """Run the backend's own DTO + graph validators. Returns error strings."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from api.services.workflow.dto import ReactFlowDTO
        from api.services.workflow.workflow_graph import WorkflowGraph
    except Exception as exc:  # pragma: no cover - environment dependent
        return [f"could not import backend validators ({exc})"]

    from pydantic import ValidationError

    try:
        dto = ReactFlowDTO.model_validate(definition)
    except ValidationError as exc:
        return [
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        ]

    try:
        WorkflowGraph(dto)
    except ValueError as exc:
        errors = exc.args[0]
        if isinstance(errors, list):
            return [
                f"{getattr(e, 'kind', '?')} {getattr(e, 'id', '')}: "
                f"{getattr(e, 'message', e)}"
                for e in errors
            ]
        return [str(exc)]
    return []


# --------------------------------------------------------------- SpinSci API


def _api_call(endpoint: str, path: str, api_key: str, body: dict) -> dict:
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"POST {path} failed ({exc.code}): {exc.read().decode(errors='replace')}"
        ) from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"POST {path} failed: {exc.reason}") from exc


def register_mcp_tool(
    endpoint: str, api_key: str, mcp_url: str, credential_uuid: str | None
) -> str:
    print(f"Registering MCP tool {MCP_TOOL_NAME!r} -> {mcp_url}")
    created = _api_call(
        endpoint,
        "/api/v1/tools/",
        api_key,
        {
            "name": MCP_TOOL_NAME,
            "description": (
                "OpenEMR-backed nutrition scheduling tools: patient lookup, "
                "eligibility, referral checks, availability, coverage, booking."
            ),
            "category": "mcp",
            "definition": {
                "schema_version": 1,
                "type": "mcp",
                "config": {
                    "transport": "streamable_http",
                    "url": mcp_url,
                    "credential_uuid": credential_uuid,
                    "tools_filter": [],
                    "timeout_secs": 30,
                    "sse_read_timeout_secs": 300,
                },
            },
        },
    )
    tool_uuid = created.get("tool_uuid") or created.get("uuid")
    if not tool_uuid:
        raise SystemExit(f"Tool creation returned no tool_uuid: {created}")
    discovered = (
        (created.get("definition") or {}).get("config", {}).get("discovered_tools") or []
    )
    print(f"  tool_uuid = {tool_uuid}")
    print(f"  discovered {len(discovered)} tools on the MCP server")
    return tool_uuid


def create_workflow(endpoint: str, api_key: str, definition: dict, name: str) -> dict:
    print(f"Creating workflow {name!r}")
    created = _api_call(
        endpoint,
        "/api/v1/workflow/create/definition",
        api_key,
        {"name": name, "workflow_definition": definition},
    )
    print(f"  workflow id = {created.get('id')} (status={created.get('status')})")
    return created


# ------------------------------------------------------------------- summary


def summarise(spec: dict, definition: dict) -> None:
    counts: dict[str, int] = {}
    for node in definition["nodes"]:
        counts[node["type"]] = counts.get(node["type"], 0) + 1
    print("\nGenerated workflow:")
    print(f"  spec nodes      : {len(spec['nodes'])}")
    print(f"  workflow nodes  : {len(definition['nodes'])} " f"({dict(sorted(counts.items()))})")
    print(f"  edges           : {len(definition['edges'])}")

    bound = [
        (n["id"], sorted(next(iter(n["data"]["mcp_tool_filters"].values()))))
        for n in definition["nodes"]
        if n["data"].get("mcp_tool_filters")
    ]
    if bound:
        print("  MCP tools per node:")
        for node_id, tools in bound:
            print(f"    {node_id}: {', '.join(tools)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--name", default=WORKFLOW_NAME)
    parser.add_argument(
        "--tool-uuid",
        default=None,
        help="Existing MCP tool uuid to bind. Omit with --create to register one.",
    )
    parser.add_argument("--mcp-url", default=os.environ.get("OPENEMR_MCP_URL", DEFAULT_MCP_URL))
    parser.add_argument(
        "--credential-uuid",
        default=None,
        help="SpinSci credential uuid holding the MCP server's API key.",
    )
    parser.add_argument("--validate", action="store_true", help="Run backend validators.")
    parser.add_argument(
        "--create", action="store_true", help="Register the MCP tool and create the workflow."
    )
    parser.add_argument(
        "--api-endpoint", default=os.environ.get("SPINSCI_API_ENDPOINT", "http://localhost:8000")
    )
    parser.add_argument("--api-key", default=os.environ.get("SPINSCI_API_TOKEN"))
    args = parser.parse_args()

    if not args.spec.exists():
        raise SystemExit(f"Spec not found: {args.spec}")
    spec = json.loads(args.spec.read_text())

    tool_uuid = args.tool_uuid
    if args.create:
        if not args.api_key:
            raise SystemExit("--create needs --api-key (or SPINSCI_API_TOKEN).")
        if not tool_uuid:
            tool_uuid = register_mcp_tool(
                args.api_endpoint, args.api_key, args.mcp_url, args.credential_uuid
            )

    definition, warnings = generate(spec, tool_uuid=tool_uuid)

    if not tool_uuid:
        print(
            "NOTE: no --tool-uuid supplied, so nodes are generated without tool "
            "bindings. Re-run with --create or --tool-uuid to attach the MCP tools."
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {"name": args.name, "workflow_definition": definition},
            indent=2,
        )
        + "\n"
    )
    print(f"Wrote {args.output.relative_to(REPO_ROOT)}")

    summarise(spec, definition)

    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(f"  - {warning}")

    exit_code = 0
    if args.validate:
        print("\nValidating against backend DTO + graph rules ...")
        errors = validate_locally(definition)
        if errors:
            print(f"  INVALID ({len(errors)} error(s)):")
            for error in errors:
                print(f"    - {error}")
            exit_code = 1
        else:
            print("  VALID: schema and graph constraints satisfied.")

    if args.create and exit_code == 0:
        create_workflow(args.api_endpoint, args.api_key, definition, args.name)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
