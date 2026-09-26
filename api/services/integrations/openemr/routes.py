"""Authenticated OpenEMR operation gateway for reusable SpinSci tools.

These endpoints intentionally return the same structured dictionaries as the
OpenEMR MCP operations. The generic SpinSci HTTP tool layer can therefore pass
the result directly back to the agent, while this gateway keeps OpenEMR OAuth
client credentials and token refresh server-side.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.db.models import UserModel
from api.services.auth.depends import get_user_with_selected_organization

router = APIRouter(prefix="/integrations/openemr", tags=["openemr"])


class PhoneRequest(BaseModel):
    phone: str = Field(min_length=1)


class PatientRequest(BaseModel):
    patient_id: str = Field(min_length=1)


class SlotsRequest(BaseModel):
    patient_id: str = ""
    visit_type: str = "Nutrition Follow Up"
    provider_name: str = ""
    days_ahead: int = Field(default=14, ge=0, le=90)
    max_results: int = Field(default=5, ge=1, le=20)


class SlotPolicyRequest(BaseModel):
    slot_id: str = Field(min_length=1)
    wants_virtual: bool = False


class BookingRequest(BaseModel):
    patient_id: str = Field(min_length=1)
    slot_id: str = Field(min_length=1)
    reason: str = "Nutrition counseling"


class InstructionsRequest(BaseModel):
    patient_id: str = Field(min_length=1)
    tests_blood_sugar_at_home: bool = False


class EscalationRequest(BaseModel):
    patient_id: str = Field(min_length=1)
    reason: str = ""


async def _operation(name: str, **arguments: Any) -> dict[str, Any]:
    """Call the tested integration operation without importing it at startup."""
    try:
        from integrations.openemr.mcp_server import server as openemr_server

        operation = getattr(openemr_server, name)
        return await operation(**arguments)
    except Exception as exc:  # noqa: BLE001 - gateway returns agent-safe errors
        return {
            "status": "error",
            "spoken_summary": "I'm having trouble reaching the medical record system right now.",
            "detail": str(exc),
        }


@router.post("/patient/lookup")
async def lookup_patient(
    request: PhoneRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
) -> dict[str, Any]:
    return await _operation("identify_patient_by_phone", phone=request.phone)


@router.post("/patient/eligibility")
async def check_eligibility(
    request: PatientRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
) -> dict[str, Any]:
    return await _operation("check_nutrition_eligibility", patient_id=request.patient_id)


@router.post("/patient/gdm-referral")
async def check_gdm_referral(
    request: PatientRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
) -> dict[str, Any]:
    return await _operation("check_gdm_referral", patient_id=request.patient_id)


@router.post("/patient/route-pediatric")
async def route_pediatric(
    request: PatientRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
) -> dict[str, Any]:
    return await _operation("route_pediatric_patient", patient_id=request.patient_id)


@router.post("/patient/coverage")
async def check_coverage(
    request: PatientRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
) -> dict[str, Any]:
    return await _operation("check_nutrition_coverage", patient_id=request.patient_id)


@router.post("/patient/instructions")
async def get_instructions(
    request: InstructionsRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
) -> dict[str, Any]:
    return await _operation(
        "get_patient_instructions",
        patient_id=request.patient_id,
        tests_blood_sugar_at_home=request.tests_blood_sugar_at_home,
    )


@router.post("/appointments/slots")
async def find_slots(
    request: SlotsRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
) -> dict[str, Any]:
    return await _operation(
        "find_available_slots",
        patient_id=request.patient_id,
        visit_type=request.visit_type,
        provider_name=request.provider_name,
        days_ahead=request.days_ahead,
        max_results=request.max_results,
    )


@router.post("/appointments/slot-policy")
async def validate_slot_policy(
    request: SlotPolicyRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
) -> dict[str, Any]:
    return await _operation(
        "validate_slot_policy",
        slot_id=request.slot_id,
        wants_virtual=request.wants_virtual,
    )


@router.post("/appointments/book")
async def book_appointment(
    request: BookingRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
) -> dict[str, Any]:
    return await _operation(
        "book_nutrition_appointment",
        patient_id=request.patient_id,
        slot_id=request.slot_id,
        reason=request.reason,
    )


@router.post("/appointments/list")
async def list_appointments(
    request: PatientRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
) -> dict[str, Any]:
    return await _operation("get_patient_appointments", patient_id=request.patient_id)


@router.post("/appointments/gdm-escalate")
async def escalate_gdm(
    request: EscalationRequest,
    user: UserModel = Depends(get_user_with_selected_organization),
) -> dict[str, Any]:
    return await _operation(
        "escalate_gdm_scheduling",
        patient_id=request.patient_id,
        reason=request.reason,
    )
