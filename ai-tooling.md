# AI Tooling, Engineering Decisions & Debug Log (`ai-tooling.md`)

**Author:** Solo Submission  
**AI Assistants Used:** Antigravity / Google Gemini coding & research workflows, Gemini API Documentation MCP (`gemini_search_docs`), Modern Web Guidance accessibility checks.

---

## 1. Where AI Accelerated Development Effectively

1. **Multi-Format Policy Corpus & Synthetic Persona Authoring (`policies/`, `mock_data/`):**
   Structured cross-references across 12 realistic company documents (`POL-001` to `POL-012`) in 4 distinct formats (`.md`, `.html`, `.pdf`, `.txt`) along with 8 internally consistent synthetic employees (`EMP-1001` through `EMP-1089`) were drafted and checked cleanly against boundary conditions (`5` vs `42` rolling workcation days, `55`-day probation cutoff, `Prod-Admin` clean travel loaner rule, and `1099` contractor benefit exclusions).
2. **FastAPI + Accessible Vanilla SPA Boilerplate (`web/`):**
   Consulting `modern-web-guidance` up front produced compliant keyboard-first markup (`<main>`, `<nav>`, `<aside>`, skip-to-main link, explicit `<label for>`, native `<dialog>.showModal()`, `aria-live` status regions, and IME-safe `Enter` handling checking `event.isComposing || event.keyCode === 229`).
3. **Structured Evaluation & Ablation Harness (`evaluation/`):**
   Rapid scaffolding of the 28-case benchmark (`evaluation/eval_dataset.json`) and automated ablation matrix (`k=2,5,8` x `hybrid` vs `dense_only`, plus Agentic MCP vs RAG-Only).

---

## 2. Issues & Edge Cases Requiring Direct Engineering Verification and Manual Fixes

AI-generated assumptions could not be trusted blindly; running real local Python verification, subprocess IPC checks, and benchmark evaluations surfaced six concrete engineering issues that were fixed iteratively:

1. **MCP Python SDK v2.3.0 Breaking API Changes (`mcp_server/`):**
   - *Initial Assumption:* Standard `from mcp.server.fastmcp import FastMCP` and 3-tuple unpacking `(r, w, get_session_id)` from `streamablehttp_client`.
   - *Verified Reality:* Probing the installed `mcp==2.3.0` package showed `FastMCP` was removed/renamed to `mcp.server.mcpserver.MCPServer`, `Tool.inputSchema` changed to `Tool.input_schema`, and `mcp.client.streamable_http.streamable_http_client` yields a 2-tuple `(read_stream, write_stream)`.
   - *Fix:* Audited exact runtime signatures (`inspect.signature`, `model_fields`) before coding `mcp_server/server.py` and `mcp_server/client.py`.

2. **Package Naming Shadowing Against PyPI `mcp`:**
   - *Root Issue:* A workspace directory literally named `mcp/` shadows `site-packages/mcp` whenever Python executes from the project root (`from mcp.server.mcpserver import ...`).
   - *Fix:* Placed the server and client inside `mcp_server/` (satisfying `"mcp/ or equivalent"`) so `mcp` SDK imports resolve deterministically in every test and container environment.

3. **Zero-Match Reciprocal Rank Fusion (RRF) Pollution (`rag/retriever.py`):**
   - *Symptom Observed:* Out-of-domain test queries (`"What is the best recipe for chocolate cake?"`, `"What is Northstar's policy on bringing pets to the Tokyo office?"`) initially received top rank-1 RRF scores (`1/61 = 0.01639`) from single generic words (`"best"`, `"northstar"`) or zero-overlap sorting.
   - *Fix:* Filtered zero-score BM25/Dense candidates out of RRF rank assignment, added generic filler stopwords, implemented query-focused sentence snippet scoring (`_make_snippet`), and added a combined RRF + lexical/cosine floor (`_is_below_threshold`).

4. **macOS Python Environment Quirks & Free-Tier Memory Guardrails:**
   - *Symptom Observed:* Local `uv` + Homebrew `python3.12` hit a `platform.mac_ver()` parse issue on macOS, while container builds targeting Render's 512 MB limit would OOM with PyTorch/sentence-transformers.
   - *Fix:* Bound local `.venv` cleanly to `/usr/local/bin/python3.13`, kept Docker pinned to `python:3.12-slim` (`.python-version`), prebuilt lightweight FAISS + SQLite indexes without `torch`, and added a startup fallback if `GEMINI_API_KEY` is missing or rate-limited.

5. **December Winter Recharge vs. SRE Blackout Distinction (`agent/llm_client.py`):**
   - *Symptom Observed:* First test run of Demo Task 2 (`Carlos Vega EMP-1018` requesting 5 days PTO starting Dec 21) conflated `"december"` / `"year-end"` with an SRE `blackout` freeze (`P2`).
   - *Fix:* Separated `mentions_holidays` (triggering `POL-002` Winter Recharge non-deduction lookup & `P3` manager+handoff workflow) from `during_blackout` (triggering `POL-001 Sec 5.1` `P2` VP+on-call swap rules only for release freezes or `blackout_team_flag=true`).

6. **Citation Snippet Truncation on Tabular HTML/PDF Rules:**
   - *Symptom Observed:* Benchmark cases `EVAL-03`, `EVAL-05`, `EVAL-08`, and `EVAL-12` retrieved the exact `#1` document ID (`POL-008`, `POL-010`, `POL-003`/`POL-005`, `POL-004`/`POL-008`), yet a naive `340`-char linear substring truncated quantitative caps (`$2,800`, `36 months`, `$50`, `MDM`).
   - *Fix:* Replaced substring slicing with sentence-level query-token relevance ranking (`_make_snippet`) and full-chunk synthesis (`_run_policy_qa`), lifting evaluation pass rate from `85.7%` to **`100.0% (28/28)`**.
