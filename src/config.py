"""Shared configuration loader for the QC Microbiology auto-apply pipeline.

Reads ``config/preferences.yaml`` (overridable via ``RESUME_OPT_CONFIG`` env var)
and exposes a single ``load_preferences()`` entry point. Callers may mutate the
returned dict before passing it downstream — we never re-read the file on a
given call.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "preferences.yaml"


def _resolve_path() -> Path:
    override = os.getenv("RESUME_OPT_CONFIG", "").strip()
    if override:
        p = Path(override).expanduser()
        if not p.is_absolute():
            p = REPO_ROOT / p
        return p
    return DEFAULT_CONFIG_PATH


def load_preferences(path: str | Path | None = None) -> dict[str, Any]:
    """Load preferences.yaml; falls back to an empty dict if the file is absent."""
    p = Path(path).expanduser() if path else _resolve_path()
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{p} must define a YAML mapping at the top level")
    return data


def resolve_repo_path(value: str | Path) -> Path:
    """Resolve a relative path against the repo root; leave absolute paths alone."""
    p = Path(value).expanduser()
    if p.is_absolute():
        return p
    return REPO_ROOT / p


def get(prefs: dict[str, Any], dotted_key: str, default: Any = None) -> Any:
    """Safe ``a.b.c`` lookup into nested preferences."""
    node: Any = prefs
    for part in dotted_key.split("."):
        if not isinstance(node, dict):
            return default
        if part not in node:
            return default
        node = node[part]
    return node
