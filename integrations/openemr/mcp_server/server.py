"""OpenEMR MCP server for the nutrition scheduling voice agent.

Exposes one tool per ``api_request`` / ``transfer`` node in
``docs/json_workflows_samples/nutrition_agent_workflow.json``, each backed by
the OpenEMR standard REST API. Nothing is stubbed: patients, problem lists,
referrals, coverage and appointments are read from and written to the running
OpenEMR instance.

Every tool returns a dict containing a ``spoken_summary`` the agent can read
aloud verbatim, plus structured fields for the workflow's branch conditions.
Tools never raise into the transport — failures come back as
``{"status": "error", ...}`` so a dead EHR degrades the call instead of
killing it.

Run:
    python integrations/openemr/mcp_server/server.py
    # streamable HTTP MCP endpoint -> http://127.0.0.1:8765/mcp

Auth: set OPENEMR_MCP_API_KEY to require an X-API-Key header. Left unset the
server is unauthenticated, which is only acceptable when bound to loopback for
local development.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from fastmcp import FastMCP  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

import nutrition_policy as policy  # noqa: E402
from openemr_client import OpenEMRClient, OpenEMRError  # noqa: E402

DEFAULT_FACILITY_FALLBACK = 3

VISIT_TYPE_CATEGORIES = {
    "Nutrition New Patient": 2700,
    "Nutrition Follow Up": 1800,
    "Nutrition Telehealth": 1800,
}

mcp = FastMCP(
    "openemr-nutrition",
    instructions=(
        "Tools for scheduling nutrition appointments against an OpenEMR EHR. "
        "Always identify the patient first with identify_patient_by_phone, then "
        "pass the returned patient_id to the other tools. Read the "
        "spoken_summary field aloud; do not invent clinical facts, slots, or "
        "coverage details that a tool did not return."
    ),
)

_client: OpenEMRClient | None = None


def _get_client() -> OpenEMRClient:
    global _client
    if _client is None:
        _client = OpenEMRClient.from_env()
    return _client


def _error(message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "spoken_summary": (
            "I'm having trouble reaching the medical record system right now."
        ),
        "detail": message,
    }


async def _find_patient(patient_id: str | int) -> dict[str, Any] | None:
    """Resolve a patient by numeric pid, tolerating a string from the LLM."""
    patients = await _get_client().get("/patient", pid=str(patient_id)) or []
    for patient in patients:
        if str(patient.get("pid")) == str(patient_id):
            return patient
    return patients[0] if patients else None


async def _problem_titles(patient_uuid: str) -> list[str]:
    problems = await _get_client().get(f"/patient/{patient_uuid}/medical_problem") or []
    return [(p.get("title") or "").strip() for p in problems if p.get("title")]


async def _facility_id() -> int:
    facilities = await _get_client().get("/facility") or []
    if facilities and facilities[0].get("id"):
        return int(facilities[0]["id"])
    return DEFAULT_FACILITY_FALLBACK


async def _category_id(visit_type: str) -> int | None:
    """Resolve a visit-type name to a calendar category id via booked events.

    OpenEMR exposes no REST route for calendar categories, so the mapping is
    recovered from appointments that already use the type. Falls back to the
    ids created by seed_data.py.
    """
    appointments = await _get_client().get("/appointment") or []
    for appointment in appointments:
        if (appointment.get("pc_title") or "").strip() == visit_type:
            return int(appointment["pc_catid"])
    return {"Nutrition New Patient": 16, "Nutrition Follow Up": 17, "Nutrition Telehealth": 18}.get(
        visit_type
    )


def _normalize_phone(value: str) -> str:
    digit_words = {
        "zero": "0",
        "oh": "0",
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "nine": "9",
    }
    tokens = re.findall(r"\d+|[a-z]+", str(value).lower())
    return "".join(
        token if token.isdigit() else digit_words.get(token, "")
        for token in tokens
    )


def _speak_date(value: date) -> str:
    return value.strftime("%A, %B %-d")


def _speak_time(value: time) -> str:
    return value.strftime("%-I:%M %p").replace("AM", "A M").replace("PM", "P M")


# ---------------------------------------------------------------- tools


@mcp.tool()
async def identify_patient_by_phone(phone: str) -> dict[str, Any]:
    """Find the patient chart for a caller's phone number.

    Returns every matching patient with name, age and whether they are
    pediatric. Use this before any other tool.

    Args:
        phone: The caller's phone number. Digits only or formatted both work.
    """
    digits = _normalize_phone(phone)
    if len(digits) < 10:
        return {
            "status": "invalid_input",
            "spoken_summary": "That phone number looked incomplete. Could you repeat it?",
        }
    digits = digits[-10:]

    try:
        client = _get_client()
        matches: list[dict] = []
        seen: set[str] = set()
        for field in ("phone_cell", "phone_home", "phone_biz"):
            for patient in await client.get("/patient", **{field: digits}) or []:
                pid = str(patient.get("pid"))
                if pid not in seen:
                    seen.add(pid)
                    matches.append(patient)
    except OpenEMRError as exc:
        return _error(str(exc))

    if not matches:
        return {
            "status": "no_match",
            "patient_count": 0,
            "spoken_summary": (
                "I wasn't able to find a record with that phone number. "
                "Could you try a different number?"
            ),
        }

    people = []
    for patient in matches:
        age = policy.calculate_age(patient.get("DOB"))
        people.append(
            {
                "patient_id": int(patient["pid"]),
                "patient_uuid": patient.get("uuid"),
                "first_name": patient.get("fname"),
                "last_name": patient.get("lname"),
                "date_of_birth": patient.get("DOB"),
                "age": age,
                "is_pediatric": policy.is_pediatric(age),
                "referring_provider": patient.get("referrer") or None,
            }
        )

    if len(people) == 1:
        person = people[0]
        summary = (
            f"I found {person['first_name']} {person['last_name']}, "
            f"age {person['age']}."
        )
    else:
        names = ", ".join(p["first_name"] for p in people)
        summary = f"I found {names}. Which patient should I use?"

    return {
        "status": "found",
        "patient_count": len(people),
        "patients": people,
        "spoken_summary": summary,
    }


@mcp.tool()
async def check_nutrition_eligibility(patient_id: str) -> dict[str, Any]:
    """Screen the patient's problem list against the nutrition clinic criteria.

    Approved: diabetes, pre-diabetes, gestational diabetes, weight management,
    gastroenterology, bariatric, hyperlipidemia, celiac, gluten intolerance,
    obesity, general nutrition. Referred out: eating disorders, adult tube
    feedings, nephrology.

    Args:
        patient_id: Numeric patient id from identify_patient_by_phone.
    """
    try:
        patient = await _find_patient(patient_id)
        if not patient:
            return {
                "status": "not_found",
                "spoken_summary": "I couldn't open that patient chart.",
            }
        titles = await _problem_titles(patient["uuid"])
    except OpenEMRError as exc:
        return _error(str(exc))

    decision = policy.classify_conditions(titles)

    if decision.status == "refer_out":
        summary = (
            f"I'm not able to schedule a nutrition visit for {decision.category}. "
            f"That needs a referral to {decision.refer_to}."
        )
    elif decision.status == "approved":
        summary = f"{decision.category} is covered by our nutrition clinic."
    else:
        summary = (
            "I don't see a nutrition diagnosis on the chart. "
            "What is the reason for the nutrition visit?"
        )

    return {
        "status": decision.status,
        "condition_category": decision.category,
        "matched_problem": decision.matched_text,
        "is_gestational_diabetes": decision.is_gdm,
        "refer_to": decision.refer_to,
        "problem_list": titles,
        "spoken_summary": summary,
    }


@mcp.tool()
async def check_gdm_referral(patient_id: str) -> dict[str, Any]:
    """Verify a gestational diabetes referral came from a Summit Health provider.

    Outside referrals must go back to the patient's OBGYN for an external
    referral.

    Args:
        patient_id: Numeric patient id from identify_patient_by_phone.
    """
    try:
        patient = await _find_patient(patient_id)
        if not patient:
            return {
                "status": "not_found",
                "spoken_summary": "I couldn't open that patient chart.",
            }
    except OpenEMRError as exc:
        return _error(str(exc))

    referrer = (patient.get("referrer") or "").strip()
    internal = policy.referral_is_internal(referrer)

    if internal:
        summary = "That referral is from a Summit Health provider, so I can schedule this."
    elif referrer:
        summary = (
            f"That referral is from {referrer}, which is an outside provider. "
            "Please contact your OBGYN for an external referral."
        )
    else:
        summary = (
            "I don't see a referring provider on the chart. "
            "Who referred you for nutrition counseling?"
        )

    return {
        "status": "internal" if internal else ("external" if referrer else "unknown"),
        "referring_provider": referrer or None,
        "required_organization": policy.GDM_REQUIRED_REFERRAL_ORG,
        "spoken_summary": summary,
    }


@mcp.tool()
async def route_pediatric_patient(patient_id: str) -> dict[str, Any]:
    """Assign a pediatric patient to the pediatric dietitian, Alexa Bacino.

    Writes the provider assignment to the patient's chart in OpenEMR.

    Args:
        patient_id: Numeric patient id from identify_patient_by_phone.
    """
    try:
        client = _get_client()
        patient = await _find_patient(patient_id)
        if not patient:
            return {
                "status": "not_found",
                "spoken_summary": "I couldn't open that patient chart.",
            }

        provider = None
        for candidate in await client.get("/practitioner") or []:
            full = f"{candidate.get('fname')} {candidate.get('lname')}".strip()
            if full == policy.PEDIATRIC_PROVIDER:
                provider = candidate
                break
        if provider is None:
            return {
                "status": "provider_missing",
                "spoken_summary": (
                    "I couldn't find our pediatric dietitian in the system. "
                    "Let me have someone call you back."
                ),
            }

        await client.put(
            f"/patient/{patient['uuid']}",
            {"providerID": int(provider["id"])},
        )
    except OpenEMRError as exc:
        return _error(str(exc))

    return {
        "status": "routed",
        "provider_name": policy.PEDIATRIC_PROVIDER,
        "provider_id": int(provider["id"]),
        "patient_id": int(patient["pid"]),
        "spoken_summary": (
            f"Because {patient.get('fname')} is under "
            f"{policy.PEDIATRIC_AGE_LIMIT}, I've routed this to "
            f"{policy.PEDIATRIC_PROVIDER}, our pediatric dietitian."
        ),
    }


@mcp.tool()
async def find_available_slots(
    patient_id: str = "",
    visit_type: str = "Nutrition Follow Up",
    provider_name: str = "",
    days_ahead: int = 14,
    max_results: int = 5,
) -> dict[str, Any]:
    """Find open nutrition appointment slots for the selected patient.

    Patient context is used to keep pediatric patients with Alexa Bacino and
    adult patients away from the pediatric provider. If the caller did not
    choose a provider, an adult search excludes pediatric-only providers.

    Availability is computed from clinic hours (weekdays 9:00 to 16:30, no
    lunch hour) minus appointments already booked in OpenEMR for that provider.

    Args:
        patient_id: Numeric patient id returned by patient lookup. Include it
            whenever available so age and chart history can constrain the search.
        visit_type: One of "Nutrition New Patient", "Nutrition Follow Up",
            "Nutrition Telehealth". Use Follow Up unless the caller explicitly
            requests a new-patient visit.
        provider_name: Optional provider full name, e.g. "Dana Whitmore".
        days_ahead: How many days forward to search. Use 3 for gestational
            diabetes, which must be scheduled within 72 hours.
        max_results: Maximum number of slots to return.
    """
    if visit_type not in VISIT_TYPE_CATEGORIES:
        return {
            "status": "invalid_input",
            "spoken_summary": (
                "I can look for a new patient visit, a follow up, or a telehealth visit."
            ),
            "valid_visit_types": sorted(VISIT_TYPE_CATEGORIES),
        }

    try:
        client = _get_client()
        providers = await client.get("/practitioner") or []
        patient = await _find_patient(patient_id) if patient_id else None
        if patient_id and not patient:
            return {
                "status": "not_found",
                "spoken_summary": "I couldn't open that patient chart to find matching slots.",
            }

        if patient:
            age = policy.calculate_age(patient.get("DOB"))
            if policy.is_pediatric(age):
                providers = [
                    p
                    for p in providers
                    if f"{p.get('fname')} {p.get('lname')}".strip()
                    == policy.PEDIATRIC_PROVIDER
                ]
            else:
                providers = [
                    p
                    for p in providers
                    if f"{p.get('fname')} {p.get('lname')}".strip()
                    != policy.PEDIATRIC_PROVIDER
                ]
        elif not provider_name:
            # Never offer the pediatric-only provider when patient context was
            # omitted. A caller can still explicitly request Alexa.
            providers = [
                p
                for p in providers
                if f"{p.get('fname')} {p.get('lname')}".strip()
                != policy.PEDIATRIC_PROVIDER
            ]

        if provider_name:
            providers = [
                p
                for p in providers
                if f"{p.get('fname')} {p.get('lname')}".strip().lower()
                == provider_name.strip().lower()
            ]
            if not providers:
                return {
                    "status": "provider_missing",
                    "spoken_summary": f"I couldn't find a provider named {provider_name} for this patient.",
                }
        booked_all = await client.get("/appointment") or []
    except OpenEMRError as exc:
        return _error(str(exc))

    duration = timedelta(seconds=VISIT_TYPE_CATEGORIES[visit_type])

    # provider users.id -> set of (date, start, end) already taken
    taken: dict[int, list[tuple[date, datetime, datetime]]] = {}
    for appointment in booked_all:
        try:
            aid = int(appointment.get("pc_aid") or 0)
            day = datetime.strptime(appointment["pc_eventDate"][:10], "%Y-%m-%d").date()
            start = datetime.strptime(
                f"{appointment['pc_eventDate'][:10]} {appointment['pc_startTime'][:8]}",
                "%Y-%m-%d %H:%M:%S",
            )
            end_raw = appointment.get("pc_endTime") or appointment["pc_startTime"]
            end = datetime.strptime(
                f"{appointment['pc_eventDate'][:10]} {end_raw[:8]}",
                "%Y-%m-%d %H:%M:%S",
            )
        except (ValueError, KeyError, TypeError):
            continue
        taken.setdefault(aid, []).append((day, start, end))

    now = datetime.now()
    deadline = policy.gdm_deadline(now)
    results: list[dict[str, Any]] = []

    for offset in range(days_ahead + 1):
        day = now.date() + timedelta(days=offset)
        starts = policy.candidate_slot_starts(day)
        if not starts:
            continue
        for provider in providers:
            provider_id = int(provider["id"])
            busy = taken.get(provider_id, [])
            for start_time in starts:
                begin = datetime.combine(day, start_time)
                finish = begin + duration
                if begin <= now:
                    continue
                if finish.time() > policy.CLINIC_CLOSE:
                    continue
                if any(begin < b_end and b_start < finish for _, b_start, b_end in busy):
                    continue

                results.append(
                    {
                        "slot_id": (
                            f"{day.isoformat()}T{start_time.strftime('%H:%M')}"
                            f"|{provider_id}|{visit_type}"
                        ),
                        "date": day.isoformat(),
                        "start_time": start_time.strftime("%H:%M"),
                        "visit_type": visit_type,
                        "is_telehealth": visit_type == policy.TELEHEALTH_VISIT_TYPE,
                        "provider_id": provider_id,
                        "provider_name": f"{provider.get('fname')} {provider.get('lname')}".strip(),
                        "within_gdm_window": begin <= deadline,
                        "spoken": (
                            f"{_speak_date(day)} at {_speak_time(start_time)} with "
                            f"{provider.get('fname')} {provider.get('lname')}"
                        ),
                    }
                )
                if len(results) >= max_results:
                    break
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break

    if not results:
        return {
            "status": "no_slots",
            "slots": [],
            "any_within_gdm_window": False,
            "spoken_summary": (
                f"I don't see any open {visit_type} slots in the next {days_ahead} days."
            ),
        }

    spoken = "; ".join(slot["spoken"] for slot in results[:3])
    return {
        "status": "found",
        "slot_count": len(results),
        "slots": results,
        "any_within_gdm_window": any(slot["within_gdm_window"] for slot in results),
        "gdm_deadline": deadline.isoformat(timespec="minutes"),
        "spoken_summary": f"I have {spoken}.",
    }


@mcp.tool()
async def validate_slot_policy(
    slot_id: str = "", wants_virtual: bool = False
) -> dict[str, Any]:
    """Validate the exact slot selected by the caller.

    The slot_id must come directly from find_available_slots. This prevents
    the model from changing a selected Nutrition Follow Up slot into a
    Nutrition New Patient slot while moving between workflow nodes.

    Args:
        slot_id: Exact slot_id returned by find_available_slots.
        wants_virtual: True when the patient asked for a virtual visit.
    """
    if not slot_id:
        return {
            "status": "invalid_input",
            "spoken_summary": "Please choose one of the appointment times I listed.",
        }

    try:
        _, _, visit_type = slot_id.split("|", 2)
    except ValueError:
        return {
            "status": "invalid_input",
            "spoken_summary": "I couldn't identify that appointment time. Please choose one of the listed times.",
        }

    allowed, reason = policy.validate_visit_type(visit_type, wants_virtual=wants_virtual)
    return {
        "status": "allowed" if allowed else "blocked",
        "slot_id": slot_id,
        "visit_type": visit_type,
        "wants_virtual": wants_virtual,
        "telehealth_visit_type": policy.TELEHEALTH_VISIT_TYPE,
        "spoken_summary": reason,
    }


@mcp.tool()
async def check_nutrition_coverage(patient_id: str) -> dict[str, Any]:
    """Check whether the patient has active insurance coverage on file.

    When there is no active coverage the patient must be told about the
    self-pay charge for a non-covered diagnosis.

    Args:
        patient_id: Numeric patient id from identify_patient_by_phone.
    """
    try:
        patient = await _find_patient(patient_id)
        if not patient:
            return {
                "status": "not_found",
                "spoken_summary": "I couldn't open that patient chart.",
            }
        coverage = await _get_client().get(f"/patient/{patient['uuid']}/insurance") or []
    except OpenEMRError as exc:
        return _error(str(exc))

    today = date.today()
    active = []
    for policy_row in coverage:
        start = (policy_row.get("date") or "")[:10]
        end = (policy_row.get("date_end") or "")[:10]
        try:
            if start and datetime.strptime(start, "%Y-%m-%d").date() > today:
                continue
            if end and datetime.strptime(end, "%Y-%m-%d").date() < today:
                continue
        except ValueError:
            pass
        active.append(policy_row)

    if active:
        plan = active[0].get("plan_name") or active[0].get("company_name") or "your plan"
        return {
            "status": "covered",
            "is_covered": True,
            "plan_name": plan,
            "self_pay_fee_usd": policy.SELF_PAY_FEE_USD,
            "spoken_summary": (
                f"I see active coverage under {plan}. If your diagnosis turns out not "
                f"to be covered, there is a {policy.SELF_PAY_FEE_USD} dollar charge."
            ),
        }

    return {
        "status": "not_covered",
        "is_covered": False,
        "plan_name": None,
        "self_pay_fee_usd": policy.SELF_PAY_FEE_USD,
        "spoken_summary": (
            "I don't see active insurance coverage on file, so there is a "
            f"{policy.SELF_PAY_FEE_USD} dollar charge for this visit."
        ),
    }


@mcp.tool()
async def book_nutrition_appointment(
    patient_id: str, slot_id: str, reason: str = "Nutrition counseling"
) -> dict[str, Any]:
    """Book a nutrition appointment in OpenEMR.

    The slot's visit type is preserved exactly as offered; it is never
    rewritten to another type.

    Args:
        patient_id: Numeric patient id from identify_patient_by_phone.
        slot_id: A slot_id returned by find_available_slots.
        reason: Short reason for the visit, recorded on the appointment.
    """
    try:
        stamp, provider_raw, visit_type = slot_id.split("|", 2)
        day_str, start_str = stamp.split("T", 1)
        day = datetime.strptime(day_str, "%Y-%m-%d").date()
        datetime.strptime(start_str, "%H:%M")
        provider_id = int(provider_raw)
    except (ValueError, AttributeError):
        return {
            "status": "invalid_input",
            "spoken_summary": (
                "I lost track of that time slot. Let me look up the available times again."
            ),
        }

    if visit_type not in VISIT_TYPE_CATEGORIES:
        return {
            "status": "invalid_input",
            "spoken_summary": "That appointment type isn't one I can book.",
        }

    try:
        client = _get_client()
        patient = await _find_patient(patient_id)
        if not patient:
            return {
                "status": "not_found",
                "spoken_summary": "I couldn't open that patient chart.",
            }

        category_id = await _category_id(visit_type)
        if category_id is None:
            return {
                "status": "error",
                "spoken_summary": "I couldn't determine the appointment type to book.",
            }
        facility_id = await _facility_id()

        pid = int(patient["pid"])
        await client.post(
            f"/patient/{pid}/appointment",
            {
                "pc_catid": category_id,
                "pc_title": visit_type,
                "pc_duration": VISIT_TYPE_CATEGORIES[visit_type],
                "pc_hometext": reason[:250],
                "pc_apptstatus": "-",
                "pc_eventDate": day.isoformat(),
                "pc_startTime": start_str,
                "pc_facility": facility_id,
                "pc_billing_location": facility_id,
                "pc_aid": provider_id,
            },
        )

        booked = await client.get(f"/patient/{pid}/appointment") or []
        match = next(
            (
                a
                for a in booked
                if a.get("pc_eventDate", "")[:10] == day.isoformat()
                and (a.get("pc_startTime") or "").startswith(start_str)
            ),
            None,
        )
    except OpenEMRError as exc:
        return _error(str(exc))

    spoken_when = (
        f"{_speak_date(day)} at {_speak_time(datetime.strptime(start_str, '%H:%M').time())}"
    )
    return {
        "status": "booked",
        "appointment_id": (match or {}).get("pc_eid"),
        "patient_id": int(patient["pid"]),
        "date": day.isoformat(),
        "start_time": start_str,
        "visit_type": visit_type,
        "provider_name": (match or {}).get("pce_aid_lname") and (
            f"{match.get('pce_aid_fname')} {match.get('pce_aid_lname')}"
        ),
        "spoken_summary": f"You're booked for a {visit_type} on {spoken_when}.",
    }


@mcp.tool()
async def get_patient_appointments(patient_id: str) -> dict[str, Any]:
    """List the patient's appointments from OpenEMR, for read-back confirmation.

    Args:
        patient_id: Numeric patient id from identify_patient_by_phone.
    """
    try:
        patient = await _find_patient(patient_id)
        if not patient:
            return {
                "status": "not_found",
                "spoken_summary": "I couldn't open that patient chart.",
            }
        pid = int(patient["pid"])
        appointments = await _get_client().get(f"/patient/{pid}/appointment") or []
    except OpenEMRError as exc:
        return _error(str(exc))

    items = []
    for appointment in appointments:
        raw_date = (appointment.get("pc_eventDate") or "")[:10]
        raw_time = (appointment.get("pc_startTime") or "")[:5]
        try:
            day = datetime.strptime(raw_date, "%Y-%m-%d").date()
            moment = datetime.strptime(raw_time, "%H:%M").time()
            spoken = f"{_speak_date(day)} at {_speak_time(moment)}"
        except ValueError:
            spoken = f"{raw_date} {raw_time}"
        items.append(
            {
                "appointment_id": appointment.get("pc_eid"),
                "date": raw_date,
                "start_time": raw_time,
                "visit_type": appointment.get("pc_title"),
                "provider_name": (
                    f"{appointment.get('pce_aid_fname') or ''} "
                    f"{appointment.get('pce_aid_lname') or ''}"
                ).strip()
                or None,
                "facility": appointment.get("facility_name"),
                "spoken": spoken,
            }
        )

    items.sort(key=lambda entry: (entry["date"], entry["start_time"]))

    if not items:
        return {
            "status": "none",
            "appointments": [],
            "spoken_summary": "I don't see any appointments on the chart.",
        }

    latest = items[-1]
    return {
        "status": "found",
        "appointment_count": len(items),
        "appointments": items,
        "spoken_summary": (
            f"I have a {latest['visit_type']} on {latest['spoken']}"
            + (f" with {latest['provider_name']}" if latest["provider_name"] else "")
            + "."
        ),
    }


@mcp.tool()
async def get_patient_instructions(
    patient_id: str, tests_blood_sugar_at_home: bool = False
) -> dict[str, Any]:
    """Get the pre-visit instructions to read to the patient.

    New patients bring recent laboratory results; patients who test at home
    bring their blood sugar logbook. "New patient" is derived from whether the
    chart already has appointment history in OpenEMR.

    Args:
        patient_id: Numeric patient id from identify_patient_by_phone.
        tests_blood_sugar_at_home: True when the patient tests at home.
    """
    try:
        patient = await _find_patient(patient_id)
        if not patient:
            return {
                "status": "not_found",
                "spoken_summary": "I couldn't open that patient chart.",
            }
        pid = int(patient["pid"])
        history = await _get_client().get(f"/patient/{pid}/appointment") or []
    except OpenEMRError as exc:
        return _error(str(exc))

    is_new = len(history) <= 1
    instructions = policy.instructions_for(
        is_new_patient=is_new, tests_at_home=tests_blood_sugar_at_home
    )
    return {
        "status": "ok",
        "is_new_patient": is_new,
        "instructions": instructions,
        "spoken_summary": " ".join(instructions)
        or "There's nothing special you need to bring to this visit.",
    }


@mcp.tool()
async def escalate_gdm_scheduling(patient_id: str, reason: str = "") -> dict[str, Any]:
    """Escalate a gestational diabetes booking that cannot meet the 72-hour window.

    Records a message on the patient's chart and returns the escalation phone
    number to give the caller.

    Args:
        patient_id: Numeric patient id from identify_patient_by_phone.
        reason: Why the escalation is needed.
    """
    note = (
        reason
        or f"No gestational diabetes slot available within "
        f"{policy.GDM_SCHEDULING_WINDOW_HOURS} hours."
    )
    recorded = False
    try:
        patient = await _find_patient(patient_id)
        if not patient:
            return {
                "status": "not_found",
                "spoken_summary": "I couldn't open that patient chart.",
            }
        pid = int(patient["pid"])
        try:
            await _get_client().post(
                f"/patient/{pid}/message",
                {
                    "body": f"GDM scheduling escalation: {note}",
                    "groupname": "Default",
                    "from": "SpinSci Voice Agent",
                    "to": "admin",
                    "title": "Other",
                    "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "message_status": "New",
                },
            )
            recorded = True
        except OpenEMRError:
            # The escalation instruction still has to reach the caller even if
            # the chart note fails to save.
            recorded = False
    except OpenEMRError as exc:
        return _error(str(exc))

    return {
        "status": "escalated",
        "note_recorded": recorded,
        "escalation_phone": policy.GDM_ESCALATION_PHONE,
        "escalation_option": policy.GDM_ESCALATION_OPTION,
        "spoken_summary": (
            "I wasn't able to find a gestational diabetes appointment within "
            f"{policy.GDM_SCHEDULING_WINDOW_HOURS} hours. Please call "
            f"{policy.GDM_ESCALATION_PHONE} and select option "
            f"{policy.GDM_ESCALATION_OPTION} so the team can fit you in."
        ),
    }


# ---------------------------------------------------------------- transport


def build_app(api_key: str | None = None):
    """ASGI app for the streamable-HTTP MCP endpoint at /mcp.

    When ``api_key`` is provided every request must carry a matching
    ``X-API-Key`` header. SpinSci supplies this from a stored credential.
    """
    app = mcp.http_app()
    if not api_key:
        return app

    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            headers = {
                key.decode("latin-1").lower(): value.decode("latin-1")
                for key, value in scope.get("headers", [])
            }
            supplied = headers.get("x-api-key")
            if supplied is None:
                auth = headers.get("authorization", "")
                if auth.lower().startswith("bearer "):
                    supplied = auth[7:]
            if supplied != api_key:
                response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await app(scope, receive, send)

    # Preserve the lifespan the FastMCP app installs; a bare function wrapper
    # would drop it and the session manager would never start.
    guarded.lifespan = getattr(app, "lifespan", None)
    return guarded


def main() -> int:
    import uvicorn

    host = os.environ.get("OPENEMR_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("OPENEMR_MCP_PORT", "8765"))
    api_key = os.environ.get("OPENEMR_MCP_API_KEY") or None

    if not api_key:
        print(
            "WARNING: OPENEMR_MCP_API_KEY is not set, so this MCP server is "
            "unauthenticated. Anyone who can reach it can read and write "
            f"patient data. Binding to {host}.",
            file=sys.stderr,
        )

    app = build_app(api_key)
    print(f"OpenEMR MCP server -> http://{host}:{port}/mcp")
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
