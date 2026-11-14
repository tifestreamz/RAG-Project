# Northstar HR Policy & Operations Copilot (Agentic Hybrid RAG + MCP)

An end-to-end **Agentic Retrieval-Augmented Generation (Hybrid RAG) + Model Context Protocol (MCP)** web application for *Northstar Cloud Labs, Inc.* designed to answer HR policy questions with verifiable section/page citations, evaluate employee eligibility against structured HR records, draft compliant approval communications, and enforce human-in-the-loop confirmation before writing mock HR tickets.

- **Deployment Readiness:** Configured for **Render Free Tier** via [Dockerfile](Dockerfile) and [render.yaml](render.yaml) (live deployment details & cold-start notes documented in [deployed.md](deployed.md)).
- **Key Architecture Docs:** [design-and-evaluation.md](design-and-evaluation.md) | [ai-tooling.md](ai-tooling.md) | [mcp_server/README.md](mcp_server/README.md)

---

## Core Capabilities

- **Multi-Format Policy Corpus (`policies/`):** 12 synthetic company policies (`POL-001` to `POL-012`) totaling **8,907 words (~34.6 equivalent pages)** across **4 formats** (`.md`, `.html`, `.pdf`, `.txt`).
- **Hybrid RAG Pipeline (`rag/`):**
  - Heading-aware chunking (`350` words/chunk, `60`-word overlap, `117` indexed chunks).
  - Dual retrieval with **FAISS `IndexFlatIP`** (768-dim `gemini-embedding-001` or deterministic signed n-gram hash fallback) + **`BM25Okapi`** sparse search + HR domain synonym expansion + metadata filters + **Reciprocal Rank Fusion (`RRF`)** + out-of-domain threshold gating.
- **Model Context Protocol (`mcp_server/`):**
  - 8 structured tools exposed through `mcp.server.mcpserver.MCPServer` (`stdio` default, `streamable-http` optional).
  - The orchestrator discovers tools dynamically via `ClientSession.list_tools()` and invokes tools exclusively via `ClientSession.call_tool()`.
- **Safety Guardrails & Human Confirmation (`agent/`):**
  - Input prompt-injection blocker, out-of-scope advice refusal, and missing-ID clarification prompts.
  - Strictly operational tool traces (`step`, `tool_name`, `arguments`, `output_summary`, `citations`, `duration_ms`) with **zero chain-of-thought exposure**.
  - Irreversible mock ticket writes (`create_mock_hr_ticket`) always run in `confirmed=False` preview mode during chat turns and persist (`is_mock: true`) only upon explicit `POST /confirm` confirmation.
- **Accessible Web Console (`web/`):** Keyboard-navigable FastAPI + Vanilla HTML/CSS/JS SPA featuring 1-click Demo Workflows, Citation & Verbatim Snippet Viewer, Operational MCP Trace Inspector, Copyable Email Drafts, and Native Modal Ticket Confirmation.

---

## Repository Structure

```text
.
├── .github/workflows/ci.yml        # GitHub Actions CI (RAG build, pytest, eval gate) + Render deploy hook
├── .env.example                    # Template environment variables (never commit real API keys)
├── .python-version                 # Python 3.12 runtime pin
├── Dockerfile                      # Free-tier container build with prebuilt FAISS/SQLite index
├── render.yaml                     # Render Free Web Service IaC blueprint
├── app_config.py                   # Pydantic settings & deterministic seed (RANDOM_SEED=42)
├── policies/                       # 12 synthetic HR policy docs (.md, .html, .pdf, .txt)
├── mock_data/                      # Synthetic JSON records (employees, pto_balances, benefits, tickets)
├── scripts/generate_pdf_policies.py# Reproducible PDF policy generator
├── rag/                            # Ingestion, embeddings (Gemini + hash), Hybrid FAISS+BM25+RRF retriever
├── mcp_server/                     # MCPServer + ClientManager (stdio / streamable-http) & 8 tools
├── agent/                          # Guardrails, compliance evaluator, Gemini Interactions & Mock runners, orchestrator
├── web/                            # FastAPI endpoints (/, /health, /demo-tasks, /tickets, /chat, /confirm) + SPA UI
├── tests/                          # Unit, MCP stdio integration, FastAPI health, and workflow tests
└── evaluation/                     # 28-case benchmark, retrieval & architecture ablations, saved reports
```

---

## Quickstart (Local Development)

### 1. Create Environment & Install Dependencies
```bash
python3.12 -m venv .venv   # or python3.13 locally
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # Optional: add GEMINI_API_KEY for live Gemini 3.5 Flash-Lite + embeddings
```

> Without a `GEMINI_API_KEY`, `LLM_PROVIDER=auto` and `EMBEDDING_PROVIDER=auto` automatically select the deterministic offline MCP Mock Runner and 768-dim signed n-gram hash embeddings so the full system runs locally and in CI with zero API cost.

### 2. Build Hybrid RAG Index
```bash
python -m rag.ingest --provider auto
```

### 3. Run the Web Application
```bash
uvicorn web.app:app --host 0.0.0.0 --port 8000
```
Open `http://127.0.0.1:8000` in your browser, or inspect Swagger API docs at `http://127.0.0.1:8000/docs`.

### 4. Reproducible Demo CLI Commands (`curl`)

**Health & MCP Readiness Check:**
```bash
curl -s http://127.0.0.1:8000/health | python -m json.tool
```

**Demo Task 1 (Maya Lin `EMP-1042` 6-Week Lisbon Workcation Compliance + Escalation Draft):**
```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Can Maya Lin (EMP-1042) take a 6-week remote workcation from Lisbon, Portugal? Check policy compliance, draft an approval/escalation email, and prepare a mock HR ticket."}' | python -m json.tool
```

**Demo Task 2 (Carlos Vega `EMP-1018` Year-End PTO + Winter Recharge + Confirmation Gate):**
```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Carlos Vega (EMP-1018) wants to take 5 PTO days starting Dec 21 through year-end. Check his PTO balance, explain how Winter Recharge applies, and prepare a mock HR ticket."}' | python -m json.tool
```

---

## Testing & Evaluation

```bash
# Run full unit, real MCP stdio discovery/call, FastAPI lifespan/health, and workflow suite
pytest -v

# Run 28-case evaluation benchmark + retrieval (k=2,5,8; Hybrid vs Dense) + RAG-only ablations
python -m evaluation.run_eval --provider mock
```

Generated reports are saved to `evaluation/results/eval_report.json` and `evaluation/results/eval_summary.md`.

---

## Solo Submission & Deployment Checklist

1. Push repository to GitHub (private or public; grant read access to **`quantic-grader`**).
2. Add `GEMINI_API_KEY` (optional/recommended for live LLM) and `RENDER_DEPLOY_HOOK_URL` (optional for GitHub Actions `deploy` job) in Render / GitHub Secrets.
3. Deploy via Render Blueprint (`render.yaml`) or Docker Web Service, verify `/health`, and update the live URL + measured cold-start timing in [deployed.md](deployed.md).
