"""Executable probes for SpinSci-owned cancellation and recording boundaries."""

from __future__ import annotations

import io
import time
import wave
from dataclasses import dataclass
from typing import Any

from api.services.langgraph_integration.protocol import CancellationState
from api.services.pipecat.in_memory_buffers import InMemoryRecordingBuffers
from api.services.workflow_run_artifacts import persist_workflow_run_artifacts

from .evidence import EligibilityCheckResult


@dataclass(frozen=True)
class PlatformEvidence:
    cancellation_verified: bool
    recording_verified: bool
    checks: tuple[EligibilityCheckResult, ...]


def _wav_valid(data: bytes, *, expected_frames: int) -> bool:
    with wave.open(io.BytesIO(data), "rb") as wav_file:
        return all(
            (
                wav_file.getnchannels() == 1,
                wav_file.getsampwidth() == 2,
                wav_file.getframerate() == 16_000,
                wav_file.getnframes() == expected_frames,
            )
        )


async def run_platform_evidence() -> PlatformEvidence:
    """Exercise production primitives without external storage or call side effects."""

    checks: list[EligibilityCheckResult] = []

    cancellation_started = time.monotonic()
    cancellation = CancellationState()
    first_accepted = cancellation.accept("caller_barge_in")
    forwarding_suppressed = not cancellation.forwarding_allowed()
    duplicate_rejected = not cancellation.accept("hangup")
    suppression_ms = (time.monotonic() - cancellation_started) * 1000
    cancellation_verified = all(
        (
            first_accepted,
            forwarding_suppressed,
            duplicate_rejected,
            cancellation.reason == "caller_barge_in",
            suppression_ms <= 250,
        )
    )
    checks.append(
        EligibilityCheckResult(
            identifier="platform.cancellation_suppression",
            passed=cancellation_verified,
            duration_ms=round(suppression_ms),
            measurements={
                "first_signal_accepted": first_accepted,
                "forwarding_suppressed": forwarding_suppressed,
                "duplicate_signal_rejected": duplicate_rejected,
                "within_250ms": suppression_ms <= 250,
            },
            error_code="cancellation_suppression_failed",
        )
    )

    recording_started = time.monotonic()
    uploads: list[tuple[str, bytes]] = []
    updates: list[dict[str, Any]] = []
    recording_error: str | None = None
    wav_valid = False
    keys_valid = False
    metadata_valid = False
    try:
        buffers = InMemoryRecordingBuffers(
            workflow_run_id=0, sample_rate=16_000, num_channels=1
        )
        pcm = b"\x01\x00\x02\x00\x03\x00\x04\x00"
        await buffers.mixed.append(pcm)
        await buffers.user.append(pcm)
        await buffers.bot.append(pcm)
        mixed_wav = await buffers.mixed.to_wav_bytes()
        user_wav = await buffers.user.to_wav_bytes()
        bot_wav = await buffers.bot.to_wav_bytes()
        wav_valid = all(
            _wav_valid(data, expected_frames=4)
            for data in (mixed_wav, user_wav, bot_wav)
        )

        async def create_file(storage_key: str, data: bytes) -> bool:
            uploads.append((storage_key, data))
            return True

        async def update_workflow_run(**values: Any) -> None:
            updates.append(values)

        await persist_workflow_run_artifacts(
            0,
            storage_backend_name="VALIDATION_MEMORY",
            storage_backend_value="validation_memory",
            create_file=create_file,
            update_workflow_run=update_workflow_run,
            mixed_audio_wav=mixed_wav,
            user_audio_wav=user_wav,
            bot_audio_wav=bot_wav,
            transcript_text="user: validation\nassistant: validation",
        )
        keys_valid = [key for key, _ in uploads] == [
            "recordings/0.wav",
            "recordings/0/user.wav",
            "recordings/0/bot.wav",
            "transcripts/0.txt",
        ]
        recording_update = any(
            update.get("recording_url") == "recordings/0.wav" for update in updates
        )
        transcript_update = any(
            update.get("transcript_url") == "transcripts/0.txt" for update in updates
        )
        recording_metadata = next(
            (
                update.get("extra", {}).get("recordings")
                for update in updates
                if update.get("extra")
            ),
            None,
        )
        metadata_valid = bool(
            recording_update
            and transcript_update
            and recording_metadata
            and set(recording_metadata) == {"mixed", "user", "bot"}
        )
    except Exception as exc:  # noqa: BLE001 - probe failure is persisted safely
        recording_error = type(exc).__name__

    recording_verified = bool(
        recording_error is None and wav_valid and keys_valid and metadata_valid
    )
    checks.append(
        EligibilityCheckResult(
            identifier="platform.recording_artifact_pipeline",
            passed=recording_verified,
            duration_ms=round((time.monotonic() - recording_started) * 1000),
            measurements={
                "wav_encoding_valid": wav_valid,
                "artifact_keys_valid": keys_valid,
                "metadata_persistence_valid": metadata_valid,
                "artifact_count": len(uploads),
            },
            error_code=recording_error or "recording_artifact_pipeline_failed",
        )
    )

    return PlatformEvidence(
        cancellation_verified=cancellation_verified,
        recording_verified=recording_verified,
        checks=tuple(checks),
    )
