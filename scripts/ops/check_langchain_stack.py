"""Check LangChain/LangGraph/LangSmith package importability and versions."""

from __future__ import annotations

import importlib
from importlib import metadata


PKGS = [
    ("langchain", "langchain"),
    ("langchain-core", "langchain_core"),
    ("langchain-community", "langchain_community"),
    ("langchain-openai", "langchain_openai"),
    ("langchain-text-splitters", "langchain_text_splitters"),
    ("langgraph", "langgraph"),
    ("langsmith", "langsmith"),
]


def main() -> int:
    ok = True
    print("LangChain stack self-check")
    print("-" * 40)
    for dist_name, module_name in PKGS:
        try:
            version = metadata.version(dist_name)
        except Exception as exc:
            ok = False
            print(f"[MISSING_DIST] {dist_name}: {exc}")
            continue
        try:
            importlib.import_module(module_name)
            print(f"[OK] {dist_name:<26} version={version}")
        except Exception as exc:
            ok = False
            print(f"[IMPORT_FAIL] {dist_name:<20} version={version} err={exc}")
    print("-" * 40)
    print("RESULT=PASS" if ok else "RESULT=FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

