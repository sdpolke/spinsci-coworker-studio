"""Tools for the eye-clinic front-desk agents.

Three kinds live here:

* **Verification tool** (`verify_patient`) — every specialist requires a
  verified patient before touching an existing chart. It's on every agent's
  tool list except triage.
* **Business tools** — scheduling (list/confirm/cancel/reschedule existing
  appointments), booking (find a doctor, check availability, book a new
  visit), and billing (check balance). They hit the mock data store in
  `mock_data.py` and return plain strings.
* **Handoff tools** (`transfer_to_*`) — move control between agent nodes.
  Each returns a ``Command`` that updates ``active_agent`` and jumps to
  another node in the *parent* graph via ``graph=Command.PARENT``, following
  the same LangChain "multiple agent subgraphs" pattern as the switchboard →
  scheduling → booking handoff chain in a real deployment (see README).

Unlike a production system (VAPI/RingCX/NextGen), there's no live phone
number to trust — the caller always states the phone, name, and date of
birth out loud, and `verify_patient` checks all three against the mock
patient record before any chart is touched.
"""

from __future__ import annotations

from datetime import datetime

from langchain.messages import AIMessage, ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.types import Command

from . import mock_data

# --- Verification ------------------------------------------------------------


@tool
def verify_patient(phone_number: str, full_name: str, date_of_birth: str) -> str:
    """Verify a caller's identity before touching their chart.

    Ask for the phone number on the account, then their full name, then their
    date of birth (month, day, year) — never skip straight to name/DOB without
    the phone. Required before any lookup, modify, book, or billing tool.
    """
    patient = mock_data.verify_patient(phone_number, full_name, date_of_birth)
    if not patient:
        return (
            "I couldn't verify an account with that phone number, name, and date "
            "of birth. Could you double-check them?"
        )
    return f"Verified. patient_id={patient['patient_id']}"


# --- Scheduling (modify existing appointments) ------------------------------


@tool
def list_appointments(patient_id: str) -> str:
    """List a verified patient's appointments (past and upcoming)."""
    appts = mock_data.get_appointments(patient_id)
    if not appts:
        return "This patient has no appointments on file."
    lines = []
    for a in appts:
        doctor = mock_data.find_doctor(a["doctor_id"])
        doctor_name = doctor["name"] if doctor else "Unknown"
        when = a["when"].strftime("%B %-d at %-I:%M %p")
        lines.append(
            f"- {a['appointment_id']}: {when} with {doctor_name} at {a['office']} "
            f"({a['reason']}) — {a['status']}"
        )
    return "Appointments:\n" + "\n".join(lines)


@tool
def confirm_appointment(patient_id: str, appointment_id: str) -> str:
    """Confirm attendance for one upcoming appointment. Never for a past visit."""
    result = mock_data.confirm_appointment(patient_id, appointment_id)
    if not result["ok"]:
        return f"Couldn't confirm that appointment: {result['reason']}."
    appt = result["appointment"]
    when = appt["when"].strftime("%B %-d at %-I:%M %p")
    return f"Confirmed for {when}. See you then."


@tool
def cancel_appointment(patient_id: str, appointment_id: str) -> str:
    """Cancel an existing appointment."""
    result = mock_data.cancel_appointment(patient_id, appointment_id)
    if not result["ok"]:
        return f"Couldn't cancel that appointment: {result['reason']}."
    return "That appointment has been cancelled."


@tool
def reschedule_appointment(
    patient_id: str, appointment_id: str, new_date: str, new_time: str
) -> str:
    """Reschedule an appointment to a new date/time with the same doctor.

    `new_date` like "2026-06-20", `new_time` like "14:00" (24-hour). Ask the
    caller for both before calling this tool — never guess a date or time
    that wasn't offered.
    """
    try:
        new_when = datetime.strptime(f"{new_date} {new_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return "That date or time didn't parse — please give a date like 2026-06-20 and a 24-hour time like 14:00."
    result = mock_data.reschedule_appointment(patient_id, appointment_id, new_when)
    if not result["ok"]:
        return f"Couldn't reschedule that appointment: {result['reason']}."
    appt = result["appointment"]
    when = appt["when"].strftime("%B %-d at %-I:%M %p")
    return f"Rescheduled to {when}."


# --- Booking (new appointments) ---------------------------------------------


@tool
def list_doctors(specialty: str = "") -> str:
    """List doctors, optionally filtered by specialty (e.g. "cataract", "hearing")."""
    doctors = mock_data.list_doctors(specialty or None)
    lines = [f"- {d['name']} ({d['specialty']}) at {d['office']}" for d in doctors]
    return "Doctors:\n" + "\n".join(lines)


@tool
def check_availability(doctor_name: str) -> str:
    """Check the next available openings for a named doctor."""
    doctor = mock_data.find_doctor(doctor_name)
    if not doctor:
        return (
            f"I couldn't find a doctor matching '{doctor_name}'. Use list_doctors "
            "to see who's on our roster."
        )
    slots = mock_data.get_available_slots(doctor["id"])
    if not slots:
        return f"No openings found for {doctor['name']} right now."
    lines = [s.strftime("%B %-d at %-I:%M %p") for s in slots[:3]]
    return f"Next openings with {doctor['name']}: " + "; ".join(lines)


@tool
def book_appointment(patient_id: str, doctor_name: str, date: str, time: str, reason: str) -> str:
    """Book a new appointment. `date` like "2026-06-20", `time` like "14:00" (24-hour).

    Only call this after offering availability and the caller picked one of
    the offered times — never invent a time that wasn't offered.
    """
    doctor = mock_data.find_doctor(doctor_name)
    if not doctor:
        return f"I couldn't find a doctor matching '{doctor_name}'."
    try:
        when = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return "That date or time didn't parse — please give a date like 2026-06-20 and a 24-hour time like 14:00."
    result = mock_data.book_appointment(patient_id, doctor["id"], when, reason)
    if not result["ok"]:
        return f"Couldn't book that appointment: {result['reason']}."
    appt = result["appointment"]
    when_str = appt["when"].strftime("%B %-d at %-I:%M %p")
    return f"Booked with {doctor['name']} on {when_str} at {doctor['office']}."


# --- Billing ------------------------------------------------------------------


@tool
def check_balance(patient_id: str) -> str:
    """Check a verified patient's account balance."""
    balance = mock_data.get_balance(patient_id)
    if balance <= 0:
        return "This account has no outstanding balance."
    return f"The current balance on file is ${balance:.2f}."


# --- Handoff tools ------------------------------------------------------------


def _handoff(goto: str, runtime: ToolRuntime, note: str) -> Command:
    """Build a Command that transfers control to another agent node.

    Passes only the triggering AIMessage and a closing ToolMessage to the
    parent graph — not the whole sub-agent history — so the receiving agent
    gets valid, focused context. Mirrors how a real front-desk → scheduling →
    booking squad hands off a live call: the transfer is invisible to the
    caller, and the state (``active_agent``, ``patient_id`` once verified)
    travels with it.
    """
    last_ai = next(
        msg for msg in reversed(runtime.state["messages"]) if isinstance(msg, AIMessage)
    )
    transfer_message = ToolMessage(content=note, tool_call_id=runtime.tool_call_id)
    return Command(
        goto=goto,
        update={"active_agent": goto, "messages": [last_ai, transfer_message]},
        graph=Command.PARENT,
    )


@tool
def transfer_to_scheduling(runtime: ToolRuntime) -> Command:
    """Transfer to the scheduling specialist to confirm, cancel, or reschedule an existing appointment."""
    return _handoff("scheduling", runtime, "Transferred to scheduling.")


@tool
def transfer_to_booking(runtime: ToolRuntime) -> Command:
    """Transfer to the booking specialist to schedule a brand-new appointment."""
    return _handoff("booking", runtime, "Transferred to booking.")


@tool
def transfer_to_billing(runtime: ToolRuntime) -> Command:
    """Transfer to the billing specialist for account balance questions."""
    return _handoff("billing", runtime, "Transferred to billing.")


@tool
def transfer_to_triage(runtime: ToolRuntime) -> Command:
    """Hand the caller back to the front desk to be re-routed."""
    return _handoff("triage", runtime, "Transferred back to the front desk.")
