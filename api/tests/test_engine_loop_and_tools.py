"""Two engine guards that run on every call.

Both exist because of behaviour seen on real calls. Tool registrations
accumulated across node transitions, so a realtime session reached the booking
step still offering every earlier transition and every earlier tool. And
nothing bounded how often a node could be re-entered, so a cycle ran until the
call hit its maximum duration.
"""

from __future__ import annotations

import pytest

from api.services.workflow import pipecat_engine as engine_module
from api.services.workflow.pipecat_engine import MAX_NODE_VISITS


class FakeEdge:
    def __init__(self, target: str, name: str):
        self.target = target
        self._name = name
        self.transition_speech = None

        class _Data:
            transition_speech_type = None
            transition_speech_recording_id = None

        self.data = _Data()

    def get_function_name(self) -> str:
        return self._name


class FakeNode:
    def __init__(self, node_id, *, edges=(), is_end=False):
        self.id = node_id
        self.name = node_id
        self.out_edges = list(edges)
        self.is_end = is_end
        self.tool_uuids = None
        self.document_uuids = None
        self.mcp_tool_filters = None


class FakeLLM:
    """Records registrations the way the realtime service accumulates them."""

    def __init__(self):
        self.registered: set[str] = set()

    def register_function(self, name, handler, **kwargs):
        self.registered.add(name)

    def unregister_function(self, name):
        self.registered.discard(name)


@pytest.fixture
def engine():
    """An engine with only the pieces these guards touch."""
    e = engine_module.PipecatEngine.__new__(engine_module.PipecatEngine)
    e.llm = FakeLLM()
    e._registered_function_names = set()
    e._gathered_context = {}

    class _Workflow:
        nodes: dict = {}

    e.workflow = _Workflow()
    return e


# --- tool registrations ----------------------------------------------------


async def test_leaving_a_node_removes_the_functions_it_registered(engine):
    """The accumulation bug. A real realtime call grew from one tool to twelve,
    so by the booking step the model could still call go_to_identify and walk
    back into a step it had finished."""
    for name in ("go_to_identify", "epic_patient_lookup"):
        engine.llm.register_function(name, None)
        engine._registered_function_names.add(name)

    await engine._unregister_node_functions()

    assert engine.llm.registered == set()
    assert engine._registered_function_names == set()


async def test_only_what_the_engine_registered_is_removed(engine):
    """Anything the pipeline registered for its own purposes is left alone."""
    engine.llm.register_function("go_to_reason", None)
    engine._registered_function_names.add("go_to_reason")
    engine.llm.register_function("pipeline_owned_tool", None)

    await engine._unregister_node_functions()

    assert engine.llm.registered == {"pipeline_owned_tool"}


async def test_unregistering_survives_a_service_that_cannot(engine):
    """Not every provider supports removal. A stale tool is not worth failing
    a live call over."""
    delattr(type(engine.llm), "unregister_function") if False else None
    engine.llm = type("NoUnregister", (), {"register_function": lambda *a, **k: None})()
    engine._registered_function_names = {"go_to_reason"}

    await engine._unregister_node_functions()
    assert engine._registered_function_names == set()


# --- the loop guard --------------------------------------------------------


def test_an_end_node_is_never_an_escape_target(engine):
    assert engine._loop_escape_edge(FakeNode("done", is_end=True)) is None


def test_the_escape_prefers_a_terminal_edge(engine):
    """A handoff or an ending cannot lead back into the cycle."""
    offer = FakeNode("offer", edges=[
        FakeEdge("slots", "go_to_slots"),
        FakeEdge("handoff", "go_to_handoff"),
    ])
    engine.workflow.nodes = {
        "slots": FakeNode("slots", edges=[FakeEdge("offer", "go_to_offer")]),
        "handoff": FakeNode("handoff", is_end=True),
    }
    assert engine._loop_escape_edge(offer).target == "handoff"


def test_the_escape_falls_back_to_somewhere_not_yet_visited(engine):
    offer = FakeNode("offer", edges=[
        FakeEdge("slots", "go_to_slots"),
        FakeEdge("book", "go_to_book"),
    ])
    engine.workflow.nodes = {
        "slots": FakeNode("slots", edges=[FakeEdge("offer", "go_to_offer")]),
        "book": FakeNode("book", edges=[FakeEdge("done", "go_to_done")]),
    }
    engine._gathered_context["visit_counts"] = {"slots": 3}
    assert engine._loop_escape_edge(offer).target == "book"


def test_no_escape_is_invented_when_every_edge_leads_back(engine):
    """Better to log and continue than to send the caller somewhere arbitrary."""
    a = FakeNode("a", edges=[FakeEdge("b", "go_to_b")])
    engine.workflow.nodes = {"b": FakeNode("b", edges=[FakeEdge("a", "go_to_a")])}
    engine._gathered_context["visit_counts"] = {"b": 3}
    assert engine._loop_escape_edge(a) is None


def test_the_cap_allows_a_genuine_retry():
    """A caller asking twice for different dates is not a loop. Three visits
    is deliberately above that."""
    assert MAX_NODE_VISITS >= 3
