"""Generate validated LangGraph contract reference artifacts.

Run from the repository root:

    python -m scripts.dump_langgraph_contract_reference

The builder validates every executable example/version association before
writing either artifact, so a failure cannot partially publish generated docs.
"""

from pathlib import Path

from api.services.langgraph_integration.contract.reference import (
    build_contract_reference,
    render_contract_reference_json,
    render_contract_reference_mdx,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
JSON_OUTPUT = (
    REPO_ROOT / "docs" / "developer" / "generated" / "langgraph-contract-reference.json"
)
MDX_OUTPUT = REPO_ROOT / "docs" / "developer" / "langgraph-contract-reference.mdx"


def main() -> None:
    reference = build_contract_reference()
    json_content = render_contract_reference_json(reference)
    mdx_content = render_contract_reference_mdx(reference)

    JSON_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT.write_text(json_content)
    MDX_OUTPUT.write_text(mdx_content)
    print(
        f"Validated {len(reference['examples'])} example/version associations and wrote "
        f"{JSON_OUTPUT.relative_to(REPO_ROOT)} and {MDX_OUTPUT.relative_to(REPO_ROOT)}"
    )


if __name__ == "__main__":
    main()
