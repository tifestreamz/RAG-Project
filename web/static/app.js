const navCorpusText = document.getElementById("nav-corpus-text");
const navStatusDot = document.getElementById("nav-status-dot");
const navMcpStat = document.getElementById("nav-mcp-stat");
const navModelStat = document.getElementById("nav-model-stat");

const demoButtons = document.getElementById("demo-buttons");
const personasList = document.getElementById("personas-list");
const ticketsList = document.getElementById("tickets-list");
const refreshTicketsBtn = document.getElementById("refresh-tickets-btn");

const chatForm = document.getElementById("chat-form");
const promptInput = document.getElementById("prompt-input");
const providerSelect = document.getElementById("provider-select");
const clearBtn = document.getElementById("clear-btn");
const submitBtn = document.getElementById("submit-btn");

const runStatusStrip = document.getElementById("run-status-strip");
const runStatusBadge = document.getElementById("run-status-badge");
const runMeta = document.getElementById("run-meta");
const errorBanner = document.getElementById("error-banner");
const outputStack = document.getElementById("output-stack");

const railTabCitations = document.getElementById("rail-tab-citations");
const railTabTrace = document.getElementById("rail-tab-trace");
const railCitationsCount = document.getElementById("rail-citations-count");
const railTraceCount = document.getElementById("rail-trace-count");
const railPanelCitations = document.getElementById("rail-panel-citations");
const railPanelTrace = document.getElementById("rail-panel-trace");
const citationsList = document.getElementById("citations-list");
const traceList = document.getElementById("trace-list");

const confirmDialog = document.getElementById("confirm-dialog");
const confirmPreview = document.getElementById("confirm-preview");
const cancelConfirmBtn = document.getElementById("cancel-confirm-btn");
const approveConfirmBtn = document.getElementById("approve-confirm-btn");

const FORMAT_LABELS = {
  html: "HTML",
  pdf: "PDF",
  markdown: "MD",
  txt: "TXT",
};

const TIER_SHORT = {
  "Production-Admin": "Prod-Admin",
  "Prod-Admin": "Prod-Admin",
  "Standard-Core": "Std-Core",
  "Standard-Corp": "Std-Corp",
  "Standard-Dev": "Std-Dev",
  "Executive-PII": "Exec-PII",
  "Contractor-Limited": "Contractor",
};

const CATEGORY_LABELS = {
  remote_work_exception: "Remote work · Global mobility exception",
  international_remote_work: "Remote work · International workcation",
  travel_loaner_device: "IT Security · Clean travel loaner",
  ethics_escalation: "Confidential Ethics / Speak-Up",
  leave_and_pto: "Leave · PTO & recharge week",
  contractor_eligibility: "Workforce · Contractor engagement",
};

let isSubmitting = false;
let currentPendingTicket = null;
let currentDraftEmail = null;
let ticketCreatedState = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatProviderName(raw) {
  const clean = String(raw || "").trim().toLowerCase();
  if (clean === "gemini") return "Gemini";
  if (clean === "mock") return "Mock";
  if (!clean) return "Auto";
  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

function humanizeCategory(raw) {
  if (!raw) return "HR Operations";
  if (CATEGORY_LABELS[raw]) return CATEGORY_LABELS[raw];
  return String(raw)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (m) => m.toUpperCase());
}

function formatSimpleRichText(rawText) {
  let src = String(rawText || "");
  if (!src) return "";
  src = src.replace(/\|\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|/g, " ");
  src = src.replace(/\s+\|\s+/g, " · ").replace(/^\|\s*|\s*\|$/g, "");
  const codeSpans = [];
  src = src.replace(/`([^`\n]+)`/g, (_, inner) => {
    const idx = codeSpans.length;
    codeSpans.push(`<code class="corpus-inline-code">${escapeHtml(inner)}</code>`);
    return `\uE000CS${idx}\uE001`;
  });
  let html = escapeHtml(src);
  html = html.replace(/\*\*((?:(?!\*\*).)+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*\*/g, "");
  html = html.replace(/(^|[^\w*])\*([^\s*](?:[^*\n]*?[^\s*])?)\*(?=[^\w*]|$)/g, "$1<em>$2</em>");
  html = html.replace(/\uE000CS(\d+)\uE001/g, (_, idx) => codeSpans[Number(idx)] || "");
  return html;
}

function extractInlinePolRefs(text) {
  const refs = [];
  const seen = new Set();
  const re = /(POL-\d{3})(?:[\s|]*(?:§|Sections?|Sec\.?)\s*([\d.]+))?/gi;
  let match;
  while ((match = re.exec(text || "")) !== null) {
    const docId = match[1].toUpperCase();
    const sec = match[2] ? `§${match[2]}` : "";
    const label = sec ? `${docId} ${sec}` : docId;
    if (!seen.has(label)) {
      seen.add(label);
      refs.push({ docId, sec, label });
    }
  }
  return refs;
}

function extractSectionToken(sectionPath, anchor) {
  const path = String(sectionPath || "");
  const numMatch = path.match(/\b(\d+(?:\.\d+)?)\b/);
  if (numMatch) return `§${numMatch[1]}`;
  if (anchor && /^p\.\d+/i.test(anchor)) return anchor;
  return sectionPath ? sectionPath.slice(0, 18) : "Policy";
}

function formatDemoMeta(task) {
  const prompt = String(task.prompt || "");
  const polMatches = Array.from(new Set(prompt.match(/POL-\d{3}/gi) || [])).map((s) => s.toUpperCase());
  let who = "";
  const empMatch = prompt.match(/\b([A-Z][a-z]+ [A-Z][a-z]+)\s*\(EMP-\d+\)/);
  if (empMatch) {
    who = empMatch[1];
  } else {
    const badgeClean = String(task.badge || "").trim();
    who = badgeClean;
  }
  if (polMatches.length) {
    return `${who ? `${who} · ` : ""}${polMatches.slice(0, 3).join(" · ")}`;
  }
  return task.badge || "Example query";
}

async function hydrateNavbarAndSidebar() {
  try {
    const [healthResp, demoResp, ticketsResp] = await Promise.all([
      fetch("/health"),
      fetch("/demo-tasks"),
      fetch("/tickets"),
    ]);

    if (healthResp.ok) {
      const h = await healthResp.json();
      if (navCorpusText) {
        navCorpusText.innerHTML = `<strong>${escapeHtml(h.corpus_docs ?? 12)}</strong> docs · <strong>${escapeHtml(h.corpus_chunks ?? 117)}</strong> chunks`;
      }
      if (navMcpStat) {
        const toolCount = Array.isArray(h.mcp_tools) ? h.mcp_tools.length : (h.mcp_tools ?? 8);
        navMcpStat.innerHTML = `MCP ${escapeHtml(h.mcp_transport || "stdio")} · <strong>${escapeHtml(toolCount)} tools</strong>`;
      }
      if (navModelStat) {
        navModelStat.innerHTML = `Model · <strong>${escapeHtml(formatProviderName(h.llm_provider))}</strong>`;
      }
      if (navStatusDot) {
        navStatusDot.className = h.mcp_connected ? "status-dot" : "status-dot warn";
      }
    }

    if (demoResp.ok) {
      const d = await demoResp.json();
      renderDemoExamples(d.demo_tasks || []);
      renderPersonas(d.personas || []);
    }

    if (ticketsResp.ok) {
      const t = await ticketsResp.json();
      renderTickets(t.tickets || []);
    }
  } catch (err) {
    if (navStatusDot) navStatusDot.className = "status-dot warn";
  }
}

function renderDemoExamples(tasks) {
  if (!tasks.length) {
    demoButtons.innerHTML = `<div class="example-card">No examples loaded.</div>`;
    return;
  }
  demoButtons.innerHTML = tasks
    .map(
      (task) => `
      <button type="button" class="example-card" data-demo-id="${escapeHtml(task.id)}">
        <span class="example-title">${escapeHtml(task.title)}</span>
        <span class="example-meta">${escapeHtml(formatDemoMeta(task))}</span>
      </button>
    `
    )
    .join("");

  demoButtons.querySelectorAll(".example-card[data-demo-id]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = tasks.find((t) => t.id === btn.dataset.demoId);
      if (!target) return;
      demoButtons.querySelectorAll(".example-card").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      promptInput.value = target.prompt;
      promptInput.focus();
    });
  });
}

function renderPersonas(personas) {
  if (!personas.length) {
    personasList.innerHTML = `<div style="padding: 12px; color: var(--muted); font-size: 0.78rem;">No employees found.</div>`;
    return;
  }
  personasList.innerHTML = personas
    .map((p) => {
      const shortNum = String(p.employee_id || "").replace(/^EMP-/i, "");
      const tier = TIER_SHORT[p.security_tier] || p.security_tier || "";
      return `
        <button
          type="button"
          class="persona-row"
          data-emp-id="${escapeHtml(p.employee_id)}"
          data-emp-name="${escapeHtml(p.name)}"
          title="Insert ${escapeHtml(p.name)} (${escapeHtml(p.employee_id)}) — ${escapeHtml(p.role)}"
        >
          <span class="persona-num">${escapeHtml(shortNum)}</span>
          <span class="persona-name">${escapeHtml(p.name)}</span>
          <span class="persona-tier">${escapeHtml(tier)}</span>
        </button>
      `;
    })
    .join("");

  personasList.querySelectorAll(".persona-row").forEach((row) => {
    row.addEventListener("click", () => {
      const empId = row.dataset.empId;
      const empName = row.dataset.empName;
      const current = promptInput.value.trim();
      const insertion = `${empName} (${empId})`;
      if (!current) {
        promptInput.value = `For ${insertion}: `;
      } else if (!current.includes(empId)) {
        promptInput.value = `${current} — Employee: ${insertion}`;
      }
      promptInput.focus();
    });
  });
}

function renderTickets(tickets) {
  if (!tickets.length) {
    ticketsList.innerHTML = `<div class="ticket-mini-card" style="color: var(--muted);">No mock tickets created yet.</div>`;
    return;
  }
  const ordered = [...tickets].reverse();
  ticketsList.innerHTML = ordered
    .map((t) => {
      const statusText = String(t.status || "Pending").replace(/_/g, " ");
      const niceStatus = statusText.charAt(0).toUpperCase() + statusText.slice(1);
      return `
        <article class="ticket-mini-card">
          <div class="ticket-mini-top">
            <span class="ticket-mini-id">${escapeHtml(t.ticket_id)} · ${escapeHtml(t.priority || "P3")}</span>
            <span class="ticket-mini-status">${escapeHtml(niceStatus)}</span>
          </div>
          <div class="ticket-mini-summary">
            <strong>${escapeHtml(t.employee_id || "HR")}:</strong> ${escapeHtml(t.summary || "")}
          </div>
        </article>
      `;
    })
    .join("");
}

async function refreshTicketsOnly() {
  try {
    const resp = await fetch("/tickets");
    if (!resp.ok) return;
    const data = await resp.json();
    renderTickets(data.tickets || []);
  } catch {
    // Non-fatal UI refresh failure
  }
}

function switchRailTab(tabName) {
  const showCitations = tabName !== "trace";
  railTabCitations.classList.toggle("active", showCitations);
  railTabTrace.classList.toggle("active", !showCitations);
  railTabCitations.setAttribute("aria-selected", String(showCitations));
  railTabTrace.setAttribute("aria-selected", String(!showCitations));
  railPanelCitations.hidden = !showCitations;
  railPanelTrace.hidden = showCitations;
}

function focusCitationCard(docId, secRef) {
  switchRailTab("citations");
  const cards = Array.from(citationsList.querySelectorAll(".rail-card[data-doc-id]"));
  cards.forEach((c) => c.classList.remove("highlighted"));
  if (!cards.length) return;

  const cleanDoc = String(docId || "").toUpperCase();
  const cleanSec = String(secRef || "").replace(/^§/, "").trim();
  let target = null;

  if (cleanSec) {
    target = cards.find(
      (c) =>
        c.dataset.docId === cleanDoc &&
        (c.dataset.secToken.includes(cleanSec) || c.textContent.includes(cleanSec))
    );
  }
  if (!target) {
    target = cards.find((c) => c.dataset.docId === cleanDoc);
  }
  if (target) {
    target.classList.add("highlighted");
    target.scrollIntoView({ block: "nearest", behavior: "smooth" });
  } else if (cleanDoc) {
    window.location.href = `/corpus?doc=${encodeURIComponent(cleanDoc)}&tab=document`;
  }
}

function renderCitationsRail(citations) {
  const items = citations || [];
  railCitationsCount.textContent = String(items.length);

  if (!items.length) {
    citationsList.innerHTML = `<li class="rail-card" style="color: var(--muted); font-size: 0.8rem;">No citations returned for this turn.</li>`;
    return;
  }

  citationsList.innerHTML = items
    .map((c, idx) => {
      const num = String(idx + 1).padStart(2, "0");
      const secToken = extractSectionToken(c.section_path, c.page_or_anchor);
      const fmtBadge = FORMAT_LABELS[(c.file_format || "").toLowerCase()] || String(c.file_format || "DOC").toUpperCase();
      const corpusHref = `/corpus?doc=${encodeURIComponent(c.doc_id || "")}&tab=chunks&chunk=${encodeURIComponent(c.chunk_id || "")}`;
      const cleanTitle = String(c.section_path || c.doc_title || "")
        .replace(/^#+\s*/, "")
        .replace(/^\d+(?:\.\d+)*\s+/, "") || c.doc_title;

      return `
        <li class="rail-card" data-doc-id="${escapeHtml((c.doc_id || "").toUpperCase())}" data-sec-token="${escapeHtml(secToken)}">
          <div class="rail-card-top">
            <span class="rail-card-ref">
              <span class="rail-idx">${escapeHtml(num)}</span>
              <a class="rail-doc-anchor" href="${escapeHtml(corpusHref)}" title="Inspect exact chunk in Policy corpus">${escapeHtml(c.doc_id)} ${escapeHtml(secToken)}</a>
            </span>
            <span class="format-tag">${escapeHtml(fmtBadge)}</span>
          </div>
          <h4 class="rail-card-title">${formatSimpleRichText(cleanTitle)}</h4>
          <p class="rail-card-snippet">${formatSimpleRichText(c.snippet || "")}</p>
        </li>
      `;
    })
    .join("");
}

function renderTraceRail(traceSteps) {
  const steps = traceSteps || [];
  railTraceCount.textContent = String(steps.length);

  if (!steps.length) {
    traceList.innerHTML = `<li class="rail-card" style="color: var(--muted); font-size: 0.8rem;">No MCP tool calls were executed for this turn.</li>`;
    return;
  }

  traceList.innerHTML = steps
    .map((step, idx) => {
      const stepNum = step.step ?? idx + 1;
      const statusOk = !step.status || step.status === "ok" || step.status === "success";
      const timing = step.duration_ms != null ? ` · ${step.duration_ms}ms` : "";
      const argsStr = JSON.stringify(step.arguments || {}, null, 2);
      return `
        <li class="rail-card">
          <div class="rail-card-top">
            <span class="rail-card-ref">
              <span class="rail-idx">#${escapeHtml(stepNum)}</span>
              <strong style="color: var(--ink); font-family: var(--font-mono); font-size: 0.77rem;">${escapeHtml(step.tool_name)}</strong>
            </span>
            <span class="format-tag" style="${statusOk ? "color: var(--teal); border-color: var(--teal-border); background: var(--teal-soft);" : "color: var(--danger); border-color: var(--danger-border);"}">${escapeHtml(step.status || "ok")}${escapeHtml(timing)}</span>
          </div>
          <pre class="trace-args-pre">${escapeHtml(argsStr)}</pre>
          <div class="trace-summary">${escapeHtml(step.output_summary || "")}</div>
        </li>
      `;
    })
    .join("");
}

function cleanLineForParsing(line) {
  return String(line || "")
    .replace(/^#{1,6}\s+/, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .trim();
}

function parseAnswerStructure(answerText) {
  const rawLines = String(answerText || "").split(/\r?\n/);
  const bullets = [];
  const options = [];
  const paragraphs = [];
  let inOptionsSection = false;
  let currentHeading = "";

  for (const rawLine of rawLines) {
    const trimmed = rawLine.trim();
    if (!trimmed) continue;

    if (/^#{1,6}\s*(options|alternatives|your options|recommended paths|paths forward)\b/i.test(trimmed)) {
      inOptionsSection = true;
      currentHeading = "";
      continue;
    }

    const optMatch = trimmed.match(/^(?:[-*•]\s*)?(?:\*\*)?(Option\s+[A-Z]|Path\s+[A-Z])\s*:?\s*(?:\*\*)?\s*(.+)$/i);
    if (optMatch || (inOptionsSection && /^(?:\d+[.)]|[-*•])\s+(.+)$/.test(trimmed))) {
      let kicker = `OPTION ${String.fromCharCode(65 + options.length)}`;
      let rest = trimmed;
      if (optMatch) {
        kicker = optMatch[1].replace(/\.$/, "").toUpperCase();
        rest = optMatch[2];
      } else {
        rest = trimmed.replace(/^(?:\d+[.)]|[-*•])\s+/, "");
      }
      rest = rest.replace(/\*\*/g, "").trim();
      const splitIdx = rest.search(/\s+[—–-]\s+|\.\s+|:\s+/);
      let title = rest;
      let desc = "";
      if (splitIdx > 0 && splitIdx < 72) {
        title = rest.slice(0, splitIdx).trim();
        desc = rest.slice(splitIdx).replace(/^[—–\-.:]+\s*/, "").trim();
      }
      options.push({ kicker, title, desc: desc || rest, raw: trimmed });
      continue;
    }

    const bulletMatch = trimmed.match(/^(?:[-*•]|\d+[.)])\s+(.+)$/);
    if (bulletMatch) {
      const content = bulletMatch[1].trim();
      let topic = currentHeading || "Policy note";
      let body = content;

      const boldTopicMatch = content.match(/^\*\*([^*]+?)\s*:\*\*\s*(.+)$/) || content.match(/^\*\*([^*]+?)\*\*\s*:\s*(.+)$/);
      if (boldTopicMatch) {
        topic = boldTopicMatch[1].replace(/`/g, "").trim();
        body = boldTopicMatch[2].trim();
      } else {
        const colonIdx = content.indexOf(":");
        if (colonIdx > 1 && colonIdx <= 44) {
          topic = content.slice(0, colonIdx).replace(/\*\*/g, "").replace(/`/g, "").trim();
          body = content.slice(colonIdx + 1).replace(/^\s*\*\*\s*/, "").trim();
        }
      }

      if (
        /^(Approval\/Escalation Email Drafted|Mock HR Ticket Queued|Confidential Escalation Email Drafted)/i.test(topic) ||
        /^Click \*\*Confirm & Create Mock HR Ticket/i.test(body)
      ) {
        continue;
      }
      bullets.push({ topic, body });
      continue;
    }

    if (/^#{1,6}\s+/.test(trimmed)) {
      inOptionsSection = false;
      currentHeading = cleanLineForParsing(trimmed).replace(/\*\*/g, "");
      continue;
    }

    paragraphs.push({ topic: currentHeading, text: cleanLineForParsing(trimmed) });
    currentHeading = "";
  }

  let headline = "";
  const firstCandidate =
    (paragraphs[0] && paragraphs[0].text) ||
    (bullets[0] ? `${bullets[0].topic}: ${bullets[0].body}` : "");
  if (firstCandidate) {
    const stripped = firstCandidate
      .replace(/\*\*/g, "")
      .replace(/^(Bottom line|Summary|Verdict|Answer)\s*:\s*/i, "")
      .trim();
    const sentenceMatch = stripped.match(/^(.+?[.!?])(?:\s|$)/);
    headline = sentenceMatch ? sentenceMatch[1] : stripped;
    if (headline.length > 140) {
      headline = `${headline.slice(0, 136).trim()}…`;
    }
  }

  return { headline, bullets, options, paragraphs };
}

function buildHeroVerdictCard(data, parsed) {
  const ui = data.ui_context || {};
  const emp = ui.employee || null;
  const comp = ui.compliance || null;
  const esc = data.escalation || null;
  const pending = data.pending_confirmation || null;
  const metrics = (comp && comp.metrics) || {};

  let statusClass = "badge-neutral";
  let statusText = "Policy guidance";

  if (data.status === "blocked") {
    statusClass = "badge-danger";
    statusText = "Request blocked";
  } else if (data.abstained) {
    statusClass = "badge-danger";
    statusText = "Abstained · Insufficient evidence";
  } else if (esc && esc.recommended) {
    statusClass = "badge-amber";
    statusText = esc.priority === "P1" ? "P1 escalation recommended" : "Escalation recommended";
  } else if (comp) {
    if (comp.eligible === false) {
      statusClass = "badge-amber";
      statusText = "Ineligible under standard rules";
    } else if (comp.violations && comp.violations.length) {
      statusClass = "badge-amber";
      statusText = "Needs exception or adjustment";
    } else if (comp.warnings && comp.warnings.length) {
      statusClass = "badge-amber";
      statusText = "Eligible · Conditions apply";
    } else if (comp.eligible === true) {
      statusClass = "badge-teal";
      statusText = "Eligible · Compliant";
    }
  }

  let priorityPill = "";
  if (pending) {
    const pri = pending.priority || "P3";
    const stateLabel = ticketCreatedState
      ? `Confirmed · ${ticketCreatedState.ticket_id}`
      : "Pending confirmation";
    priorityPill = `<span id="verdict-priority-pill" class="badge badge-neutral">${escapeHtml(pri)} · ${escapeHtml(stateLabel)}</span>`;
  } else if (esc && esc.priority) {
    priorityPill = `<span class="badge badge-neutral">${escapeHtml(esc.priority)} · ${escapeHtml(esc.status || "Urgent review")}</span>`;
  }

  let headline = parsed.headline || "HR Policy Response";
  if (comp && comp.request_type === "international_remote_work" && typeof metrics.projected_rolling_total === "number" && metrics.projected_rolling_total > 30) {
    const over = metrics.projected_rolling_total - 30;
    const reqDays = metrics.requested_days || 0;
    const firstName = emp && emp.name ? `${emp.name.split(" ")[0]}'s` : "the employee's";
    headline = `A ${reqDays}-day workcation exceeds ${firstName} international cap by ${over} day${over === 1 ? "" : "s"}.`;
  } else if (comp && comp.violations && comp.violations.length && (!parsed.paragraphs.length || parsed.headline.startsWith("Employee Profile"))) {
    headline = comp.violations[0].replace(/\s*\(POL-\d+[^)]*\)\.?$/, ".");
  } else if (comp && comp.request_type === "pto_request" && comp.eligible && typeof metrics.requested_days === "number" && !parsed.paragraphs.length) {
    const firstName = emp && emp.name ? emp.name : "Employee";
    const proj = metrics.projected_balance_after_request != null ? metrics.projected_balance_after_request : metrics.remaining_pto_days;
    headline = `${firstName} is eligible for ${metrics.requested_days} PTO days (${proj} days remaining after).`;
  } else if (comp && comp.request_type === "international_remote_work" && metrics.requires_loaner_laptop && !parsed.paragraphs.length) {
    const reqDays = metrics.requested_days || 0;
    headline = `Eligible for ${reqDays} international remote days with a clean travel loaner laptop.`;
  } else if (esc && esc.recommended && esc.priority === "P1" && !parsed.paragraphs.length) {
    headline = "P1 confidential ethics escalation required — route directly to Ethics & Legal.";
  }

  let subline = "";
  if (emp) {
    const standingLabel = emp.standing || (emp.good_standing === true ? "Good Standing" : emp.good_standing === false ? "Standing review" : "");
    const parts = [
      emp.name,
      emp.employee_id,
      emp.role,
      emp.employment_type,
      standingLabel,
      emp.security_tier,
    ].filter(Boolean);
    subline = parts.join(" · ");
  } else if (data.citations && data.citations.length) {
    const docIds = Array.from(new Set(data.citations.map((c) => c.doc_id).filter(Boolean)));
    subline = `Grounded in ${docIds.join(" · ")}`;
  }

  let metricsHtml = "";
  if (comp && comp.request_type === "international_remote_work" && typeof metrics.requested_days === "number") {
    const used = Number(metrics.rolling_12m_used_days || 0);
    const req = Number(metrics.requested_days || 0);
    const remBefore = Math.max(0, 30 - used);
    const projected = Number(metrics.projected_rolling_total ?? used + req);
    const over = Math.max(0, projected - 30);

    const availBarDays = req > remBefore ? remBefore : req;
    const leftoverBarDays = Math.max(0, 30 - used - availBarDays);
    const scaleTotal = Math.max(30, used + remBefore + over);

    const usedPct = (used / scaleTotal) * 100;
    const availPct = ((over > 0 ? remBefore : availBarDays) / scaleTotal) * 100;
    const overPct = (over / scaleTotal) * 100;
    const capTickPct = (30 / scaleTotal) * 100;

    metricsHtml = `
      <div class="metric-trio">
        <div class="metric-cell">
          <div class="metric-cell-label">Requested</div>
          <div class="metric-cell-value">${escapeHtml(req)} <span>days</span></div>
        </div>
        <div class="metric-cell">
          <div class="metric-cell-label">Remaining allowance</div>
          <div class="metric-cell-value teal">${escapeHtml(remBefore)} <span>of 30 days</span></div>
        </div>
        <div class="metric-cell">
          <div class="metric-cell-label">${over > 0 ? "Over cap" : "Projected total"}</div>
          <div class="metric-cell-value ${over > 0 ? "amber" : "teal"}">${escapeHtml(over > 0 ? over : projected)} <span>${over > 0 ? "days" : "of 30 days"}</span></div>
        </div>
      </div>

      <div class="cap-viz">
        <div class="cap-viz-top">
          <span>Rolling 12-month international workcation</span>
          <span>${escapeHtml(projected)} / 30 day cap</span>
        </div>
        <div class="cap-bar-track" aria-hidden="true">
          ${used > 0 ? `<div class="cap-seg-used" style="width: ${usedPct.toFixed(2)}%;"></div>` : ""}
          ${(over > 0 ? remBefore : availBarDays) > 0 ? `<div class="cap-seg-avail" style="width: ${availPct.toFixed(2)}%;"></div>` : ""}
          ${over > 0 ? `<div class="cap-seg-over" style="width: ${overPct.toFixed(2)}%;"></div>` : ""}
          ${leftoverBarDays > 0 && over === 0 ? `<div style="flex: 1;"></div>` : ""}
        </div>
        <div class="cap-marker-row">
          <span class="cap-marker" style="left: ${Math.min(96, capTickPct).toFixed(2)}%;">30 day cap</span>
        </div>
        <div class="cap-legend">
          <span class="cap-legend-item"><span class="swatch swatch-used"></span>Used · ${escapeHtml(used)}</span>
          <span class="cap-legend-item"><span class="swatch swatch-avail"></span>Available · ${escapeHtml(remBefore)}</span>
          ${over > 0 ? `<span class="cap-legend-item"><span class="swatch swatch-over"></span>Requested over cap · ${escapeHtml(over)}</span>` : ""}
        </div>
      </div>
    `;
  } else if (comp && typeof metrics.remaining_pto_days === "number") {
    const avail = Number(metrics.remaining_pto_days || 0);
    const pendingDays = Number(metrics.pending_pto_days || 0);
    const requestedPto = Number(metrics.requested_days ?? metrics.requested_pto_days ?? 0);
    const projectedBal = metrics.projected_balance_after_request != null ? Number(metrics.projected_balance_after_request) : avail;
    metricsHtml = `
      <div class="metric-trio">
        <div class="metric-cell">
          <div class="metric-cell-label">Available PTO</div>
          <div class="metric-cell-value teal">${escapeHtml(avail)} <span>days</span></div>
        </div>
        <div class="metric-cell">
          <div class="metric-cell-label">${requestedPto > 0 ? "Requested PTO" : "Pending requests"}</div>
          <div class="metric-cell-value">${escapeHtml(requestedPto > 0 ? requestedPto : pendingDays)} <span>days</span></div>
        </div>
        <div class="metric-cell">
          <div class="metric-cell-label">Projected balance</div>
          <div class="metric-cell-value ${projectedBal < 0 ? "amber" : "teal"}">${escapeHtml(projectedBal)} <span>days</span></div>
        </div>
      </div>
    `;
  } else if (comp && comp.request_type === "business_travel_loaner" && metrics.security_tier) {
    metricsHtml = `
      <div class="metric-trio">
        <div class="metric-cell">
          <div class="metric-cell-label">Security tier</div>
          <div class="metric-cell-value" style="font-size: 1.05rem;">${escapeHtml(metrics.security_tier)}</div>
        </div>
        <div class="metric-cell">
          <div class="metric-cell-label">Loaner laptop</div>
          <div class="metric-cell-value amber" style="font-size: 1.05rem;">${metrics.requires_loaner_laptop ? "Required" : "Optional"}</div>
        </div>
        <div class="metric-cell">
          <div class="metric-cell-label">Lead time</div>
          <div class="metric-cell-value" style="font-size: 1.05rem;">${escapeHtml(metrics.minimum_advance_request_business_days ?? 10)} <span>bus. days</span></div>
        </div>
      </div>
    `;
  }

  return `
    <article class="verdict-card">
      <div class="verdict-pills">
        <span class="badge ${statusClass}">${escapeHtml(statusText)}</span>
        ${priorityPill}
      </div>
      <h2 class="verdict-headline">${escapeHtml(headline)}</h2>
      ${subline ? `<p class="verdict-subline">${escapeHtml(subline)}</p>` : ""}
      ${metricsHtml}
    </article>
  `;
}

function buildFindingsCard(data, parsed) {
  let rows = [...parsed.bullets];
  if (!rows.length && parsed.paragraphs.length) {
    rows = parsed.paragraphs.map((p, idx) => ({
      topic: p.topic || (idx === 0 ? "Policy summary" : `Detail ${idx + 1}`),
      body: p.text,
    }));
  }
  if (!rows.length) return "";

  const docFallback = (data.citations && data.citations[0] && data.citations[0].doc_id) || "";

  const rowsHtml = rows
    .map((row) => {
      const refs = extractInlinePolRefs(row.body);
      const citePills = refs.length
        ? `<div class="finding-cites">${refs
            .map(
              (r) =>
                `<button type="button" class="cite-pill" data-cite-doc="${escapeHtml(r.docId)}" data-cite-sec="${escapeHtml(r.sec)}">${escapeHtml(r.label)}</button>`
            )
            .join("")}</div>`
        : docFallback && parsed.bullets.length <= 2
          ? `<div class="finding-cites"><button type="button" class="cite-pill" data-cite-doc="${escapeHtml(docFallback)}" data-cite-sec="">${escapeHtml(docFallback)}</button></div>`
          : "";

      return `
        <div class="finding-row">
          <div class="finding-topic">
            <span class="finding-dot" aria-hidden="true"></span>
            <span>${escapeHtml(row.topic)}</span>
          </div>
          <div class="finding-body">
            <div>${formatSimpleRichText(row.body)}</div>
            ${citePills}
          </div>
        </div>
      `;
    })
    .join("");

  return `
    <section>
      <div class="section-bar">
        <h2>Policy findings</h2>
        <span>Every claim linked to a source</span>
      </div>
      <div class="findings-card">${rowsHtml}</div>
    </section>
  `;
}

function buildOptionsSection(data, parsed) {
  const opts = parsed.options || [];
  if (!opts.length) return "";

  const empFirst = data.ui_context && data.ui_context.employee && data.ui_context.employee.name
    ? `${data.ui_context.employee.name.split(" ")[0]}'s options`
    : "Next-step options";

  const cardsHtml = opts
    .slice(0, 4)
    .map((opt) => {
      const refs = extractInlinePolRefs(`${opt.title} ${opt.desc}`);
      const pills = refs.length
        ? `<div class="finding-cites">${refs
            .map(
              (r) =>
                `<button type="button" class="cite-pill" data-cite-doc="${escapeHtml(r.docId)}" data-cite-sec="${escapeHtml(r.sec)}">${escapeHtml(r.label)}</button>`
            )
            .join("")}</div>`
        : "";
      return `
        <article class="option-card">
          <div>
            <div class="option-kicker">${escapeHtml(opt.kicker)}</div>
            <h3 class="option-title">${escapeHtml(opt.title)}</h3>
            <p class="option-desc">${formatSimpleRichText(opt.desc)}</p>
          </div>
          ${pills}
        </article>
      `;
    })
    .join("");

  return `
    <section>
      <div class="section-bar">
        <h2>${escapeHtml(empFirst)}</h2>
        <span>Two paths available before submitting a ticket</span>
      </div>
      <div class="options-grid">${cardsHtml}</div>
    </section>
  `;
}

function buildEscalationCard(esc) {
  if (!esc || !esc.recommended) return "";
  const routing = Array.isArray(esc.routing) ? esc.routing.join(" · ") : String(esc.routing || "");
  const reasons = (esc.reasons || []).map((r) => `<li>${escapeHtml(r)}</li>`).join("");
  return `
    <article class="surface-card">
      <div class="surface-card-head">
        <div class="surface-card-title-row">
          <h3>Escalation &amp; confidentiality routing</h3>
          <span class="surface-card-subtitle amber">${escapeHtml(esc.priority || "P1")} · ${escapeHtml(esc.status || "Escalation required")}</span>
        </div>
      </div>
      <div class="ticket-body">
        ${routing ? `<p class="ticket-summary-text" style="margin-bottom: 8px;"><strong>Route to:</strong> ${escapeHtml(routing)}</p>` : ""}
        ${reasons ? `<ul style="margin: 0; padding-left: 18px; font-size: 0.83rem; color: var(--ink-2); line-height: 1.55;">${reasons}</ul>` : ""}
      </div>
    </article>
  `;
}

function buildEmailCard(email) {
  if (!email) return "";
  const ccVal = Array.isArray(email.cc) ? email.cc.join(", ") : String(email.cc || "None");
  return `
    <article class="surface-card">
      <div class="surface-card-head">
        <div class="surface-card-title-row">
          <h3>Escalation email</h3>
          <span class="surface-card-subtitle">Draft · review only</span>
        </div>
        <button id="copy-email-btn" class="btn-outline" type="button" style="padding: 4px 10px; font-size: 0.78rem;">Copy</button>
      </div>
      <div class="email-meta-grid">
        <div class="email-meta-key">To</div>
        <div class="email-meta-val">${escapeHtml(email.to || "")}</div>
        <div class="email-meta-key">CC</div>
        <div class="email-meta-val">${escapeHtml(ccVal)}</div>
        <div class="email-meta-key">Subject</div>
        <div class="email-meta-val">${escapeHtml(email.subject || "")}</div>
      </div>
      <div class="email-body-box">${escapeHtml(email.body || "")}</div>
    </article>
  `;
}

function buildTicketCard(ticket) {
  if (!ticket) return "";
  const polList = (ticket.policy_references || []).join(" · ") || "—";
  const isConfidential = String(ticket.priority || "").toUpperCase() === "P1";
  const queueLabel = isConfidential
    ? "Routes to Confidential Ethics / Speak-Up queue"
    : "Routes to People Operations queue";

  const statusText = ticketCreatedState
    ? `Created · ${ticketCreatedState.ticket_id}`
    : "Preview · not saved";
  const statusClass = ticketCreatedState ? "surface-card-subtitle" : "surface-card-subtitle amber";

  return `
    <article class="surface-card" id="hr-ticket-card">
      <div class="surface-card-head">
        <div class="surface-card-title-row">
          <h3>HR ticket</h3>
          <span id="ticket-status-subtitle" class="${statusClass}" style="${ticketCreatedState ? "color: var(--teal); font-weight: 600;" : ""}">${escapeHtml(statusText)}</span>
        </div>
        <span class="surface-card-subtitle">${escapeHtml(queueLabel)}</span>
      </div>

      <div class="ticket-body">
        <div class="ticket-meta-grid">
          <div>
            <div class="ticket-meta-label">Employee</div>
            <div class="ticket-meta-value mono">${escapeHtml(ticket.employee_id || "—")}</div>
          </div>
          <div>
            <div class="ticket-meta-label">Priority</div>
            <div id="ticket-priority-display" class="ticket-meta-value mono">${escapeHtml(ticket.priority || "P3")}</div>
          </div>
          <div>
            <div class="ticket-meta-label">Category</div>
            <div class="ticket-meta-value">${escapeHtml(humanizeCategory(ticket.category))}</div>
          </div>
          <div>
            <div class="ticket-meta-label">Policies</div>
            <div class="ticket-meta-value">${escapeHtml(polList)}</div>
          </div>
        </div>

        <p id="ticket-summary-display" class="ticket-summary-text">${escapeHtml(ticket.summary || "")}</p>

        <div id="ticket-edit-panel" class="ticket-edit-grid" hidden>
          <div>
            <label for="edit-ticket-priority" class="ticket-meta-label" style="display: block;">Priority</label>
            <select id="edit-ticket-priority" class="form-field">
              <option value="P1" ${ticket.priority === "P1" ? "selected" : ""}>P1</option>
              <option value="P2" ${ticket.priority === "P2" ? "selected" : ""}>P2</option>
              <option value="P3" ${(!ticket.priority || ticket.priority === "P3") ? "selected" : ""}>P3</option>
              <option value="P4" ${ticket.priority === "P4" ? "selected" : ""}>P4</option>
            </select>
          </div>
          <div>
            <label for="edit-ticket-summary" class="ticket-meta-label" style="display: block;">Ticket summary</label>
            <input id="edit-ticket-summary" class="form-field" type="text" value="${escapeHtml(ticket.summary || "")}">
          </div>
        </div>

        <div class="ticket-actions">
          <button
            id="confirm-ticket-btn"
            class="btn-dark"
            type="button"
            ${ticketCreatedState ? "disabled" : ""}
          >
            ${ticketCreatedState ? `Created (${escapeHtml(ticketCreatedState.ticket_id)})` : "Confirm & create ticket"}
          </button>
          <button
            id="edit-ticket-btn"
            class="btn-outline"
            type="button"
            ${ticketCreatedState ? "disabled" : ""}
          >
            Edit details
          </button>
        </div>
      </div>
    </article>
  `;
}

function wireDynamicCardEvents() {
  outputStack.querySelectorAll(".cite-pill[data-cite-doc]").forEach((btn) => {
    btn.addEventListener("click", () => {
      focusCitationCard(btn.dataset.citeDoc, btn.dataset.citeSec);
    });
  });

  const copyBtn = document.getElementById("copy-email-btn");
  if (copyBtn && currentDraftEmail) {
    copyBtn.addEventListener("click", async () => {
      const ccLine = Array.isArray(currentDraftEmail.cc)
        ? currentDraftEmail.cc.join(", ")
        : currentDraftEmail.cc || "";
      const fullText =
        `To: ${currentDraftEmail.to || ""}\n` +
        (ccLine ? `CC: ${ccLine}\n` : "") +
        `Subject: ${currentDraftEmail.subject || ""}\n\n` +
        `${currentDraftEmail.body || ""}`;
      try {
        await navigator.clipboard.writeText(fullText);
        copyBtn.textContent = "Copied ✓";
        setTimeout(() => {
          copyBtn.textContent = "Copy";
        }, 1600);
      } catch {
        copyBtn.textContent = "Copy failed";
      }
    });
  }

  const editBtn = document.getElementById("edit-ticket-btn");
  const editPanel = document.getElementById("ticket-edit-panel");
  const priSelect = document.getElementById("edit-ticket-priority");
  const summaryInput = document.getElementById("edit-ticket-summary");
  const priDisplay = document.getElementById("ticket-priority-display");
  const summaryDisplay = document.getElementById("ticket-summary-display");

  if (editBtn && editPanel && currentPendingTicket) {
    editBtn.addEventListener("click", () => {
      const opening = editPanel.hidden;
      editPanel.hidden = !opening;
      editBtn.textContent = opening ? "Done editing" : "Edit details";
      if (!opening && priSelect && summaryInput) {
        currentPendingTicket.priority = priSelect.value;
        currentPendingTicket.summary = summaryInput.value.trim() || currentPendingTicket.summary;
        if (priDisplay) priDisplay.textContent = currentPendingTicket.priority;
        if (summaryDisplay) summaryDisplay.textContent = currentPendingTicket.summary;
      }
    });
  }

  if (priSelect && currentPendingTicket) {
    priSelect.addEventListener("change", () => {
      currentPendingTicket.priority = priSelect.value;
      if (priDisplay) priDisplay.textContent = priSelect.value;
    });
  }
  if (summaryInput && currentPendingTicket) {
    summaryInput.addEventListener("input", () => {
      currentPendingTicket.summary = summaryInput.value;
      if (summaryDisplay) summaryDisplay.textContent = summaryInput.value;
    });
  }

  const confirmBtn = document.getElementById("confirm-ticket-btn");
  if (confirmBtn && currentPendingTicket && !ticketCreatedState) {
    confirmBtn.addEventListener("click", () => {
      confirmPreview.textContent = JSON.stringify(currentPendingTicket, null, 2);
      confirmDialog.showModal();
    });
  }
}

function renderChatResult(data) {
  currentDraftEmail = data.draft_email || null;
  currentPendingTicket = data.pending_confirmation ? { ...data.pending_confirmation } : null;
  ticketCreatedState = null;

  const sec = typeof data.latency_ms === "number" ? (data.latency_ms / 1000).toFixed(2) : "—";
  const citeCount = (data.citations || []).length;
  const traceCount = (data.trace || []).length;
  const modeLabel = formatProviderName(data.mode_used);

  runStatusStrip.hidden = false;
  if (data.status === "blocked") {
    runStatusBadge.className = "run-status-badge danger";
    runStatusBadge.textContent = "✕ Blocked by guardrail";
  } else if (data.abstained) {
    runStatusBadge.className = "run-status-badge warn";
    runStatusBadge.textContent = "⚠ Abstained";
  } else {
    runStatusBadge.className = "run-status-badge";
    runStatusBadge.textContent = "✓ Completed";
  }
  runMeta.textContent = `${modeLabel} · ${sec} s · ${citeCount} citation${citeCount === 1 ? "" : "s"} · ${traceCount} tool call${traceCount === 1 ? "" : "s"}`;

  const parsed = parseAnswerStructure(data.answer || "");
  const cards = [
    buildHeroVerdictCard(data, parsed),
    buildFindingsCard(data, parsed),
    buildOptionsSection(data, parsed),
    buildEscalationCard(data.escalation),
    buildEmailCard(currentDraftEmail),
    buildTicketCard(currentPendingTicket),
  ].filter(Boolean);

  outputStack.innerHTML = cards.join("");
  renderCitationsRail(data.citations || []);
  renderTraceRail(data.trace || []);
  wireDynamicCardEvents();
}

async function submitPrompt() {
  const prompt = promptInput.value.trim();
  if (!prompt || isSubmitting) return;

  isSubmitting = true;
  submitBtn.disabled = true;
  submitBtn.textContent = "Working…";
  errorBanner.hidden = true;
  runStatusStrip.hidden = false;
  runStatusBadge.className = "run-status-badge";
  runStatusBadge.textContent = "Working…";
  runMeta.textContent = "Running hybrid retrieval & MCP verification";

  try {
    const resp = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: prompt,
        provider_override: providerSelect.value,
      }),
    });

    if (!resp.ok) {
      const detail = await resp.text();
      throw new Error(`HTTP ${resp.status}: ${detail}`);
    }

    const data = await resp.json();
    renderChatResult(data);
  } catch (err) {
    runStatusStrip.hidden = true;
    errorBanner.hidden = false;
    errorBanner.textContent = `Request failed: ${err.message}`;
  } finally {
    isSubmitting = false;
    submitBtn.disabled = false;
    submitBtn.textContent = "Ask →";
  }
}

function resetWorkspace() {
  promptInput.value = "";
  demoButtons.querySelectorAll(".example-card").forEach((b) => b.classList.remove("active"));
  runStatusStrip.hidden = true;
  errorBanner.hidden = true;
  currentPendingTicket = null;
  currentDraftEmail = null;
  ticketCreatedState = null;

  outputStack.innerHTML = `
    <div class="empty-workspace-card">
      Select an example on the left, click a persona to include their employee ID, or ask any Northstar HR policy question above. Every answer runs hybrid FAISS + BM25 retrieval over the 12 policy documents and verifies employee eligibility via MCP tools before proposing emails or tickets.
    </div>
  `;
  railCitationsCount.textContent = "0";
  railTraceCount.textContent = "0";
  citationsList.innerHTML = `<li class="rail-card" style="color: var(--muted); font-size: 0.8rem;">No citations yet. Ask a question to inspect retrieved policy chunks.</li>`;
  traceList.innerHTML = `<li class="rail-card" style="color: var(--muted); font-size: 0.8rem;">No tool calls yet. Every MCP retrieval, directory lookup, and compliance check is traced here.</li>`;
  promptInput.focus();
}

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  submitPrompt();
});

promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submitPrompt();
  }
});

clearBtn.addEventListener("click", resetWorkspace);
refreshTicketsBtn.addEventListener("click", refreshTicketsOnly);
railTabCitations.addEventListener("click", () => switchRailTab("citations"));
railTabTrace.addEventListener("click", () => switchRailTab("trace"));

cancelConfirmBtn.addEventListener("click", () => confirmDialog.close());
confirmDialog.addEventListener("click", (event) => {
  if (event.target === confirmDialog) confirmDialog.close();
});

approveConfirmBtn.addEventListener("click", async () => {
  if (!currentPendingTicket) return;
  approveConfirmBtn.disabled = true;
  approveConfirmBtn.textContent = "Creating…";

  try {
    const resp = await fetch("/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        proposed_ticket: currentPendingTicket,
        confirmed: true,
      }),
    });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    const payload = await resp.json();
    const createdTicket = payload.result && payload.result.ticket;
    ticketCreatedState = createdTicket || { ticket_id: "Confirmed" };
    confirmDialog.close();

    const statusEl = document.getElementById("ticket-status-subtitle");
    const confirmBtn = document.getElementById("confirm-ticket-btn");
    const editBtn = document.getElementById("edit-ticket-btn");
    const editPanel = document.getElementById("ticket-edit-panel");
    const verdictPill = document.getElementById("verdict-priority-pill");

    if (statusEl) {
      statusEl.className = "surface-card-subtitle";
      statusEl.style.color = "var(--teal)";
      statusEl.style.fontWeight = "600";
      statusEl.textContent = `Created · ${ticketCreatedState.ticket_id}`;
    }
    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.textContent = `Created (${ticketCreatedState.ticket_id})`;
    }
    if (editBtn) editBtn.disabled = true;
    if (editPanel) editPanel.hidden = true;
    if (verdictPill) {
      verdictPill.textContent = `${currentPendingTicket.priority || "P3"} · Confirmed ${ticketCreatedState.ticket_id}`;
    }

    await refreshTicketsOnly();
  } catch (err) {
    errorBanner.hidden = false;
    errorBanner.textContent = `Ticket confirmation failed: ${err.message}`;
  } finally {
    approveConfirmBtn.disabled = false;
    approveConfirmBtn.textContent = "Confirm & create ticket";
  }
});

(function initCopilotPage() {
  hydrateNavbarAndSidebar();

  const params = new URLSearchParams(window.location.search);
  const initialQuery = params.get("q");
  if (initialQuery) {
    promptInput.value = initialQuery;
    promptInput.focus();
    window.history.replaceState({}, "", "/");
  }
})();
