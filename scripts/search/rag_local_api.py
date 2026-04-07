"""本地 RAG HTTP 服务壳层：处理请求、调用 rag 服务层并返回 JSON。"""

import json
import mimetypes
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from typing import Any

try:
    from scripts.search.rag_langchain import format_contexts_for_prompt
except Exception:
    def format_contexts_for_prompt(contexts: list[dict[str, Any]]) -> str:
        blocks: list[str] = []
        for item in contexts:
            blocks.append(
                "\n".join(
                    [
                        f"[Context #{item.get('rank')}]",
                        f"doc_id: {item.get('doc_id')}",
                        f"chunk_id: {item.get('chunk_id')}",
                        f"score: {item.get('score')}",
                        f"text: {item.get('text')}",
                    ]
                )
            )
        return "\n\n".join(blocks)

# Ensure repo root is importable when executing:
# python scripts/search/rag_local_api.py
repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

try:
    from orchestration.langgraph_flow import run_wind_agent_flow
except Exception:
    run_wind_agent_flow = None  # type: ignore

from rag.service import handle_chat_request

from rag.retrieval import (
    build_citations_and_media,
    build_preview_images,
    call_vllm_chat,
    render_citation_index,
    retrieve_contexts,
    summarize_media_for_prompt,
)
from rag.runtime import Runtime, parse_args


def build_app_handler(runtime: Runtime):
    repo_root_local = Path(__file__).resolve().parents[2]
    allowed_asset_roots = [
        "/work/Data/embedding/assets",
        "/share/home/lijiyao/CCCC/Data/embedding/assets",
        str(repo_root_local / "wind_data"),
        str(repo_root_local / "storage"),
    ]

    class Handler(BaseHTTPRequestHandler):
        server_version = "LocalRagApi/0.1"

        def _send_json(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "service": "rag_local_api",
                        "collection": runtime.args.collection,
                        "llm_base_url": runtime.args.llm_base_url,
                        "observability": getattr(runtime, "tracer", None).info() if getattr(runtime, "tracer", None) else {},
                    },
                )
                return
            if self.path.startswith("/api/asset"):
                try:
                    parsed = urlparse(self.path)
                    q = parse_qs(parsed.query)
                    path_val = (q.get("path") or [""])[0].strip()
                    if not path_val:
                        self._send_json(400, {"ok": False, "error": "missing path"})
                        return
                    real = os.path.realpath(path_val)
                    allowed = any(real.startswith(root + os.sep) or real == root for root in allowed_asset_roots)
                    if not allowed:
                        self._send_json(403, {"ok": False, "error": "path not allowed"})
                        return
                    if not os.path.exists(real) or not os.path.isfile(real):
                        self._send_json(404, {"ok": False, "error": "asset not found"})
                        return
                    ctype = mimetypes.guess_type(real)[0] or "application/octet-stream"
                    with open(real, "rb") as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Cache-Control", "public, max-age=300")
                    self.end_headers()
                    self.wfile.write(data)
                    return
                except Exception as exc:
                    self._send_json(500, {"ok": False, "error": str(exc)})
                    return
            self._send_json(404, {"ok": False, "error": "Not Found"})

        def do_POST(self) -> None:
            if self.path not in {"/api/chat", "/api/retrieve"}:
                self._send_json(404, {"ok": False, "error": "Not Found"})
                return

            started = time.time()
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
                req = json.loads(raw)
                if handle_chat_request is None:
                    raise RuntimeError("rag.service.handle_chat_request is unavailable")
                status_code, payload = handle_chat_request(
                    request_path=self.path,
                    req=req,
                    runtime=runtime,
                    run_wind_agent_flow=run_wind_agent_flow,
                    call_vllm_chat=call_vllm_chat,
                    retrieve_contexts=retrieve_contexts,
                    build_citations_and_media=build_citations_and_media,
                    build_preview_images=build_preview_images,
                    format_contexts_for_prompt=format_contexts_for_prompt,
                    summarize_media_for_prompt=summarize_media_for_prompt,
                    render_citation_index=render_citation_index,
                )
                self._send_json(status_code, payload)
            except Exception as exc:
                self._send_json(
                    500,
                    {
                        "ok": False,
                        "error": str(exc),
                        "elapsed_seconds": round(time.time() - started, 4),
                    },
                )

    return Handler


def main() -> None:
    args = parse_args()
    runtime = Runtime(args)
    print(f"[rag_local_api] starting http://{args.host}:{args.port}")
    print(f"[rag_local_api] milvus={args.uri} collection={args.collection}")
    print(f"[rag_local_api] llm_base_url={args.llm_base_url}")
    if getattr(runtime, "tracer", None):
        print(f"[rag_local_api] observability={runtime.tracer.info()}")
    server = ThreadingHTTPServer((args.host, args.port), build_app_handler(runtime))
    server.serve_forever()


if __name__ == "__main__":
    main()

