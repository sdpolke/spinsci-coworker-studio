"""Grant local credits to an organization by user email or organization id.

Requires LOCAL_CREDITS_ENABLED (default on for OSS/local deployments).

Usage (from repo root, with api/.env loaded)::

    source venv/bin/activate && set -a && source api/.env && set +a \\
        && python -m scripts.grant_credits --email user@example.com --credits 5000

    python -m scripts.grant_credits --organization-id 2 --amount-usd 50 \\
        --note "Support top-up"
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy.future import select

from api.constants import LOCAL_CREDITS_ENABLED
from api.db import db_client
from api.db.models import organization_users_association
from api.services import local_credits


async def _organization_ids_for_user(user_id: int) -> list[int]:
    async with db_client.async_session() as session:
        result = await session.execute(
            select(organization_users_association.c.organization_id).where(
                organization_users_association.c.user_id == user_id
            )
        )
        return [row[0] for row in result.all()]


async def _resolve_organization_id(
    *,
    email: str | None,
    organization_id: int | None,
) -> tuple[int, str]:
    if organization_id is not None:
        organization = await db_client.get_organization_by_id(organization_id)
        if organization is None:
            raise SystemExit(f"Organization {organization_id} not found")
        label = f"organization {organization_id}"
        return organization_id, label

    if not email:
        raise SystemExit("Provide --email or --organization-id")

    user = await db_client.get_user_by_email(email)
    if user is None:
        raise SystemExit(f"User not found: {email}")

    if user.selected_organization_id is not None:
        org_id = user.selected_organization_id
        label = f"{email} (selected org {org_id})"
        return org_id, label

    org_ids = await _organization_ids_for_user(user.id)
    if not org_ids:
        raise SystemExit(f"User {email} is not a member of any organization")

    if len(org_ids) == 1:
        org_id = org_ids[0]
        label = f"{email} (org {org_id})"
        return org_id, label

    org_list = ", ".join(str(org_id) for org_id in org_ids)
    raise SystemExit(
        f"User {email} has no selected organization. "
        f"Pass --organization-id (memberships: {org_list})"
    )


def _parse_credits(args: argparse.Namespace) -> float:
    if args.credits is None and args.amount_usd is None:
        raise SystemExit("Provide --credits or --amount-usd")
    if args.credits is not None and args.amount_usd is not None:
        raise SystemExit("Provide only one of --credits or --amount-usd")

    if args.credits is not None:
        return float(args.credits)
    assert args.amount_usd is not None
    return float(args.amount_usd) * 100


async def _grant(args: argparse.Namespace) -> None:
    if not LOCAL_CREDITS_ENABLED:
        raise SystemExit(
            "LOCAL_CREDITS_ENABLED is false for this deployment. "
            "Enable local credits in api/.env before using this script."
        )

    credits = _parse_credits(args)
    organization_id, target = await _resolve_organization_id(
        email=args.email,
        organization_id=args.organization_id,
    )

    balance_before = await db_client.get_credit_balance(organization_id)
    balance_after = await local_credits.grant_credits(
        organization_id,
        credits=credits,
        created_by="devops",
        note=args.note,
    )

    print(f"Target: {target}")
    print(f"Organization ID: {organization_id}")
    print(f"Credits granted: {credits:g}")
    print(f"Balance: {balance_before:g} -> {balance_after:g}")
    if args.note:
        print(f"Note: {args.note}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Grant local credits to a user's organization.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--email",
        help="User email; credits go to their selected organization",
    )
    target.add_argument(
        "--organization-id",
        type=int,
        help="Organization id to credit directly",
    )

    amount = parser.add_mutually_exclusive_group(required=True)
    amount.add_argument(
        "--credits",
        type=float,
        help="Credits to grant (1 credit = $0.01)",
    )
    amount.add_argument(
        "--amount-usd",
        type=float,
        help="USD amount to grant (converted at 100 credits per dollar)",
    )
    parser.add_argument(
        "--note",
        help="Optional ledger note",
    )

    args = parser.parse_args()
    try:
        asyncio.run(_grant(args))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
