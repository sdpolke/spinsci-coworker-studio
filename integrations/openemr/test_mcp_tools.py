"""Exercise every OpenEMR MCP tool over the real MCP protocol.

Connects to the running server as an MCP client (streamable HTTP) and drives
the paths the nutrition workflow takes: adult approved, pediatric routing,
refer-out, GDM internal vs outside referral, uncovered patient, and a booking
round-trip that is read back from OpenEMR.

Start the server first:
    OPENEMR_MCP_API_KEY=spinsci-openemr-dev-key \
        python integrations/openemr/mcp_server/server.py

Then:
    python integrations/openemr/test_mcp_tools.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import timedelta

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.environ.get("OPENEMR_MCP_URL", "http://127.0.0.1:8765/mcp")
API_KEY = os.environ.get("OPENEMR_MCP_API_KEY", "spinsci-openemr-dev-key")

PHONES = {
    "adult_diabetes": "9085551001",
    "gdm_internal": "9085551002",
    "gdm_outside": "9085551003",
    "pediatric": "9085551004",
    "refer_out": "9085551005",
    "uncovered": "9085551006",
}

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def payload(result) -> dict:
    """Unwrap an MCP tool result into the dict the tool returned."""
    if getattr(result, "structuredContent", None):
        inner = result.structuredContent
        # FastMCP wraps non-model returns under "result".
        if isinstance(inner, dict) and set(inner) == {"result"}:
            return inner["result"]
        return inner
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"_raw": text}
    return {}


async def main() -> int:
    async with streamablehttp_client(
        MCP_URL,
        headers={"X-API-Key": API_KEY},
        timeout=timedelta(seconds=30),
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            listed = await session.list_tools()
            names = sorted(t.name for t in listed.tools)
            print(f"\n=== Discovered {len(names)} tools ===")
            for name in names:
                print("   ", name)

            expected = {
                "identify_patient_by_phone",
                "check_nutrition_eligibility",
                "check_gdm_referral",
                "route_pediatric_patient",
                "find_available_slots",
                "validate_slot_policy",
                "check_nutrition_coverage",
                "book_nutrition_appointment",
                "get_patient_appointments",
                "get_patient_instructions",
                "escalate_gdm_scheduling",
            }
            print("\n=== Tool inventory ===")
            check(
                "all workflow tools exposed",
                expected.issubset(set(names)),
                f"missing={sorted(expected - set(names))}",
            )

            async def call(tool: str, **args) -> dict:
                return payload(await session.call_tool(tool, args))

            # ---------------------------------------------- identification
            print("\n=== identify_patient_by_phone ===")
            adult = await call(
                "identify_patient_by_phone", phone=PHONES["adult_diabetes"]
            )
            check("adult found", adult.get("status") == "found", str(adult.get("status")))
            adult_person = (adult.get("patients") or [{}])[0]
            adult_id = adult_person.get("patient_id")
            check(
                "adult name + age resolved",
                adult_person.get("last_name") == "Whitfield" and adult_person.get("age") == 42,
                f"{adult_person.get('first_name')} {adult_person.get('last_name')} age={adult_person.get('age')}",
            )
            check("adult not flagged pediatric", adult_person.get("is_pediatric") is False)

            formatted = await call(
                "identify_patient_by_phone", phone="(908) 555-1001"
            )
            check(
                "formatted phone normalises to same patient",
                (formatted.get("patients") or [{}])[0].get("patient_id") == adult_id,
            )

            missing = await call("identify_patient_by_phone", phone="9999999999")
            check("unknown number -> no_match", missing.get("status") == "no_match")

            peds = await call("identify_patient_by_phone", phone=PHONES["pediatric"])
            peds_person = (peds.get("patients") or [{}])[0]
            peds_id = peds_person.get("patient_id")
            check(
                "pediatric patient flagged",
                peds_person.get("is_pediatric") is True,
                f"age={peds_person.get('age')}",
            )

            # ---------------------------------------------- eligibility
            print("\n=== check_nutrition_eligibility ===")
            elig = await call("check_nutrition_eligibility", patient_id=str(adult_id))
            check(
                "diabetes approved",
                elig.get("status") == "approved" and elig.get("condition_category") == "Diabetes",
                f"{elig.get('status')}/{elig.get('condition_category')}",
            )
            check("reads real problem list", bool(elig.get("problem_list")), str(elig.get("problem_list")))

            refer = await call("identify_patient_by_phone", phone=PHONES["refer_out"])
            refer_id = (refer.get("patients") or [{}])[0].get("patient_id")
            refer_elig = await call("check_nutrition_eligibility", patient_id=str(refer_id))
            check(
                "eating disorder refers out",
                refer_elig.get("status") == "refer_out",
                f"{refer_elig.get('condition_category')} -> {refer_elig.get('refer_to')}",
            )

            gdm_in = await call("identify_patient_by_phone", phone=PHONES["gdm_internal"])
            gdm_in_id = (gdm_in.get("patients") or [{}])[0].get("patient_id")
            gdm_elig = await call("check_nutrition_eligibility", patient_id=str(gdm_in_id))
            check(
                "GDM detected as gestational diabetes",
                gdm_elig.get("is_gestational_diabetes") is True,
                str(gdm_elig.get("condition_category")),
            )

            # ---------------------------------------------- GDM referral
            print("\n=== check_gdm_referral ===")
            internal = await call("check_gdm_referral", patient_id=str(gdm_in_id))
            check(
                "Summit Health referral accepted",
                internal.get("status") == "internal",
                str(internal.get("referring_provider")),
            )

            gdm_out = await call("identify_patient_by_phone", phone=PHONES["gdm_outside"])
            gdm_out_id = (gdm_out.get("patients") or [{}])[0].get("patient_id")
            external = await call("check_gdm_referral", patient_id=str(gdm_out_id))
            check(
                "outside referral rejected",
                external.get("status") == "external",
                str(external.get("referring_provider")),
            )

            # ---------------------------------------------- pediatric routing
            print("\n=== route_pediatric_patient ===")
            routed = await call("route_pediatric_patient", patient_id=str(peds_id))
            check(
                "pediatric routed to Alexa Bacino",
                routed.get("status") == "routed" and routed.get("provider_name") == "Alexa Bacino",
                f"{routed.get('status')}/{routed.get('provider_name')}",
            )

            # ---------------------------------------------- coverage
            print("\n=== check_nutrition_coverage ===")
            covered = await call("check_nutrition_coverage", patient_id=str(adult_id))
            check("insured patient covered", covered.get("is_covered") is True, str(covered.get("plan_name")))

            unc = await call("identify_patient_by_phone", phone=PHONES["uncovered"])
            unc_id = (unc.get("patients") or [{}])[0].get("patient_id")
            uncovered = await call("check_nutrition_coverage", patient_id=str(unc_id))
            check(
                "uninsured patient quoted the fee",
                uncovered.get("is_covered") is False and uncovered.get("self_pay_fee_usd") == 200,
                str(uncovered.get("spoken_summary")),
            )

            # ---------------------------------------------- slots
            print("\n=== find_available_slots ===")
            slots = await call(
                "find_available_slots",
                patient_id=str(adult_id),
                visit_type="Nutrition Follow Up",
                provider_name="Dana Whitmore",
                days_ahead=14,
                max_results=5,
            )
            check("slots found", slots.get("status") == "found", f"count={slots.get('slot_count')}")
            slot_list = slots.get("slots") or []
            check("slots carry a spoken form", bool(slot_list and slot_list[0].get("spoken")),
                  slot_list[0].get("spoken") if slot_list else "")

            # The seeded appointments occupy 09:00 and 10:30 with Dana Whitmore.
            seeded_day = None
            appts = await call("get_patient_appointments", patient_id=str(adult_id))
            for entry in appts.get("appointments") or []:
                if entry.get("start_time") == "09:00":
                    seeded_day = entry.get("date")
            clash = [
                s
                for s in slot_list
                if seeded_day and s["date"] == seeded_day and s["start_time"] in {"09:00", "10:30"}
            ]
            check(
                "booked times excluded from availability",
                not clash,
                f"seeded_day={seeded_day} clashes={[(c['date'], c['start_time']) for c in clash]}",
            )

            bad_type = await call("find_available_slots", visit_type="Massage")
            check("unknown visit type rejected", bad_type.get("status") == "invalid_input")

            gdm_slots = await call(
                "find_available_slots", patient_id=str(gdm_in_id),
                visit_type="Nutrition Follow Up", days_ahead=3
            )
            check(
                "GDM window flag present",
                "any_within_gdm_window" in gdm_slots,
                f"any_within_72h={gdm_slots.get('any_within_gdm_window')}",
            )

            # ---------------------------------------------- slot policy
            print("\n=== validate_slot_policy ===")
            selected_slot_id = (slot_list[0] if slot_list else {}).get("slot_id", "")
            blocked = await call(
                "validate_slot_policy", slot_id=selected_slot_id, wants_virtual=True
            )
            check("virtual in non-telehealth slot blocked", blocked.get("status") == "blocked",
                  str(blocked.get("spoken_summary")))
            ok_virtual = await call(
                "validate_slot_policy",
                slot_id="2026-09-23T09:00|19|Nutrition Telehealth",
                wants_virtual=True,
            )
            check("virtual in telehealth slot allowed", ok_virtual.get("status") == "allowed")
            ok_inperson = await call(
                "validate_slot_policy",
                slot_id="2026-09-23T09:00|19|Nutrition New Patient",
                wants_virtual=False,
            )
            check("in-person in in-person slot allowed", ok_inperson.get("status") == "allowed")

            # ---------------------------------------------- booking round-trip
            print("\n=== book_nutrition_appointment (round-trip) ===")
            before = await call("get_patient_appointments", patient_id=str(gdm_in_id))
            before_count = before.get("appointment_count", 0) or 0

            target = None
            for slot in slot_list:
                target = slot
                break
            if target is None:
                check("had a slot to book", False)
            else:
                booked = await call(
                    "book_nutrition_appointment",
                    patient_id=str(gdm_in_id),
                    slot_id=target["slot_id"],
                    reason="Gestational diabetes nutrition counseling",
                )
                check(
                    "appointment booked",
                    booked.get("status") == "booked",
                    str(booked.get("spoken_summary")),
                )
                check(
                    "visit type preserved (not rewritten)",
                    booked.get("visit_type") == target["visit_type"],
                    f"{target['visit_type']} -> {booked.get('visit_type')}",
                )

                after = await call("get_patient_appointments", patient_id=str(gdm_in_id))
                after_count = after.get("appointment_count", 0) or 0
                check(
                    "appointment readable back from OpenEMR",
                    after_count == before_count + 1,
                    f"{before_count} -> {after_count}",
                )
                check(
                    "booked slot no longer offered",
                    not any(
                        s["date"] == target["date"] and s["start_time"] == target["start_time"]
                        for s in (
                            await call(
                                "find_available_slots",
                                patient_id=str(adult_id),
                                visit_type="Nutrition Follow Up",
                                provider_name="Dana Whitmore",
                                days_ahead=14,
                                max_results=20,
                            )
                        ).get("slots")
                        or []
                    ),
                    f"{target['date']} {target['start_time']}",
                )

            bad_slot = await call(
                "book_nutrition_appointment", patient_id=str(adult_id), slot_id="garbage"
            )
            check("malformed slot_id rejected", bad_slot.get("status") == "invalid_input")

            # ---------------------------------------------- instructions
            print("\n=== get_patient_instructions ===")
            instr = await call(
                "get_patient_instructions",
                patient_id=str(gdm_in_id),
                tests_blood_sugar_at_home=True,
            )
            check(
                "logbook instruction included",
                any("logbook" in line.lower() for line in instr.get("instructions") or []),
                str(instr.get("instructions")),
            )

            # ---------------------------------------------- escalation
            print("\n=== escalate_gdm_scheduling ===")
            esc = await call(
                "escalate_gdm_scheduling",
                patient_id=str(gdm_in_id),
                reason="No slot within 72 hours",
            )
            check(
                "escalation returns the published number and option",
                esc.get("escalation_phone") == "908-516-9850"
                and esc.get("escalation_option") == "2",
                str(esc.get("spoken_summary")),
            )

    print("\n" + "=" * 60)
    if failures:
        print(f"FAILED ({len(failures)}):")
        for name in failures:
            print("   -", name)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
