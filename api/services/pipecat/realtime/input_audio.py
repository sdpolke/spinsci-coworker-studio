"""What the OpenAI Realtime session is told about the caller's microphone.

A speech-to-speech model owns its own turn taking. There is no local VAD in
front of it -- :func:`_create_realtime_user_turn_config` deliberately hands
turn detection to the provider -- so whatever the session is configured with is
the only thing standing between room noise and a model turn.

Left unset, OpenAI applies ``server_vad`` at a threshold of 0.5 with 500ms of
trailing silence, and no noise reduction at all. On a clean headset that is
fine. On a speakerphone in a clinic corridor, or a mobile in a car, it is not:
a door closing clears 0.5, the model takes it for the caller starting to speak,
and either barges in over its own sentence or answers something nobody said.
Both were heard on test calls.

Two session settings fix it, and this module decides them:

**Noise reduction** is off unless asked for. ``near_field`` is for a microphone
at the mouth -- a handset, a headset -- and ``far_field`` for one across a room,
a laptop or a speakerphone, where the voice arrives quieter than the room. The
wrong one is worse than none, so the default is derived from the transport
rather than guessed: a telephony leg at 8 kHz is somebody holding a phone, a
browser leg is a laptop on a desk.

**Turn detection** is left as ``server_vad`` but tuned: the threshold goes up so
that a knock does not read as speech, and the trailing silence out a little so a
caller pausing mid-sentence is not cut off. ``semantic_vad`` is available for
genuinely noisy lines -- it asks the model whether the caller sounds finished
rather than measuring energy -- at the cost of a less predictable reply delay,
which is why it is opt-in rather than the default.

Every value here is overridable per agent through workflow configurations. The
defaults are what the GI scheduling calls were tuned to; a drive-through or a
ward phone will want different ones.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from api.services.pipecat.audio_config import AudioConfig

#: Above this, the leg is a browser or an app rather than a phone line.
#: Telephony wire formats are 8 kHz; WebRTC reaches the pipeline at 16 kHz.
_TELEPHONY_SAMPLE_RATE_CEILING = 8000


def _default_noise_reduction(sample_rate: int | None) -> str:
    """``near_field`` for a phone in someone's hand, ``far_field`` otherwise."""
    if sample_rate is not None and sample_rate <= _TELEPHONY_SAMPLE_RATE_CEILING:
        return "near_field"
    return "far_field"


def resolve_input_audio_tuning(
    run_configs: dict[str, Any] | None,
    audio_config: "AudioConfig | None" = None,
) -> dict[str, Any]:
    """Build the ``noise_reduction`` and ``turn_detection`` session settings.

    Returns a kwargs dict for ``AudioInput``, carrying only the keys that are
    actually being set. An agent that switches both off gets an empty dict and
    therefore the provider's own defaults, which is the documented way to opt
    out of this tuning entirely.
    """
    from pipecat.services.openai.realtime.events import (
        InputAudioNoiseReduction,
        SemanticTurnDetection,
        TurnDetection,
    )

    from api.schemas.workflow_configurations import RealtimeAudioInputDefaults

    raw = (run_configs or {}).get("realtime_audio_input")
    if isinstance(raw, RealtimeAudioInputDefaults):
        tuning = raw
    elif isinstance(raw, dict):
        try:
            tuning = RealtimeAudioInputDefaults.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 - bad config must not drop the call
            logger.warning(
                f"Ignoring invalid realtime_audio_input configuration ({exc}); "
                "using defaults."
            )
            tuning = RealtimeAudioInputDefaults()
    else:
        tuning = RealtimeAudioInputDefaults()

    kwargs: dict[str, Any] = {}

    if tuning.noise_reduction != "off":
        mode = tuning.noise_reduction
        if mode == "auto":
            sample_rate = (
                getattr(audio_config, "transport_in_sample_rate", None)
                if audio_config is not None
                else None
            )
            mode = _default_noise_reduction(sample_rate)
        kwargs["noise_reduction"] = InputAudioNoiseReduction(type=mode)

    if tuning.turn_detection == "semantic_vad":
        kwargs["turn_detection"] = SemanticTurnDetection(eagerness=tuning.eagerness)
    elif tuning.turn_detection == "server_vad":
        kwargs["turn_detection"] = TurnDetection(
            threshold=tuning.threshold,
            prefix_padding_ms=tuning.prefix_padding_ms,
            silence_duration_ms=tuning.silence_duration_ms,
        )

    if kwargs:
        logger.info(
            "Realtime input audio tuning: "
            f"noise_reduction={getattr(kwargs.get('noise_reduction'), 'type', None)}, "
            f"turn_detection={getattr(kwargs.get('turn_detection'), 'type', None)}"
        )
    return kwargs
