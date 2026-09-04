"""In-memory mock data for the eye-clinic front-desk demo.

There is no database and no EHR integration. Patients are looked up by the
phone number "on file" (mocked here), doctors are a small fixed roster, and
slots are generated on the fly. Everything resets when the server restarts.

This mock stands in for what a real deployment (e.g. St. Luke's NextGen /
RingCX integration) would call `lookup_patient`, `get_appointments`,
`get_available_slots`, `book_appointment`, etc. — same shape, much smaller.
"""

from __future__ import annotations

import itertools
import uuid
from copy import deepcopy
from datetime import datetime, timedelta

# --- Doctor roster ----------------------------------------------------------

DOCTORS: list[dict[str, str]] = [
    {"id": "doc-arcaro", "name": "Dr. Arcaro", "specialty": "general eye exams", "office": "Riverside"},
    {"id": "doc-hoffert", "name": "Dr. Hoffert", "specialty": "cataract evaluations", "office": "Riverside"},
    {"id": "doc-glass", "name": "Dr. Glass", "specialty": "LASIK evaluations", "office": "Lakeview"},
    {"id": "doc-posey", "name": "Dr. Posey", "specialty": "hearing services", "office": "Lakeview"},
]

_OFFICES = sorted({d["office"] for d in DOCTORS})

# --- Patients (keyed by 10-digit phone "on file") ---------------------------

_PATIENTS: dict[str, dict] = {
    "5551230001": {
        "patient_id": "pat-0001",
        "name": "Alex Rivera",
        "date_of_birth": "1985-03-14",
        "appointments": [
            {
                "appointment_id": "appt-1001",
                "doctor_id": "doc-arcaro",
                "office": "Riverside",
                "reason": "annual eye exam",
                "when": (datetime.now() + timedelta(days=9)).replace(
                    hour=10, minute=30, second=0, microsecond=0
                ),
                "status": "scheduled",
            }
        ],
    },
    "5551230002": {
        "patient_id": "pat-0002",
        "name": "Jamie Chen",
        "date_of_birth": "1990-11-02",
        "appointments": [],
    },
}

_id_counter = itertools.count(2001)


def _new_appointment_id() -> str:
    return f"appt-{next(_id_counter)}"


def find_patient_by_phone(phone: str) -> dict | None:
    """Look up the patient "on file" for a 10-digit phone number."""
    key = "".join(ch for ch in (phone or "") if ch.isdigit())[-10:]
    return _PATIENTS.get(key)


def _parse_date_loosely(value: str) -> str | None:
    """Best-effort parse of a spoken/typed date into YYYY-MM-DD.

    Caller speech (transcribed by STT, or typed in the text chat) comes in as
    "March 14, 1985", "1985-03-14", "3/14/1985", etc. — never assume the
    caller-facing format matches the record's storage format.
    """
    value = (value or "").strip()
    if not value:
        return None
    formats = (
        "%Y-%m-%d",
        "%B %d %Y",
        "%B %d, %Y",
        "%b %d %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
        "%m-%d-%Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def verify_patient(phone: str, full_name: str, date_of_birth: str) -> dict | None:
    """Confirm a caller's identity: phone must resolve, and name + DOB must match.

    Returns the patient record on a match, or None. Comparison is
    case-insensitive and ignores extra whitespace and date formatting,
    mirroring how a real verification step would normalize caller speech
    before comparing it to the record on file — never trust an unverified
    phone lookup alone.
    """
    patient = find_patient_by_phone(phone)
    if not patient:
        return None
    if patient["name"].strip().lower() != (full_name or "").strip().lower():
        return None
    parsed_dob = _parse_date_loosely(date_of_birth)
    if parsed_dob is None or patient["date_of_birth"] != parsed_dob:
        return None
    return patient


def get_appointments(patient_id: str) -> list[dict]:
    for patient in _PATIENTS.values():
        if patient["patient_id"] == patient_id:
            return deepcopy(patient["appointments"])
    return []


def _find_patient_record(patient_id: str) -> dict | None:
    for patient in _PATIENTS.values():
        if patient["patient_id"] == patient_id:
            return patient
    return None


def _find_appointment(patient: dict, appointment_id: str) -> dict | None:
    for appt in patient["appointments"]:
        if appt["appointment_id"] == appointment_id:
            return appt
    return None


def confirm_appointment(patient_id: str, appointment_id: str) -> dict:
    patient = _find_patient_record(patient_id)
    appt = _find_appointment(patient, appointment_id) if patient else None
    if not appt:
        return {"ok": False, "reason": "appointment not found"}
    if appt["when"] < datetime.now():
        return {"ok": False, "reason": "that appointment has already passed"}
    appt["status"] = "confirmed"
    return {"ok": True, "appointment": deepcopy(appt)}


def cancel_appointment(patient_id: str, appointment_id: str) -> dict:
    patient = _find_patient_record(patient_id)
    appt = _find_appointment(patient, appointment_id) if patient else None
    if not appt:
        return {"ok": False, "reason": "appointment not found"}
    appt["status"] = "cancelled"
    return {"ok": True, "appointment": deepcopy(appt)}


def reschedule_appointment(patient_id: str, appointment_id: str, new_when: datetime) -> dict:
    patient = _find_patient_record(patient_id)
    appt = _find_appointment(patient, appointment_id) if patient else None
    if not appt:
        return {"ok": False, "reason": "appointment not found"}
    appt["when"] = new_when
    appt["status"] = "scheduled"
    return {"ok": True, "appointment": deepcopy(appt)}


def list_doctors(specialty_hint: str | None = None) -> list[dict]:
    if not specialty_hint:
        return deepcopy(DOCTORS)
    hint = specialty_hint.strip().lower()
    matches = [d for d in DOCTORS if hint in d["specialty"].lower() or hint in d["name"].lower()]
    return deepcopy(matches or DOCTORS)


def find_doctor(name_or_id: str) -> dict | None:
    q = (name_or_id or "").strip().lower()
    for d in DOCTORS:
        if q in d["id"].lower() or q in d["name"].lower():
            return deepcopy(d)
    return None


def get_available_slots(doctor_id: str, days_ahead: int = 14) -> list[datetime]:
    """Deterministic mock slots: doctor's office hours, 30-minute increments."""
    doctor = next((d for d in DOCTORS if d["id"] == doctor_id), None)
    if doctor is None:
        return []
    base = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
    slots: list[datetime] = []
    day_offset = 0
    while len(slots) < 6 and day_offset < days_ahead:
        day = base + timedelta(days=day_offset)
        if day.weekday() < 5:  # weekdays only
            for hour in (9, 11, 14):
                slots.append(day.replace(hour=hour, minute=0))
        day_offset += 1
    return slots[:6]


def book_appointment(patient_id: str, doctor_id: str, when: datetime, reason: str) -> dict:
    patient = _find_patient_record(patient_id)
    doctor = next((d for d in DOCTORS if d["id"] == doctor_id), None)
    if not patient or not doctor:
        return {"ok": False, "reason": "patient or doctor not found"}
    appt = {
        "appointment_id": _new_appointment_id(),
        "doctor_id": doctor_id,
        "office": doctor["office"],
        "reason": reason,
        "when": when,
        "status": "scheduled",
    }
    patient["appointments"].append(appt)
    return {"ok": True, "appointment": deepcopy(appt)}


# --- Billing -----------------------------------------------------------------

_BALANCES: dict[str, float] = {
    "pat-0001": 45.00,
    "pat-0002": 0.00,
}


def get_balance(patient_id: str) -> float:
    return _BALANCES.get(patient_id, 0.00)
