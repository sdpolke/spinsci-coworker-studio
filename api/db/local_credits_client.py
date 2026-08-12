import math
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.future import select as future_select

from api.constants import INITIAL_ORGANIZATION_CREDITS, MINIMUM_CREDITS_FOR_CALL
from api.db.base_client import BaseDBClient
from api.db.models import OrganizationCreditAccountModel, OrganizationCreditLedgerModel


class InsufficientCreditsError(Exception):
    """Raised when a debit or hold would overdraw the account."""


class LocalCreditsClient(BaseDBClient):
    async def ensure_credit_account(
        self,
        organization_id: int,
        *,
        initial_balance: float | None = None,
    ) -> OrganizationCreditAccountModel:
        async with self.async_session() as session:
            result = await session.execute(
                future_select(OrganizationCreditAccountModel).where(
                    OrganizationCreditAccountModel.organization_id == organization_id
                )
            )
            account = result.scalars().first()
            if account is not None:
                return account

            starting_balance = (
                INITIAL_ORGANIZATION_CREDITS
                if initial_balance is None
                else initial_balance
            )
            stmt = (
                insert(OrganizationCreditAccountModel.__table__)
                .values(
                    organization_id=organization_id,
                    balance_credits=starting_balance,
                    currency="USD",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(index_elements=["organization_id"])
            )
            await session.execute(stmt)
            await session.commit()

            result = await session.execute(
                future_select(OrganizationCreditAccountModel).where(
                    OrganizationCreditAccountModel.organization_id == organization_id
                )
            )
            account = result.scalars().one()

            if starting_balance > 0:
                try:
                    session.add(
                        OrganizationCreditLedgerModel(
                            organization_id=organization_id,
                            entry_type="grant",
                            origin="initial_grant",
                            credits_delta=starting_balance,
                            balance_after=float(account.balance_credits or 0.0),
                            idempotency_key=f"initial_grant:{organization_id}",
                            metadata_json={},
                            created_at=datetime.now(UTC),
                        )
                    )
                    await session.commit()
                except IntegrityError:
                    await session.rollback()

            return account

    async def get_credit_balance(self, organization_id: int) -> float:
        account = await self.ensure_credit_account(organization_id)
        return float(account.balance_credits or 0.0)

    async def get_ledger_entry_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> Optional[OrganizationCreditLedgerModel]:
        async with self.async_session() as session:
            result = await session.execute(
                future_select(OrganizationCreditLedgerModel).where(
                    OrganizationCreditLedgerModel.idempotency_key == idempotency_key
                )
            )
            return result.scalars().first()

    async def _locked_account(self, session, organization_id: int):
        account_result = await session.execute(
            future_select(OrganizationCreditAccountModel)
            .where(OrganizationCreditAccountModel.organization_id == organization_id)
            .with_for_update()
        )
        account = account_result.scalars().first()
        if account is None:
            account = OrganizationCreditAccountModel(
                organization_id=organization_id,
                balance_credits=0.0,
                currency="USD",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(account)
            await session.flush()
        return account

    async def append_ledger_entry(
        self,
        *,
        organization_id: int,
        entry_type: str,
        origin: str,
        credits_delta: float,
        idempotency_key: str | None = None,
        metric_code: str | None = None,
        billable_quantity: float | None = None,
        quantity_unit: str | None = None,
        workflow_run_id: int | None = None,
        workflow_id: int | None = None,
        metadata: dict[str, Any] | None = None,
        created_by: str | None = None,
        allow_negative: bool = False,
    ) -> OrganizationCreditLedgerModel:
        async with self.async_session() as session:
            if idempotency_key:
                existing = await session.execute(
                    future_select(OrganizationCreditLedgerModel).where(
                        OrganizationCreditLedgerModel.idempotency_key == idempotency_key
                    )
                )
                existing_entry = existing.scalars().first()
                if existing_entry is not None:
                    return existing_entry

            account = await self._locked_account(session, organization_id)
            new_balance = float(account.balance_credits or 0.0) + credits_delta
            if not allow_negative and new_balance < -1e-9:
                raise InsufficientCreditsError(
                    f"Insufficient credits for organization {organization_id}"
                )

            account.balance_credits = new_balance
            account.updated_at = datetime.now(UTC)

            entry = OrganizationCreditLedgerModel(
                organization_id=organization_id,
                entry_type=entry_type,
                origin=origin,
                credits_delta=credits_delta,
                balance_after=new_balance,
                metric_code=metric_code,
                billable_quantity=billable_quantity,
                quantity_unit=quantity_unit,
                workflow_run_id=workflow_run_id,
                workflow_id=workflow_id,
                idempotency_key=idempotency_key,
                metadata_json=metadata or {},
                created_by=created_by,
                created_at=datetime.now(UTC),
            )
            session.add(entry)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                if idempotency_key:
                    existing = await self.get_ledger_entry_by_idempotency_key(
                        idempotency_key
                    )
                    if existing is not None:
                        return existing
                raise
            await session.refresh(entry)
            return entry

    async def place_run_hold(
        self,
        *,
        organization_id: int,
        workflow_run_id: int,
        workflow_id: int | None = None,
        hold_credits: float | None = None,
    ) -> OrganizationCreditLedgerModel:
        """Reserve minimum credits for a run under a row lock."""
        amount = float(
            MINIMUM_CREDITS_FOR_CALL if hold_credits is None else hold_credits
        )
        if amount <= 0:
            raise ValueError("Hold amount must be positive")

        idempotency_key = f"run_hold:{workflow_run_id}"
        async with self.async_session() as session:
            existing = await session.execute(
                future_select(OrganizationCreditLedgerModel).where(
                    OrganizationCreditLedgerModel.idempotency_key == idempotency_key
                )
            )
            existing_entry = existing.scalars().first()
            if existing_entry is not None:
                return existing_entry

            # Already settled — treat as authorized.
            settled = await session.execute(
                future_select(OrganizationCreditLedgerModel).where(
                    OrganizationCreditLedgerModel.idempotency_key
                    == f"platform_usage:{workflow_run_id}"
                )
            )
            settled_entry = settled.scalars().first()
            if settled_entry is not None:
                return settled_entry

            account = await self._locked_account(session, organization_id)
            balance = float(account.balance_credits or 0.0)
            if balance < amount:
                raise InsufficientCreditsError(
                    f"Insufficient credits for organization {organization_id}"
                )

            new_balance = balance - amount
            account.balance_credits = new_balance
            account.updated_at = datetime.now(UTC)
            entry = OrganizationCreditLedgerModel(
                organization_id=organization_id,
                entry_type="debit",
                origin="run_hold",
                credits_delta=-amount,
                balance_after=new_balance,
                metric_code="run_hold",
                billable_quantity=None,
                quantity_unit=None,
                workflow_run_id=workflow_run_id,
                workflow_id=workflow_id,
                idempotency_key=idempotency_key,
                metadata_json={"hold_credits": amount},
                created_at=datetime.now(UTC),
            )
            session.add(entry)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await self.get_ledger_entry_by_idempotency_key(
                    idempotency_key
                )
                if existing is not None:
                    return existing
                raise
            await session.refresh(entry)
            return entry

    async def release_run_hold(
        self,
        *,
        organization_id: int,
        workflow_run_id: int,
    ) -> None:
        """Release an unused run hold (e.g. textchat / no duration)."""
        hold_key = f"run_hold:{workflow_run_id}"
        release_key = f"run_hold_release:{workflow_run_id}"

        async with self.async_session() as session:
            release_existing = await session.execute(
                future_select(OrganizationCreditLedgerModel).where(
                    OrganizationCreditLedgerModel.idempotency_key == release_key
                )
            )
            if release_existing.scalars().first() is not None:
                return

            hold_result = await session.execute(
                future_select(OrganizationCreditLedgerModel).where(
                    OrganizationCreditLedgerModel.idempotency_key == hold_key
                )
            )
            hold = hold_result.scalars().first()
            if hold is None:
                return

            account = await self._locked_account(session, organization_id)
            release_amount = abs(float(hold.credits_delta or 0.0))
            new_balance = float(account.balance_credits or 0.0) + release_amount
            account.balance_credits = new_balance
            account.updated_at = datetime.now(UTC)
            session.add(
                OrganizationCreditLedgerModel(
                    organization_id=organization_id,
                    entry_type="adjustment",
                    origin="run_hold_release",
                    credits_delta=release_amount,
                    balance_after=new_balance,
                    workflow_run_id=workflow_run_id,
                    workflow_id=hold.workflow_id,
                    idempotency_key=release_key,
                    metadata_json={"released_hold_key": hold_key},
                    created_at=datetime.now(UTC),
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()

    async def settle_platform_usage(
        self,
        *,
        organization_id: int,
        workflow_run_id: int,
        workflow_id: int | None,
        credits: float,
        billable_minutes: float,
        metadata: dict[str, Any] | None = None,
    ) -> OrganizationCreditLedgerModel:
        """Release any run hold and apply the final platform usage debit without going negative."""
        usage_key = f"platform_usage:{workflow_run_id}"
        hold_key = f"run_hold:{workflow_run_id}"
        release_key = f"run_hold_release:{workflow_run_id}"

        async with self.async_session() as session:
            existing_usage = await session.execute(
                future_select(OrganizationCreditLedgerModel).where(
                    OrganizationCreditLedgerModel.idempotency_key == usage_key
                )
            )
            existing_entry = existing_usage.scalars().first()
            if existing_entry is not None:
                return existing_entry

            account = await self._locked_account(session, organization_id)
            balance = float(account.balance_credits or 0.0)

            hold_result = await session.execute(
                future_select(OrganizationCreditLedgerModel).where(
                    OrganizationCreditLedgerModel.idempotency_key == hold_key
                )
            )
            hold = hold_result.scalars().first()

            release_existing = await session.execute(
                future_select(OrganizationCreditLedgerModel).where(
                    OrganizationCreditLedgerModel.idempotency_key == release_key
                )
            )
            hold_already_released = release_existing.scalars().first() is not None

            if hold is not None and not hold_already_released:
                release_amount = abs(float(hold.credits_delta or 0.0))
                balance += release_amount
                session.add(
                    OrganizationCreditLedgerModel(
                        organization_id=organization_id,
                        entry_type="adjustment",
                        origin="run_hold_release",
                        credits_delta=release_amount,
                        balance_after=balance,
                        workflow_run_id=workflow_run_id,
                        workflow_id=workflow_id or hold.workflow_id,
                        idempotency_key=release_key,
                        metadata_json={"released_hold_key": hold_key},
                        created_at=datetime.now(UTC),
                    )
                )

            debit_amount = min(float(credits), max(balance, 0.0))
            new_balance = balance - debit_amount
            if new_balance < 0:
                new_balance = 0.0
                debit_amount = balance

            account.balance_credits = new_balance
            account.updated_at = datetime.now(UTC)
            entry = OrganizationCreditLedgerModel(
                organization_id=organization_id,
                entry_type="debit",
                origin="platform_usage",
                credits_delta=-debit_amount,
                balance_after=new_balance,
                metric_code="platform_usage",
                billable_quantity=billable_minutes,
                quantity_unit="minute",
                workflow_run_id=workflow_run_id,
                workflow_id=workflow_id,
                idempotency_key=usage_key,
                metadata_json={
                    **(metadata or {}),
                    "requested_credits": credits,
                    "debited_credits": debit_amount,
                },
                created_at=datetime.now(UTC),
            )
            session.add(entry)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await self.get_ledger_entry_by_idempotency_key(usage_key)
                if existing is not None:
                    return existing
                raise
            await session.refresh(entry)
            return entry

    async def get_paginated_ledger(
        self,
        organization_id: int,
        *,
        page: int,
        limit: int,
    ) -> tuple[list[OrganizationCreditLedgerModel], int, float]:
        await self.ensure_credit_account(organization_id)
        offset = (page - 1) * limit

        async with self.async_session() as session:
            total_count_result = await session.execute(
                select(func.count())
                .select_from(OrganizationCreditLedgerModel)
                .where(OrganizationCreditLedgerModel.organization_id == organization_id)
            )
            total_count = int(total_count_result.scalar() or 0)

            total_debits_result = await session.execute(
                select(
                    func.coalesce(
                        func.sum(OrganizationCreditLedgerModel.credits_delta), 0.0
                    )
                ).where(
                    OrganizationCreditLedgerModel.organization_id == organization_id,
                    OrganizationCreditLedgerModel.credits_delta < 0,
                    OrganizationCreditLedgerModel.origin == "platform_usage",
                )
            )
            total_debits = abs(float(total_debits_result.scalar() or 0.0))

            entries_result = await session.execute(
                future_select(OrganizationCreditLedgerModel)
                .where(OrganizationCreditLedgerModel.organization_id == organization_id)
                .order_by(
                    OrganizationCreditLedgerModel.created_at.desc(),
                    OrganizationCreditLedgerModel.id.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
            entries = list(entries_result.scalars().all())
            return entries, total_count, total_debits

    @staticmethod
    def billable_minutes(duration_seconds: float) -> int:
        if duration_seconds <= 0:
            return 0
        return max(1, math.ceil(duration_seconds / 60))
