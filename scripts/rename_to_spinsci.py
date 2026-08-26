#!/usr/bin/env python3
"""One-off bulk rename: dograh/crescendo -> spinsci in code (not documentation)."""

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
    ("dograh.com", "spinsci.com"),
    ("crescendoworldwide.com", "spinsci.com"),
    ("@dograh/sdk", "@spinsci/sdk"),
    ("DograhWidget", "SpinSciWidget"),
    ("dograh-widget.js", "spinsci-widget.js"),
    ("dograh-widget", "spinsci-widget"),
    ("dograh-inline-container", "spinsci-inline-container"),
    ("data-dograh-context", "data-spinsci-context"),
    ("dograh_auth_token", "spinsci_auth_token"),
    ("dograh_auth_user", "spinsci_auth_user"),
    ("dograh-hq/dograh", "spinsci-hq/spinsci"),
    ("dograh-hq", "spinsci-hq"),
    ("dograh_embedding_v1", "spinsci_embedding_v1"),
    ("total_dograh_tokens", "total_spinsci_tokens"),
    ("dograh:hireNudge", "spinsci:hireNudge"),
    ("dograh-latest-release", "spinsci-latest-release"),
    ("DOGRAH_MCP_INSTRUCTIONS", "SPINSCI_MCP_INSTRUCTIONS"),
    ("DOGRAH_DEVOPS_SECRET", "SPINSCI_DEVOPS_SECRET"),
    ("DOGRAH_MPS_SECRET_KEY", "SPINSCI_MPS_SECRET_KEY"),
    ("X-Dograh-Devops-Secret", "X-SpinSci-Devops-Secret"),
    ("_dograh_failure_metadata", "_spinsci_failure_metadata"),
    ("_dograh_failure_reported", "_spinsci_failure_reported"),
    ("DograhFailure", "SpinSciFailure"),
    ("dograh-connection", "spinsci-connection"),
    ("DograhAzureRealtimeLLMService", "SpinSciAzureRealtimeLLMService"),
    ("DograhOpenAIRealtimeLLMService", "SpinSciOpenAIRealtimeLLMService"),
    ("DograhLLMService", "SpinSciLLMService"),
    ("DograhTTSService", "SpinSciTTSService"),
    ("DograhSTTService", "SpinSciSTTService"),
    ("DograhEmbeddingsConfiguration", "SpinSciEmbeddingsConfiguration"),
    ("dograh_service.py", "spinsci_service.py"),
    ("services.dograh", "services.spinsci"),
    ("services/dograh", "services/spinsci"),
    ("pipecat.services.dograh", "pipecat.services.spinsci"),
    ("dograh_sdk", "spinsci_sdk"),
    ("dograh-of6c", "spinsci-of6c"),
    ("dograh-logo", "spinsci-logo"),
    ("crescendo-logo", "spinsci-logo"),
    ("overview-crescendo", "overview-spinsci"),
    ("overview_crescendo", "overview_spinsci"),
    ("Crescendo Worldwide", "SpinSci"),
    ("Welcome to Crescendo", "Welcome to SpinSci"),
    ("About Crescendo", "About SpinSci"),
    ("Crescendo", "SpinSci"),
    ("crescendo", "spinsci"),
    ("DOGRAH_PROVIDER", "SPINSCI_PROVIDER"),
    ("DOGRAH_LLM", "SPINSCI_LLM"),
    ("DOGRAH_TTS", "SPINSCI_TTS"),
    ("DOGRAH_STT", "SPINSCI_STT"),
    ("DOGRAH_EMBEDDING", "SPINSCI_EMBEDDING"),
    ("DOGRAH_MULTILINGUAL", "SPINSCI_MULTILINGUAL"),
    ("ServiceProviders.DOGRAH", "ServiceProviders.SPINSCI"),
    ('provider="dograh"', 'provider="spinsci"'),
    ("provider='dograh'", "provider='spinsci'"),
    ("app_name=\"dograh\"", "app_name=\"spinsci\""),
    ("app_name='dograh'", "app_name='spinsci'"),
    ("Dograh ", "SpinSci "),
    ("Dograh", "SpinSci"),
    ("DOGRAH", "SPINSCI"),
    ("dograh", "spinsci"),
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
