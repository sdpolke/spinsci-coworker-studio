"""Local organization credit ledger — balance, grants, holds, and usage debits."""

from dataclasses import dataclass
from typing import Any

from loguru import logger

from api.constants import (
    CREDIT_USD_PER_MINUTE,
    CREDITS_PER_MINUTE,
    MINIMUM_CREDITS_FOR_CALL,
)
from api.db import db_client
from api.db.local_credits_client import InsufficientCreditsError
from api.db.models import OrganizationCreditLedgerModel
from api.enums import WorkflowRunMode


@dataclass
class LocalCreditAuthResult:
    has_quota: bool
    error_code: str = ""
    error_message: str = ""


@dataclass
class LocalBillingSnapshot:
    balance: float
    total_debits: float
    entries: list[OrganizationCreditLedgerModel]
    total_count: int
    page: int
    limit: int


def billable_minutes(duration_seconds: float) -> int:
    return db_client.billable_minutes(duration_seconds)


def credits_for_duration(duration_seconds: float) -> float:
    minutes = billable_minutes(duration_seconds)
    if minutes <= 0:
        return 0.0
    return float(minutes * CREDITS_PER_MINUTE)


async def get_billing_snapshot(
    organization_id: int,
    *,
    page: int,
    limit: int,
) -> LocalBillingSnapshot:
    balance = await db_client.get_credit_balance(organization_id)
    entries, total_count, total_debits = await db_client.get_paginated_ledger(
        organization_id,
        page=page,
        limit=limit,
    )
    return LocalBillingSnapshot(
        balance=balance,
        total_debits=total_debits,
        entries=entries,
        total_count=total_count,
        page=page,
        limit=limit,
    )


async def authorize_run(
    organization_id: int,
    *,
    workflow_run_id: int | None = None,
    workflow_id: int | None = None,
) -> LocalCreditAuthResult:
    """Gate a run on local balance; place a hold when a run id is available."""
    try:
        if workflow_run_id is not None:
            await db_client.place_run_hold(
                organization_id=organization_id,
                workflow_run_id=workflow_run_id,
                workflow_id=workflow_id,
            )
        else:
            balance = await db_client.get_credit_balance(organization_id)
            if balance < MINIMUM_CREDITS_FOR_CALL:
                raise InsufficientCreditsError("insufficient")
    except InsufficientCreditsError:
        return LocalCreditAuthResult(
            has_quota=False,
            error_code="insufficient_credits",
            error_message=(
                "You have exhausted your credits. "
                f"Please add credits from /billing (minimum {MINIMUM_CREDITS_FOR_CALL:.0f} "
                f"credits required for one minute at ${CREDIT_USD_PER_MINUTE:.2f}/min)."
            ),
        )
    return LocalCreditAuthResult(has_quota=True)


async def grant_credits(
    organization_id: int,
    *,
    credits: float,
    created_by: str | None = None,
    note: str | None = None,
) -> float:
    if credits <= 0:
        raise ValueError("Grant amount must be positive")

    await db_client.ensure_credit_account(organization_id)
    metadata: dict[str, Any] = {}
    if note:
        metadata["note"] = note

    entry = await db_client.append_ledger_entry(
        organization_id=organization_id,
        entry_type="grant",
        origin="admin_topup",
        credits_delta=credits,
        metadata=metadata,
        created_by=created_by,
        allow_negative=False,
    )
    logger.info(
        "Granted {:.2f} credits to org {} (balance {:.2f})",
        credits,
        organization_id,
        entry.balance_after,
    )
    return float(entry.balance_after)


def _duration_seconds_from_usage_info(workflow_run) -> float | None:
    usage_info: dict[str, Any] = getattr(workflow_run, "usage_info", None) or {}
    duration = usage_info.get("call_duration_seconds")
    try:
        duration_seconds = float(duration)
    except (TypeError, ValueError):
        return None
    return duration_seconds if duration_seconds > 0 else None


async def debit_platform_usage(workflow_run) -> None:
    workflow = getattr(workflow_run, "workflow", None)
    organization_id = getattr(workflow, "organization_id", None)

    async def _release_hold_if_needed() -> None:
        if organization_id is None:
            return
        await db_client.release_run_hold(
            organization_id=organization_id,
            workflow_run_id=workflow_run.id,
        )

    if getattr(workflow_run, "mode", None) == WorkflowRunMode.TEXTCHAT.value:
        logger.info(
            "Skipping local platform debit for text chat workflow run {}",
            workflow_run.id,
        )
        await _release_hold_if_needed()
        return

    if not getattr(workflow_run, "is_completed", False):
        logger.warning(
            "Workflow run {} is not completed; skipping local platform debit",
            workflow_run.id,
        )
        return

    if organization_id is None:
        logger.warning(
            "Skipping local platform debit for workflow run {}: no organization_id",
            workflow_run.id,
        )
        return

    duration_seconds = _duration_seconds_from_usage_info(workflow_run)
    if duration_seconds is None:
        logger.warning(
            "Skipping local platform debit for workflow run {}: no billable duration",
            workflow_run.id,
        )
        await _release_hold_if_needed()
        return

    minutes = billable_minutes(duration_seconds)
    credits = credits_for_duration(duration_seconds)
    if credits <= 0:
        await _release_hold_if_needed()
        return

    entry = await db_client.settle_platform_usage(
        organization_id=organization_id,
        workflow_run_id=workflow_run.id,
        workflow_id=getattr(workflow_run, "workflow_id", None),
        credits=credits,
        billable_minutes=float(minutes),
        metadata={
            "duration_seconds": duration_seconds,
            "usd_per_minute": CREDIT_USD_PER_MINUTE,
            "credits_per_minute": CREDITS_PER_MINUTE,
        },
    )
    logger.info(
        "Settled {:.2f} credits ({:.0f} min) for workflow run {} (balance {:.2f})",
        abs(float(entry.credits_delta)),
        minutes,
        workflow_run.id,
        entry.balance_after,
    )


async def ensure_organization_account(organization_id: int) -> None:
    await db_client.ensure_credit_account(organization_id)
