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

function formatInlineMarkdown(raw) {
  const src = String(raw || "");
  if (!src) return "";
  const codeSpans = [];
  let work = src.replace(/`([^`\n]+)`/g, (_, inner) => {
    const idx = codeSpans.length;
    codeSpans.push(`<code class="corpus-inline-code">${escapeHtml(inner)}</code>`);
    return `\uE000CS${idx}\uE001`;
  });
  work = work.replace(/\\\|/g, "|");
  work = escapeHtml(work);
  work = work.replace(/\*\*((?:(?!\*\*).)+?)\*\*/g, "<strong>$1</strong>");
  work = work.replace(/(^|[^\w])__([^\s_](?:[^\n]*?[^\s_])?)__(?=$|[^\w])/g, "$1<strong>$2</strong>");
  // Strip unmatched ** remnants from chunk word-overlap boundaries
  work = work.replace(/\*\*/g, "");
  work = work.replace(/(^|[^\w*])\*([^\s*](?:[^*\n]*?[^\s*])?)\*(?=[^\w*]|$)/g, "$1<em>$2</em>");
  work = work.replace(/(^|[^\w_])_([^\s_](?:[^_\n]*?[^\s_])?)_(?=[^\w_]|$)/g, "$1<em>$2</em>");
  work = work.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)<>]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  work = work.replace(/\uE000CS(\d+)\uE001/g, (_, idx) => codeSpans[Number(idx)] || "");
  return work;
}

function splitPipeRow(line) {
  let trimmed = String(line || "").trim();
  if (trimmed.startsWith("|")) trimmed = trimmed.slice(1);
  if (trimmed.endsWith("|") && !trimmed.endsWith("\\|")) trimmed = trimmed.slice(0, -1);
  const cells = [];
  let cur = "";
  for (let i = 0; i < trimmed.length; i++) {
    if (trimmed[i] === "\\" && trimmed[i + 1] === "|") {
      cur += "|";
      i += 1;
    } else if (trimmed[i] === "|") {
      cells.push(cur.trim());
      cur = "";
    } else {
      cur += trimmed[i];
    }
  }
  cells.push(cur.trim());
  return cells;
}

function parseTableAlignments(sepLine) {
  const raw = String(sepLine || "").trim();
  if (!raw.includes("|") || !raw.includes("-")) return null;
  const cells = splitPipeRow(raw);
  if (cells.length < 1) return null;
  const aligns = [];
  for (const cell of cells) {
    if (!/^:?-{2,}:?$/.test(cell)) return null;
    const left = cell.startsWith(":");
    const right = cell.endsWith(":");
    aligns.push(left && right ? "center" : right ? "right" : "left");
  }
  return aligns;
}

function buildHtmlTable(headers, rows, alignments, tableClass) {
  const colCount = headers.length;
  const aligns = alignments || headers.map(() => "left");
  const ths = headers
    .map((h, i) => {
      const alignAttr = aligns[i] && aligns[i] !== "left" ? ` style="text-align:${aligns[i]}"` : "";
      return `<th${alignAttr}>${formatInlineMarkdown(h)}</th>`;
    })
    .join("");
  const trs = rows
    .map((row) => {
      const tds = Array.from({ length: colCount }, (_, i) => {
        const alignAttr = aligns[i] && aligns[i] !== "left" ? ` style="text-align:${aligns[i]}"` : "";
        return `<td${alignAttr}>${formatInlineMarkdown(row[i] ?? "")}</td>`;
      }).join("");
      return `<tr>${tds}</tr>`;
    })
    .join("");
  return `<div class="corpus-table-wrap"><table class="${tableClass}"><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table></div>`;
}

function parseKvPipeRow(line) {
  const raw = String(line || "").trim();
  if (!raw.includes("|") || raw.startsWith("|")) return null;
  const parts = raw.split("|").map((p) => p.trim());
  if (parts.length < 2) return null;
  const pairs = [];
  for (const part of parts) {
    const m = part.match(/^([A-Za-z][A-Za-z0-9 /&()-]{1,40}):\s*(.+)$/);
    if (!m) return null;
    pairs.push([m[1].trim(), m[2].trim()]);
  }
  return pairs;
}

function renderSectionBody(text, heading) {
  const rawLines = String(text || "").split(/\r?\n/);
  const normHeading = String(heading || "").replace(/\s+/g, " ").trim().toLowerCase();
  const blocks = [];
  let paraLines = [];
  let listType = null;
  let listStart = 1;
  let listItems = [];
  let quoteLines = [];
  let checkedFirst = false;

  const flushPara = () => {
    if (!paraLines.length) return;
    blocks.push(`<p>${formatInlineMarkdown(paraLines.join(" "))}</p>`);
    paraLines = [];
  };

  const flushList = () => {
    if (!listItems.length) return;
    const tag = listType === "ol" ? "ol" : "ul";
    const startAttr = tag === "ol" && listStart !== 1 ? ` start="${listStart}"` : "";
    blocks.push(`<${tag}${startAttr}>${listItems.map((item) => `<li>${formatInlineMarkdown(item)}</li>`).join("")}</${tag}>`);
    listItems = [];
    listType = null;
    listStart = 1;
  };

  const flushQuote = () => {
    if (!quoteLines.length) return;
    blocks.push(`<blockquote class="corpus-doc-quote">${quoteLines.map((q) => formatInlineMarkdown(q)).join("<br>")}</blockquote>`);
    quoteLines = [];
  };

  const flushAll = () => {
    flushPara();
    flushList();
    flushQuote();
  };

  for (let i = 0; i < rawLines.length; i++) {
    const line = rawLines[i].trim();
    if (!line) {
      flushAll();
      continue;
    }

    if (!checkedFirst) {
      checkedFirst = true;
      const normLine = line.replace(/^#+\s*/, "").replace(/\s+/g, " ").trim().toLowerCase();
      if (normHeading && (normLine === normHeading || normHeading.endsWith(normLine))) {
        continue;
      }
    }

    // Markdown pipe table: header line + alignment separator line
    if (line.includes("|") && i + 1 < rawLines.length) {
      const aligns = parseTableAlignments(rawLines[i + 1]);
      if (aligns) {
        const headers = splitPipeRow(line);
        if (headers.length >= 1) {
          flushAll();
          const rows = [];
          let j = i + 2;
          while (j < rawLines.length) {
            const rowLine = rawLines[j].trim();
            if (!rowLine || !rowLine.includes("|")) break;
            rows.push(splitPipeRow(rowLine));
            j += 1;
          }
          blocks.push(buildHtmlTable(headers, rows, aligns, "corpus-doc-table"));
          i = j - 1;
          continue;
        }
      }
    }

    // Repeated Key: Val | Key2: Val2 lines (>= 2 consecutive rows sharing keys)
    const kvFirst = parseKvPipeRow(line);
    if (kvFirst && i + 1 < rawLines.length) {
      const keySig = kvFirst.map(([k]) => k).join("\uE000");
      const kvRows = [kvFirst.map(([, v]) => v)];
      let j = i + 1;
      while (j < rawLines.length) {
        const kvNext = parseKvPipeRow(rawLines[j]);
        if (!kvNext || kvNext.map(([k]) => k).join("\uE000") !== keySig) break;
        kvRows.push(kvNext.map(([, v]) => v));
        j += 1;
      }
      if (kvRows.length >= 2) {
        flushAll();
        blocks.push(buildHtmlTable(kvFirst.map(([k]) => k), kvRows, null, "corpus-doc-table"));
        i = j - 1;
        continue;
      }
    }

    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(line)) {
      flushAll();
      blocks.push('<hr class="corpus-doc-hr">');
      continue;
    }

    const headingMatch = line.match(/^#{2,4}\s+(.+)$/);
    if (headingMatch) {
      flushAll();
      blocks.push(`<h4 class="corpus-doc-subhead">${formatInlineMarkdown(headingMatch[1].trim())}</h4>`);
      continue;
    }

    if (line.startsWith("> ")) {
      flushPara();
      flushList();
      quoteLines.push(line.slice(2).trim());
      continue;
    }
    flushQuote();

    const ulMatch = line.match(/^(?:[-•*])\s+(.+)$/);
    if (ulMatch) {
      flushPara();
      if (listType !== "ul") {
        flushList();
        listType = "ul";
      }
      listItems.push(ulMatch[1].trim());
      continue;
    }

    const olMatch = line.match(/^(\d+)\.\s+(.+)$/);
    if (olMatch) {
      flushPara();
      if (listType !== "ol") {
        flushList();
        listType = "ol";
        listStart = Number(olMatch[1]) || 1;
      }
      listItems.push(olMatch[2].trim());
      continue;
    }

    flushList();
    paraLines.push(line);
  }

  flushAll();
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
      const title = leafSectionTitle(sec.section_path, `Section ${idx + 1}`)
        .replace(/`([^`]+)`/g, "$1")
        .replace(/\*\*/g, "");
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
          <h3>${formatInlineMarkdown(heading)}</h3>
          ${renderSectionBody(sec.text, heading)}
        </article>
      `;
    })
    .join("");
}

function renderChunkProse(raw) {
  const src = String(raw || "").trim();
  if (!src) return "";
  if (/\n\s*(?:[-•*]|\d+\.)\s+/.test(src) || /\n\s*\n/.test(src)) {
    return renderSectionBody(src, "");
  }
  const normalized = src.replace(/\s+/g, " ").trim();
  const boldBulletRe = /(?:^|\s)-\s+(?=\*\*)/g;
  const matches = [...normalized.matchAll(boldBulletRe)];
  if (matches.length >= 2) {
    const firstIdx = matches[0].index;
    const intro = normalized.slice(0, firstIdx).trim();
    const rest = normalized.slice(firstIdx).trim();
    const items = rest
      .split(/\s+-\s+(?=\*\*)/)
      .map((s) => s.replace(/^-\s+/, "").trim())
      .filter(Boolean);
    const introHtml = intro ? `<p>${formatInlineMarkdown(intro)}</p>` : "";
    const listHtml = items.length ? `<ul>${items.map((item) => `<li>${formatInlineMarkdown(item)}</li>`).join("")}</ul>` : "";
    return `${introHtml}${listHtml}`;
  }
  return `<p>${formatInlineMarkdown(normalized)}</p>`;
}

function tryExtractInlinePipeTable(src) {
  const sepRe = /\|\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|/g;
  let sepMatch;
  while ((sepMatch = sepRe.exec(src)) !== null) {
    const aligns = parseTableAlignments(sepMatch[0]);
    if (!aligns) continue;
    const colCount = aligns.length;
    let p = sepMatch.index - 1;
    while (p >= 0 && /\s/.test(src[p])) p -= 1;
    if (p < 0 || src[p] !== "|") continue;

    // Walk backward across `colCount` earlier unescaped pipes to find header opening `|`
    const hdrCloseIdx = p;
    let pipesNeeded = colCount;
    let hdrOpenIdx = -1;
    for (let k = hdrCloseIdx - 1; k >= 0; k--) {
      if (src[k] === "|" && (k === 0 || src[k - 1] !== "\\")) {
        pipesNeeded -= 1;
        if (pipesNeeded === 0) {
          hdrOpenIdx = k;
          break;
        }
      }
    }
    if (hdrOpenIdx < 0) continue;
    const headers = splitPipeRow(src.slice(hdrOpenIdx, hdrCloseIdx + 1));
    if (headers.length !== colCount) continue;

    let cursor = sepMatch.index + sepMatch[0].length;
    const rows = [];
    while (cursor < src.length) {
      let rowStart = cursor;
      while (rowStart < src.length && /\s/.test(src[rowStart])) rowStart += 1;
      if (rowStart >= src.length || src[rowStart] !== "|") break;

      let pipesFound = 0;
      let rowCloseIdx = -1;
      for (let k = rowStart + 1; k < src.length; k++) {
        if (src[k] === "\\" && src[k + 1] === "|") {
          k += 1;
          continue;
        }
        if (src[k] === "|") {
          pipesFound += 1;
          if (pipesFound === colCount) {
            rowCloseIdx = k;
            break;
          }
        }
      }
      if (rowCloseIdx < 0) break;
      const cells = splitPipeRow(src.slice(rowStart, rowCloseIdx + 1));
      if (cells.length !== colCount) break;
      rows.push(cells);
      cursor = rowCloseIdx + 1;
    }

    if (!rows.length) continue;
    return {
      start: hdrOpenIdx,
      end: cursor,
      tableHtml: buildHtmlTable(headers, rows, aligns, "corpus-chunk-table"),
    };
  }
  return null;
}

function tryExtractInlineKvTable(src) {
  if (!src.includes("|")) return null;
  const keyTokenRe = /\b([A-Z][A-Za-z0-9 /&()-]{1,32}):\s/g;
  const seenKeys = new Set();
  let match;
  while ((match = keyTokenRe.exec(src)) !== null) {
    const firstKey = match[1].trim();
    if (seenKeys.has(firstKey)) continue;
    seenKeys.add(firstKey);

    const keyStart = match.index;
    const tailAfterKey = src.slice(keyStart);
    const firstPipeIdx = tailAfterKey.indexOf("|");
    if (firstPipeIdx < 0 || firstPipeIdx > 180) continue;

    const escapedKey = firstKey.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const rowAnchorRe = new RegExp(`\\b(${escapedKey}:\\s)`, "g");
    const anchors = [];
    let am;
    while ((am = rowAnchorRe.exec(src)) !== null) {
      anchors.push(am.index);
    }
    if (anchors.length < 2) continue;

    const slices = anchors.map((start, idx) =>
      src.slice(start, idx + 1 < anchors.length ? anchors[idx + 1] : src.length).trim()
    );
    const parsedRows = slices.map(parseKvPipeRow);
    if (parsedRows.some((r) => !r)) continue;

    const keySig = parsedRows[0].map(([k]) => k).join("\uE000");
    if (!parsedRows.every((r) => r.map(([k]) => k).join("\uE000") === keySig)) continue;

    const headers = parsedRows[0].map(([k]) => k);
    const rows = parsedRows.map((r) => r.map(([, v]) => v));
    const lastRowIdx = rows.length - 1;
    const lastColIdx = headers.length - 1;
    const prevLengths = rows.slice(0, lastRowIdx).map((r) => r[lastColIdx].length);
    const maxPrevLen = prevLengths.length ? Math.max(...prevLengths) : 32;
    let lastCell = rows[lastRowIdx][lastColIdx];
    let trailingProse = "";

    if (lastCell.length > maxPrevLen + 10) {
      const parenSplit = lastCell.match(/^(.+?\))\s+([A-Z][a-z]+(?:\s+[a-z*].*|\s+[A-Z].*))$/);
      const proseStarterSplit = lastCell.match(
        /^([A-Z0-9$][^\n]{2,40}?)\s+((?:Employees|Staff|Workers|Contractors|Interns|Managers|Travelers|Approvals|Requests|Exceptions|All|Any|The|This|These|Those|Please|See|For|If|When|Note|Eligible|Standard)\s+[a-z(].+)$/
      );
      const sentenceSplit =
        lastCell.length > Math.max(55, maxPrevLen * 2)
          ? lastCell.match(/^([^.!?]+[.!?])\s+([A-Z*].+)$/)
          : null;
      const chosen = parenSplit || proseStarterSplit || sentenceSplit;
      if (chosen) {
        lastCell = chosen[1].trim();
        trailingProse = chosen[2].trim();
        rows[lastRowIdx][lastColIdx] = lastCell;
      }
    }

    return {
      start: anchors[0],
      end: trailingProse ? src.length - trailingProse.length : src.length,
      tableHtml: buildHtmlTable(headers, rows, null, "corpus-chunk-table"),
    };
  }
  return null;
}

function renderChunkBody(rawText) {
  const src = String(rawText || "").trim();
  if (!src) return "";
  const pipeTable = tryExtractInlinePipeTable(src);
  if (pipeTable) {
    return `${renderChunkBody(src.slice(0, pipeTable.start))}${pipeTable.tableHtml}${renderChunkBody(src.slice(pipeTable.end))}`;
  }
  const kvTable = tryExtractInlineKvTable(src);
  if (kvTable) {
    return `${renderChunkBody(src.slice(0, kvTable.start))}${kvTable.tableHtml}${renderChunkBody(src.slice(kvTable.end))}`;
  }
  return renderChunkProse(src);
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
            <div class="chunk-card-sec">${formatInlineMarkdown(secPath)}</div>
          </div>
          <div class="chunk-card-text">${renderChunkBody(chunk.text)}</div>
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
