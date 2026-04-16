"""Typhoon BST data store and path resolution utilities."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


DEFAULT_ENV_KEY = "TYPHOON_BST_PATH"


def _candidate_paths() -> Iterable[Path]:
    repo_root = Path(__file__).resolve().parents[1]
    yield repo_root / "wind_data" / "bst_all.txt"
    yield repo_root / "Data" / "bst_all.txt"
    yield Path(r"C:\typhoon forecasting\台风预测\TC_Track_prob_JMA_Total\bst_all.txt")
    yield Path(r"C:\typhoon forecasting\台风预测\TC_Track_prob_JMA_SCS\bst_all.txt")


def resolve_bst_path(override_path: str | None = None) -> tuple[Path, str]:
    """Resolve bst_all.txt path by priority: request override > env > built-in candidates."""
    if override_path:
        chosen = Path(override_path).expanduser().resolve()
        if not chosen.exists() or not chosen.is_file():
            raise FileNotFoundError(f"bst_all.txt override path not found: {chosen}")
        return chosen, "request_override"

    env_path = str(os.getenv(DEFAULT_ENV_KEY, "")).strip()
    if env_path:
        chosen = Path(env_path).expanduser().resolve()
        if not chosen.exists() or not chosen.is_file():
            raise FileNotFoundError(f"{DEFAULT_ENV_KEY} path not found: {chosen}")
        return chosen, "env_override"

    for candidate in _candidate_paths():
        if candidate.exists() and candidate.is_file():
            return candidate.resolve(), "built_in"

    explored = "\n".join(str(p) for p in _candidate_paths())
    raise FileNotFoundError(
        "bst_all.txt not found. Set request bst_path or environment variable "
        f"{DEFAULT_ENV_KEY}. Tried:\n{explored}"
    )
