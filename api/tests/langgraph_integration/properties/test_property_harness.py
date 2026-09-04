import re
from pathlib import Path

PROPERTY_COMMENT = re.compile(r"# Feature: langgraph-voice-integration, Property \d+: .+")


def test_every_property_module_has_required_design_comment():
    directory = Path(__file__).parent
    modules = [path for path in directory.glob("test_property_*.py") if path.name != Path(__file__).name]
    assert modules
    for module in modules:
        assert PROPERTY_COMMENT.search(module.read_text()), f"missing property design comment: {module.name}"
