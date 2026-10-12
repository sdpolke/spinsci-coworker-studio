"""What a span is allowed to record, and how much of it.

Tool calls on this platform carry patient data: names, dates of birth, phone
numbers, reasons for calling. A span that records its arguments verbatim ships
that to whatever backend tracing points at. So payload capture is off by
default and has to be turned on deliberately, per deployment.

Three settings, each doing one job:

``SPINSCI_TRACE_TOOL_PAYLOADS``
    Record tool arguments and results at all. Off by default. Turn it on in
    development, where the data is synthetic and seeing the actual arguments is
    the fastest way to find a bug.

``SPINSCI_TRACE_PAYLOAD_MAX_BYTES``
    Ceiling on any single captured payload. A slot search can return hundreds
    of entries; without a cap one span can be larger than the rest of the call
    put together, and tracing backends reject or truncate oversized spans in
    ways that lose the whole span rather than the payload.

``SPINSCI_TRACE_REDACT``
    Run captured payloads through the existing key-based redaction before they
    leave the process. On by default, and left on even in development: it
    costs nothing and it is the difference between a token appearing in a
    trace and not.

Sizes and counts are always recorded, whatever these are set to. Knowing a
result was 14KB, or that a call took 3.6 seconds, requires none of its content,
and those are the numbers a latency dashboard is built from.
"""

from __future__ import annotations

import json
import os
from typing import Any

from api.services.langgraph_integration.privacy import redact_sensitive_data


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


# Read once at import. These are deployment-level decisions, not per-request
# ones, and re-reading os.environ on every tool call would be a syscall in the
# hot path of a live conversation.
CAPTURE_PAYLOADS: bool = _flag("SPINSCI_TRACE_TOOL_PAYLOADS", default=False)
PAYLOAD_MAX_BYTES: int = _int("SPINSCI_TRACE_PAYLOAD_MAX_BYTES", default=4096)
REDACT_PAYLOADS: bool = _flag("SPINSCI_TRACE_REDACT", default=True)

_TRUNCATION_SUFFIX = "...[truncated]"


def payload_size(value: Any) -> int:
    """Serialised size in bytes, for recording without recording the content.

    Returns 0 rather than raising on anything unserialisable: a span attribute
    is never worth failing a tool call over.
    """
    try:
        if isinstance(value, (str, bytes)):
            return len(value)
        return len(json.dumps(value, default=str))
    except Exception:
        return 0


def prepare_payload(value: Any) -> str | None:
    """Render a payload for a span, or None when capture is disabled.

    Redacts first and truncates second. The other order would let a secret sit
    in the final bytes of a payload that was cut short before the redactor
    reached it.
    """
    if not CAPTURE_PAYLOADS:
        return None
    try:
        prepared = redact_sensitive_data(value) if REDACT_PAYLOADS else value
        text = prepared if isinstance(prepared, str) else json.dumps(prepared, default=str)
    except Exception:
        # Never let a payload we cannot serialise break the span, and never
        # fall back to repr() -- that is how unredacted objects leak.
        return "[unserialisable]"

    if len(text) <= PAYLOAD_MAX_BYTES:
        return text
    keep = max(PAYLOAD_MAX_BYTES - len(_TRUNCATION_SUFFIX), 0)
    return text[:keep] + _TRUNCATION_SUFFIX
