"""Which way out the engine takes when a step keeps being re-entered.

A node on a cycle can be re-entered until the engine stops it, and then
something has to be chosen. Inferring it from the shape of the graph resolves
to the order the edges were declared in, which is arbitrary, and the thing
being chosen is not arbitrary at all: every ending makes a claim to the caller.
On a real workflow the inferred choice told three steps' worth of callers "no
problem, ring back any time" after the engine gave up on them, and for a
booking step it picked the edge asserting a confirmed appointment.

So the workflow says. These cover that it is obeyed, that a workflow which says
nothing behaves exactly as it did before rather than shifting underneath us,
and the two ways the inference went wrong.
"""

from __future__ import annotations

from api.services.workflow.dto import ReactFlowDTO
from api.services.workflow.pipecat_engine import PipecatEngine
from api.services.workflow.workflow_graph import WorkflowGraph


def node(node_id: str, *, is_end: bool = False, node_type: str | None = None):
    if node_type is None:
        node_type = "startCall" if node_id == "start" else "agentNode"
    return {
        "id": node_id,
        "type": "endCall" if is_end else node_type,
        "position": {"x": 0, "y": 0},
        "data": {
            "name": node_id,
            "prompt": f"{node_id} prompt",
            "is_start": node_id == "start",
            "is_end": is_end,
        },
    }


def edge(source: str, target: str, label: str, *, escape: bool = False, index: int = 0):
    data = {"label": label, "condition": f"when {label}"}
    if escape:
        data["is_loop_escape"] = True
    return {
        "id": f"{source}__{target}__{index}",
        "source": source,
        "target": target,
        "data": data,
    }


def engine_for(nodes, edges):
    """A stand-in carrying only what _loop_escape_edge reads."""
    graph = WorkflowGraph(ReactFlowDTO.model_validate({"nodes": nodes, "edges": edges}))

    class Shim:
        workflow = graph
        _gathered_context: dict = {"visit_counts": {}}

    return Shim(), graph


def escape_from(nodes, edges, node_id: str):
    shim, graph = engine_for(nodes, edges)
    found = PipecatEngine._loop_escape_edge(shim, graph.nodes[node_id])
    return None if found is None else found.target


# --------------------------------------------------- the workflow decides


def test_a_declared_escape_is_taken():
    nodes = [
        node("start"),
        node("loop"),
        node("mid"),
        node("handover"),
        node("bye", is_end=True),
    ]
    edges = [
        edge("start", "loop", "go_to_loop"),
        edge("loop", "mid", "go_to_mid"),
        edge("mid", "loop", "go_to_loop", index=1),
        edge("loop", "bye", "go_to_bye", index=2),
        edge("loop", "handover", "go_to_handover", escape=True, index=3),
    ]
    assert escape_from(nodes, edges, "loop") == "handover"


def test_a_declared_escape_beats_an_ending_declared_before_it():
    """The ordering bug: the ending came first and used to win."""
    nodes = [node("start"), node("loop"), node("handover"), node("bye", is_end=True)]
    edges = [
        edge("start", "loop", "go_to_loop"),
        edge("loop", "bye", "go_to_bye"),
        edge("loop", "handover", "go_to_handover", escape=True, index=1),
    ]
    assert escape_from(nodes, edges, "loop") == "handover"


def test_a_declared_escape_may_be_an_ending():
    """At a handover, "a colleague will ring you" is the honest outcome."""
    nodes = [node("start"), node("handover"), node("retry"), node("bye", is_end=True)]
    edges = [
        edge("start", "handover", "go_to_handover"),
        edge("handover", "retry", "go_to_retry"),
        edge("retry", "handover", "go_to_handover", index=1),
        edge("handover", "bye", "go_to_bye", escape=True, index=2),
    ]
    assert escape_from(nodes, edges, "handover") == "bye"


def test_the_first_is_used_when_a_node_marks_several():
    nodes = [node("start"), node("loop"), node("a"), node("b")]
    edges = [
        edge("start", "loop", "go_to_loop"),
        edge("loop", "a", "go_to_a", escape=True),
        edge("loop", "b", "go_to_b", escape=True, index=1),
    ]
    assert escape_from(nodes, edges, "loop") == "a"


# ------------------------------- a silent workflow keeps its old behaviour


def test_without_a_declaration_the_old_guess_is_unchanged():
    """Existing workflows must not shift. An ending still wins, as before."""
    nodes = [node("start"), node("loop"), node("handover"), node("bye", is_end=True)]
    edges = [
        edge("start", "loop", "go_to_loop"),
        edge("loop", "bye", "go_to_bye"),
        edge("loop", "handover", "go_to_handover", index=1),
    ]
    assert escape_from(nodes, edges, "loop") == "bye"


def test_without_a_declaration_an_unvisited_step_is_used_when_nothing_ends():
    nodes = [node("start"), node("loop"), node("onward"), node("more")]
    edges = [
        edge("start", "loop", "go_to_loop"),
        edge("loop", "onward", "go_to_onward"),
        edge("onward", "more", "go_to_more"),
        edge("more", "loop", "go_to_loop", index=1),
    ]
    assert escape_from(nodes, edges, "loop") == "onward"


# --------------------------------------------------------- the guard rails


def test_an_ending_has_no_escape():
    nodes = [node("start"), node("bye", is_end=True)]
    edges = [edge("start", "bye", "go_to_bye")]
    assert escape_from(nodes, edges, "bye") is None


def test_a_node_with_one_exit_and_nowhere_new_gives_up():
    """Better to stay with the caller than to assert something untrue."""
    nodes = [node("start"), node("loop"), node("mid")]
    edges = [
        edge("start", "loop", "go_to_loop"),
        edge("loop", "mid", "go_to_mid"),
        edge("mid", "loop", "go_to_loop", index=1),
    ]
    shim, graph = engine_for(nodes, edges)
    shim._gathered_context = {"visit_counts": {"start": 1, "loop": 4, "mid": 3}}
    assert PipecatEngine._loop_escape_edge(shim, graph.nodes["loop"]) is None


def test_the_field_survives_a_round_trip_through_the_dto():
    """Edge data is filtered to known fields, so an unknown one is dropped."""
    nodes = [node("start"), node("loop"), node("handover")]
    edges = [
        edge("start", "loop", "go_to_loop"),
        edge("loop", "handover", "go_to_handover", escape=True),
    ]
    dto = ReactFlowDTO.model_validate({"nodes": nodes, "edges": edges})
    marked = [e for e in dto.edges if e.data.is_loop_escape]
    assert [e.target for e in marked] == ["handover"]


def test_the_field_defaults_to_false_when_absent():
    """Every workflow already saved predates this field."""
    dto = ReactFlowDTO.model_validate(
        {
            "nodes": [node("start"), node("next")],
            "edges": [edge("start", "next", "go_to_next")],
        }
    )
    assert dto.edges[0].data.is_loop_escape is False
