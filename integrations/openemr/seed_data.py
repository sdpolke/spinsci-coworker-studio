"""Seed the local OpenEMR instance with nutrition-clinic demo data.

The nutrition workflow branches on real clinical facts — patient age, the
nutrition condition on the problem list, who made the GDM referral, whether
nutrition counselling is covered — so those facts have to exist in OpenEMR for
the MCP tools to return anything meaningful. This script creates them.

Idempotent: every record is matched on a natural key first (phone number for
patients, name for providers and insurers) and skipped if already present, so
re-running does not duplicate data.

Usage:
    python integrations/openemr/seed_data.py
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "mcp_server"))

from openemr_client import OpenEMRClient, OpenEMRError  # noqa: E402

DB_CONTAINER = "openemr-db"
DB_NAME = "openemr"
DB_ROOT_PASSWORD = "openemr_root_pw"

# Visit types the scheduling-policy node cares about. OpenEMR has no REST
# route for calendar categories, so these go in over SQL — the same table the
# Administration -> Calendar screen writes.
#   (name, duration_seconds, telehealth_flag)
NUTRITION_CATEGORIES = [
    ("Nutrition New Patient", 2700),
    ("Nutrition Follow Up", 1800),
    ("Nutrition Telehealth", 1800),
]

# `username` matters. GET /api/practitioner only returns users that have an NPI
# *and* either a username or an abook_type of ord_lab/spe/external_provider
# (PractitionerService::search). abook_type is not in the REST controller's
# field whitelist, so username is the only one of the two we can set over the
# API — without it these providers are invisible to the API even though the
# rows exist. They get no password, so they cannot log in.
PRACTITIONERS = [
    {
        "fname": "Alexa",
        "lname": "Bacino",
        "npi": "1234567893",
        "specialty": "Pediatric Nutrition",
        "state_license_number": "PD-0001",
        "username": "abacino",
    },
    {
        "fname": "Dana",
        "lname": "Whitmore",
        "npi": "1234567810",
        "specialty": "Adult Nutrition - Diabetes",
        "state_license_number": "RD-0002",
        "username": "dwhitmore",
    },
    {
        "fname": "Priya",
        "lname": "Raman",
        "npi": "1234567828",
        "specialty": "Adult Nutrition - Bariatric and GI",
        "state_license_number": "RD-0003",
        "username": "praman",
    },
]

# `referrer` carries the referring provider, which is what the GDM referral
# check reads. `nutrition_condition` becomes a problem-list entry.
PATIENTS = [
    {
        "fname": "Aaron",
        "lname": "Whitfield",
        "sex": "Male",
        "DOB": "1984-03-12",
        "phone": "9085551001",
        "referrer": "Summit Health Internal Medicine",
        "nutrition_condition": "Type 2 Diabetes Mellitus",
        "insured": True,
    },
    {
        "fname": "Maria",
        "lname": "Delgado",
        "sex": "Female",
        "DOB": "1992-07-02",
        "phone": "9085551002",
        "referrer": "Summit Health OBGYN",
        "nutrition_condition": "Gestational Diabetes Mellitus",
        "insured": True,
    },
    {
        "fname": "Jenna",
        "lname": "Cole",
        "sex": "Female",
        "DOB": "1990-11-18",
        "phone": "9085551003",
        "referrer": "Riverside Women's Health",
        "nutrition_condition": "Gestational Diabetes Mellitus",
        "insured": True,
    },
    {
        "fname": "Liam",
        "lname": "Foster",
        "sex": "Male",
        "DOB": "2016-05-20",
        "phone": "9085551004",
        "referrer": "Summit Health Pediatrics",
        "nutrition_condition": "General Nutrition Counseling",
        "insured": True,
    },
    {
        "fname": "Rachel",
        "lname": "Nunez",
        "sex": "Female",
        "DOB": "1995-02-09",
        "phone": "9085551005",
        "referrer": "Summit Health Behavioral Health",
        "nutrition_condition": "Eating Disorder",
        "insured": True,
    },
    {
        "fname": "Tom",
        "lname": "Becker",
        "sex": "Male",
        "DOB": "1978-09-30",
        "phone": "9085551006",
        "referrer": "Summit Health Family Medicine",
        "nutrition_condition": "Weight Management",
        "insured": False,
    },
]

INSURANCE_COMPANY = "Summit Health Plan"


def _sql(statement: str) -> str:
    result = subprocess.run(
        [
            "docker",
            "exec",
            DB_CONTAINER,
            "mariadb",
            "-uroot",
            f"-p{DB_ROOT_PASSWORD}",
            "-D",
            DB_NAME,
            "-N",
            "-B",
            "-e",
            statement,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"SQL failed: {result.stderr.strip()}")
    return result.stdout.strip()


def seed_categories() -> None:
    print("Appointment categories:")
    for name, duration in NUTRITION_CATEGORIES:
        existing = _sql(
            "SELECT pc_catid FROM openemr_postcalendar_categories "
            f"WHERE pc_catname = '{name}';"
        )
        if existing:
            print(f"  = {name} (pc_catid={existing})")
            continue
        _sql(
            "INSERT INTO openemr_postcalendar_categories "
            "(pc_catname, pc_catcolor, pc_catdesc, pc_recurrtype, pc_enddate, "
            " pc_recurrspec, pc_recurrfreq, pc_duration, pc_end_date_flag, "
            " pc_end_date_type, pc_end_date_freq, pc_end_all_day, pc_dailylimit, "
            " pc_cattype, pc_active, pc_seq, aco_spec) "
            f"VALUES ('{name}', '#E0FFC2', '{name}', 0, NULL, '', 0, {duration}, "
            "0, NULL, 0, 0, 0, 0, 1, 10, 'Calendar|appt')"
        )
        new_id = _sql(
            "SELECT pc_catid FROM openemr_postcalendar_categories "
            f"WHERE pc_catname = '{name}';"
        )
        print(f"  + {name} (pc_catid={new_id})")


async def seed_practitioners(client: OpenEMRClient) -> dict[str, dict]:
    print("Practitioners:")
    existing = await client.get("/practitioner") or []
    by_name = {f"{p.get('fname')} {p.get('lname')}": p for p in existing}

    out: dict[str, dict] = {}
    for spec in PRACTITIONERS:
        full_name = f"{spec['fname']} {spec['lname']}"
        if full_name in by_name:
            print(f"  = {full_name}")
            out[full_name] = by_name[full_name]
            continue
        created = await client.post("/practitioner", {"title": "", **spec}) or {}
        print(f"  + {full_name} (uuid={created.get('uuid')})")
        refreshed = await client.get("/practitioner") or []
        for p in refreshed:
            if f"{p.get('fname')} {p.get('lname')}" == full_name:
                out[full_name] = p
                break
    return out


async def seed_insurance_company(client: OpenEMRClient) -> int | None:
    print("Insurance company:")
    companies = await client.get("/insurance_company") or []
    for company in companies:
        if company.get("name") == INSURANCE_COMPANY:
            print(f"  = {INSURANCE_COMPANY} (id={company.get('id')})")
            return int(company["id"])

    await client.post(
        "/insurance_company",
        {
            "name": INSURANCE_COMPANY,
            "attn": "Claims Department",
            "cms_id": "SHP01",
            "ins_type_code": 2,
            "city": "Summit",
            "state": "NJ",
            "postal_code": "07901",
            "line1": "1 Plan Way",
            "country": "USA",
        },
    )
    companies = await client.get("/insurance_company") or []
    for company in companies:
        if company.get("name") == INSURANCE_COMPANY:
            print(f"  + {INSURANCE_COMPANY} (id={company.get('id')})")
            return int(company["id"])
    print("  ! could not resolve insurance company id")
    return None


async def seed_patients(client: OpenEMRClient, insurer_id: int | None) -> dict[str, dict]:
    print("Patients:")
    out: dict[str, dict] = {}

    for spec in PATIENTS:
        phone = spec["phone"]
        found = await client.get("/patient", phone_cell=phone) or []
        if found:
            patient = found[0]
            print(f"  = {spec['fname']} {spec['lname']} (pid={patient.get('pid')})")
        else:
            await client.post(
                "/patient",
                {
                    "title": "",
                    "fname": spec["fname"],
                    "lname": spec["lname"],
                    "sex": spec["sex"],
                    "DOB": spec["DOB"],
                    "street": "12 Maple Ave",
                    "postal_code": "07901",
                    "city": "Summit",
                    "state": "NJ",
                    "phone_home": phone,
                    "phone_cell": phone,
                    "email": f"{spec['fname'].lower()}.{spec['lname'].lower()}@example.com",
                    "referrer": spec["referrer"],
                },
            )
            found = await client.get("/patient", phone_cell=phone) or []
            if not found:
                print(f"  ! failed to create {spec['fname']} {spec['lname']}")
                continue
            patient = found[0]
            print(f"  + {spec['fname']} {spec['lname']} (pid={patient.get('pid')})")

        out[phone] = patient
        await _ensure_problem(client, patient, spec["nutrition_condition"])
        if spec["insured"] and insurer_id:
            await _ensure_coverage(client, patient, spec, insurer_id)

    return out


async def _ensure_problem(client: OpenEMRClient, patient: dict, title: str) -> None:
    puuid = patient["uuid"]
    problems = await client.get(f"/patient/{puuid}/medical_problem") or []
    if any((p.get("title") or "").strip() == title for p in problems):
        print(f"      = problem: {title}")
        return
    try:
        await client.post(
            f"/patient/{puuid}/medical_problem",
            {"title": title, "begdate": "2026-01-15"},
        )
        print(f"      + problem: {title}")
    except OpenEMRError as exc:
        print(f"      ! problem {title!r}: {exc}")


async def _ensure_coverage(
    client: OpenEMRClient, patient: dict, spec: dict, insurer_id: int
) -> None:
    puuid = patient["uuid"]
    coverage = await client.get(f"/patient/{puuid}/insurance") or []
    if any((c.get("type") or c.get("type_name")) == "primary" for c in coverage):
        print("      = coverage: primary")
        return
    try:
        await client.post(
            f"/patient/{puuid}/insurance",
            {
                "type": "primary",
                "provider": insurer_id,
                "plan_name": "Summit Health Nutrition PPO",
                "policy_number": f"SHP{spec['phone'][-4:]}",
                "group_number": "GRP1001",
                "subscriber_lname": spec["lname"],
                "subscriber_fname": spec["fname"],
                "subscriber_relationship": "self",
                "subscriber_DOB": spec["DOB"],
                "subscriber_street": "12 Maple Ave",
                "subscriber_postal_code": "07901",
                "subscriber_city": "Summit",
                "subscriber_state": "NJ",
                "subscriber_phone": spec["phone"],
                "subscriber_sex": spec["sex"],
                "accept_assignment": "TRUE",
                "date": "2026-01-01",
                # OpenEMR makes date_end required once date + pid + type are
                # present. A future end date keeps the policy active today.
                "date_end": "2027-12-31",
            },
        )
        print("      + coverage: primary")
    except OpenEMRError as exc:
        print(f"      ! coverage: {exc}")


async def seed_appointments(
    client: OpenEMRClient, patients: dict[str, dict], providers: dict[str, dict]
) -> None:
    """Book a couple of appointments so availability has real gaps in it."""
    print("Existing appointments (so slot search has something to avoid):")

    facility_id = None
    facilities = await client.get("/facility") or []
    if facilities:
        facility_id = facilities[0].get("id")
    if facility_id is None:
        print("  ! no facility found; skipping")
        return

    category_id = _sql(
        "SELECT pc_catid FROM openemr_postcalendar_categories "
        "WHERE pc_catname = 'Nutrition Follow Up';"
    )
    if not category_id:
        print("  ! Nutrition Follow Up category missing; skipping")
        return

    provider = providers.get("Dana Whitmore") or {}
    provider_user_id = _sql(
        "SELECT id FROM users WHERE fname = 'Dana' AND lname = 'Whitmore' LIMIT 1;"
    )

    target_date = _next_weekday(date.today() + timedelta(days=2))
    bookings = [
        ("9085551001", "09:00"),
        ("9085551006", "10:30"),
    ]

    for phone, start_time in bookings:
        patient = patients.get(phone)
        if not patient:
            continue
        pid = patient["pid"]
        # Appointment routes are keyed on the numeric pid, not the uuid that
        # the insurance/encounter/problem routes use.
        existing = await client.get(f"/patient/{pid}/appointment") or []
        if any(
            a.get("pc_eventDate") == target_date.isoformat()
            and (a.get("pc_startTime") or "").startswith(start_time)
            for a in existing
        ):
            print(f"  = {patient['fname']} {patient['lname']} {target_date} {start_time}")
            continue
        body = {
            "pc_catid": int(category_id),
            "pc_title": "Nutrition Follow Up",
            "pc_duration": 1800,
            "pc_hometext": "Seeded demo appointment",
            "pc_apptstatus": "-",
            "pc_eventDate": target_date.isoformat(),
            "pc_startTime": start_time,
            "pc_facility": int(facility_id),
            "pc_billing_location": int(facility_id),
        }
        if provider_user_id:
            body["pc_aid"] = int(provider_user_id)
        try:
            await client.post(f"/patient/{pid}/appointment", body)
            print(f"  + {patient['fname']} {patient['lname']} {target_date} {start_time}")
        except OpenEMRError as exc:
            print(f"  ! appointment for pid={pid}: {exc}")

    if provider:
        print(f"  (provider Dana Whitmore users.id={provider_user_id})")


def _next_weekday(value: date) -> date:
    while value.weekday() >= 5:
        value += timedelta(days=1)
    return value


async def main() -> int:
    print(f"Seeding OpenEMR demo data at {datetime.now():%Y-%m-%d %H:%M}\n")
    seed_categories()
    print()

    client = OpenEMRClient.from_env()
    try:
        providers = await seed_practitioners(client)
        print()
        insurer_id = await seed_insurance_company(client)
        print()
        patients = await seed_patients(client, insurer_id)
        print()
        await seed_appointments(client, patients, providers)
    finally:
        await client.aclose()

    print("\nSeeding complete.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
