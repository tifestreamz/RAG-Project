# Deployment Documentation (`deployed.md`)

## 1. Service & Platform Summary

- **Hosting Platform:** Render Free Web Service (Docker runtime via `render.yaml` & `Dockerfile`)
- **Live Base URL:** `https://northstar-hr-agentic-rag.onrender.com`
- **Health Endpoint:** `https://northstar-hr-agentic-rag.onrender.com/health`
- **Interactive API Docs (Swagger):** `https://northstar-hr-agentic-rag.onrender.com/docs`
- **GitHub Repository:** `https://github.com/tifestreamz/RAG-Project` (public; if switched to private, grant read access to **`quantic-grader`**)

---

## 2. Configured Environment Variables (No Secret Values Committed)

| Variable | Configured Value | Purpose |
| :--- | :--- | :--- |
| `GEMINI_API_KEY` | *(Set privately in Render Dashboard)* | Enables live `gemini-3.5-flash-lite` Interactions API & `gemini-embedding-001` |
| `LLM_PROVIDER` | `auto` | Uses `gemini` when key is set; falls back safely to deterministic `mock` MCP runner |
| `EMBEDDING_PROVIDER` | `auto` | Uses `gemini` when key is set (with safe boot fallback to prebuilt `hash` index) |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Target Gemini reasoning + function-calling model |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | `768`-dim L2-normalized document & query embeddings |
| `MCP_TRANSPORT` | `stdio` | Runs `mcp_server.server` in-container over JSON-RPC stdio (no secondary port required) |
| `RAG_TOP_K` | `5` | Optimal Hybrid RRF retrieval cutoff from ablations |
| `RANDOM_SEED` | `42` | Reproducible seeding |
| `PORT` | *(Injected dynamically by Render)* | Bound in container startup CMD `--port ${PORT:-8000}` |

---

## 3. Memory Footprint & Cold-Start Behavior

- **RAM Efficiency (`< 512 MB` Free Tier):** Zero `torch` or `sentence-transformers` weights are loaded in container memory. Embeddings execute via the Google Gemini REST API (`google-genai`) or lightweight pure-NumPy hashing, while `faiss-cpu`, `rank-bm25`, and `chunks.db` occupy minimal memory (~120 MB total Python + FastAPI + child MCP server footprint).
- **Prebuilt Index at Image Build Time:** `Dockerfile` runs `python -m rag.ingest --provider hash` during `docker build`, baking `data/rag_index/` directly into the image so cold container startup only loads existing files and starts the MCP stdio session.
- **Cold-Start Measurement:**
  - **Render Free Tier Sleep Behavior:** Render Free Web Services spin down after **15 minutes of HTTP inactivity** and wake automatically on the next inbound HTTP request (`/`, `/health`, `/chat`). Expect a **~25–50 second cold-start delay** on the very first request after sleep, after which warm requests complete in milliseconds/seconds.
  - **Measured Local Application Startup Timing:** Verified via live Uvicorn (`127.0.0.1:8765`) + child `stdio` MCP subprocess check: **`3,083.04 ms` (~3.08 s)** to HTTP 200 `/health` readiness (`12` docs / `117` chunks, `8` discovered MCP tools); live Demo Task 1 completed in `75.47 ms` (`7` MCP steps) and Demo Task 2 in `13.43 ms` (`8` MCP steps).
  - **Measured Live Render Timing (Warm, verified `2026-11-14`):**
    - `GET /health`: HTTP `200` in **`682 ms` – `1,250 ms`** (`status: ok`, `corpus_docs: 12`, `corpus_chunks: 117`, `embedding_provider: gemini`, `embedding_model: gemini-embedding-001`, `llm_provider: gemini`, `gemini_model: gemini-3.5-flash-lite`, `mcp_connected: true`, `8` MCP tools).
    - `GET /`, `GET /static/app.js`, and `GET /docs`: HTTP `200` in **`642 ms`**, **`1,051 ms`**, and **`962 ms`**.
    - `POST /chat` (Live Gemini `gemini-3.5-flash-lite` + Hybrid RRF `gemini-embedding-001` + MCP `stdio`):
      - Demo Task 1 (`EMP-1042` 6-week Lisbon workcation): HTTP `200`, **`10,378.82 ms`** total (`9,705.35 ms` app latency), `7` MCP tool steps, `5` policy citations, generated email draft + unconfirmed mock ticket preview (`tickets` count remained `3`).
      - Demo Task 2 (`EMP-1018` year-end PTO + Winter Recharge): HTTP `200`, **`20,843.00 ms`** total (`20,174.03 ms` app latency), `5` MCP tool steps, `5` policy citations, escalation + unconfirmed mock ticket preview.
      - Off-domain guardrail check (`"Give me a recipe for chocolate cake."`): HTTP `200`, **`3,275.73 ms`** total (`2,595.91 ms` app latency), `status: abstained` (`abstained: true`), `guardrail_flags: []`.
    - *(Service was already warm when measured; after 15+ minutes of Render Free Tier idle sleep, expect cold container wake latency plus ~1–2 minutes of non-blocking background `gemini-embedding-001` index upgrade while `/health` and queries remain available on the prebuilt `hash` index.)*

---

## 4. Verification & Troubleshooting Notes

1. **Verifying Live Health & MCP Registration:**
   ```bash
   curl -s https://northstar-hr-agentic-rag.onrender.com/health | python -m json.tool
   ```
   Confirm `"status": "ok"`, `"corpus_docs": 12`, `"mcp_connected": true`, and all 8 tool names in `"mcp_tools"`.
2. **GitHub Actions CI Gate (`.github/workflows/ci.yml`):**
   Every push/PR on `main` automatically verifies `rag.ingest`, `pytest -v`, and `evaluation.run_eval` before the optional `deploy` job posts to `RENDER_DEPLOY_HOOK_URL`.
3. **Resetting Mock Ticket State After Testing:**
   Mock tickets persisted through `/confirm` are stored safely in `mock_data/tickets.json` with `"is_mock": true`. Seed tickets are `HR-1001` through `HR-1003`.
