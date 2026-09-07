"""Upload end-of-call artifacts (recordings, transcript) to object storage.

Called from the pipeline process itself, straight from the in-memory call
buffers, so no local file ever has to cross a process/host boundary (no
shared /tmp between web and ARQ workers). Uploads happen before the
workflow-completion job is enqueued so QA and webhooks see the artifacts
in storage.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from api.db import db_client
from api.services.storage import get_current_storage_backend, storage_fs

CreateFile = Callable[[str, bytes], Awaitable[bool]]
UpdateWorkflowRun = Callable[..., Awaitable[Any]]


def _recording_metadata(storage_key: str, storage_backend: str, track: str) -> dict:
    return {
        "storage_key": storage_key,
        "storage_backend": storage_backend,
        "format": "wav",
        "track": track,
    }


async def _upload_bytes(
    workflow_run_id: int,
    data: bytes,
    storage_key: str,
    label: str,
    *,
    create_file: CreateFile,
) -> bool:
    try:
        logger.debug(f"{label} size: {len(data)} bytes")
        if await create_file(storage_key, data):
            logger.info(f"Successfully uploaded {label}: {storage_key}")
            return True
        logger.error(
            f"Storage backend rejected {label} upload for workflow "
            f"{workflow_run_id}: {storage_key}"
        )
        return False
    except Exception as exc:  # noqa: BLE001 - one artifact must not block the others
        logger.error(f"Error uploading {label} for workflow {workflow_run_id}: {exc}")
        return False


async def persist_workflow_run_artifacts(
    workflow_run_id: int,
    *,
    storage_backend_name: str,
    storage_backend_value: str,
    create_file: CreateFile,
    update_workflow_run: UpdateWorkflowRun,
    mixed_audio_wav: bytes | None = None,
    user_audio_wav: bytes | None = None,
    bot_audio_wav: bytes | None = None,
    transcript_text: str | None = None,
) -> None:
    """Persist artifacts through explicit dependencies for runtime use and probes."""

    recordings_metadata: dict[str, dict] = {}

    if mixed_audio_wav:
        recording_url = f"recordings/{workflow_run_id}.wav"
        logger.info(
            f"Uploading mixed audio to {storage_backend_name} - workflow_run_id: {workflow_run_id}"
        )
        if await _upload_bytes(
            workflow_run_id,
            mixed_audio_wav,
            recording_url,
            "mixed audio",
            create_file=create_file,
        ):
            recordings_metadata["mixed"] = _recording_metadata(
                recording_url, storage_backend_value, "mixed"
            )
            await update_workflow_run(
                run_id=workflow_run_id,
                recording_url=recording_url,
                storage_backend=storage_backend_value,
            )

    for track, data in (("user", user_audio_wav), ("bot", bot_audio_wav)):
        if not data:
            continue
        recording_url = f"recordings/{workflow_run_id}/{track}.wav"
        logger.info(
            f"Uploading {track} audio to {storage_backend_name} - workflow_run_id: {workflow_run_id}"
        )
        if await _upload_bytes(
            workflow_run_id,
            data,
            recording_url,
            f"{track} audio",
            create_file=create_file,
        ):
            recordings_metadata[track] = _recording_metadata(
                recording_url, storage_backend_value, track
            )

    if recordings_metadata:
        await update_workflow_run(
            run_id=workflow_run_id,
            storage_backend=storage_backend_value,
            extra={"recordings": recordings_metadata},
        )

    if transcript_text:
        transcript_url = f"transcripts/{workflow_run_id}.txt"
        logger.info(
            f"Uploading transcript to {storage_backend_name} - workflow_run_id: {workflow_run_id}"
        )
        if await _upload_bytes(
            workflow_run_id,
            transcript_text.encode("utf-8"),
            transcript_url,
            "transcript",
            create_file=create_file,
        ):
            await update_workflow_run(
                run_id=workflow_run_id,
                transcript_url=transcript_url,
                storage_backend=storage_backend_value,
            )


async def upload_workflow_run_artifacts(
    workflow_run_id: int,
    *,
    mixed_audio_wav: bytes | None = None,
    user_audio_wav: bytes | None = None,
    bot_audio_wav: bytes | None = None,
    transcript_text: str | None = None,
) -> None:
    """Upload call artifacts to object storage and persist their metadata."""

    storage_backend = get_current_storage_backend()
    await persist_workflow_run_artifacts(
        workflow_run_id,
        storage_backend_name=storage_backend.name,
        storage_backend_value=storage_backend.value,
        create_file=storage_fs.acreate_file_from_bytes,
        update_workflow_run=db_client.update_workflow_run,
        mixed_audio_wav=mixed_audio_wav,
        user_audio_wav=user_audio_wav,
        bot_audio_wav=bot_audio_wav,
        transcript_text=transcript_text,
    )
