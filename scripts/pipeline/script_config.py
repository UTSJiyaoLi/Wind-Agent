import json
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any, Optional, Set, List


DEFAULT_CONFIG_PATH = "pipeline_config.json"


def _collect_cli_provided_keys(argv: Optional[List[str]] = None) -> Set[str]:
    args = argv if argv is not None else sys.argv[1:]
    provided: set[str] = set()
    i = 0
    while i < len(args):
        token = args[i]
        if token.startswith("--"):
            name = token[2:]
            if "=" in name:
                name = name.split("=", 1)[0]
            provided.add(name.replace("-", "_"))
        i += 1
    return provided


def _load_config_file(config_path: Optional[str]) -> dict[str, Any]:
    if not config_path:
        return {}
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"Config file must be a JSON object: {path}")
    return data


def apply_config_overrides(args: Namespace, section: str, argv: Optional[List[str]] = None) -> Namespace:
    config_path = getattr(args, "config", "") or ""
    config_data = _load_config_file(config_path)
    if not config_data:
        return args

    cli_provided = _collect_cli_provided_keys(argv=argv)
    merged: dict[str, Any] = {}

    global_section = config_data.get("global", {})
    if isinstance(global_section, dict):
        merged.update(global_section)

    local_section = config_data.get(section, {})
    if isinstance(local_section, dict):
        merged.update(local_section)

    for key, value in merged.items():
        if key in cli_provided:
            continue
        if hasattr(args, key):
            setattr(args, key, value)
    return args
