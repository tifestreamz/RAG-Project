"use strict";

const state = {
  pendingTicket: null,
  lastDraft: null,
  busy: false,
};

const els = {
  healthPill: document.getElementById("health-pill"),
  mcpPill: document.getElementById("mcp-pill"),
  llmPill: document.getElementById("llm-pill"),
  srStatus: document.getElementById("sr-status"),
  errorBanner: document.getElementById("error-banner"),
  demoButtons: document.getElementById("demo-buttons"),
  personaList: document.getElementById("persona-list"),
  ticketsList: document.getElementById("tickets-list"),
  refreshTicketsBtn: document.getElementById("refresh-tickets-btn"),
  chatForm: document.getElementById("chat-form"),
  queryInput: document.getElementById("query-input"),
  providerSelect: document.getElementById("provider-select"),
  sendBtn: document.getElementById("send-btn"),
  clearBtn: document.getElementById("clear-btn"),
  modeBadge: document.getElementById("mode-badge"),
  latencyBadge: document.getElementById("latency-badge"),
  answerContainer: document.getElementById("answer-container"),
  escalationCard: document.getElementById("escalation-card"),
  escalationPriorityPill: document.getElementById("escalation-priority-pill"),
  escalationBody: document.getElementById("escalation-body"),
  draftCard: document.getElementById("draft-card"),
  draftMeta: document.getElementById("draft-meta"),
  draftBody: document.getElementById("draft-body"),
  copyDraftBtn: document.getElementById("copy-draft-btn"),
  confirmCard: document.getElementById("confirm-card"),
  confirmPreviewBody: document.getElementById("confirm-preview-body"),
  openConfirmDialogBtn: document.getElementById("open-confirm-dialog-btn"),
  confirmDialog: document.getElementById("confirm-dialog"),
  dialogPayloadPreview: document.getElementById("dialog-payload-preview"),
  dialogCancelBtn: document.getElementById("dialog-cancel-btn"),
  dialogConfirmBtn: document.getElementById("dialog-confirm-btn"),
  tabCitations: document.getElementById("tab-citations"),
  tabTrace: document.getElementById("tab-trace"),
  panelCitations: document.getElementById("panel-citations"),
  panelTrace: document.getElementById("panel-trace"),
  citationsCount: document.getElementById("citations-count"),
  traceCount: document.getElementById("trace-count"),
  citationsList: document.getElementById("citations-list"),
  traceList: document.getElementById("trace-list"),
};

function announce(text) {
  els.srStatus.textContent = text;
}

function showError(msg) {
  if (!msg) {
    els.errorBanner.hidden = true;
    els.errorBanner.textContent = "";
    return;
  }
  els.errorBanner.textContent = msg;
  els.errorBanner.hidden = false;
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = String(value ?? "");
  return div.innerHTML;
}

function renderSafeMarkdown(mdText) {
  const lines = String(mdText || "").split(/\r?\n/);
  const out = [];
  let inList = false;

  const formatInline = (raw) =>
    escapeHtml(raw)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      if (inList) {
        out.push("</ul>");
        inList = false;
      }
      continue;
    }
    if (trimmed.startsWith("### ")) {
      if (inList) {
        out.push("</ul>");
        inList = false;
      }
      out.push(`<h3>${formatInline(trimmed.slice(4))}</h3>`);
    } else if (trimmed.startsWith("- ")) {
      if (!inList) {
        out.push("<ul>");
        inList = true;
      }
      out.push(`<li>${formatInline(trimmed.slice(2))}</li>`);
    } else {
      if (inList) {
        out.push("</ul>");
        inList = false;
      }
      out.push(`<p>${formatInline(trimmed)}</p>`);
    }
  }
  if (inList) out.push("</ul>");
  return out.join("");
}

function switchTab(tabName) {
  const isCitations = tabName === "citations";
  els.tabCitations.classList.toggle("active", isCitations);
  els.tabTrace.classList.toggle("active", !isCitations);
  els.tabCitations.setAttribute("aria-selected", String(isCitations));
  els.tabTrace.setAttribute("aria-selected", String(!isCitations));
  els.panelCitations.hidden = !isCitations;
  els.panelTrace.hidden = isCitations;
}

async function loadHealth() {
  try {
    const res = await fetch("/health");
    const data = await res.json();
    els.healthPill.textContent = `Corpus: ${data.corpus_docs} docs / ${data.corpus_chunks} chunks`;
    els.healthPill.className = "pill pill-ok";
    const toolCount = (data.mcp_tools || []).length;
    els.mcpPill.textContent = `MCP (${data.mcp_transport}): ${toolCount} tools`;
    els.mcpPill.className = data.mcp_connected ? "pill pill-ok" : "pill pill-warn";
    els.llmPill.textContent = `LLM: ${data.llm_provider}`;
    els.llmPill.className = "pill pill-neutral";
  } catch (err) {
    els.healthPill.textContent = "Health check failed";
    els.healthPill.className = "pill pill-danger";
  }
}

async function loadDemoTasks() {
  try {
    const res = await fetch("/demo-tasks");
    const data = await res.json();

    els.demoButtons.innerHTML = "";
    for (const task of data.demo_tasks || []) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "demo-btn";
      btn.innerHTML = `<span class="demo-title">${escapeHtml(task.title)}</span><span class="demo-badge">${escapeHtml(task.badge)}</span>`;
      btn.addEventListener("click", () => {
        els.queryInput.value = task.prompt;
        els.chatForm.requestSubmit();
      });
      els.demoButtons.appendChild(btn);
    }

    els.personaList.innerHTML = "";
    for (const p of data.personas || []) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "persona-btn";
      btn.textContent = `${p.employee_id} — ${p.name} (${p.security_tier})`;
      btn.addEventListener("click", () => {
        const prefix = els.queryInput.value.trim();
        els.queryInput.value = prefix ? `${prefix} [${p.employee_id}]` : `${p.name} (${p.employee_id}) `;
        els.queryInput.focus();
      });
      li.appendChild(btn);
      els.personaList.appendChild(li);
    }
  } catch (err) {
    showError("Unable to load demo workflows.");
  }
}

async function loadTickets() {
  try {
    const res = await fetch("/tickets");
    const data = await res.json();
    els.ticketsList.innerHTML = "";
    for (const t of [...(data.tickets || [])].reverse()) {
      const li = document.createElement("li");
      li.className = "ticket-item";
      li.innerHTML = `<strong>${escapeHtml(t.ticket_id)}</strong> &bull; ${escapeHtml(t.priority)} &bull; ${escapeHtml(t.status)}<br>${escapeHtml(t.employee_id)}: ${escapeHtml(t.summary)}`;
      els.ticketsList.appendChild(li);
    }
  } catch (err) {
    // Non-blocking error
  }
}

function renderResult(data) {
  els.modeBadge.textContent = `${data.mode_used || "agent"} (${data.status || "ok"})`;
  els.latencyBadge.textContent = `${data.latency_ms ?? 0} ms`;
  els.answerContainer.innerHTML = renderSafeMarkdown(data.answer);

  // Escalation card
  if (data.escalation && data.escalation.recommended) {
    els.escalationCard.hidden = false;
    els.escalationPriorityPill.textContent = `${data.escalation.priority} — ${data.escalation.status || "ESCALATION"}`;
    const routing = (data.escalation.routing || []).map((r) => `<li>${escapeHtml(r)}</li>`).join("");
    const reasons = (data.escalation.reasons || []).map((r) => `<li>${escapeHtml(r)}</li>`).join("");
    els.escalationBody.innerHTML = `
      ${reasons ? `<p><strong>Compliance Findings:</strong></p><ul>${reasons}</ul>` : ""}
      ${routing ? `<p><strong>Required Routing / Approvers:</strong></p><ul>${routing}</ul>` : ""}
    `;
  } else {
    els.escalationCard.hidden = true;
  }

  // Draft email
  if (data.draft_email) {
    state.lastDraft = data.draft_email;
    els.draftCard.hidden = false;
    const cc = (data.draft_email.cc || []).join(", ") || "None";
    els.draftMeta.innerHTML = `<strong>To:</strong> ${escapeHtml(data.draft_email.to)}<br><strong>CC:</strong> ${escapeHtml(cc)}<br><strong>Subject:</strong> ${escapeHtml(data.draft_email.subject)}`;
    els.draftBody.textContent = data.draft_email.body || "";
  } else {
    state.lastDraft = null;
    els.draftCard.hidden = true;
  }

  // Pending ticket confirmation gate
  if (data.pending_confirmation) {
    state.pendingTicket = data.pending_confirmation;
    els.confirmCard.hidden = false;
    const pt = data.pending_confirmation;
    els.confirmPreviewBody.innerHTML = `
      <strong>Employee:</strong> ${escapeHtml(pt.employee_id)} &bull;
      <strong>Priority:</strong> ${escapeHtml(pt.priority)} &bull;
      <strong>Category:</strong> ${escapeHtml(pt.category)}<br>
      <strong>Summary:</strong> ${escapeHtml(pt.summary)}<br>
      <strong>Policies:</strong> ${escapeHtml((pt.policy_references || []).join(", "))}
    `;
  } else {
    state.pendingTicket = null;
    els.confirmCard.hidden = true;
  }

  // Citations
  const citations = data.citations || [];
  els.citationsCount.textContent = String(citations.length);
  els.citationsList.innerHTML = "";
  if (!citations.length) {
    els.citationsList.innerHTML = `<p class="placeholder-text">No policy citations attached for this response.</p>`;
  } else {
    for (const c of citations) {
      const div = document.createElement("div");
      div.className = "citation-item";
      div.innerHTML = `
        <div class="citation-head">
          <span>${escapeHtml(c.doc_id)} (${escapeHtml(c.page_or_anchor)})</span>
          <span class="pill pill-neutral">${escapeHtml(c.file_format || "policy")}</span>
        </div>
        <div class="citation-sec">${escapeHtml(c.doc_title)} &mdash; ${escapeHtml(c.section_path)}</div>
        <p class="citation-snippet">${escapeHtml(c.snippet)}</p>
      `;
      els.citationsList.appendChild(div);
    }
  }

  // Operational MCP trace
  const trace = data.trace || [];
  els.traceCount.textContent = String(trace.length);
  els.traceList.innerHTML = "";
  if (!trace.length) {
    els.traceList.innerHTML = `<li class="trace-item"><p class="placeholder-text">No MCP tool calls executed (handled directly by input guardrails).</p></li>`;
  } else {
    for (const step of trace) {
      const li = document.createElement("li");
      li.className = "trace-item";
      const pillCls = step.status === "ok" ? "pill-ok" : "pill-danger";
      li.innerHTML = `
        <div class="trace-item-head">
          <span>#${step.step} ${escapeHtml(step.tool_name)}</span>
          <span class="pill ${pillCls}">${escapeHtml(step.status)} &bull; ${step.duration_ms}ms</span>
        </div>
        <div class="trace-args">${escapeHtml(JSON.stringify(step.arguments))}</div>
        <div>${escapeHtml(step.output_summary)}</div>
      `;
      els.traceList.appendChild(li);
    }
  }
}

async function submitQuery(event) {
  event.preventDefault();
  if (state.busy) return;
  const message = els.queryInput.value.trim();
  showError("");
  state.busy = true;
  els.sendBtn.disabled = true;
  els.sendBtn.textContent = "Running MCP Agent\u2026";
  announce("Running HR policy lookup and MCP workflow.");

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        provider_override: els.providerSelect.value,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || `HTTP ${res.status}`);
    }
    renderResult(data);
    announce(`Workflow ${data.status} in ${data.latency_ms} milliseconds with ${(data.trace || []).length} tool calls.`);
  } catch (err) {
    showError(`Request failed: ${err.message}`);
    announce(`Error: ${err.message}`);
  } finally {
    state.busy = false;
    els.sendBtn.disabled = false;
    els.sendBtn.textContent = "Run Agent Workflow";
  }
}

// IME-safe Enter-to-submit per modern-web-guidance
els.queryInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    if (event.isComposing || event.keyCode === 229) {
      return;
    }
    event.preventDefault();
    els.chatForm.requestSubmit();
  }
});

els.chatForm.addEventListener("submit", submitQuery);

els.clearBtn.addEventListener("click", () => {
  els.queryInput.value = "";
  els.queryInput.focus();
});

els.tabCitations.addEventListener("click", () => switchTab("citations"));
els.tabTrace.addEventListener("click", () => switchTab("trace"));
els.refreshTicketsBtn.addEventListener("click", loadTickets);

els.copyDraftBtn.addEventListener("click", async () => {
  if (!state.lastDraft) return;
  const fullText = `To: ${state.lastDraft.to}\nCC: ${(state.lastDraft.cc || []).join(", ")}\nSubject: ${state.lastDraft.subject}\n\n${state.lastDraft.body}`;
  try {
    await navigator.clipboard.writeText(fullText);
    els.copyDraftBtn.textContent = "Copied!";
    setTimeout(() => { els.copyDraftBtn.textContent = "Copy Draft"; }, 1800);
  } catch (err) {
    showError("Clipboard copy blocked by browser permissions.");
  }
});

els.openConfirmDialogBtn.addEventListener("click", () => {
  if (!state.pendingTicket) return;
  els.dialogPayloadPreview.textContent = JSON.stringify(state.pendingTicket, null, 2);
  els.confirmDialog.showModal();
});

els.dialogCancelBtn.addEventListener("click", () => els.confirmDialog.close());

els.dialogConfirmBtn.addEventListener("click", async () => {
  if (!state.pendingTicket) return;
  els.dialogConfirmBtn.disabled = true;
  try {
    const res = await fetch("/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        proposed_ticket: state.pendingTicket,
        confirmed: true,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || `HTTP ${res.status}`);
    }
    const ticket = data.result?.ticket;
    els.confirmDialog.close();
    els.confirmCard.hidden = true;
    state.pendingTicket = null;
    announce(`Mock ticket ${ticket?.ticket_id || ""} persisted.`);
    await loadTickets();
  } catch (err) {
    showError(`Ticket confirmation failed: ${err.message}`);
  } finally {
    els.dialogConfirmBtn.disabled = false;
  }
});

loadHealth();
loadDemoTasks();
loadTickets();
