"""The listening settings a speech-to-speech session is opened with.

A realtime model runs with no local VAD in front of it, so these settings are
the only thing between room noise and a model turn. The cases that matter are
the ones where a bad value is worse than none: a telephony leg told to expect a
far-field microphone, or a malformed stored config taking a live call down.
"""

from __future__ import annotations

import pytest

from api.schemas.workflow_configurations import (
    DEFAULT_REALTIME_VAD_SILENCE_MS,
    DEFAULT_REALTIME_VAD_THRESHOLD,
    RealtimeAudioInputDefaults,
    WorkflowConfigurationDefaults,
)
from api.services.pipecat.audio_config import create_audio_config
from api.services.pipecat.realtime.input_audio import resolve_input_audio_tuning


def _telephony():
    return create_audio_config("twilio")


def _browser():
    return create_audio_config("webrtc")


def test_defaults_tune_server_vad_above_the_provider_default():
    """Unset means tuned, not absent: the provider's own 0.5 is too twitchy."""
    tuning = resolve_input_audio_tuning(None, _telephony())

    assert tuning["turn_detection"].type == "server_vad"
    assert tuning["turn_detection"].threshold == DEFAULT_REALTIME_VAD_THRESHOLD
    assert tuning["turn_detection"].threshold > 0.5
    assert (
        tuning["turn_detection"].silence_duration_ms == DEFAULT_REALTIME_VAD_SILENCE_MS
    )
    assert tuning["turn_detection"].silence_duration_ms > 500


def test_auto_picks_near_field_for_a_phone_line():
    """8 kHz is a handset at someone's mouth."""
    tuning = resolve_input_audio_tuning({}, _telephony())
    assert tuning["noise_reduction"].type == "near_field"


def test_auto_picks_far_field_for_a_browser():
    """A laptop sits across a desk, so the voice arrives quieter than the room."""
    tuning = resolve_input_audio_tuning({}, _browser())
    assert tuning["noise_reduction"].type == "far_field"


def test_auto_without_an_audio_config_does_not_claim_a_phone():
    """No transport known is the room case, which is the safer wrong answer."""
    tuning = resolve_input_audio_tuning({}, None)
    assert tuning["noise_reduction"].type == "far_field"


def test_explicit_mode_overrides_the_transport():
    """A headset on a browser leg is near field, whatever the sample rate says."""
    tuning = resolve_input_audio_tuning(
        {"realtime_audio_input": {"noise_reduction": "near_field"}}, _browser()
    )
    assert tuning["noise_reduction"].type == "near_field"


def test_off_sends_nothing_at_all():
    """Both off must mean the provider's defaults, not an empty object."""
    tuning = resolve_input_audio_tuning(
        {"realtime_audio_input": {"noise_reduction": "off", "turn_detection": "off"}},
        _telephony(),
    )
    assert tuning == {}


def test_semantic_vad_carries_its_eagerness_and_no_thresholds():
    """server_vad's numbers are meaningless to semantic_vad and must not leak."""
    tuning = resolve_input_audio_tuning(
        {
            "realtime_audio_input": {
                "turn_detection": "semantic_vad",
                "eagerness": "low",
            }
        },
        _telephony(),
    )
    detection = tuning["turn_detection"]
    assert detection.type == "semantic_vad"
    assert detection.eagerness == "low"
    assert not hasattr(detection, "threshold")


def test_a_malformed_stored_config_falls_back_instead_of_raising():
    """A bad value in the database must not drop a live call."""
    tuning = resolve_input_audio_tuning(
        {"realtime_audio_input": {"threshold": "loud-ish"}}, _telephony()
    )
    assert tuning["turn_detection"].threshold == DEFAULT_REALTIME_VAD_THRESHOLD


def test_a_non_dict_config_falls_back_instead_of_raising():
    tuning = resolve_input_audio_tuning(
        {"realtime_audio_input": "near_field"}, _telephony()
    )
    assert tuning["noise_reduction"].type == "near_field"
    assert tuning["turn_detection"].type == "server_vad"


def test_an_already_parsed_model_is_accepted():
    """run_configs may arrive parsed rather than as raw JSON."""
    tuning = resolve_input_audio_tuning(
        {"realtime_audio_input": RealtimeAudioInputDefaults(noise_reduction="off")},
        _telephony(),
    )
    assert "noise_reduction" not in tuning


@pytest.mark.parametrize(
    "field, value",
    [
        ("threshold", 1.5),
        ("threshold", -0.1),
        ("silence_duration_ms", 50),
        ("silence_duration_ms", 100_000),
        ("noise_reduction", "medium_field"),
        ("turn_detection", "silero"),
        ("eagerness", "eager"),
    ],
)
def test_out_of_range_values_are_rejected_at_the_schema(field, value):
    """Rejected on save, so a nonsense value never reaches a call."""
    with pytest.raises(Exception):
        RealtimeAudioInputDefaults.model_validate({field: value})


def test_unknown_keys_are_rejected_rather_than_silently_ignored():
    """A typo should fail loudly; a silently dropped key looks like it worked."""
    with pytest.raises(Exception):
        RealtimeAudioInputDefaults.model_validate({"noise_reduciton": "near_field"})


def test_workflow_configurations_default_without_the_section():
    """Existing agents have no such section and must still get the tuning."""
    defaults = WorkflowConfigurationDefaults.model_validate({})
    assert defaults.realtime_audio_input.noise_reduction == "auto"
    assert defaults.realtime_audio_input.turn_detection == "server_vad"


def test_an_explicit_null_section_falls_back_to_defaults():
    """Stored configs carry JSON nulls for things nobody configured."""
    defaults = WorkflowConfigurationDefaults.model_validate(
        {"realtime_audio_input": None}
    )
    assert defaults.realtime_audio_input.threshold == DEFAULT_REALTIME_VAD_THRESHOLD
