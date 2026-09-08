#!/usr/bin/env python3
"""One-off bulk rename: SpinSci/crescendo -> spinsci in code (not documentation)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIR_PARTS = {
    "docs",
    "node_modules",
    ".git",
    "__pycache__",
    ".next",
    "dist",
    "venv",
    ".venv",
    ".vscode",
}

SKIP_FILES = {
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "README.md",
    "README.ja-JP.md",
    "README.zh-CN.md",
}

EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".mts",
    ".json",
    ".yaml",
    ".yml",
    ".css",
    ".sh",
    ".ps1",
    ".toml",
    ".html",
    ".tpl",
    ".template",
    ".ini",
}

REPLACEMENTS = [
    ("SpinSci.com", "spinsci.com"),
    ("crescendoworldwide.com", "spinsci.com"),
    ("@SpinSci/sdk", "@spinsci/sdk"),
    ("SpinSciWidget", "SpinSciWidget"),
    ("SpinSci-widget.js", "spinsci-widget.js"),
    ("SpinSci-widget", "spinsci-widget"),
    ("SpinSci-inline-container", "spinsci-inline-container"),
    ("data-SpinSci-context", "data-spinsci-context"),
    ("SpinSci_auth_token", "spinsci_auth_token"),
    ("SpinSci_auth_user", "spinsci_auth_user"),
    ("SpinSci-hq/SpinSci", "spinsci-hq/spinsci"),
    ("SpinSci-hq", "spinsci-hq"),
    ("SpinSci_embedding_v1", "spinsci_embedding_v1"),
    ("total_SpinSci_tokens", "total_spinsci_tokens"),
    ("SpinSci:hireNudge", "spinsci:hireNudge"),
    ("SpinSci-latest-release", "spinsci-latest-release"),
    ("SpinSci_MCP_INSTRUCTIONS", "SPINSCI_MCP_INSTRUCTIONS"),
    ("SpinSci_DEVOPS_SECRET", "SPINSCI_DEVOPS_SECRET"),
    ("SpinSci_MPS_SECRET_KEY", "SPINSCI_MPS_SECRET_KEY"),
    ("X-SpinSci-Devops-Secret", "X-SpinSci-Devops-Secret"),
    ("_SpinSci_failure_metadata", "_spinsci_failure_metadata"),
    ("_SpinSci_failure_reported", "_spinsci_failure_reported"),
    ("SpinSciFailure", "SpinSciFailure"),
    ("SpinSci-connection", "spinsci-connection"),
    ("SpinSciAzureRealtimeLLMService", "SpinSciAzureRealtimeLLMService"),
    ("SpinSciOpenAIRealtimeLLMService", "SpinSciOpenAIRealtimeLLMService"),
    ("SpinSciLLMService", "SpinSciLLMService"),
    ("SpinSciTTSService", "SpinSciTTSService"),
    ("SpinSciSTTService", "SpinSciSTTService"),
    ("SpinSciEmbeddingsConfiguration", "SpinSciEmbeddingsConfiguration"),
    ("SpinSci_service.py", "spinsci_service.py"),
    ("services.SpinSci", "services.spinsci"),
    ("services/SpinSci", "services/spinsci"),
    ("pipecat.services.SpinSci", "pipecat.services.spinsci"),
    ("SpinSci_sdk", "spinsci_sdk"),
    ("SpinSci-of6c", "spinsci-of6c"),
    ("SpinSci-logo", "spinsci-logo"),
    ("crescendo-logo", "spinsci-logo"),
    ("overview-crescendo", "overview-spinsci"),
    ("overview_crescendo", "overview_spinsci"),
    ("Crescendo Worldwide", "SpinSci"),
    ("Welcome to Crescendo", "Welcome to SpinSci"),
    ("About Crescendo", "About SpinSci"),
    ("Crescendo", "SpinSci"),
    ("crescendo", "spinsci"),
    ("SpinSci_PROVIDER", "SPINSCI_PROVIDER"),
    ("SpinSci_LLM", "SPINSCI_LLM"),
    ("SpinSci_TTS", "SPINSCI_TTS"),
    ("SpinSci_STT", "SPINSCI_STT"),
    ("SpinSci_EMBEDDING", "SPINSCI_EMBEDDING"),
    ("SpinSci_MULTILINGUAL", "SPINSCI_MULTILINGUAL"),
    ("ServiceProviders.SpinSci", "ServiceProviders.SPINSCI"),
    ('provider="SpinSci"', 'provider="spinsci"'),
    ("provider='SpinSci'", "provider='spinsci'"),
    ("app_name=\"SpinSci\"", "app_name=\"spinsci\""),
    ("app_name='SpinSci'", "app_name='spinsci'"),
    ("SpinSci ", "SpinSci "),
    ("SpinSci", "SpinSci"),
    ("SpinSci", "SPINSCI"),
    ("SpinSci", "spinsci"),
]


def should_skip(path: Path) -> bool:
    if path.name in SKIP_FILES or path.name.endswith(".md"):
        return True
    if path.name == "rename_to_spinsci.py":
        return True
    if "docs" in path.parts:
        return True
    for part in path.parts:
        if part in SKIP_DIR_PARTS:
            return True
    if path.name.startswith(".env") or path.name.endswith(".env.example"):
        return False
    return path.suffix not in EXTENSIONS


def transform(text: str) -> str:
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return text


def main() -> None:
    changed = 0
    for path in ROOT.rglob("*"):
        if not path.is_file() or should_skip(path):
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        updated = transform(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed += 1
    print(f"Updated {changed} files")


if __name__ == "__main__":
    main()
