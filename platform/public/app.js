// Review UI: the leveling sheet, the review queue and evidence-linked chat. No framework, no
// third-party requests.
const $ = (s, el = document) => el.querySelector(s);
const eur = (x, d = 2) => (x == null ? "" : x.toLocaleString("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d }));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const SEV = { missing_price: "high", qty_changed: "high", unit_changed: "high", missing_position: "high", spec_change: "high", outdated_version: "high", reservation: "high", arithmetic_error: "medium", extra_position: "medium", included_price: "medium", price_outlier: "medium", speculative_pricing: "medium", product_alternative: "low" };
const LABEL = { missing_price: "No price", included_price: "Priced as included", arithmetic_error: "EP × qty ≠ total", qty_changed: "Quantity changed", unit_changed: "Unit changed", missing_position: "Not priced", extra_position: "Added position", spec_change: "Long text changed", product_alternative: "Other product", price_outlier: "Price outlier", speculative_pricing: "Unbalanced pricing", outdated_version: "Outdated BoQ", reservation: "Reservation" };

let key = "";
try { key = sessionStorage.getItem("ble-key") || ""; } catch { /* storage may be blocked */ }
const state = { tender: null, detail: null, sheet: null, findings: [] };

async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { "content-type": "application/json", ...(key ? { "x-api-key": key } : {}), ...(opts.headers || {}) } });
  if (r.status === 401) {
    $("#key-btn").hidden = false;
    throw new Error("This platform needs an API key.");
  }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  return r.json();
}

$("#key-btn").addEventListener("click", () => {
  const k = prompt("API key");
  if (k) {
    key = k;
    try { sessionStorage.setItem("ble-key", k); } catch { /* keep in memory */ }
    loadTenders();
  }
});

async function loadTenders() {
  const ts = await api("/api/tenders");
  const nav = $("#tenders");
  nav.innerHTML = ts.map((t) => `<button type="button" data-id="${esc(t.id)}" title="${esc(t.project)}">${esc(t.id)}<small>${t.openFindings} open</small></button>`).join("");
  nav.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => openTender(b.dataset.id)));
  const want = location.hash.slice(1) || ts[0]?.id;
  if (want) openTender(want);
}

async function openTender(id) {
  location.hash = id;
  document.querySelectorAll("#tenders button").forEach((b) => b.setAttribute("aria-current", String(b.dataset.id === id)));
  const [detail, sheet, findings] = await Promise.all([api(`/api/tenders/${id}`), api(`/api/tenders/${id}/sheet`), api(`/api/tenders/${id}/findings`)]);
  Object.assign(state, { tender: id, detail, sheet, findings });
  $("#empty").hidden = true;
  $("#tender").hidden = false;
  $("#project").textContent = detail.project;
  const vs = detail.versions.map((v) => `<b>${esc(v.version)}</b> ${esc(v.date)}`).join(" → ");
  const outdated = detail.bids.filter((b) => b.pricedVersion !== detail.latestVersion).length;
  $("#lineage").innerHTML = `BoQ ${vs}${outdated ? ` · ${outdated} bid${outdated > 1 ? "s" : ""} priced an earlier version` : ""} · run ${esc(detail.runId)}`;
  renderRanking();
  renderSheet();
  renderQueue();
}

function renderRanking() {
  const by = Object.fromEntries(state.detail.bids.map((b) => [b.id, b]));
  $("#ranking").innerHTML = state.sheet.ranking
    .map((r, i) => {
      const b = by[r.bid_id];
      const moved = r.stated_rank !== r.rank ? `<span class="moved">was ${r.stated_rank} by its own total</span>` : "";
      const open = b.findings.open || 0;
      return `<div class="rank ${i === 0 ? "first" : ""}"><div class="pos"><span>${r.rank}</span>${moved}</div><div class="co" title="${esc(b.company)}">${esc(b.company)}</div><div class="tot">${eur(r.comparable_total, 0)} €</div><div class="sub">stated ${eur(b.statedTotal, 0)} € · ${esc(b.route)} · ${open} open finding${open === 1 ? "" : "s"}</div></div>`;
    })
    .join("");
}

function sevOf(flags) {
  if (flags.some((f) => SEV[f] === "high")) return "high";
  if (flags.some((f) => SEV[f] === "medium")) return "medium";
  return flags.length ? "low" : "";
}

function renderSheet() {
  const s = state.sheet;
  const bids = s.ranking.map((r) => s.bidders.find((b) => b.bid_id === r.bid_id));
  const head1 = `<tr><th class="oz">OZ</th><th>Position</th><th>Qty</th>${bids.map((b) => `<th class="bidder" colspan="2" title="${esc(b.company)}"><span class="bn">${esc(b.company)}</span></th>`).join("")}</tr>`;
  const head2 = `<tr><th class="oz"></th><th></th><th></th>${bids.map(() => `<th>EP €</th><th>GP €</th>`).join("")}</tr>`;
  let rows = "";
  let trade = "";
  for (const p of s.positions) {
    if (p.trade !== trade) {
      trade = p.trade;
      rows += `<tr class="trade"><td class="oz">${esc(trade)}</td><td colspan="${2 + 2 * bids.length}">${esc((s.trades || {})[trade] || "")}</td></tr>`;
    }
    const eps = bids.map((b) => s.cells[p.oz][b.bid_id]).filter((c) => c.ep != null && !c.filled).map((c) => c.ep);
    const min = eps.length ? Math.min(...eps) : null;
    rows += `<tr><td class="oz">${esc(p.oz)}</td><td class="txt" title="${esc(p.short)}">${esc(p.short)}</td><td>${eur(p.qty, 2)} ${esc(p.unit)}</td>`;
    for (const b of bids) {
      const c = s.cells[p.oz][b.bid_id];
      const sev = sevOf(c.flags);
      const cls = ["cell", "ep", sev && "flag", sev, c.filled && "filled", c.ep != null && c.ep === min && eps.length > 1 && "min"].filter(Boolean).join(" ");
      const tip = c.flags.map((f) => LABEL[f] || f).join(", ");
      const ep = c.filled ? `(${eur(c.gp_comparable / (p.qty || 1))})` : c.ep == null ? "enth." : eur(c.ep);
      rows += `<td class="${cls}" ${sev ? `tabindex="0" data-bid="${esc(b.bid_id)}" data-oz="${esc(p.oz)}"` : ""} title="${esc(tip)}">${ep}</td><td class="cell">${eur(c.gp_comparable, 0)}</td>`;
    }
    rows += "</tr>";
  }
  const foot = `<tr><td class="oz"></td><td style="text-align:left">Comparable total</td><td></td>${bids.map((b) => `<td colspan="2">${eur(b.comparable_total, 0)} €</td>`).join("")}</tr>`;
  $("#sheet").innerHTML = `<thead>${head1}${head2}</thead><tbody>${rows}</tbody><tfoot>${foot}</tfoot>`;
  $("#sheet").querySelectorAll("td.flag").forEach((td) => {
    const open = () => openFinding(state.findings.filter((f) => f.bidId === td.dataset.bid && f.oz === td.dataset.oz));
    td.addEventListener("click", open);
    td.addEventListener("keydown", (e) => e.key === "Enter" && open());
  });
}

function renderQueue() {
  const q = state.findings.filter((f) => f.status === "open" && f.needsReview).sort((a, b) => a.confidence - b.confidence);
  const all = state.findings.filter((f) => f.status === "open");
  $("#review-count").textContent = q.length || "";
  const co = Object.fromEntries(state.detail.bids.map((b) => [b.id, b.company]));
  const item = (f) => `<li class="${SEV[f.type] || ""}" data-id="${esc(f.id)}"><div><div>${esc(f.message)}</div><div class="meta">${esc(co[f.bidId] || f.bidId)} · ${esc(LABEL[f.type] || f.type)} · confidence ${(100 * f.confidence).toFixed(0)}%</div></div><div class="actions"><button class="btn-ok" type="button">Confirm</button><button class="btn-no" type="button">Reject</button><button class="ghost show" type="button">Evidence</button></div></li>`;
  $("#queue").innerHTML = (q.length ? q.map(item).join("") : `<li><div>Nothing waits for review. ${all.length} open findings are confident enough to stand on their own.</div></li>`);
  $("#queue").querySelectorAll("li[data-id]").forEach((li) => {
    const f = state.findings.find((x) => x.id === li.dataset.id);
    li.querySelector(".btn-ok").addEventListener("click", () => decide(f, "confirmed", li));
    li.querySelector(".btn-no").addEventListener("click", () => decide(f, "rejected", li));
    li.querySelector(".show").addEventListener("click", () => openFinding([f]));
  });
}

async function decide(f, verdict, li, note) {
  await api(`/api/findings/${encodeURIComponent(f.id)}/decision`, { method: "POST", body: JSON.stringify({ verdict, note }) });
  f.status = verdict;
  if (li) li.classList.add("done");
  state.sheet = await api(`/api/tenders/${state.tender}/sheet`);
  renderSheet();
  renderRanking();
  $("#review-count").textContent = state.findings.filter((x) => x.status === "open" && x.needsReview).length || "";
}

function evidenceImg(ev) {
  if (!ev || !ev.page || !String(ev.doc).includes(".pdf@")) return `<div class="src">${esc(ev?.doc || "")}${ev?.row ? ` · row ${ev.row}` : ""}${ev?.xml_line ? ` · XML line ${ev.xml_line}` : ""}\n${esc(ev?.text || "")}</div>`;
  const q = new URLSearchParams({ doc: ev.doc, page: String(ev.page), ...(ev.bbox ? { bbox: ev.bbox.join(",") } : {}) });
  return `<figure><img alt="Evidence: ${esc(ev.text)}" src="/api/evidence?${q}${key ? "" : ""}" loading="lazy"><figcaption>${esc(ev.doc)} · page ${ev.page}</figcaption></figure>`;
}

function openFinding(fs) {
  if (!fs.length) return;
  const body = fs
    .map(
      (f) => `<section><h2>${esc(LABEL[f.type] || f.type)} ${f.oz ? esc(f.oz) : ""}</h2>
      <span class="sev ${SEV[f.type]}">${esc(f.severity)}</span> <span class="status ${esc(f.status)}">${f.status === "open" ? "" : esc(f.status)}</span>
      <p>${esc(f.message)}</p>
      ${f.detail && (f.detail.expected != null || f.detail.found != null) ? `<div class="src">BoQ / field: ${esc(JSON.stringify(f.detail.expected))}\nBid:        ${esc(JSON.stringify(f.detail.found))}</div>` : ""}
      ${(f.detail?.diffs || []).map((d) => `<div class="src">BoQ: …${esc(d.context)} <b>${esc(d.was)}</b>\nBid: …${esc(d.context)} <b>${esc(d.now)}</b>  (${esc(d.direction)})</div>`).join("")}
      ${f.evidence.map(evidenceImg).join("")}
      <p class="note">Confidence ${(100 * f.confidence).toFixed(0)}%${f.needsReview ? " · sent to review" : ""}</p>
      ${f.status === "open" ? `<textarea placeholder="Note for the file (optional)" data-note="${esc(f.id)}"></textarea><div class="decide"><button class="btn-ok" data-ok="${esc(f.id)}" type="button">Confirm</button><button class="btn-no" data-no="${esc(f.id)}" type="button">Reject</button></div>` : ""}
      </section>`,
    )
    .join("<hr>");
  $("#panel-body").innerHTML = body;
  $("#panel").hidden = false;
  $("#panel").querySelectorAll("[data-ok],[data-no]").forEach((b) =>
    b.addEventListener("click", async () => {
      const id = b.dataset.ok || b.dataset.no;
      const f = state.findings.find((x) => x.id === id);
      const note = $(`[data-note="${CSS.escape(id)}"]`)?.value || undefined;
      await decide(f, b.dataset.ok ? "confirmed" : "rejected", null, note);
      openFinding(fs);
      renderQueue();
    }),
  );
  // images need the key too: fetch them with it when one is set
  if (key) $("#panel").querySelectorAll("img").forEach(async (img) => {
    const r = await fetch(img.src, { headers: { "x-api-key": key } });
    if (r.ok) img.src = URL.createObjectURL(await r.blob());
  });
}
$("#panel-close").addEventListener("click", () => ($("#panel").hidden = true));
document.addEventListener("keydown", (e) => e.key === "Escape" && ($("#panel").hidden = true));

document.querySelectorAll(".tabs button").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    for (const t of ["sheet", "review", "ask"]) $(`#tab-${t}`).hidden = t !== b.dataset.tab;
  }),
);

$("#ask").addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = $("#question").value.trim();
  if (!question) return;
  $("#answer").textContent = "…";
  try {
    const a = await api(`/api/tenders/${state.tender}/chat`, { method: "POST", body: JSON.stringify({ question }) });
    const cites = Object.fromEntries(a.citations.map((c) => [c.ref, c]));
    const html = a.text
      .split("\n")
      .map((line) => `<div class="line ${line.startsWith("  ") ? "indent" : ""}">${esc(line.trim()).replace(/\[(E\d+)\]/g, (_m, r) => `<button class="cite" type="button" data-ref="${r}">${r}</button>`)}</div>`)
      .join("");
    $("#answer").innerHTML = html + (a.dropped ? `<div class="note">${a.dropped} unsupported sentence(s) removed by the citation check.</div>` : "");
    $("#answer").querySelectorAll(".cite").forEach((b) => b.addEventListener("click", () => openFinding([{ id: "", type: "evidence", oz: b.dataset.ref, severity: "low", status: "evidence", message: cites[b.dataset.ref].text, evidence: [cites[b.dataset.ref]], confidence: 1, detail: {} }])));
  } catch (err) {
    $("#answer").textContent = err.message;
  }
});

loadTenders().catch((e) => {
  $("#empty").hidden = false;
  $("#empty p").textContent = e.message;
});
