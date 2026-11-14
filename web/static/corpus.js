const navCorpusText = document.getElementById("nav-corpus-text");
const navStatusDot = document.getElementById("nav-status-dot");
const navMcpStat = document.getElementById("nav-mcp-stat");
const navModelStat = document.getElementById("nav-model-stat");
const corpusSubtitle = document.getElementById("corpus-subtitle");
const corpusSearch = document.getElementById("corpus-search");
const formatFilters = document.getElementById("format-filters");
const corpusTbody = document.getElementById("corpus-tbody");

const docModal = document.getElementById("doc-modal");
const modalDocId = document.getElementById("modal-doc-id");
const modalDocFormat = document.getElementById("modal-doc-format");
const modalDocCat = document.getElementById("modal-doc-cat");
const modalDocChunksCount = document.getElementById("modal-doc-chunks-count");
const modalDocTitle = document.getElementById("modal-doc-title");
const askPolicyBtn = document.getElementById("ask-policy-btn");
const closeDocModalBtn = document.getElementById("close-doc-modal");
const tabBtnDocument = document.getElementById("tab-btn-document");
const tabBtnChunks = document.getElementById("tab-btn-chunks");
const modalTabChunkCount = document.getElementById("modal-tab-chunk-count");
const docModalBody = document.getElementById("doc-modal-body");
const tabPanelDocument = document.getElementById("tab-panel-document");
const tabPanelChunks = document.getElementById("tab-panel-chunks");
const docTocList = document.getElementById("doc-toc-list");
const docSectionsContainer = document.getElementById("doc-sections-container");
const chunksLead = document.getElementById("chunks-lead");
const chunkCardsStack = document.getElementById("chunk-cards-stack");

const FORMAT_LABELS = {
  html: "HTML",
  pdf: "PDF",
  markdown: "MD",
  txt: "TXT",
};

const FORMAT_FILTER_NAMES = {
  html: "HTML",
  pdf: "PDF",
  markdown: "Markdown",
  txt: "Text",
};

let corpusDocs = [];
let maxChunks = 1;
let activeFormat = "all";
let searchQuery = "";
let activeDocDetail = null;
let activeModalTab = "document";

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

async function hydrateNavbar() {
  try {
    const resp = await fetch("/health");
    if (!resp.ok) return;
    const h = await resp.json();
    const docs = h.corpus_docs ?? 12;
    const chunks = h.corpus_chunks ?? 117;
    const tools = Array.isArray(h.mcp_tools) ? h.mcp_tools.length : (h.mcp_tools ?? 8);
    const model = formatProviderName(h.llm_provider);

    if (navCorpusText) {
      navCorpusText.innerHTML = `<strong>${escapeHtml(docs)}</strong> docs · <strong>${escapeHtml(chunks)}</strong> chunks`;
    }
    if (navMcpStat) {
      navMcpStat.innerHTML = `MCP ${escapeHtml(h.mcp_transport || "stdio")} · <strong>${escapeHtml(tools)} tools</strong>`;
    }
    if (navModelStat) {
      navModelStat.innerHTML = `Model · <strong>${escapeHtml(model)}</strong>`;
    }
    if (navStatusDot) {
      navStatusDot.className = h.mcp_connected ? "status-dot" : "status-dot warn";
    }
  } catch {
    if (navStatusDot) navStatusDot.className = "status-dot warn";
  }
}

function renderFilterPills(data) {
  const counts = data.format_counts || {};
  const total = data.doc_count ?? corpusDocs.length;
  const order = ["html", "pdf", "markdown", "txt"];

  const buttons = [
    `<button type="button" class="filter-pill ${activeFormat === "all" ? "active" : ""}" data-format="all">All ${escapeHtml(total)}</button>`,
  ];
  for (const fmt of order) {
    const count = counts[fmt] ?? 0;
    if (count > 0 || fmt in counts) {
      const label = FORMAT_FILTER_NAMES[fmt] || fmt.toUpperCase();
      buttons.push(
        `<button type="button" class="filter-pill ${activeFormat === fmt ? "active" : ""}" data-format="${escapeHtml(fmt)}">${escapeHtml(label)} ${escapeHtml(count)}</button>`
      );
    }
  }
  formatFilters.innerHTML = buttons.join("");
}

function getFilteredDocs() {
  const q = searchQuery.trim().toLowerCase();
  return corpusDocs.filter((doc) => {
    if (activeFormat !== "all" && doc.file_format !== activeFormat) {
      return false;
    }
    if (!q) return true;
    const haystack = `${doc.doc_id} ${doc.doc_title} ${doc.category_label || doc.category} ${doc.source_file}`.toLowerCase();
    return haystack.includes(q);
  });
}

function renderTable() {
  const rows = getFilteredDocs();
  if (!rows.length) {
    corpusTbody.innerHTML = `
      <tr>
        <td colspan="5" style="color: var(--muted); padding: 24px 18px; text-align: center;">
          No policies match the current search or format filter.
        </td>
      </tr>
    `;
    return;
  }

  corpusTbody.innerHTML = rows
    .map((doc) => {
      const pct = Math.max(8, Math.round(((doc.chunks || 0) / Math.max(1, maxChunks)) * 100));
      const fmtBadge = FORMAT_LABELS[doc.file_format] || String(doc.file_format || "").toUpperCase();
      return `
        <tr tabindex="0" data-doc-id="${escapeHtml(doc.doc_id)}" aria-label="Open ${escapeHtml(doc.doc_id)} ${escapeHtml(doc.doc_title)}">
          <td><span class="corpus-pol-id">${escapeHtml(doc.doc_id)}</span></td>
          <td><span class="corpus-doc-title">${escapeHtml(doc.doc_title)}</span></td>
          <td><span class="corpus-cat">${escapeHtml(doc.category_label || doc.category)}</span></td>
          <td><span class="format-tag">${escapeHtml(fmtBadge)}</span></td>
          <td>
            <div class="chunk-bar-cell">
              <span class="chunk-num">${escapeHtml(doc.chunks)}</span>
              <span class="chunk-track" aria-hidden="true">
                <span class="chunk-fill" style="width: ${pct}%;"></span>
              </span>
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

function switchModalTab(tabName) {
  activeModalTab = tabName === "chunks" ? "chunks" : "document";
  const isDoc = activeModalTab === "document";

  tabBtnDocument.classList.toggle("active", isDoc);
  tabBtnChunks.classList.toggle("active", !isDoc);
  tabBtnDocument.setAttribute("aria-selected", String(isDoc));
  tabBtnChunks.setAttribute("aria-selected", String(!isDoc));

  tabPanelDocument.hidden = !isDoc;
  tabPanelChunks.hidden = isDoc;
  docModalBody.scrollTop = 0;
}

function renderSectionBody(text, heading) {
  const lines = String(text || "").split(/\n+/);
  const normHeading = String(heading || "").replace(/\s+/g, " ").trim().toLowerCase();
  const blocks = [];
  let bullets = [];
  let checkedFirst = false;

  const flushBullets = () => {
    if (!bullets.length) return;
    blocks.push(`<ul>${bullets.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`);
    bullets = [];
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) continue;
    if (!checkedFirst) {
      checkedFirst = true;
      const normLine = line.replace(/^#+\s*/, "").replace(/\s+/g, " ").trim().toLowerCase();
      if (normHeading && (normLine === normHeading || normHeading.endsWith(normLine))) {
        continue;
      }
    }
    if (line.startsWith("- ") || line.startsWith("• ") || line.startsWith("* ")) {
      bullets.push(line.slice(2).trim());
    } else {
      flushBullets();
      blocks.push(`<p>${escapeHtml(line)}</p>`);
    }
  }
  flushBullets();
  return blocks.join("");
}

function formatAnchor(rawAnchor) {
  const clean = String(rawAnchor || "").trim();
  if (!clean) return "#section";
  if (clean.startsWith("#") || /^p\.\d+/i.test(clean) || clean.startsWith("page-")) {
    return clean;
  }
  return `#${clean}`;
}

function leafSectionTitle(rawPath, fallback) {
  const clean = String(rawPath || "").trim();
  if (!clean) return fallback;
  const parts = clean.split(">").map((s) => s.trim()).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : clean;
}

function renderModalDocument(detail) {
  const sections = detail.sections || [];
  if (!sections.length) {
    docTocList.innerHTML = `<li style="color: var(--muted); font-size: 0.78rem;">Full text</li>`;
    docSectionsContainer.innerHTML = `<p style="color: var(--muted);">No sections extracted.</p>`;
    return;
  }

  docTocList.innerHTML = sections
    .map((sec, idx) => {
      const title = leafSectionTitle(sec.section_path, `Section ${idx + 1}`);
      return `
        <li>
          <a href="#doc-sec-${idx}" class="doc-toc-link ${idx === 0 ? "active" : ""}" data-sec-idx="${idx}">
            ${escapeHtml(title)}
          </a>
        </li>
      `;
    })
    .join("");

  docSectionsContainer.innerHTML = sections
    .map((sec, idx) => {
      const heading = leafSectionTitle(sec.section_path, `Section ${idx + 1}`);
      return `
        <article id="doc-sec-${idx}" class="doc-section-block" data-anchor="${escapeHtml(sec.page_or_anchor || "")}">
          <h3>${escapeHtml(heading)}</h3>
          ${renderSectionBody(sec.text, heading)}
        </article>
      `;
    })
    .join("");
}

function renderModalChunks(detail) {
  const fmt = (detail.file_format || "").toLowerCase();
  const strategy =
    fmt === "html"
      ? "Split on section headings for HTML, preserving heading path and #anchor metadata."
      : fmt === "markdown"
        ? "Split on Markdown heading structure with fixed word overlap across long sections."
        : fmt === "pdf"
          ? "Split by page region and boundary for PDF extraction with ~28-word overlap."
          : "Split by section blocks and fixed word windows (~220 words, ~28-word overlap).";

  chunksLead.textContent = `Chunks exactly as they are indexed and retrieved. ${strategy}`;

  const chunks = detail.chunks || [];
  chunkCardsStack.innerHTML = chunks
    .map((chunk) => {
      const num = String(chunk.index || chunk.chunk_idx + 1).padStart(2, "0");
      const anchor = formatAnchor(chunk.page_or_anchor);
      const secPath = chunk.section_path || detail.doc_title || "";
      return `
        <article class="chunk-card" id="chunk-card-${escapeHtml(chunk.index || chunk.chunk_idx + 1)}" data-chunk-id="${escapeHtml(chunk.chunk_id)}">
          <div class="chunk-card-head">
            <div class="chunk-card-id">
              <strong>chunk ${escapeHtml(num)}</strong>
              <span class="chunk-card-anchor">${escapeHtml(anchor)}</span>
            </div>
            <div class="chunk-card-sec">${escapeHtml(secPath)}</div>
          </div>
          <div class="chunk-card-text">${escapeHtml(chunk.text)}</div>
        </article>
      `;
    })
    .join("");
}

async function openPolicyModal(docId, options = {}) {
  const requestedTab = options.tab === "chunks" ? "chunks" : "document";
  const targetAnchor = options.anchor || "";
  const targetChunkId = options.chunkId || "";

  const summary = corpusDocs.find((d) => d.doc_id === docId);
  modalDocId.textContent = docId;
  modalDocFormat.textContent = summary ? (FORMAT_LABELS[summary.file_format] || summary.file_format.toUpperCase()) : "";
  modalDocCat.textContent = summary ? (summary.category_label || summary.category) : "";
  modalDocChunksCount.textContent = summary ? `${summary.chunks} chunks` : "…";
  modalDocTitle.textContent = summary ? summary.doc_title : "Loading document…";
  modalTabChunkCount.textContent = summary ? String(summary.chunks) : "0";
  docTocList.innerHTML = "";
  docSectionsContainer.innerHTML = `<p style="color: var(--muted);">Loading document content…</p>`;
  chunkCardsStack.innerHTML = `<p style="color: var(--muted);">Loading indexed chunks…</p>`;

  switchModalTab(requestedTab);
  if (!docModal.open) {
    docModal.showModal();
  }

  try {
    const resp = await fetch(`/api/corpus/${encodeURIComponent(docId)}`);
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    const detail = await resp.json();
    activeDocDetail = detail;

    modalDocId.textContent = detail.doc_id;
    modalDocFormat.textContent = FORMAT_LABELS[detail.file_format] || String(detail.file_format || "").toUpperCase();
    modalDocCat.textContent = detail.category_label || detail.category || "";
    modalDocChunksCount.textContent = `${detail.chunk_count} chunks`;
    modalDocTitle.textContent = detail.doc_title;
    modalTabChunkCount.textContent = String(detail.chunk_count);

    renderModalDocument(detail);
    renderModalChunks(detail);

    if (targetChunkId) {
      switchModalTab("chunks");
      const targetEl = chunkCardsStack.querySelector(`[data-chunk-id="${CSS.escape(targetChunkId)}"]`);
      if (targetEl) {
        targetEl.scrollIntoView({ block: "center", behavior: "smooth" });
        targetEl.style.borderColor = "var(--teal)";
      }
    } else if (targetAnchor && requestedTab === "document") {
      const cleanAnchor = targetAnchor.replace(/^#/, "").toLowerCase();
      const blocks = Array.from(docSectionsContainer.querySelectorAll(".doc-section-block"));
      const match = blocks.find((b) => (b.dataset.anchor || "").replace(/^#/, "").toLowerCase() === cleanAnchor);
      if (match) {
        match.scrollIntoView({ block: "start", behavior: "smooth" });
      }
    }
  } catch (err) {
    docSectionsContainer.innerHTML = `<div class="error-banner">Failed to load policy details: ${escapeHtml(err.message)}</div>`;
    chunkCardsStack.innerHTML = `<div class="error-banner">Failed to load indexed chunks: ${escapeHtml(err.message)}</div>`;
  }
}

function closePolicyModal() {
  if (docModal.open) {
    docModal.close();
  }
  const url = new URL(window.location.href);
  if (url.searchParams.has("doc") || url.searchParams.has("tab") || url.searchParams.has("chunk")) {
    url.searchParams.delete("doc");
    url.searchParams.delete("tab");
    url.searchParams.delete("chunk");
    url.searchParams.delete("anchor");
    window.history.replaceState({}, "", url.pathname);
  }
}

async function initCorpusPage() {
  hydrateNavbar();
  try {
    const resp = await fetch("/api/corpus");
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    const data = await resp.json();
    corpusDocs = data.documents || [];
    maxChunks = Math.max(1, ...corpusDocs.map((d) => Number(d.chunks) || 0));

    if (corpusSubtitle) {
      corpusSubtitle.textContent =
        `The ${data.doc_count} documents the copilot answers from, split into ${data.chunk_count} chunks ` +
        `for hybrid retrieval (FAISS + BM25, fused with RRF). Open a document to read it or inspect the chunks the retriever searches.`;
    }

    renderFilterPills(data);
    renderTable();

    const params = new URLSearchParams(window.location.search);
    const initialDoc = params.get("doc");
    if (initialDoc) {
      const normalizedDoc = corpusDocs.find(
        (d) => d.doc_id.toUpperCase() === initialDoc.trim().toUpperCase()
      );
      if (normalizedDoc) {
        openPolicyModal(normalizedDoc.doc_id, {
          tab: params.get("tab") || "document",
          chunkId: params.get("chunk") || "",
          anchor: params.get("anchor") || "",
        });
      }
    }
  } catch (err) {
    corpusTbody.innerHTML = `
      <tr>
        <td colspan="5">
          <div class="error-banner">Failed to load policy corpus: ${escapeHtml(err.message)}</div>
        </td>
      </tr>
    `;
  }
}

corpusSearch.addEventListener("input", (event) => {
  searchQuery = event.target.value || "";
  renderTable();
});

formatFilters.addEventListener("click", (event) => {
  const pill = event.target.closest(".filter-pill");
  if (!pill) return;
  activeFormat = pill.dataset.format || "all";
  Array.from(formatFilters.querySelectorAll(".filter-pill")).forEach((btn) => {
    btn.classList.toggle("active", btn === pill);
  });
  renderTable();
});

corpusTbody.addEventListener("click", (event) => {
  const row = event.target.closest("tr[data-doc-id]");
  if (!row) return;
  openPolicyModal(row.dataset.docId, { tab: "document" });
});

corpusTbody.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const row = event.target.closest("tr[data-doc-id]");
  if (!row) return;
  event.preventDefault();
  openPolicyModal(row.dataset.docId, { tab: "document" });
});

tabBtnDocument.addEventListener("click", () => switchModalTab("document"));
tabBtnChunks.addEventListener("click", () => switchModalTab("chunks"));

docTocList.addEventListener("click", (event) => {
  const link = event.target.closest(".doc-toc-link");
  if (!link) return;
  event.preventDefault();
  const idx = link.dataset.secIdx;
  const target = document.getElementById(`doc-sec-${idx}`);
  if (target) {
    target.scrollIntoView({ block: "start", behavior: "smooth" });
  }
  Array.from(docTocList.querySelectorAll(".doc-toc-link")).forEach((el) => {
    el.classList.toggle("active", el === link);
  });
});

askPolicyBtn.addEventListener("click", () => {
  if (!activeDocDetail) return;
  const q = `What are the key eligibility rules, limits, and required approvals under ${activeDocDetail.doc_id} (${activeDocDetail.doc_title})?`;
  window.location.href = `/?q=${encodeURIComponent(q)}`;
});

closeDocModalBtn.addEventListener("click", closePolicyModal);
docModal.addEventListener("click", (event) => {
  if (event.target === docModal) {
    closePolicyModal();
  }
});
docModal.addEventListener("cancel", (event) => {
  event.preventDefault();
  closePolicyModal();
});

initCorpusPage();
