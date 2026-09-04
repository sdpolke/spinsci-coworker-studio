"""Non-secret projections and bounded retention/capture policy helpers."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class CredentialProjection:
    credential_type: str
    reference_id: str
    last_updated_at: datetime


def project_credential(credential: Any) -> CredentialProjection:
    credential_type = getattr(credential.credential_type, "value", credential.credential_type)
    return CredentialProjection(
        credential_type=str(credential_type),
        reference_id=str(credential.credential_uuid),
        last_updated_at=credential.updated_at,
    )


@dataclass(frozen=True)
class RetentionPolicy:
    invocation_metadata_days: int
    external_identifier_days: int
    checkpoint_days: int
    payload_days: int
    capture_payloads: bool = False


def apply_retention_request(
    active: RetentionPolicy,
    requested: RetentionPolicy,
    *,
    minimum_days: int,
    maximum_days: int,
) -> RetentionPolicy:
    values = (
        requested.invocation_metadata_days,
        requested.external_identifier_days,
        requested.checkpoint_days,
        requested.payload_days,
    )
    if any(value < minimum_days or value > maximum_days for value in values):
        return active
    return requested


_GOVERNED_CONTENT_KEYS = frozenset(
    {
        "prompt",
        "prompt_text",
        "transcript",
        "transcript_text",
        "tool_arguments",
        "tool_args",
        "tool_result",
        "tool_results",
        "checkpoint",
        "checkpoint_contents",
        "payload",
        "request_payload",
        "response_payload",
    }
)


def persistence_projection(
    payload: Mapping[str, Any], *, capture_payloads: bool
) -> dict[str, Any]:
    """Keep operational metadata while recursively removing governed content."""
    if capture_payloads:
        return dict(payload)

    def sanitize(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                key: sanitize(item)
                for key, item in value.items()
                if key.lower() not in _GOVERNED_CONTENT_KEYS
            }
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        return value

    return sanitize(payload)


_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:authorization|credential|secret|token|api[_-]?key|password|prompt|transcript|tool[_-]?(?:arguments?|results?)|checkpoint(?:_reference|_contents)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CompiledPrivacyPolicy:
    """Immutable Workflow-Version policy used at transmission and persistence boundaries."""

    workflow_version_id: str
    allowed_fields: frozenset[str]
    redacted_fields: frozenset[str]
    replacement: str = "[REDACTED]"


def compile_privacy_policy(
    *,
    workflow_version_id: str,
    data_sharing_policy: Mapping[str, Any],
    redaction_policy: Mapping[str, Any],
    supported_fields: Sequence[str],
) -> CompiledPrivacyPolicy:
    if not workflow_version_id:
        raise ValueError("workflow_version_id is required")
    supported = frozenset(supported_fields)
    requested = data_sharing_policy.get("allow", ())
    redacted = redaction_policy.get("fields", ())
    if not isinstance(requested, (list, tuple, set, frozenset)) or not isinstance(
        redacted, (list, tuple, set, frozenset)
    ):
        raise TypeError("privacy policy fields must be collections")
    allowed_fields = frozenset(str(item) for item in requested)
    redacted_fields = frozenset(str(item) for item in redacted)
    if not allowed_fields <= supported:
        raise ValueError("data-sharing policy contains unsupported fields")
    if not redacted_fields <= supported:
        raise ValueError("redaction policy contains unsupported fields")
    replacement = redaction_policy.get("replacement", "[REDACTED]")
    if not isinstance(replacement, str) or not replacement or len(replacement) > 64:
        raise ValueError("redaction replacement must contain 1 to 64 characters")
    return CompiledPrivacyPolicy(
        workflow_version_id=workflow_version_id,
        allowed_fields=allowed_fields,
        redacted_fields=redacted_fields,
        replacement=replacement,
    )


def project_outbound_fields(
    payload: Mapping[str, Any], policy: CompiledPrivacyPolicy
) -> dict[str, Any]:
    """Allowlist first, then redact, so omitted data never reaches serialization."""
    projected = {key: payload[key] for key in policy.allowed_fields if key in payload}
    return {
        key: (policy.replacement if key in policy.redacted_fields else value)
        for key, value in projected.items()
    }


def redact_sensitive_data(value: Any, *, replacement: str = "[REDACTED]") -> Any:
    """Recursively redact sensitive keyed values before logs, traces, reports, or errors."""
    if isinstance(value, Mapping):
        return {
            str(key): (
                replacement
                if _SENSITIVE_KEY_PATTERN.search(str(key))
                else redact_sensitive_data(item, replacement=replacement)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_sensitive_data(item, replacement=replacement) for item in value[:100]]
    if isinstance(value, str) and len(value) > 512:
        return f"{value[:509]}..."
    return value


def governed_capture(
    *, payload: Mapping[str, Any], policy: CompiledPrivacyPolicy, capture_payloads: bool
) -> dict[str, Any]:
    """Apply the pinned redaction policy before the capture-off persistence projection."""
    redacted = redact_sensitive_data(payload, replacement=policy.replacement)
    return persistence_projection(redacted, capture_payloads=capture_payloads)
