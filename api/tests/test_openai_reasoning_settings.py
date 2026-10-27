"""Which OpenAI models get a forced reasoning effort.

This exists because a substring test shipped. ``"gpt-5" in model`` was true for
every ``gpt-5.6-*`` model, which rejects ``reasoning_effort: "minimal"`` --
supported values there are none, low, medium, high and xhigh. The request 400s,
the completion fails, and on a voice call a failed completion is silence: the
caller hears nothing and the turn never arrives.
"""

from __future__ import annotations

import pytest

from api.services.pipecat.service_factory import _openai_reasoning_settings

MINIMAL = {"reasoning_effort": "minimal", "verbosity": "low"}


@pytest.mark.parametrize("model", ["gpt-5", "gpt-5-mini", "gpt-5-nano"])
def test_the_gpt5_family_keeps_minimal_effort(model):
    """Unchanged behaviour for the models this was written for."""
    assert _openai_reasoning_settings(model) == MINIMAL


@pytest.mark.parametrize("model", ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"])
def test_the_gpt56_family_is_not_given_an_effort_it_rejects(model):
    """The bug, pinned. These accept none/low/medium/high/xhigh, not minimal."""
    assert _openai_reasoning_settings(model) is None


@pytest.mark.parametrize(
    "model", ["gpt-live-1", "gpt-4o", "gpt-4.1", "o3", "", "some-model-from-next-year"]
)
def test_an_unrecognised_model_is_left_alone(model):
    """The default has to be "send nothing". A forced value that a model does
    not accept fails the whole turn, and a model released next month cannot be
    enumerated here in advance."""
    assert _openai_reasoning_settings(model) is None


@pytest.mark.parametrize("model", ["GPT-5", " gpt-5 ", "GPT-5-Mini"])
def test_case_and_whitespace_do_not_change_the_answer(model):
    """The model name arrives from a free-text field in the UI."""
    assert _openai_reasoning_settings(model) == MINIMAL


def test_a_name_that_merely_contains_a_known_one_is_not_matched():
    """The whole point: containment is not identity."""
    assert _openai_reasoning_settings("gpt-5.6-luna") is None
    assert _openai_reasoning_settings("not-gpt-5-really") is None


def test_none_is_handled():
    assert _openai_reasoning_settings(None) is None
