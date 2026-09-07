"""Publish endpoint-orchestrated LangGraph compatibility matrix.

Revision ID: a7c1e4d9b2f0
Revises: 9fceb739ca1a
Create Date: 2026-09-07 00:00:00.000000
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "a7c1e4d9b2f0"
down_revision: str | None = "9fceb739ca1a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MATRIX_UUID = "aa6c4715-3217-588a-a000-546cbf64d860"
_MATRIX_VERSION = "2026-02"
_EFFECTIVE_AT = datetime(2026, 2, 15, tzinfo=UTC)
_MURAL_RELEASE_VERSION = "1.44.0"
_PUBLISHED_AT = datetime(2026, 2, 15, tzinfo=UTC)
_MATRIX: dict[str, Any] = {
    "effective_date": "2026-02-15",
    "limitations": [
        "The integration is experimental.",
        "Realtime speech-to-speech workflows bypass the text integration.",
        "Compatibility is based on contract behavior, not a specific LangGraph package version.",
    ],
    "matrix_version": "2026-02",
    "mural_release_version": "1.44.0",
    "profiles": [
        {
            "allowed_state_modes": ["mural_authoritative"],
            "limitations": [
                "Live voice requires streaming mode.",
                "The endpoint receives chat-oriented requests, never raw audio or Pipecat processors.",
            ],
            "profile": "chat",
            "required_features": [],
            "required_invocation_modes": ["streaming"],
        },
        {
            "allowed_state_modes": ["endpoint_checkpointed"],
            "limitations": [
                "The endpoint owns graph orchestration and checkpoint state.",
                "Interrupt and resume behavior is optional and must be selected explicitly.",
            ],
            "profile": "stateful_run",
            "required_features": [],
            "required_invocation_modes": ["streaming"],
        },
    ],
    "supported_contract_versions": ["1.0", "1.1", "1.2"],
}

_MATRICES = sa.table(
    "langgraph_compatibility_matrices",
    sa.column("id", sa.Integer()),
    sa.column("matrix_uuid", sa.String()),
    sa.column("matrix_version", sa.String()),
    sa.column("effective_at", sa.DateTime(timezone=True)),
    sa.column("mural_release_version", sa.String()),
    sa.column("matrix", sa.JSON()),
    sa.column("published_at", sa.DateTime(timezone=True)),
)
_REPORTS = sa.table(
    "langgraph_validation_reports",
    sa.column("compatibility_matrix_id", sa.Integer()),
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _find_existing(bind: sa.Connection) -> list[sa.Row[Any]]:
    return list(
        bind.execute(
            sa.select(_MATRICES).where(
                sa.or_(
                    _MATRICES.c.matrix_version == _MATRIX_VERSION,
                    _MATRICES.c.matrix_uuid == _MATRIX_UUID,
                )
            )
        )
    )


def _mismatches(row: sa.Row[Any]) -> list[str]:
    actual = row._mapping
    expected = {
        "matrix_uuid": _MATRIX_UUID,
        "matrix_version": _MATRIX_VERSION,
        "effective_at": _EFFECTIVE_AT,
        "mural_release_version": _MURAL_RELEASE_VERSION,
        "matrix": _MATRIX,
        "published_at": _PUBLISHED_AT,
    }
    mismatches: list[str] = []
    for field, expected_value in expected.items():
        actual_value = actual[field]
        if isinstance(expected_value, datetime):
            actual_value = _utc(actual_value)
        if actual_value != expected_value:
            mismatches.append(field)
    return mismatches


def upgrade() -> None:
    bind = op.get_bind()
    existing = _find_existing(bind)
    if not existing:
        bind.execute(
            _MATRICES.insert().values(
                matrix_uuid=_MATRIX_UUID,
                matrix_version=_MATRIX_VERSION,
                effective_at=_EFFECTIVE_AT,
                mural_release_version=_MURAL_RELEASE_VERSION,
                matrix=_MATRIX,
                published_at=_PUBLISHED_AT,
            )
        )
        return
    if len(existing) != 1:
        raise RuntimeError(
            "endpoint-orchestrated LangGraph matrix UUID and version identify different rows"
        )
    mismatches = _mismatches(existing[0])
    if mismatches:
        raise RuntimeError(
            "existing LangGraph compatibility matrix 2026-02 conflicts with the "
            f"canonical release artifact in fields: {', '.join(mismatches)}"
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = _find_existing(bind)
    if not existing:
        return
    if len(existing) != 1:
        raise RuntimeError(
            "cannot remove endpoint-orchestrated LangGraph matrix: UUID and version identify different rows"
        )
    row = existing[0]
    mismatches = _mismatches(row)
    if mismatches:
        raise RuntimeError(
            "cannot remove non-canonical LangGraph matrix during downgrade; "
            f"conflicting fields: {', '.join(mismatches)}"
        )
    report_count = bind.scalar(
        sa.select(sa.func.count())
        .select_from(_REPORTS)
        .where(_REPORTS.c.compatibility_matrix_id == row._mapping["id"])
    )
    if report_count:
        raise RuntimeError(
            "cannot remove endpoint-orchestrated LangGraph matrix while validation reports reference it"
        )
    bind.execute(
        _MATRICES.delete().where(
            sa.and_(
                _MATRICES.c.matrix_uuid == _MATRIX_UUID,
                _MATRICES.c.matrix_version == _MATRIX_VERSION,
            )
        )
    )
