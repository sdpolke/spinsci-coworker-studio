"""Organization catalog snapshot for workflow generation grounding."""

from __future__ import annotations

from api.db import db_client
from api.services.workflow.generation.models import CatalogSnapshot
from api.services.workflow.node_specs import all_specs


async def load_catalog_snapshot(
    *,
    organization_id: int | None,
) -> CatalogSnapshot:
    tools = []
    documents = []
    credentials = []

    if organization_id is not None:
        tool_rows = await db_client.get_tools_for_organization(
            organization_id=organization_id,
            status="active",
        )
        tools = [
            {
                "tool_uuid": tool.tool_uuid,
                "name": tool.name,
                "description": tool.description or "",
                "category": tool.category,
            }
            for tool in tool_rows
        ]

        document_rows = await db_client.get_documents_for_organization(
            organization_id=organization_id,
        )
        documents = [
            {
                "document_uuid": document.document_uuid,
                "filename": document.filename,
                "processing_status": document.processing_status,
            }
            for document in document_rows
        ]

        credential_rows = await db_client.get_credentials_for_organization(
            organization_id=organization_id,
        )
        credentials = [
            {
                "credential_uuid": credential.credential_uuid,
                "name": credential.name,
                "description": credential.description or "",
                "credential_type": credential.credential_type,
            }
            for credential in credential_rows
        ]

    node_types = [
        {
            "name": spec.name,
            "display_name": spec.display_name,
            "description": spec.description,
            "category": spec.category.value,
        }
        for spec in all_specs()
    ]

    return CatalogSnapshot(
        node_types=node_types,
        tools=tools,
        documents=documents,
        credentials=credentials,
    )


def format_catalog_for_prompt(catalog: CatalogSnapshot) -> str:
    lines = ["## Available node types"]
    for node_type in catalog.node_types:
        lines.append(
            f"- {node_type['name']}: {node_type.get('description') or node_type['display_name']}"
        )

    lines.append("\n## Existing tools (use tool_uuids only from this list)")
    if catalog.tools:
        for tool in catalog.tools:
            lines.append(
                f"- {tool['name']} ({tool['tool_uuid']}) [{tool['category']}]: "
                f"{tool.get('description') or ''}"
            )
    else:
        lines.append("- None configured. Do not attach tools until the user creates them.")

    lines.append("\n## Existing documents")
    if catalog.documents:
        for document in catalog.documents:
            lines.append(
                f"- {document['filename']} ({document['document_uuid']}) "
                f"[{document['processing_status']}]"
            )
    else:
        lines.append("- None configured.")

    lines.append("\n## Existing credentials")
    if catalog.credentials:
        for credential in catalog.credentials:
            lines.append(
                f"- {credential['name']} ({credential['credential_uuid']}) "
                f"[{credential['credential_type']}]"
            )
    else:
        lines.append("- None configured.")

    return "\n".join(lines)
