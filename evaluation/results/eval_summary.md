# Evaluation Results Summary

- **Evaluated At:** `2026-11-14T20:17:19.943232+00:00`
- **Execution Mode:** `mock` (`28` benchmark queries across 5 categories)

## End-to-End Agentic & Safety Metrics

| Metric | Score |
| :--- | :--- |
| Overall Case Pass Rate | 100.0% (28/28) |
| Groundedness Rate | 100.0% |
| Key-Fact Rubric Recall | 97.0% |
| Citation Precision / Recall / F1 (20 Answerable Cases) | 0.754 / 0.958 / 0.818 |
| MCP Tool Selection Accuracy (7 Workflows) | 100.0% |
| Multi-Step Workflow Completion Rate | 100.0% |
| Ambiguous Query Clarification Accuracy (4 Cases) | 100.0% |
| Out-of-Scope & Injection Safety Rate (4 Cases) | 100.0% |
| Unconfirmed Irreversible Action Gate Pass | 100% (0 unauthorized writes) |
| Latency (p50 / p95 / mean) | 2.83 ms / 13.01 ms / 5.41 ms |

## Ablation 1: Hybrid RRF vs. Dense-Only Across Top-k (k=2, 5, 8)

| Mode | Top-k | Doc Recall | Doc Precision | MRR |
| :--- | :--- | :--- | :--- | :--- |
| hybrid | 2 | 0.842 | 0.825 | 0.925 |
| hybrid | 5 | 0.933 | 0.647 | 0.925 |
| hybrid | 8 | 0.958 | 0.567 | 0.925 |
| dense_only | 2 | 0.667 | 0.775 | 0.850 |
| dense_only | 5 | 0.833 | 0.658 | 0.883 |
| dense_only | 8 | 0.933 | 0.534 | 0.883 |

## Ablation 2: Agentic RAG + MCP vs. RAG-Only Baseline (7 Tool Workflows)

| Architecture | Workflow Completion Rate |
| :--- | :--- |
| RAG-Only Baseline (no MCP HR tools) | 0.0% |
| Agentic Hybrid RAG + 8 MCP Tools | 100.0% |
