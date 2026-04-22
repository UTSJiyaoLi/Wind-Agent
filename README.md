# Wind Resource Agent

<p align="center">
  <a href="#english">English</a> |
  <a href="#涓枃">涓枃</a>
</p>

<p align="center">
  <a href="#english">
    <img src="https://img.shields.io/badge/Language-English-blue" alt="English">
  </a>
  <a href="#涓枃">
    <img src="https://img.shields.io/badge/璇█-涓枃-red" alt="涓枃">
  </a>
</p>

---

## English

A public-friendly FastAPI + RAG/LangGraph backend with a lightweight local Web UI for wind-energy intelligence workflows.

This repository intentionally avoids private usernames, hostnames, and internal infrastructure identifiers.

### Table of Contents

- [Wind Resource Agent](#wind-resource-agent)
  - [English](#english)
    - [Table of Contents](#table-of-contents)
    - [Overview](#overview)
    - [What Is Not Included](#what-is-not-included)
    - [Required Assets](#required-assets)
    - [Architecture](#architecture)
    - [Prerequisites](#prerequisites)
      - [Local machine](#local-machine)
      - [Remote machine](#remote-machine)
    - [Generic Host Configuration](#generic-host-configuration)
    - [Quick Start](#quick-start)
      - [1. Start or verify remote backend sessions](#1-start-or-verify-remote-backend-sessions)
      - [2. Open the local tunnel and Web UI](#2-open-the-local-tunnel-and-web-ui)
      - [3. Web UI fields](#3-web-ui-fields)
    - [Operations](#operations)
    - [Offline Container Build (Optional)](#offline-container-build-optional)
    - [Post-Startup Smoke Checks](#post-startup-smoke-checks)
    - [Project Layout](#project-layout)
    - [API Surface](#api-surface)
    - [Observability](#observability)
    - [Config Hygiene](#config-hygiene)
    - [Testing](#testing)
  - [涓枃](#涓枃)
    - [鐩綍](#鐩綍)
    - [姒傝堪](#姒傝堪)
    - [浠撳簱涓嶅寘鍚殑鍐呭](#浠撳簱涓嶅寘鍚殑鍐呭)
    - [蹇呭璧勬簮](#蹇呭璧勬簮)
    - [鏋舵瀯](#鏋舵瀯)
    - [鍓嶇疆鏉′欢](#鍓嶇疆鏉′欢)
      - [鏈湴鏈哄櫒](#鏈湴鏈哄櫒)
      - [杩滅鏈哄櫒](#杩滅鏈哄櫒)
    - [閫氱敤涓绘満閰嶇疆](#閫氱敤涓绘満閰嶇疆)
    - [蹇€熷紑濮媇(#蹇€熷紑濮?
      - [1. 鍚姩鎴栨鏌ヨ繙绔悗绔細璇漖(#1-鍚姩鎴栨鏌ヨ繙绔悗绔細璇?
      - [2. 鎵撳紑鏈湴闅ч亾鍜?Web UI](#2-鎵撳紑鏈湴闅ч亾鍜?web-ui)
      - [3. Web UI 瀛楁](#3-web-ui-瀛楁)
    - [杩愮淮鍛戒护](#杩愮淮鍛戒护)
    - [绂荤嚎瀹瑰櫒鏋勫缓锛堝彲閫夛級](#绂荤嚎瀹瑰櫒鏋勫缓鍙€?
    - [鍚姩鍚庢鏌(#鍚姩鍚庢鏌?
    - [椤圭洰缁撴瀯](#椤圭洰缁撴瀯)
    - [API 鎺ュ彛](#api-鎺ュ彛)
    - [鍙娴嬫€(#鍙娴嬫€?
    - [閰嶇疆瑙勮寖](#閰嶇疆瑙勮寖)
    - [娴嬭瘯](#娴嬭瘯)

### Overview

Wind Resource Agent is a FastAPI + RAG/LangGraph backend with a lightweight local Web UI for wind-energy intelligence workflows.

### What Is Not Included

To keep the repository reproducible and Git-friendly, the following private or large assets are not included:

1. Foundation/chat model weights
2. Embedding model weights
3. Reranker model weights
4. Vector database persistent data (Milvus data directories)
5. Internal datasets and metadata indexes
6. Prebuilt Apptainer/Singularity images (`*.sif`, offline tar)
7. Local/remote secret env files (`.env.local`, `.env.server`)

### Required Assets

Prepare equivalents of the following in your own environment:

- LLM endpoint reachable by the backend (local vLLM or remote API)
- Embedding model path
- Reranker model path
- Metadata files used by retrieval hydration
- Running Milvus service with collection already built
- Container image with Python/runtime dependencies (if using container deployment)

If these are missing, the service may start, but retrieval and agent calls will fail.

### Architecture

- **Backend runtime:** remote Linux server (recommended via `tmux` + `apptainer`)
- **Frontend runtime:** local browser (`docs/local_rag_web_v3.0.html`)
- **Connectivity:** local SSH tunnel to remote backend (`127.0.0.1:8787` by default)

### Prerequisites

#### Local machine

- Windows PowerShell (`.cmd` scripts)
- `ssh` client available in `PATH`
- Conda environment `rag_task` for ops/check scripts

#### Remote machine

- Linux with `tmux`, `curl`, and `apptainer`
- Accessible model and data paths
- Available Milvus and model-serving endpoints

### Generic Host Configuration

Use your own hosts:

- Jump host: `<jump-user>@<jump-host>`
- Target host: `<target-user>@<target-host>`

For `wind_services.py`, prefer environment variables instead of hardcoded values:

- `WIND_JUMP_HOST`
- `WIND_TARGET_HOST`
- `WIND_REMOTE_REPO`
- `WIND_REMOTE_BIND`
- `WIND_REMOTE_IMG_INFORHUB`
- `WIND_REMOTE_IMG_VLLM`
- `WIND_REMOTE_LOGDIR`
- `WIND_REMOTE_MODEL_EMBED`
- `WIND_REMOTE_MODEL_CHAT`
- `WIND_REMOTE_MODEL_ORCH`
- `WIND_REMOTE_MODEL_RERANKER`
- `WIND_REMOTE_META_JSONL`
- `WIND_REMOTE_META_IDX`

If your setup differs, update:

- `scripts/ops/wind_services.py`
- `scripts/ops/start_rag_web_local.cmd`

### Quick Start

#### 1. Start or verify remote backend sessions

```powershell
.\scripts\ops\wind_services.cmd start
.\scripts\ops\wind_services.cmd health
```

Alternative wrapper:

```powershell
.\scripts\ops\start_remote_rag_backend_gpu6000.cmd
```

#### 2. Open the local tunnel and Web UI

```powershell
.\scripts\ops\start_rag_web_local.cmd
```

Optional fixed local port:

```powershell
.\scripts\ops\start_rag_web_local.cmd 19087
```

#### 3. Web UI fields

- `Mode`: `RAG` or `Wind Agent Tool`
- `RAG Backend URL`: auto-injected by the startup script

### Operations

```powershell
.\scripts\ops\wind_services.cmd status
.\scripts\ops\wind_services.cmd start
.\scripts\ops\wind_services.cmd health
.\scripts\ops\wind_services.cmd restart
.\scripts\ops\wind_services.cmd stop
```

These scripts only manage `wind-*` tmux sessions.

### Offline Container Build (Optional)

Use your own Linux user path:

- `\home\<your-user>\container_build`

```bash
cd /mnt/c/wind-agent
bash scripts/ops/build_apptainer_in_wsl2.sh
```

Then upload the generated artifacts to your server and update image references in your ops config.

### Post-Startup Smoke Checks

```bash
# 1) health
curl -s http://127.0.0.1:8787/health

# 2) dependency self-check
python scripts/ops/check_langchain_stack.py

# 3) chat smoke test
curl -s -X POST http://127.0.0.1:8787/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"mode\":\"auto\",\"messages\":[{\"role\":\"user\",\"content\":\"What is wind turbine wake effect?\"}]}"
```

### Project Layout

```text
api/                         FastAPI endpoints
orchestration/               LangGraph orchestration
services/                    Domain and business logic
tools/                       Tool wrappers
scripts/search/rag_local_api.py  Unified RAG/Agent backend
scripts/ops/                 Ops scripts (remote start, tunnel, build)
docs/local_rag_web_v3.0.html Local Web UI
```

### API Surface

- `POST /api/chat`
  - `mode=llm_direct`
  - `mode=rag`
  - `mode=wind_agent`
- `POST /agent/chat`
- `POST /tasks`
- `GET /tasks/{task_id}`

### Observability

Default offline JSONL tracing:

- `OBS_BACKEND=jsonl`
- `OBS_ENABLED=true`
- `OBS_TRACE_DIR=storage/traces`
- `OBS_REDACTION_MODE=summary_id`

Optional LangSmith:

- `LANGSMITH_ENDPOINT`
- `LANGSMITH_PROJECT`
- `LANGSMITH_API_KEY`

### Config Hygiene

- Local: copy `.env.local.example` to `.env.local` and do not commit it
- Server: copy `.env.server.example` to `.env.server` and do not commit it
- Keep secrets and internal paths in environment variables, not in code or scripts

### Testing

```powershell
conda activate rag_task
pytest -q
```

<p align="right"><a href="#wind-resource-agent">Back to top</a></p>

---

## 涓枃

涓€涓潰鍚戦鑳芥櫤鑳藉伐浣滄祦鐨勫叕寮€鍙嬪ソ鍨?FastAPI + RAG/LangGraph 鍚庣锛岄厤鏈夎交閲忕骇鏈湴 Web UI銆?
鏈粨搴撳埢鎰忕Щ闄や簡绉佹湁鐢ㄦ埛鍚嶃€佷富鏈哄悕鍜屽唴閮ㄥ熀纭€璁炬柦鏍囪瘑銆?
### 鐩綍

- [姒傝堪](#姒傝堪)
- [浠撳簱涓嶅寘鍚殑鍐呭](#浠撳簱涓嶅寘鍚殑鍐呭)
- [蹇呭璧勬簮](#蹇呭璧勬簮)
- [鏋舵瀯](#鏋舵瀯)
- [鍓嶇疆鏉′欢](#鍓嶇疆鏉′欢)
- [閫氱敤涓绘満閰嶇疆](#閫氱敤涓绘満閰嶇疆)
- [蹇€熷紑濮媇(#蹇€熷紑濮?
- [杩愮淮鍛戒护](#杩愮淮鍛戒护)
- [绂荤嚎瀹瑰櫒鏋勫缓锛堝彲閫夛級](#绂荤嚎瀹瑰櫒鏋勫缓鍙€?
- [鍚姩鍚庢鏌(#鍚姩鍚庢鏌?
- [椤圭洰缁撴瀯](#椤圭洰缁撴瀯)
- [API 鎺ュ彛](#api-鎺ュ彛)
- [鍙娴嬫€(#鍙娴嬫€?
- [閰嶇疆瑙勮寖](#閰嶇疆瑙勮寖)
- [娴嬭瘯](#娴嬭瘯)

### 姒傝堪

Wind Resource Agent 鏄竴涓?FastAPI + RAG/LangGraph 鍚庣锛岄厤鏈夎交閲忕骇鏈湴 Web UI锛岀敤浜庨鑳芥櫤鑳藉伐浣滄祦銆?
### 浠撳簱涓嶅寘鍚殑鍐呭

涓轰簡淇濊瘉浠撳簱鍙鐜颁笖閫傚悎 Git 绠＄悊锛屼互涓嬬鏈夋垨澶т綋绉祫婧愪笉鍖呭惈鍦ㄤ粨搴撲腑锛?
1. Foundation/chat 妯″瀷鏉冮噸
2. Embedding 妯″瀷鏉冮噸
3. Reranker 妯″瀷鏉冮噸
4. 鍚戦噺鏁版嵁搴撴寔涔呭寲鏁版嵁锛圡ilvus 鏁版嵁鐩綍锛?5. 鍐呴儴鏁版嵁闆嗗拰鍏冩暟鎹储寮?6. 棰勬瀯寤虹殑 Apptainer/Singularity 闀滃儚锛坄*.sif`銆佺绾?tar锛?7. 鏈湴/杩滅瀵嗛挜鐜鏂囦欢锛坄.env.local`銆乣.env.server`锛?
### 蹇呭璧勬簮

璇峰湪浣犵殑鐜涓噯澶囦互涓嬬瓑浠疯祫婧愶細

- 鍚庣鍙闂殑 LLM 绔偣锛堟湰鍦?vLLM 鎴栬繙绋?API锛?- Embedding 妯″瀷璺緞
- Reranker 妯″瀷璺緞
- 妫€绱㈣ˉ鍏ㄦ墍闇€鐨勫厓鏁版嵁鏂囦欢
- 宸茶繍琛屽苟瀹屾垚 collection 鏋勫缓鐨?Milvus 鏈嶅姟
- Python/杩愯鏃朵緷璧栨墍鍦ㄧ殑瀹瑰櫒闀滃儚锛堝浣跨敤瀹瑰櫒閮ㄧ讲锛?
濡傛灉杩欎簺璧勬簮缂哄け锛屾湇鍔″彲鑳藉彲浠ュ惎鍔紝浣嗘绱㈠拰 agent 璋冪敤浼氬け璐ャ€?
### 鏋舵瀯

- **鍚庣杩愯鐜锛?* 杩滅 Linux 鏈嶅姟鍣紙鎺ㄨ崘 `tmux` + `apptainer`锛?- **鍓嶇杩愯鐜锛?* 鏈湴娴忚鍣紙`docs/local_rag_web_v3.0.html`锛?- **杩炴帴鏂瑰紡锛?* 鏈湴 SSH 闅ч亾杩炴帴杩滅鍚庣锛堥粯璁?`127.0.0.1:8787`锛?
### 鍓嶇疆鏉′欢

#### 鏈湴鏈哄櫒

- Windows PowerShell锛坄.cmd` 鑴氭湰锛?- `PATH` 涓彲鐢ㄧ殑 `ssh` 瀹㈡埛绔?- 鐢ㄤ簬杩愮淮/妫€鏌ヨ剼鏈殑 Conda 鐜 `rag_task`

#### 杩滅鏈哄櫒

- 瀹夎浜?`tmux`銆乣curl`銆乣apptainer` 鐨?Linux 鐜
- 鍙闂殑妯″瀷涓庢暟鎹矾寰?- 鍙敤鐨?Milvus 鍜屾ā鍨嬫湇鍔＄鐐?
### 閫氱敤涓绘満閰嶇疆

璇蜂娇鐢ㄤ綘鑷繁鐨勪富鏈猴細

- 璺虫澘鏈猴細`<jump-user>@<jump-host>`
- 鐩爣鏈猴細`<target-user>@<target-host>`

瀵逛簬 `wind_services.py`锛屽缓璁紭鍏堜娇鐢ㄧ幆澧冨彉閲忚€屼笉鏄‖缂栫爜锛?
- `WIND_JUMP_HOST`
- `WIND_TARGET_HOST`
- `WIND_REMOTE_REPO`
- `WIND_REMOTE_BIND`
- `WIND_REMOTE_IMG_INFORHUB`
- `WIND_REMOTE_IMG_VLLM`
- `WIND_REMOTE_LOGDIR`
- `WIND_REMOTE_MODEL_EMBED`
- `WIND_REMOTE_MODEL_CHAT`
- `WIND_REMOTE_MODEL_ORCH`
- `WIND_REMOTE_MODEL_RERANKER`
- `WIND_REMOTE_META_JSONL`
- `WIND_REMOTE_META_IDX`

濡傛灉浣犵殑鐜涓嶅悓锛岃淇敼锛?
- `scripts/ops/wind_services.py`
- `scripts/ops/start_rag_web_local.cmd`

### 蹇€熷紑濮?
#### 1. 鍚姩鎴栨鏌ヨ繙绔悗绔細璇?
```powershell
.\scripts\ops\wind_services.cmd start
.\scripts\ops\wind_services.cmd health
```

鍙€夊寘瑁呰剼鏈細

```powershell
.\scripts\ops\start_remote_rag_backend_gpu6000.cmd
```

#### 2. 鎵撳紑鏈湴闅ч亾鍜?Web UI

```powershell
.\scripts\ops\start_rag_web_local.cmd
```

鍙€夊浐瀹氭湰鍦扮鍙ｏ細

```powershell
.\scripts\ops\start_rag_web_local.cmd 19087
```

#### 3. Web UI 瀛楁

- `Mode`锛歚RAG` 鎴?`Wind Agent Tool`
- `RAG Backend URL`锛氱敱鍚姩鑴氭湰鑷姩娉ㄥ叆

### 杩愮淮鍛戒护

```powershell
.\scripts\ops\wind_services.cmd status
.\scripts\ops\wind_services.cmd start
.\scripts\ops\wind_services.cmd health
.\scripts\ops\wind_services.cmd restart
.\scripts\ops\wind_services.cmd stop
```

杩欎簺鑴氭湰鍙鐞?`wind-*` 鐨?tmux 浼氳瘽銆?
### 绂荤嚎瀹瑰櫒鏋勫缓锛堝彲閫夛級

璇蜂娇鐢ㄤ綘鑷繁鐨?Linux 鐢ㄦ埛璺緞锛?
- `\home\<your-user>\container_build`

```bash
cd /mnt/c/wind-agent
bash scripts/ops/build_apptainer_in_wsl2.sh
```

鐒跺悗灏嗙敓鎴愮殑鏋勪欢涓婁紶鍒版湇鍔″櫒锛屽苟鍦ㄨ繍缁撮厤缃腑鏇存柊闀滃儚寮曠敤銆?
### 鍚姩鍚庢鏌?
```bash
# 1) health
curl -s http://127.0.0.1:8787/health

# 2) dependency self-check
python scripts/ops/check_langchain_stack.py

# 3) chat smoke test
curl -s -X POST http://127.0.0.1:8787/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"mode\":\"auto\",\"messages\":[{\"role\":\"user\",\"content\":\"What is wind turbine wake effect?\"}]}"
```

### 椤圭洰缁撴瀯

```text
api/                         FastAPI 鎺ュ彛
orchestration/               LangGraph 缂栨帓
services/                    棰嗗煙涓庝笟鍔￠€昏緫
tools/                       宸ュ叿灏佽
scripts/search/rag_local_api.py  缁熶竴 RAG/Agent 鍚庣
scripts/ops/                 杩愮淮鑴氭湰锛堣繙绔惎鍔ㄣ€侀毀閬撱€佹瀯寤猴級
docs/local_rag_web_v3.0.html 鏈湴 Web UI
```

### API 鎺ュ彛

- `POST /api/chat`
  - `mode=llm_direct`
  - `mode=rag`
  - `mode=wind_agent`
- `POST /agent/chat`
- `POST /tasks`
- `GET /tasks/{task_id}`

### 鍙娴嬫€?
榛樿绂荤嚎 JSONL tracing锛?
- `OBS_BACKEND=jsonl`
- `OBS_ENABLED=true`
- `OBS_TRACE_DIR=storage/traces`
- `OBS_REDACTION_MODE=summary_id`

鍙€?LangSmith锛?
- `LANGSMITH_ENDPOINT`
- `LANGSMITH_PROJECT`
- `LANGSMITH_API_KEY`

### 閰嶇疆瑙勮寖

- 鏈湴锛氬鍒?`.env.local.example` 涓?`.env.local`锛屼笉瑕佹彁浜?- 鏈嶅姟鍣細澶嶅埗 `.env.server.example` 涓?`.env.server`锛屼笉瑕佹彁浜?- 灏嗗瘑閽ュ拰鍐呴儴璺緞淇濆瓨鍦ㄧ幆澧冨彉閲忎腑锛岃€屼笉鏄唬鐮佹垨鑴氭湰閲?
### 娴嬭瘯

```powershell
conda activate rag_task
pytest -q
```

<p align="right"><a href="#wind-resource-agent">杩斿洖椤堕儴</a></p>
