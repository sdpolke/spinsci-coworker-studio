"""Organization-scoped persistence for the LangGraph integration domain."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import String, cast, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import (
    ExternalCredentialModel,
    LangGraphAcceptedEventModel,
    LangGraphCapabilitySnapshotModel,
    LangGraphCompatibilityMatrixModel,
    LangGraphEndpointRegistrationModel,
    LangGraphExternalIdentifierModel,
    LangGraphInvocationAttemptModel,
    LangGraphInvocationModel,
    LangGraphRetentionPolicyModel,
    LangGraphRolloutAlertModel,
    LangGraphRolloutStateModel,
    LangGraphRunObservationModel,
    LangGraphSecurityEventModel,
    LangGraphToolEffectModel,
    LangGraphValidationReportModel,
    LangGraphValidationResultModel,
    LangGraphVoiceRunBindingModel,
    WorkflowDefinitionModel,
    WorkflowModel,
    WorkflowRunModel,
)


class LangGraphEndpointClient(BaseDBClient):
    """All tenant-owned methods require organization_id explicitly."""

    async def create_langgraph_endpoint(
        self,
        *,
        organization_id: int,
        name: str,
        endpoint_url: str,
        credential_id: int,
        selected_profile: str,
        selected_capabilities: list[str],
        created_by: int | None,
    ) -> LangGraphEndpointRegistrationModel:
        async with self.async_session() as session:
            credential = await session.scalar(
                select(ExternalCredentialModel).where(
                    ExternalCredentialModel.id == credential_id,
                    ExternalCredentialModel.organization_id == organization_id,
                    ExternalCredentialModel.is_active.is_(True),
                )
            )
            if credential is None:
                raise PermissionError("credential is not owned by organization")
            endpoint = LangGraphEndpointRegistrationModel(
                organization_id=organization_id,
                name=name,
                endpoint_url=endpoint_url,
                credential_id=credential_id,
                selected_profile=selected_profile,
                selected_capabilities=selected_capabilities,
                created_by=created_by,
            )
            session.add(endpoint)
            await session.commit()
            await session.refresh(endpoint)
            return endpoint

    async def get_langgraph_endpoint(
        self, *, organization_id: int, endpoint_uuid: str
    ) -> LangGraphEndpointRegistrationModel | None:
        async with self.async_session() as session:
            return await session.scalar(
                select(LangGraphEndpointRegistrationModel).where(
                    LangGraphEndpointRegistrationModel.organization_id == organization_id,
                    LangGraphEndpointRegistrationModel.endpoint_uuid == endpoint_uuid,
                )
            )

    async def get_langgraph_endpoint_credential(
        self, *, organization_id: int, credential_id: int
    ) -> ExternalCredentialModel | None:
        """Resolve an endpoint's stored credential FK, scoped to its organization."""
        async with self.async_session() as session:
            return await session.scalar(
                select(ExternalCredentialModel).where(
                    ExternalCredentialModel.id == credential_id,
                    ExternalCredentialModel.organization_id == organization_id,
                )
            )

    async def list_langgraph_endpoints(
        self, *, organization_id: int
    ) -> list[LangGraphEndpointRegistrationModel]:
        async with self.async_session() as session:
            result = await session.scalars(
                select(LangGraphEndpointRegistrationModel)
                .where(LangGraphEndpointRegistrationModel.organization_id == organization_id)
                .order_by(LangGraphEndpointRegistrationModel.created_at.desc())
            )
            return list(result.all())

    async def compare_and_set_langgraph_lifecycle(
        self,
        *,
        organization_id: int,
        endpoint_uuid: str,
        expected_status: str,
        new_status: str,
    ) -> bool:
        values: dict[str, Any] = {
            "lifecycle_status": new_status,
            "updated_at": datetime.now(UTC),
        }
        if new_status == "retired":
            values["retired_at"] = datetime.now(UTC)
        async with self.async_session() as session:
            result = await session.execute(
                update(LangGraphEndpointRegistrationModel)
                .where(
                    LangGraphEndpointRegistrationModel.organization_id == organization_id,
                    LangGraphEndpointRegistrationModel.endpoint_uuid == endpoint_uuid,
                    LangGraphEndpointRegistrationModel.lifecycle_status == expected_status,
                )
                .values(**values)
            )
            await session.commit()
            return result.rowcount == 1

    async def insert_langgraph_capability_snapshot(
        self,
        *,
        organization_id: int,
        registration_id: int,
        manifest: dict[str, Any],
        manifest_digest: str,
        schema_version: str,
    ) -> tuple[LangGraphCapabilitySnapshotModel, bool]:
        async with self.async_session() as session:
            registration = await session.scalar(
                select(LangGraphEndpointRegistrationModel).where(
                    LangGraphEndpointRegistrationModel.id == registration_id,
                    LangGraphEndpointRegistrationModel.organization_id == organization_id,
                )
            )
            if registration is None:
                raise PermissionError("endpoint is not owned by organization")
            existing = await session.scalar(
                select(LangGraphCapabilitySnapshotModel).where(
                    LangGraphCapabilitySnapshotModel.organization_id == organization_id,
                    LangGraphCapabilitySnapshotModel.registration_id == registration_id,
                    LangGraphCapabilitySnapshotModel.manifest_digest == manifest_digest,
                )
            )
            if existing:
                changed = registration.current_capability_snapshot_id != existing.id
                if changed:
                    registration.current_capability_snapshot_id = existing.id
                    registration.current_validation_report_id = None
                    if registration.lifecycle_status != "retired":
                        registration.lifecycle_status = "pending_validation"
                    registration.updated_at = datetime.now(UTC)
                    await session.commit()
                return existing, changed
            changed = registration.current_capability_snapshot_id is not None
            snapshot = LangGraphCapabilitySnapshotModel(
                organization_id=organization_id,
                registration_id=registration_id,
                manifest=manifest,
                manifest_digest=manifest_digest,
                schema_version=schema_version,
            )
            session.add(snapshot)
            await session.flush()
            changed = registration.current_capability_snapshot_id is not None
            registration.current_capability_snapshot_id = snapshot.id
            if changed:
                registration.current_validation_report_id = None
                if registration.lifecycle_status != "retired":
                    registration.lifecycle_status = "pending_validation"
            registration.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(snapshot)
            return snapshot, changed

    async def insert_langgraph_validation_report(
        self,
        *,
        organization_id: int,
        registration_id: int,
        capability_snapshot_id: int | None,
        compatibility_matrix_id: int,
        suite_version: str,
        contract_version: str,
        selected_profile: str,
        status: str,
        started_at: datetime,
        completed_at: datetime | None,
        evidence: dict[str, Any],
        report_digest: str,
        results: list[dict[str, Any]],
    ) -> LangGraphValidationReportModel:
        async with self.async_session() as session:
            registration = await session.scalar(
                select(LangGraphEndpointRegistrationModel).where(
                    LangGraphEndpointRegistrationModel.id == registration_id,
                    LangGraphEndpointRegistrationModel.organization_id == organization_id,
                )
            )
            if registration is None:
                raise PermissionError("endpoint is not owned by organization")
            if capability_snapshot_id is not None:
                snapshot = await session.scalar(
                    select(LangGraphCapabilitySnapshotModel.id).where(
                        LangGraphCapabilitySnapshotModel.id == capability_snapshot_id,
                        LangGraphCapabilitySnapshotModel.organization_id == organization_id,
                        LangGraphCapabilitySnapshotModel.registration_id == registration_id,
                    )
                )
                if snapshot is None:
                    raise PermissionError("capability snapshot is not owned by endpoint")
            matrix = await session.scalar(
                select(LangGraphCompatibilityMatrixModel.id).where(
                    LangGraphCompatibilityMatrixModel.id == compatibility_matrix_id
                )
            )
            if matrix is None:
                raise ValueError("compatibility matrix does not exist")
            report = LangGraphValidationReportModel(
                organization_id=organization_id,
                registration_id=registration_id,
                capability_snapshot_id=capability_snapshot_id,
                compatibility_matrix_id=compatibility_matrix_id,
                suite_version=suite_version,
                contract_version=contract_version,
                selected_profile=selected_profile,
                status=status,
                started_at=started_at,
                completed_at=completed_at,
                evidence=evidence,
                report_digest=report_digest,
            )
            session.add(report)
            await session.flush()
            for item in results:
                session.add(
                    LangGraphValidationResultModel(
                        organization_id=organization_id,
                        report_id=report.id,
                        **item,
                    )
                )
            registration.current_validation_report_id = report.id
            if capability_snapshot_id is not None:
                registration.current_capability_snapshot_id = capability_snapshot_id
            if completed_at is not None:
                if status in {"failed", "incompatible"}:
                    registration.lifecycle_status = "incompatible"
                elif (
                    status in {"validation_only", "passed", "live_voice_eligible"}
                    and registration.lifecycle_status != "active"
                ):
                    registration.lifecycle_status = "validation_only"
            registration.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(report)
            return report

    async def create_langgraph_invocation(
        self,
        *,
        organization_id: int,
        run_binding_id: int,
        invocation_uuid: str,
        operation: str,
        mode: str,
        status: str = "pending",
        active_node_id: str | None = None,
        trace_id: str | None = None,
    ) -> LangGraphInvocationModel:
        async with self.async_session() as session:
            binding = await session.scalar(
                select(LangGraphVoiceRunBindingModel.id).where(
                    LangGraphVoiceRunBindingModel.id == run_binding_id,
                    LangGraphVoiceRunBindingModel.organization_id == organization_id,
                )
            )
            if binding is None:
                raise PermissionError("run binding is not owned by organization")
            invocation = LangGraphInvocationModel(
                invocation_uuid=invocation_uuid,
                organization_id=organization_id,
                run_binding_id=run_binding_id,
                operation=operation,
                mode=mode,
                status=status,
                active_node_id=active_node_id,
                trace_id=trace_id,
            )
            session.add(invocation)
            await session.commit()
            await session.refresh(invocation)
            return invocation

    async def record_langgraph_attempt(
        self,
        *,
        organization_id: int,
        invocation_id: int,
        attempt_uuid: str,
        ordinal: int,
        dispatched_at: datetime,
    ) -> tuple[LangGraphInvocationAttemptModel, bool]:
        return await self._insert_deduplicated(
            organization_id=organization_id,
            parent_id=invocation_id,
            model=LangGraphInvocationAttemptModel,
            lookup=(LangGraphInvocationAttemptModel.invocation_id == invocation_id, LangGraphInvocationAttemptModel.ordinal == ordinal),
            values={
                "attempt_uuid": attempt_uuid,
                "invocation_id": invocation_id,
                "ordinal": ordinal,
                "dispatched_at": dispatched_at,
            },
        )

    async def complete_langgraph_attempt(
        self,
        *,
        organization_id: int,
        invocation_id: int,
        ordinal: int,
        ended_at: datetime,
        http_status: int | None,
        transport_outcome: str,
        accepted_event: bool,
        error_category: str | None,
    ) -> bool:
        """Complete one tenant-scoped attempt without permitting cross-tenant writes."""
        async with self.async_session() as session:
            result = await session.execute(
                update(LangGraphInvocationAttemptModel)
                .where(
                    LangGraphInvocationAttemptModel.organization_id == organization_id,
                    LangGraphInvocationAttemptModel.invocation_id == invocation_id,
                    LangGraphInvocationAttemptModel.ordinal == ordinal,
                    LangGraphInvocationAttemptModel.ended_at.is_(None),
                )
                .values(
                    ended_at=ended_at,
                    http_status=http_status,
                    transport_outcome=transport_outcome,
                    accepted_event=accepted_event,
                    error_category=error_category,
                )
            )
            await session.commit()
            return result.rowcount == 1

    async def accept_langgraph_cancellation(
        self,
        *,
        organization_id: int,
        invocation_id: int,
        accepted_at: datetime,
    ) -> bool:
        """Atomically close forwarding eligibility for an active invocation."""
        async with self.async_session() as session:
            result = await session.execute(
                update(LangGraphInvocationModel)
                .where(
                    LangGraphInvocationModel.id == invocation_id,
                    LangGraphInvocationModel.organization_id == organization_id,
                    LangGraphInvocationModel.cancellation_accepted_at.is_(None),
                    LangGraphInvocationModel.terminal_at.is_(None),
                )
                .values(cancellation_accepted_at=accepted_at, status="cancelled")
            )
            await session.commit()
            return result.rowcount == 1

    async def claim_langgraph_terminal_outcome(
        self,
        *,
        organization_id: int,
        invocation_id: int,
        terminal_at: datetime,
        outcome: dict[str, Any],
        failure_action: str | None = None,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Persist one terminal outcome/action and return it on every replay."""
        stored = {"outcome": outcome, "failure_action": failure_action}
        async with self.async_session() as session:
            result = await session.execute(
                update(LangGraphInvocationModel)
                .where(
                    LangGraphInvocationModel.id == invocation_id,
                    LangGraphInvocationModel.organization_id == organization_id,
                    LangGraphInvocationModel.terminal_outcome.is_(None),
                )
                .values(
                    terminal_outcome=stored,
                    terminal_at=terminal_at,
                    status="terminal",
                )
            )
            await session.commit()
            invocation = await session.scalar(
                select(LangGraphInvocationModel).where(
                    LangGraphInvocationModel.id == invocation_id,
                    LangGraphInvocationModel.organization_id == organization_id,
                )
            )
            if invocation is None:
                raise PermissionError("invocation is not owned by organization")
            return invocation.terminal_outcome, result.rowcount == 1

    async def record_langgraph_event(
        self,
        *,
        organization_id: int,
        invocation_id: int,
        sequence: int,
        endpoint_event_id: str | None,
        event_type: str,
        payload_digest: str,
        metadata: dict[str, Any],
        mutation_outcome: str,
    ) -> tuple[LangGraphAcceptedEventModel, bool]:
        return await self._insert_deduplicated(
            organization_id=organization_id,
            parent_id=invocation_id,
            model=LangGraphAcceptedEventModel,
            lookup=(LangGraphAcceptedEventModel.invocation_id == invocation_id, LangGraphAcceptedEventModel.sequence == sequence),
            values={
                "invocation_id": invocation_id,
                "sequence": sequence,
                "endpoint_event_id": endpoint_event_id,
                "event_type": event_type,
                "payload_digest": payload_digest,
                "metadata_json": metadata,
                "mutation_outcome": mutation_outcome,
            },
        )

    async def record_langgraph_tool_effect(
        self,
        *,
        organization_id: int,
        invocation_id: int,
        tool_call_id: str,
        name: str,
        argument_digest: str,
        authorization_outcome: str,
        execution_status: str,
        cached_result: dict[str, Any] | None = None,
    ) -> tuple[LangGraphToolEffectModel, bool]:
        return await self._insert_deduplicated(
            organization_id=organization_id,
            parent_id=invocation_id,
            model=LangGraphToolEffectModel,
            lookup=(LangGraphToolEffectModel.invocation_id == invocation_id, LangGraphToolEffectModel.tool_call_id == tool_call_id),
            values={
                "invocation_id": invocation_id,
                "tool_call_id": tool_call_id,
                "name": name,
                "argument_digest": argument_digest,
                "authorization_outcome": authorization_outcome,
                "execution_status": execution_status,
                "cached_result": cached_result,
            },
        )

    async def complete_langgraph_tool_effect(
        self,
        *,
        organization_id: int,
        invocation_id: int,
        tool_call_id: str,
        result_digest: str,
        cached_result: dict[str, Any],
        transition_target: str | None = None,
    ) -> bool:
        """Complete only a tenant-owned, previously accepted effect."""
        async with self.async_session() as session:
            result = await session.execute(
                update(LangGraphToolEffectModel)
                .where(
                    LangGraphToolEffectModel.organization_id == organization_id,
                    LangGraphToolEffectModel.invocation_id == invocation_id,
                    LangGraphToolEffectModel.tool_call_id == tool_call_id,
                    LangGraphToolEffectModel.execution_status == "accepted",
                )
                .values(
                    execution_status="completed",
                    result_digest=result_digest,
                    cached_result=cached_result,
                    transition_target=transition_target,
                )
            )
            await session.commit()
            return result.rowcount == 1

    async def record_langgraph_run_observation(
        self,
        *,
        organization_id: int,
        workflow_run_id: int,
        invocation_id: int | None,
        observation_type: str,
        monotonic_order: int,
        observed_at_ms: int,
        runtime_sequence: int | None,
        attributes: dict[str, Any],
    ) -> tuple[LangGraphRunObservationModel, bool]:
        """Append one causally ordered observation after tenant/run validation."""
        async with self.async_session() as session:
            binding = await session.scalar(
                select(LangGraphVoiceRunBindingModel.id).where(
                    LangGraphVoiceRunBindingModel.organization_id == organization_id,
                    LangGraphVoiceRunBindingModel.workflow_run_id == workflow_run_id,
                )
            )
            if binding is None:
                raise PermissionError("workflow run binding is not owned by organization")
            if invocation_id is not None:
                invocation = await session.scalar(
                    select(LangGraphInvocationModel.id).where(
                        LangGraphInvocationModel.organization_id == organization_id,
                        LangGraphInvocationModel.id == invocation_id,
                        LangGraphInvocationModel.run_binding_id == binding,
                    )
                )
                if invocation is None:
                    raise PermissionError("invocation is not owned by workflow run")
            existing = await session.scalar(
                select(LangGraphRunObservationModel).where(
                    LangGraphRunObservationModel.organization_id == organization_id,
                    LangGraphRunObservationModel.workflow_run_id == workflow_run_id,
                    LangGraphRunObservationModel.monotonic_order == monotonic_order,
                )
            )
            if existing is not None:
                return existing, False
            latest = await session.scalar(
                select(LangGraphRunObservationModel)
                .where(
                    LangGraphRunObservationModel.organization_id == organization_id,
                    LangGraphRunObservationModel.workflow_run_id == workflow_run_id,
                )
                .order_by(LangGraphRunObservationModel.monotonic_order.desc())
                .limit(1)
            )
            if latest is not None and (
                monotonic_order <= latest.monotonic_order
                or observed_at_ms < latest.observed_at_ms
            ):
                raise ValueError("run observation must advance monotonic order and timestamp")
            row = LangGraphRunObservationModel(
                organization_id=organization_id,
                workflow_run_id=workflow_run_id,
                invocation_id=invocation_id,
                observation_type=observation_type,
                monotonic_order=monotonic_order,
                observed_at_ms=observed_at_ms,
                runtime_sequence=runtime_sequence,
                attributes=attributes,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row, True

    async def record_langgraph_security_event(
        self,
        *,
        organization_id: int,
        registration_id: int,
        workflow_run_id: int | None,
        invocation_id: int | None,
        tool_call_id: str | None,
        tool_name: str | None,
        violation_category: str,
        enforcement_decision: str,
        trace_id: str | None,
    ) -> LangGraphSecurityEventModel:
        """Append a tenant-scoped security event after validating its parents."""
        async with self.async_session() as session:
            registration = await session.scalar(
                select(LangGraphEndpointRegistrationModel.id).where(
                    LangGraphEndpointRegistrationModel.id == registration_id,
                    LangGraphEndpointRegistrationModel.organization_id == organization_id,
                )
            )
            if registration is None:
                raise PermissionError("endpoint registration is not owned by organization")
            if invocation_id is not None:
                invocation = await session.scalar(
                    select(LangGraphInvocationModel.id).where(
                        LangGraphInvocationModel.id == invocation_id,
                        LangGraphInvocationModel.organization_id == organization_id,
                    )
                )
                if invocation is None:
                    raise PermissionError("invocation is not owned by organization")
            row = LangGraphSecurityEventModel(
                organization_id=organization_id,
                registration_id=registration_id,
                workflow_run_id=workflow_run_id,
                invocation_id=invocation_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                violation_category=violation_category,
                enforcement_decision=enforcement_decision,
                trace_id=trace_id,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def persist_langgraph_endpoint_identifiers(
        self,
        *,
        organization_id: int,
        workflow_run_id: int,
        identifiers: dict[str, str],
        trace_id: str | None = None,
    ) -> bool:
        """Persist validated opaque identifiers only on the matching tenant/run binding."""
        allowed = {"thread_id", "external_run_id", "checkpoint_reference"}
        if not identifiers.keys() <= allowed or not all(
            isinstance(value, str) and 0 < len(value) <= 512 for value in identifiers.values()
        ):
            raise ValueError("invalid endpoint identifiers")
        if trace_id is not None and (len(trace_id) > 64 or not trace_id):
            raise ValueError("invalid trace identifier")
        async with self.async_session() as session:
            binding = await session.scalar(
                select(LangGraphVoiceRunBindingModel).where(
                    LangGraphVoiceRunBindingModel.organization_id == organization_id,
                    LangGraphVoiceRunBindingModel.workflow_run_id == workflow_run_id,
                )
            )
            if binding is None:
                raise PermissionError("workflow run binding is not owned by organization")
            binding.external_identifiers = {**(binding.external_identifiers or {}), **identifiers}
            if trace_id is not None:
                for identifier_type, opaque_value in identifiers.items():
                    existing = await session.scalar(
                        select(LangGraphExternalIdentifierModel.id).where(
                            LangGraphExternalIdentifierModel.organization_id == organization_id,
                            LangGraphExternalIdentifierModel.run_binding_id == binding.id,
                            LangGraphExternalIdentifierModel.identifier_type == identifier_type,
                            LangGraphExternalIdentifierModel.opaque_value == opaque_value,
                        )
                    )
                    if existing is None:
                        session.add(
                            LangGraphExternalIdentifierModel(
                                organization_id=organization_id,
                                run_binding_id=binding.id,
                                identifier_type=identifier_type,
                                opaque_value=opaque_value,
                                trace_id=trace_id,
                            )
                        )
            await session.commit()
            return True

    async def configure_langgraph_retention_policy(
        self,
        *,
        organization_id: int,
        invocation_metadata_days: int,
        external_identifier_days: int,
        checkpoint_days: int,
        payload_days: int,
        capture_payloads: bool,
        policy: dict[str, Any],
        updated_by: int | None,
        minimum_days: int,
        maximum_days: int,
    ) -> LangGraphRetentionPolicyModel:
        values = (
            invocation_metadata_days,
            external_identifier_days,
            checkpoint_days,
            payload_days,
        )
        if any(value < minimum_days or value > maximum_days for value in values):
            raise ValueError("retention period is outside deployment bounds")
        async with self.async_session() as session:
            row = await session.scalar(
                select(LangGraphRetentionPolicyModel).where(
                    LangGraphRetentionPolicyModel.organization_id == organization_id
                )
            )
            if row is None:
                row = LangGraphRetentionPolicyModel(organization_id=organization_id)
                session.add(row)
            row.invocation_metadata_days = invocation_metadata_days
            row.external_identifier_days = external_identifier_days
            row.checkpoint_days = checkpoint_days
            row.payload_days = payload_days
            row.capture_payloads = capture_payloads
            row.policy = policy
            row.updated_by = updated_by
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return row

    async def list_langgraph_retention_organizations(self) -> list[int]:
        async with self.async_session() as session:
            return list(
                (
                    await session.scalars(
                        select(LangGraphRetentionPolicyModel.organization_id).order_by(
                            LangGraphRetentionPolicyModel.organization_id
                        )
                    )
                ).all()
            )

    async def sweep_langgraph_retention(
        self, *, organization_id: int, now: datetime
    ) -> dict[str, int]:
        """Idempotently expire one tenant's governed data while retaining operational evidence."""
        async with self.async_session() as session:
            policy = await session.scalar(
                select(LangGraphRetentionPolicyModel).where(
                    LangGraphRetentionPolicyModel.organization_id == organization_id
                )
            )
            if policy is None:
                return {"bindings_anonymized": 0, "payloads_anonymized": 0, "invocations_deleted": 0}

            identifier_cutoff = now - timedelta(days=policy.external_identifier_days)
            bindings = list(
                (
                    await session.scalars(
                        select(LangGraphVoiceRunBindingModel).where(
                            LangGraphVoiceRunBindingModel.organization_id == organization_id,
                            LangGraphVoiceRunBindingModel.created_at <= identifier_cutoff,
                        )
                    )
                ).all()
            )
            binding_count = 0
            for binding in bindings:
                identifiers = binding.external_identifiers or {}
                if identifiers:
                    binding.external_identifiers = {
                        key: (
                            value
                            if key in {"checkpoint_reference", "checkpoint"}
                            else "[EXPIRED]"
                        )
                        for key, value in identifiers.items()
                    }
                    binding_count += 1

            external_identifier_rows = list(
                (
                    await session.scalars(
                        select(LangGraphExternalIdentifierModel).where(
                            LangGraphExternalIdentifierModel.organization_id == organization_id,
                            LangGraphExternalIdentifierModel.created_at <= identifier_cutoff,
                        )
                    )
                ).all()
            )
            for identifier in external_identifier_rows:
                await session.delete(identifier)

            checkpoint_cutoff = now - timedelta(days=policy.checkpoint_days)
            for binding in bindings:
                if binding.created_at <= checkpoint_cutoff and any(
                    key in (binding.external_identifiers or {})
                    for key in ("checkpoint_reference", "checkpoint")
                ):
                    binding.external_identifiers = {
                        **(binding.external_identifiers or {}),
                        "checkpoint_reference": "[EXPIRED]",
                    }

            payload_cutoff = now - timedelta(days=policy.payload_days)
            events = list(
                (
                    await session.scalars(
                        select(LangGraphAcceptedEventModel).where(
                            LangGraphAcceptedEventModel.organization_id == organization_id,
                            LangGraphAcceptedEventModel.accepted_at <= payload_cutoff,
                        )
                    )
                ).all()
            )
            payload_count = 0
            for event in events:
                if event.metadata_json:
                    event.metadata_json = {"retention_status": "expired"}
                    payload_count += 1
            tools = list(
                (
                    await session.scalars(
                        select(LangGraphToolEffectModel).where(
                            LangGraphToolEffectModel.organization_id == organization_id,
                            LangGraphToolEffectModel.created_at <= payload_cutoff,
                        )
                    )
                ).all()
            )
            for tool in tools:
                if tool.cached_result is not None:
                    tool.cached_result = None
                    payload_count += 1
            reports = list(
                (
                    await session.scalars(
                        select(LangGraphValidationReportModel).where(
                            LangGraphValidationReportModel.organization_id == organization_id,
                            LangGraphValidationReportModel.created_at <= payload_cutoff,
                        )
                    )
                ).all()
            )
            for report in reports:
                if report.evidence:
                    report.evidence = {"retention_status": "expired", "report_digest": report.report_digest}
                    payload_count += 1

            invocation_cutoff = now - timedelta(days=policy.invocation_metadata_days)
            stale_invocations = list(
                (
                    await session.scalars(
                        select(LangGraphInvocationModel).where(
                            LangGraphInvocationModel.organization_id == organization_id,
                            LangGraphInvocationModel.created_at <= invocation_cutoff,
                        )
                    )
                ).all()
            )
            for invocation in stale_invocations:
                await session.delete(invocation)
            await session.commit()
            return {
                "bindings_anonymized": binding_count,
                "payloads_anonymized": payload_count,
                "invocations_deleted": len(stale_invocations),
            }

    async def get_langgraph_rollout_state(
        self, *, organization_id: int
    ) -> LangGraphRolloutStateModel | None:
        async with self.async_session() as session:
            return await session.scalar(
                select(LangGraphRolloutStateModel).where(
                    LangGraphRolloutStateModel.organization_id == organization_id
                )
            )

    async def upsert_langgraph_rollout_state(
        self,
        *,
        organization_id: int,
        feature_enabled: bool,
        experimental_acknowledged_at: datetime | None,
        experimental_acknowledged_by: int | None,
        rollout_stage: str,
        internal_tenant_ids: list[int],
        allowlisted_tenant_ids: list[int],
        percentage_cohort: int,
        cohort_salt: str,
        private_network_enabled: bool,
        private_network_decided_at: datetime | None,
        private_network_decided_by: int | None,
        changed_at: datetime,
    ) -> LangGraphRolloutStateModel:
        """Persist the tenant-scoped runtime gate used when creating new runs."""
        async with self.async_session() as session:
            state = await session.scalar(
                select(LangGraphRolloutStateModel).where(
                    LangGraphRolloutStateModel.organization_id == organization_id
                )
            )
            if state is None:
                state = LangGraphRolloutStateModel(organization_id=organization_id)
                session.add(state)
            state.feature_enabled = feature_enabled
            state.disabled_at = None if feature_enabled else state.disabled_at or changed_at
            state.experimental_acknowledged_at = experimental_acknowledged_at
            state.experimental_acknowledged_by = experimental_acknowledged_by
            state.rollout_stage = rollout_stage
            state.internal_tenant_ids = sorted(set(internal_tenant_ids))
            state.allowlisted_tenant_ids = sorted(set(allowlisted_tenant_ids))
            state.percentage_cohort = percentage_cohort
            state.cohort_salt = cohort_salt
            state.private_network_enabled = private_network_enabled
            state.private_network_decided_at = private_network_decided_at
            state.private_network_decided_by = private_network_decided_by
            state.updated_at = changed_at
            await session.commit()
            await session.refresh(state)
            return state

    async def record_langgraph_rollout_evaluation(
        self,
        *,
        organization_id: int,
        evaluated_at: datetime,
        halt_expansion: bool,
        alert_payload: dict[str, Any] | None,
    ) -> tuple[LangGraphRolloutStateModel, bool]:
        """Persist a gate decision and deduplicate its tenant-scoped operator alert."""
        async with self.async_session() as session:
            state = await session.scalar(
                select(LangGraphRolloutStateModel).where(
                    LangGraphRolloutStateModel.organization_id == organization_id
                )
            )
            if state is None:
                raise ValueError("LangGraph rollout state is not configured")
            state.last_evaluated_at = evaluated_at
            state.expansion_halted = halt_expansion
            state.expansion_halted_at = evaluated_at if halt_expansion else None
            alert_inserted = False
            if alert_payload is not None:
                lookup = (
                    LangGraphRolloutAlertModel.organization_id == organization_id,
                    LangGraphRolloutAlertModel.rollout_stage == alert_payload["stage"],
                    LangGraphRolloutAlertModel.evaluation_ended_at
                    == alert_payload["evaluation_ended_at"],
                    LangGraphRolloutAlertModel.reason == alert_payload["reason"],
                )
                existing = await session.scalar(
                    select(LangGraphRolloutAlertModel).where(*lookup)
                )
                if existing is None:
                    serialized_payload = {
                        **alert_payload,
                        "evaluation_started_at": alert_payload[
                            "evaluation_started_at"
                        ].isoformat(),
                        "evaluation_ended_at": alert_payload[
                            "evaluation_ended_at"
                        ].isoformat(),
                    }
                    alert = LangGraphRolloutAlertModel(
                        organization_id=organization_id,
                        rollout_stage=alert_payload["stage"],
                        evaluation_started_at=alert_payload["evaluation_started_at"],
                        evaluation_ended_at=alert_payload["evaluation_ended_at"],
                        reason=alert_payload["reason"],
                        payload=serialized_payload,
                    )
                    try:
                        async with session.begin_nested():
                            session.add(alert)
                            await session.flush()
                        alert_inserted = True
                    except IntegrityError:
                        alert_inserted = False
            await session.commit()
            await session.refresh(state)
            return state, alert_inserted

    async def _insert_deduplicated(
        self, *, organization_id: int, parent_id: int, model, lookup: tuple, values: dict[str, Any]
    ):
        async with self.async_session() as session:
            invocation = await session.scalar(
                select(LangGraphInvocationModel.id).where(
                    LangGraphInvocationModel.id == parent_id,
                    LangGraphInvocationModel.organization_id == organization_id,
                )
            )
            if invocation is None:
                raise PermissionError("invocation is not owned by organization")
            existing = await session.scalar(
                select(model).where(model.organization_id == organization_id, *lookup)
            )
            if existing:
                return existing, False
            row = model(organization_id=organization_id, **values)
            try:
                async with session.begin_nested():
                    session.add(row)
                    await session.flush()
            except IntegrityError:
                existing = await session.scalar(
                    select(model).where(model.organization_id == organization_id, *lookup)
                )
                if existing is None:
                    raise
                return existing, False
            await session.commit()
            await session.refresh(row)
            return row, True

    async def retire_or_delete_langgraph_endpoint(
        self, *, organization_id: int, endpoint_uuid: str
    ) -> str | None:
        async with self.async_session() as session:
            endpoint = await session.scalar(
                select(LangGraphEndpointRegistrationModel).where(
                    LangGraphEndpointRegistrationModel.organization_id == organization_id,
                    LangGraphEndpointRegistrationModel.endpoint_uuid == endpoint_uuid,
                )
            )
            if endpoint is None:
                return None
            binding_exists = await session.scalar(
                select(LangGraphVoiceRunBindingModel.id).where(
                    LangGraphVoiceRunBindingModel.organization_id == organization_id,
                    LangGraphVoiceRunBindingModel.registration_id == endpoint.id,
                ).limit(1)
            )
            definition_exists = await session.scalar(
                select(WorkflowDefinitionModel.id)
                .join(
                    WorkflowModel,
                    WorkflowModel.id == WorkflowDefinitionModel.workflow_id,
                )
                .where(
                    WorkflowModel.organization_id == organization_id,
                    cast(
                        WorkflowDefinitionModel.workflow_configurations, String
                    ).contains(endpoint_uuid),
                )
                .limit(1)
            )
            if binding_exists or definition_exists:
                endpoint.lifecycle_status = "retired"
                endpoint.retired_at = datetime.now(UTC)
                endpoint.updated_at = datetime.now(UTC)
                outcome = "retired"
            else:
                await session.delete(endpoint)
                outcome = "deleted"
            await session.commit()
            return outcome

    async def get_langgraph_endpoint_management_view(
        self, *, organization_id: int, endpoint_uuid: str
    ) -> tuple[
        LangGraphEndpointRegistrationModel,
        ExternalCredentialModel,
        LangGraphCapabilitySnapshotModel | None,
        LangGraphValidationReportModel | None,
    ] | None:
        """Load an endpoint and its non-secret management metadata in one scope."""
        async with self.async_session() as session:
            endpoint = await session.scalar(
                select(LangGraphEndpointRegistrationModel).where(
                    LangGraphEndpointRegistrationModel.organization_id == organization_id,
                    LangGraphEndpointRegistrationModel.endpoint_uuid == endpoint_uuid,
                )
            )
            if endpoint is None:
                return None
            credential = await session.scalar(
                select(ExternalCredentialModel).where(
                    ExternalCredentialModel.id == endpoint.credential_id,
                    ExternalCredentialModel.organization_id == organization_id,
                )
            )
            if credential is None:
                raise RuntimeError("endpoint credential reference is unavailable")
            snapshot = None
            if endpoint.current_capability_snapshot_id is not None:
                snapshot = await session.scalar(
                    select(LangGraphCapabilitySnapshotModel).where(
                        LangGraphCapabilitySnapshotModel.id
                        == endpoint.current_capability_snapshot_id,
                        LangGraphCapabilitySnapshotModel.organization_id
                        == organization_id,
                        LangGraphCapabilitySnapshotModel.registration_id == endpoint.id,
                    )
                )
            report = None
            if endpoint.current_validation_report_id is not None:
                report = await session.scalar(
                    select(LangGraphValidationReportModel).where(
                        LangGraphValidationReportModel.id
                        == endpoint.current_validation_report_id,
                        LangGraphValidationReportModel.organization_id
                        == organization_id,
                        LangGraphValidationReportModel.registration_id == endpoint.id,
                    )
                )
            return endpoint, credential, snapshot, report

    async def list_langgraph_endpoint_management_views(
        self, *, organization_id: int
    ) -> list[
        tuple[
            LangGraphEndpointRegistrationModel,
            ExternalCredentialModel,
            LangGraphCapabilitySnapshotModel | None,
            LangGraphValidationReportModel | None,
        ]
    ]:
        endpoints = await self.list_langgraph_endpoints(organization_id=organization_id)
        views = []
        for endpoint in endpoints:
            view = await self.get_langgraph_endpoint_management_view(
                organization_id=organization_id,
                endpoint_uuid=endpoint.endpoint_uuid,
            )
            if view is not None:
                views.append(view)
        return views

    async def update_langgraph_endpoint(
        self,
        *,
        organization_id: int,
        endpoint_uuid: str,
        name: str | None = None,
        endpoint_url: str | None = None,
        credential_uuid: str | None = None,
        selected_profile: str | None = None,
        selected_capabilities: list[str] | None = None,
    ) -> LangGraphEndpointRegistrationModel | None:
        """Update mutable metadata and invalidate behavioral validation atomically."""
        async with self.async_session() as session:
            endpoint = await session.scalar(
                select(LangGraphEndpointRegistrationModel).where(
                    LangGraphEndpointRegistrationModel.organization_id == organization_id,
                    LangGraphEndpointRegistrationModel.endpoint_uuid == endpoint_uuid,
                )
            )
            if endpoint is None:
                return None
            if endpoint.lifecycle_status == "retired":
                raise ValueError("retired endpoints are immutable")

            behavior_changed = False
            if name is not None:
                endpoint.name = name
            if endpoint_url is not None and endpoint_url != endpoint.endpoint_url:
                endpoint.endpoint_url = endpoint_url
                behavior_changed = True
            if credential_uuid is not None:
                credential = await session.scalar(
                    select(ExternalCredentialModel).where(
                        ExternalCredentialModel.credential_uuid == credential_uuid,
                        ExternalCredentialModel.organization_id == organization_id,
                        ExternalCredentialModel.is_active.is_(True),
                    )
                )
                if credential is None:
                    raise PermissionError("credential is not owned by organization")
                if endpoint.credential_id != credential.id:
                    endpoint.credential_id = credential.id
                    behavior_changed = True
            if selected_profile is not None and selected_profile != endpoint.selected_profile:
                endpoint.selected_profile = selected_profile
                behavior_changed = True
            if (
                selected_capabilities is not None
                and selected_capabilities != endpoint.selected_capabilities
            ):
                endpoint.selected_capabilities = selected_capabilities
                behavior_changed = True
            if behavior_changed:
                endpoint.lifecycle_status = "pending_validation"
                endpoint.current_validation_report_id = None
            endpoint.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(endpoint)
            return endpoint

    async def list_langgraph_validation_history(
        self, *, organization_id: int, endpoint_uuid: str
    ) -> list[
        tuple[
            LangGraphValidationReportModel,
            LangGraphCapabilitySnapshotModel | None,
            LangGraphCompatibilityMatrixModel,
            list[LangGraphValidationResultModel],
        ]
    ] | None:
        async with self.async_session() as session:
            endpoint = await session.scalar(
                select(LangGraphEndpointRegistrationModel).where(
                    LangGraphEndpointRegistrationModel.organization_id == organization_id,
                    LangGraphEndpointRegistrationModel.endpoint_uuid == endpoint_uuid,
                )
            )
            if endpoint is None:
                return None
            reports = list(
                (
                    await session.scalars(
                        select(LangGraphValidationReportModel)
                        .where(
                            LangGraphValidationReportModel.organization_id
                            == organization_id,
                            LangGraphValidationReportModel.registration_id == endpoint.id,
                        )
                        .order_by(LangGraphValidationReportModel.created_at.desc())
                    )
                ).all()
            )
            history = []
            for report in reports:
                snapshot = None
                if report.capability_snapshot_id is not None:
                    snapshot = await session.scalar(
                        select(LangGraphCapabilitySnapshotModel).where(
                            LangGraphCapabilitySnapshotModel.id
                            == report.capability_snapshot_id,
                            LangGraphCapabilitySnapshotModel.organization_id
                            == organization_id,
                        )
                    )
                matrix = await session.scalar(
                    select(LangGraphCompatibilityMatrixModel).where(
                        LangGraphCompatibilityMatrixModel.id
                        == report.compatibility_matrix_id
                    )
                )
                if matrix is None:
                    raise RuntimeError("validation report matrix is unavailable")
                results = list(
                    (
                        await session.scalars(
                            select(LangGraphValidationResultModel)
                            .where(
                                LangGraphValidationResultModel.organization_id
                                == organization_id,
                                LangGraphValidationResultModel.report_id == report.id,
                            )
                            .order_by(LangGraphValidationResultModel.id)
                        )
                    ).all()
                )
                history.append((report, snapshot, matrix, results))
            return history

    async def list_langgraph_compatibility_matrices(
        self,
    ) -> list[LangGraphCompatibilityMatrixModel]:
        async with self.async_session() as session:
            return list(
                (
                    await session.scalars(
                        select(LangGraphCompatibilityMatrixModel).order_by(
                            LangGraphCompatibilityMatrixModel.effective_at.desc(),
                            LangGraphCompatibilityMatrixModel.published_at.desc(),
                        )
                    )
                ).all()
            )

    async def get_current_langgraph_activation_evidence(
        self, *, organization_id: int, endpoint_uuid: str
    ) -> tuple[
        LangGraphEndpointRegistrationModel,
        LangGraphValidationReportModel | None,
        LangGraphCapabilitySnapshotModel | None,
    ] | None:
        view = await self.get_langgraph_endpoint_management_view(
            organization_id=organization_id, endpoint_uuid=endpoint_uuid
        )
        if view is None:
            return None
        endpoint, _, snapshot, report = view
        return endpoint, report, snapshot

    async def get_langgraph_run_diagnostics(
        self, *, organization_id: int, workflow_run_id: int
    ) -> tuple[Any, Any, Any, list[Any], list[Any], list[Any], list[Any], list[Any], list[Any], list[Any]] | None:
        """Load every diagnostic record through a tenant-scoped run binding."""
        async with self.async_session() as session:
            row = (
                await session.execute(
                    select(
                        WorkflowRunModel,
                        LangGraphVoiceRunBindingModel,
                        LangGraphEndpointRegistrationModel,
                    )
                    .join(WorkflowModel, WorkflowRunModel.workflow_id == WorkflowModel.id)
                    .join(
                        LangGraphVoiceRunBindingModel,
                        LangGraphVoiceRunBindingModel.workflow_run_id == WorkflowRunModel.id,
                    )
                    .join(
                        LangGraphEndpointRegistrationModel,
                        LangGraphEndpointRegistrationModel.id
                        == LangGraphVoiceRunBindingModel.registration_id,
                    )
                    .where(
                        WorkflowRunModel.id == workflow_run_id,
                        WorkflowModel.organization_id == organization_id,
                        LangGraphVoiceRunBindingModel.organization_id == organization_id,
                        LangGraphEndpointRegistrationModel.organization_id == organization_id,
                    )
                )
            ).first()
            if row is None:
                return None
            run, binding, registration = row
            external_identifier_rows = list(
                (
                    await session.scalars(
                        select(LangGraphExternalIdentifierModel)
                        .where(
                            LangGraphExternalIdentifierModel.organization_id == organization_id,
                            LangGraphExternalIdentifierModel.run_binding_id == binding.id,
                        )
                        .order_by(LangGraphExternalIdentifierModel.created_at, LangGraphExternalIdentifierModel.id)
                    )
                ).all()
            )
            invocations = list(
                (
                    await session.scalars(
                        select(LangGraphInvocationModel)
                        .where(
                            LangGraphInvocationModel.organization_id == organization_id,
                            LangGraphInvocationModel.run_binding_id == binding.id,
                        )
                        .order_by(LangGraphInvocationModel.created_at, LangGraphInvocationModel.id)
                    )
                ).all()
            )
            invocation_ids = [invocation.id for invocation in invocations]
            if not invocation_ids:
                observations = list(
                    (
                        await session.scalars(
                            select(LangGraphRunObservationModel)
                            .where(
                                LangGraphRunObservationModel.organization_id == organization_id,
                                LangGraphRunObservationModel.workflow_run_id == workflow_run_id,
                            )
                            .order_by(LangGraphRunObservationModel.monotonic_order)
                        )
                    ).all()
                )
                security_events = list(
                    (
                        await session.scalars(
                            select(LangGraphSecurityEventModel)
                            .where(
                                LangGraphSecurityEventModel.organization_id == organization_id,
                                LangGraphSecurityEventModel.workflow_run_id == workflow_run_id,
                            )
                            .order_by(LangGraphSecurityEventModel.created_at, LangGraphSecurityEventModel.id)
                        )
                    ).all()
                )
                return run, binding, registration, invocations, [], [], [], observations, security_events, external_identifier_rows
            attempts = list(
                (
                    await session.scalars(
                        select(LangGraphInvocationAttemptModel)
                        .where(
                            LangGraphInvocationAttemptModel.organization_id == organization_id,
                            LangGraphInvocationAttemptModel.invocation_id.in_(invocation_ids),
                        )
                        .order_by(
                            LangGraphInvocationAttemptModel.dispatched_at,
                            LangGraphInvocationAttemptModel.id,
                        )
                    )
                ).all()
            )
            events = list(
                (
                    await session.scalars(
                        select(LangGraphAcceptedEventModel)
                        .where(
                            LangGraphAcceptedEventModel.organization_id == organization_id,
                            LangGraphAcceptedEventModel.invocation_id.in_(invocation_ids),
                        )
                        .order_by(
                            LangGraphAcceptedEventModel.accepted_at,
                            LangGraphAcceptedEventModel.sequence,
                        )
                    )
                ).all()
            )
            tools = list(
                (
                    await session.scalars(
                        select(LangGraphToolEffectModel)
                        .where(
                            LangGraphToolEffectModel.organization_id == organization_id,
                            LangGraphToolEffectModel.invocation_id.in_(invocation_ids),
                        )
                        .order_by(
                            LangGraphToolEffectModel.created_at,
                            LangGraphToolEffectModel.id,
                        )
                    )
                ).all()
            )
            observations = list(
                (
                    await session.scalars(
                        select(LangGraphRunObservationModel)
                        .where(
                            LangGraphRunObservationModel.organization_id == organization_id,
                            LangGraphRunObservationModel.workflow_run_id == workflow_run_id,
                        )
                        .order_by(LangGraphRunObservationModel.monotonic_order)
                    )
                ).all()
            )
            security_events = list(
                (
                    await session.scalars(
                        select(LangGraphSecurityEventModel)
                        .where(
                            LangGraphSecurityEventModel.organization_id == organization_id,
                            LangGraphSecurityEventModel.workflow_run_id == workflow_run_id,
                        )
                        .order_by(LangGraphSecurityEventModel.created_at, LangGraphSecurityEventModel.id)
                    )
                ).all()
            )
            return run, binding, registration, invocations, attempts, events, tools, observations, security_events, external_identifier_rows
