/* Campaign dashboard logic — requires shared.js */
let leads = [];
let meta = {};
const selected = new Set();
const filters = { query: "", status: "all", contact: "all", sort: "name_asc" };
let pageSize = 25;
let pageIndex = 0;
let activeLeadId = "";
let searchDebounce = null;
let previewDebounce = null;
let loadError = null;
let isLoading = false;
let previewLoading = false;

const STATUS_LABELS = {
  sendable: "Versendbar", lead: "Lead", new: "Neu", working: "Kontaktiert",
  bounced: "Bounced", unsubscribed: "Abgemeldet", supabase_unsubscribed: "Abgemeldet (Store)",
  paused: "Pausiert", replied: "Geantwortet", no_response: "Keine Antwort", blocked: "Gesperrt",
};

const PRESETS = {
  business_card: {
    subject: "Kurzes Certiq Update",
    paragraphs: ["ich wollte dir kurz ein Update zu Certiq geben.", "Wir helfen Teams, Anforderungen schneller in validierbare Aufgaben zu uebersetzen."],
    utm_campaign: "business_card_intro",
  },
  live_demo: {
    subject: "Certiq Live-Demo — passt das zu eurem Prozess?",
    paragraphs: ["kurzes Update zu Certiq.", "Wenn du magst, zeige ich dir in 15 Minuten den konkreten Fit."],
    utm_campaign: "live_demo_tp1",
  },
};

const LS_KEY = "certiq_campaign_editor";

function isLeadSendable(lead) {
  return lead.sendable === true || lead.sendable === "true";
}

function utmQuery() {
  const s = document.getElementById("utmSource").value.trim() || "newsletter";
  const m = document.getElementById("utmMedium").value.trim() || "email";
  const c = document.getElementById("utmCampaign").value.trim() || "certiq_campaign";
  return `utm_source=${encodeURIComponent(s)}&utm_medium=${encodeURIComponent(m)}&utm_campaign=${encodeURIComponent(c)}`;
}

function saveEditor() {
  const data = {
    subject: document.getElementById("subject").value,
    paragraphs: document.getElementById("paragraphs").value,
    ctaLabel: document.getElementById("ctaLabel").value,
    signature: document.getElementById("signature").value,
    addressing: document.getElementById("addressing").value,
    utmSource: document.getElementById("utmSource").value,
    utmMedium: document.getElementById("utmMedium").value,
    utmCampaign: document.getElementById("utmCampaign").value,
  };
  try { localStorage.setItem(LS_KEY, JSON.stringify(data)); } catch (e) { /* ignore */ }
}

function loadEditor() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    ["subject", "paragraphs", "ctaLabel", "signature", "addressing", "utmSource", "utmMedium", "utmCampaign"].forEach((k) => {
      const el = document.getElementById(k === "paragraphs" ? "paragraphs" : k);
      if (el && data[k] != null) el.value = data[k];
    });
  } catch (e) { /* ignore */ }
}

function formatLastContact(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
}

function leadStatusKey(lead) {
  const blocked = (lead.blockedReason || "").toLowerCase();
  if (blocked) return blocked;
  const state = (lead.emailState || lead.status || "").toLowerCase();
  if (["bounced", "unsubscribed", "supabase_unsubscribed", "paused", "replied", "cold_disqualified", "no_response"].includes(state)) return state;
  if (!isLeadSendable(lead)) return state || "blocked";
  if (state === "lead" || state === "new" || state === "working" || !state) return state || "sendable";
  return state;
}

function leadStatusLabel(lead) { return STATUS_LABELS[leadStatusKey(lead)] || leadStatusKey(lead); }
function leadStatusBadgeClass(lead) {
  const key = leadStatusKey(lead);
  if (["sendable", "new", "working"].includes(key)) return key === "sendable" ? "sendable" : key;
  if (["bounced", "unsubscribed", "supabase_unsubscribed", "paused", "replied", "lead", "blocked"].includes(key)) return key;
  return "other";
}

function formatCampaignHistory(lead) {
  const campaigns = Array.isArray(lead.sentCampaigns) ? lead.sentCampaigns.filter(Boolean) : [];
  const lastContact = formatLastContact(lead.lastContactedAt);
  if (campaigns.length && lastContact) return `Kampagnen: ${campaigns.join(", ")} · zuletzt ${lastContact}`;
  if (campaigns.length) return `Kampagnen: ${campaigns.join(", ")}`;
  if (lead.lastContactCampaign) return `Letzte Kampagne: ${lead.lastContactCampaign}`;
  return "";
}

function leadSearchHaystack(lead) {
  return [lead.firstName, lead.lastName, lead.company, lead.email, lead.kundenId,
    `${lead.firstName || ""} ${lead.lastName || ""}`.trim()].filter(Boolean).join(" ").toLowerCase();
}

function matchesQuery(lead) {
  const q = filters.query.trim().toLowerCase();
  if (!q) return true;
  const haystack = leadSearchHaystack(lead);
  if (haystack.includes(q)) return true;
  return q.split(/\s+/).filter(Boolean).every((t) => haystack.includes(t));
}

function matchesStatusFilter(lead) {
  switch (filters.status) {
    case "sendable": return isLeadSendable(lead);
    case "bounced": return leadStatusKey(lead) === "bounced";
    case "unsubscribed": return ["unsubscribed", "supabase_unsubscribed"].includes(leadStatusKey(lead));
    case "blocked": return !isLeadSendable(lead);
    case "has_email": return !!lead.email;
    case "no_optout": return isLeadSendable(lead);
    default: return true;
  }
}

function parseContactDate(lead) {
  if (!lead.lastContactedAt) return null;
  const date = new Date(lead.lastContactedAt);
  return Number.isNaN(date.getTime()) ? null : date;
}

function matchesContactFilter(lead) {
  const date = parseContactDate(lead);
  const now = Date.now();
  switch (filters.contact) {
    case "never": return !date;
    case "contacted": return !!date;
    case "7d": return date && now - date.getTime() <= 7 * 86400000;
    case "30d": return date && now - date.getTime() <= 30 * 86400000;
    case "90d": return date && now - date.getTime() <= 90 * 86400000;
    default: return true;
  }
}

function sortLeads(list) {
  const sorted = [...list];
  const cmp = (a, b) => (a || "").localeCompare(b || "", "de", { sensitivity: "base" });
  sorted.sort((a, b) => {
    let r = 0;
    switch (filters.sort) {
      case "company_asc": r = cmp(a.company, b.company) || cmp(a.lastName, b.lastName); break;
      case "email_asc": r = cmp(a.email, b.email); break;
      case "contact_desc": {
        const da = parseContactDate(a), db = parseContactDate(b);
        if (!da && !db) r = 0; else if (!da) r = 1; else if (!db) r = -1; else r = db - da; break;
      }
      case "status": r = cmp(leadStatusLabel(a), leadStatusLabel(b)); break;
      default: r = cmp(a.lastName, b.lastName) || cmp(a.firstName, b.firstName);
    }
    return r;
  });
  return sorted;
}

function getVisibleLeads() {
  return sortLeads(leads.filter((l) => matchesQuery(l) && matchesStatusFilter(l) && matchesContactFilter(l)));
}

function getPagedLeads() {
  const visible = getVisibleLeads();
  const start = pageIndex * pageSize;
  return { visible, page: visible.slice(start, start + pageSize), totalPages: Math.max(1, Math.ceil(visible.length / pageSize)) };
}

function updateStats() {
  const total = meta.total ?? leads.length;
  document.querySelector("#statTotal strong").textContent = total;
  document.querySelector("#statSendable strong").textContent = meta.sendable ?? leads.filter(isLeadSendable).length;
  document.querySelector("#statBounced strong").textContent = meta.bounced ?? leads.filter((l) => leadStatusKey(l) === "bounced").length;
  document.querySelector("#statUnsubscribed strong").textContent = meta.unsubscribed ?? leads.filter((l) => ["unsubscribed", "supabase_unsubscribed"].includes(leadStatusKey(l))).length;
  document.querySelector("#statSelected strong").textContent = selected.size;
  const { visible, totalPages } = getPagedLeads();
  document.getElementById("filterCount").textContent = `${visible.length} von ${leads.length} Leads · Seite ${pageIndex + 1}/${totalPages}`;
  document.getElementById("resetFiltersBtn").hidden = !(filters.query.trim() || filters.status !== "all" || filters.contact !== "all");
  const ml = document.getElementById("metaLine");
  if (ml) {
    ml.textContent = `Resend: ${meta.resendConfigured ? "ok" : "fehlt"} · Twenty: ${meta.twentyConfigured ? "ok" : "fehlt"} · Absender: ${meta.resendFrom || "—"}`;
  }
}

function renderLeadList() {
  const list = document.getElementById("leadList");
  updateStats();
  if (isLoading) { list.innerHTML = '<div class="emptyState">Leads werden geladen…</div>'; return; }
  if (loadError) { list.innerHTML = `<div class="emptyState">${escapeHtml(loadError)}</div>`; return; }
  if (!leads.length) { list.innerHTML = '<div class="emptyState">Keine Leads gefunden.</div>'; return; }
  const { visible, page } = getPagedLeads();
  if (!visible.length) {
    list.innerHTML = '<div class="emptyState">Keine Leads für diese Filter.<br><button type="button" id="emptyResetBtn" class="btn">Filter zurücksetzen</button></div>';
    document.getElementById("emptyResetBtn").addEventListener("click", resetFilters);
    return;
  }
  list.innerHTML = page.map((lead) => {
    const disabled = !isLeadSendable(lead);
    const active = lead.id === activeLeadId ? " active" : "";
    const campaignText = formatCampaignHistory(lead);
    const contactText = campaignText ? "" : (formatLastContact(lead.lastContactedAt) ? `Zuletzt: ${formatLastContact(lead.lastContactedAt)}` : "Nie kontaktiert");
    return `<div class="lead${disabled ? " blocked disabled" : ""}${active}" data-id="${lead.id}">
      <input type="checkbox" data-id="${lead.id}" ${selected.has(lead.id) ? "checked" : ""} ${disabled ? "disabled" : ""} />
      <div class="leadBody">
        <div class="leadRow1"><span class="leadName">${escapeHtml(lead.firstName || "")} ${escapeHtml(lead.lastName || "")}</span>
        <span class="badge ${leadStatusBadgeClass(lead)}">${escapeHtml(leadStatusLabel(lead))}</span></div>
        <div class="leadCompany">${escapeHtml(lead.company || "—")}</div>
        <div class="leadEmail">${escapeHtml(lead.email || "—")}</div>
        ${campaignText ? `<div class="leadCampaign">${escapeHtml(campaignText)}</div>` : ""}
        <div class="leadContact">${escapeHtml(contactText)}</div>
      </div></div>`;
  }).join("");

  list.querySelectorAll("input[type=checkbox]").forEach((el) => {
    el.addEventListener("change", (e) => {
      e.stopPropagation();
      const id = el.getAttribute("data-id");
      if (el.checked) selected.add(id); else selected.delete(id);
      updateStats();
    });
  });
  list.querySelectorAll(".lead").forEach((row) => {
    row.addEventListener("click", async (e) => {
      if (e.target.type === "checkbox") return;
      const id = row.getAttribute("data-id");
      activeLeadId = id;
      renderLeadList();
      if (!row.classList.contains("disabled")) {
        const cb = row.querySelector("input[type=checkbox]");
        if (cb && !cb.checked) { cb.checked = true; selected.add(id); updateStats(); }
      }
      await loadPreview(id);
    });
  });
}

function setPreviewPlaceholder(message) {
  const frame = document.getElementById("previewFrame");
  frame.srcdoc = `<!DOCTYPE html><html><body style="margin:0;padding:24px;font-family:Arial,sans-serif;color:#5a6b75;background:#f0f4f3;">${escapeHtml(message)}</body></html>`;
  document.getElementById("previewSubject").textContent = "Betreff: —";
  document.getElementById("previewRecipient").textContent = "";
  document.getElementById("previewMeta").textContent = "";
  document.getElementById("previewText").textContent = "";
}

function schedulePreviewRefresh() {
  if (!activeLeadId) return;
  clearTimeout(previewDebounce);
  previewDebounce = setTimeout(() => loadPreview(activeLeadId), 350);
}

async function loadPreview(leadId) {
  if (!leadId) return;
  previewLoading = true;
  const frame = document.getElementById("previewFrame");
  frame.srcdoc = `<!DOCTYPE html><html><body style="margin:0;padding:24px;font-family:Arial,sans-serif;color:#5a6b75;background:#f0f4f3;">Vorschau wird geladen…</body></html>`;
  const payload = contentPayload();
  payload.leadId = leadId;
  const result = await callApi("/api/admin/campaign/preview", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  previewLoading = false;
  if (!result || result.status >= 400) {
    const msg = result?.body?.message || "Vorschau konnte nicht geladen werden.";
    setPreviewPlaceholder(msg);
    showToast(msg);
    return;
  }
  frame.srcdoc = result.body.html || "";
  document.getElementById("previewSubject").textContent = `Betreff: ${result.body.subject || payload.content.subject || "—"}`;
  const recipient = result.body.recipientName || leads.find((l) => l.id === leadId)?.firstName || "";
  document.getElementById("previewRecipient").textContent = recipient ? `An: ${recipient}` : "";
  document.getElementById("previewMeta").textContent = result.body.trackingLink || "";
  document.getElementById("previewText").textContent = result.body.text || "";
}

function pickDefaultPreviewLead() {
  const visible = getVisibleLeads();
  return visible.find(isLeadSendable) || visible[0] || leads.find(isLeadSendable) || leads[0] || null;
}

function contentPayload() {
  const paragraphs = document.getElementById("paragraphs").value.split("\n").map((x) => x.trim()).filter(Boolean);
  return {
    utm: {
      utm_source: document.getElementById("utmSource").value.trim() || "newsletter",
      utm_medium: document.getElementById("utmMedium").value.trim() || "email",
      utm_campaign: document.getElementById("utmCampaign").value.trim() || "certiq_campaign",
    },
    content: {
      subject: document.getElementById("subject").value.trim(),
      paragraphs,
      ctaLabel: document.getElementById("ctaLabel").value.trim(),
      signature: document.getElementById("signature").value,
      addressing: document.getElementById("addressing").value,
    },
  };
}

function resetFilters() {
  filters.query = ""; filters.status = "all"; filters.contact = "all"; filters.sort = "name_asc";
  pageIndex = 0;
  document.getElementById("leadSearch").value = "";
  document.getElementById("filterStatus").value = "all";
  document.getElementById("filterContact").value = "all";
  document.getElementById("sortLeads").value = "name_asc";
  renderLeadList();
}

async function loadLeads() {
  isLoading = true; loadError = null; renderLeadList();
  const result = await callApi(`/api/admin/campaign?${utmQuery()}`);
  isLoading = false;
  if (!result) return;
  if (result.status >= 400) {
    loadError = result.body.message || "Leads konnten nicht geladen werden.";
    leads = []; meta = {}; renderLeadList(); return;
  }
  leads = result.body.leads || [];
  meta = result.body.meta || {};
  pageIndex = 0;
  const defaultLead = pickDefaultPreviewLead();
  if (defaultLead) {
    activeLeadId = defaultLead.id;
    await loadPreview(defaultLead.id);
  } else {
    setPreviewPlaceholder("Keine Leads für die Vorschau.");
  }
  renderLeadList();
  showToast(`${meta.sendable || 0} versendbare Leads geladen`);
}

function renderSendLog(body) {
  const log = document.getElementById("sendLog");
  const results = body.results || [];
  log.innerHTML = results.map((r) => `<div>${escapeHtml(r.email)} — ${escapeHtml(r.status)}${r.reason ? " (" + escapeHtml(r.reason) + ")" : ""}</div>`).join("") || "Keine Ergebnisse.";
}

async function runCampaign(dryRun) {
  const payload = contentPayload();
  payload.leadIds = Array.from(selected);
  payload.dryRun = dryRun;
  if (!dryRun) {
    const ok = confirm(`Wirklich ${selected.size} Lead(s) mit Betreff „${payload.content.subject}" versenden?`);
    if (!ok) return;
  }
  const result = await callApi("/api/admin/campaign", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  if (!result) return;
  renderSendLog(result.body);
  document.getElementById("sendLogPanel").open = true;
  showToast(dryRun ? "Dry-Run abgeschlossen" : `Gesendet: ${result.body.sent || 0}`);
}

async function runTest() {
  const to = prompt("Test-Mail an welche Adresse?");
  if (!to) return;
  const p = contentPayload();
  const result = await callApi("/api/admin/campaign/test", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to, utm: p.utm, content: p.content }),
  });
  if (result) showToast("Test-Mail gesendet");
}

async function runSuggest() {
  const topic = document.getElementById("subject").value.trim() || "Certiq Update";
  const lead = leads.find((l) => l.id === activeLeadId);
  const result = await callApi("/api/admin/campaign/suggest", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, company: lead?.company || "", addressing: document.getElementById("addressing").value }),
  });
  if (!result) return;
  const s = result.body.suggestion || {};
  if (s.subject) document.getElementById("subject").value = s.subject;
  if (s.paragraphs?.length) document.getElementById("paragraphs").value = s.paragraphs.join("\n");
  saveEditor();
  schedulePreviewRefresh();
  showToast(result.body.suggestion?.available ? "KI-Vorschlag geladen" : "Fallback-Vorschlag geladen");
}

function applyPreset(key) {
  const p = PRESETS[key];
  if (!p) return;
  document.getElementById("subject").value = p.subject;
  document.getElementById("paragraphs").value = p.paragraphs.join("\n");
  document.getElementById("utmCampaign").value = p.utm_campaign;
  saveEditor();
  loadLeads().then(() => schedulePreviewRefresh());
}

function bindCampaignUi() {
  document.getElementById("navMount").innerHTML = adminNav("/admin/campaign");
  bindLogout();
  loadEditor();
  ["subject", "paragraphs", "ctaLabel", "signature", "addressing", "utmSource", "utmMedium", "utmCampaign"].forEach((id) => {
    const el = document.getElementById(id);
    el.addEventListener("input", () => {
      saveEditor();
      schedulePreviewRefresh();
    });
    if (id === "addressing" || id.startsWith("utm")) {
      el.addEventListener("change", schedulePreviewRefresh);
    }
  });
  document.getElementById("leadSearch").addEventListener("input", (e) => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => { filters.query = e.target.value; pageIndex = 0; renderLeadList(); }, 200);
  });
  document.getElementById("filterStatus").addEventListener("change", (e) => { filters.status = e.target.value; pageIndex = 0; renderLeadList(); });
  document.getElementById("filterContact").addEventListener("change", (e) => { filters.contact = e.target.value; pageIndex = 0; renderLeadList(); });
  document.getElementById("sortLeads").addEventListener("change", (e) => { filters.sort = e.target.value; renderLeadList(); });
  document.getElementById("pageSize").addEventListener("change", (e) => { pageSize = parseInt(e.target.value, 10) || 25; pageIndex = 0; renderLeadList(); });
  document.getElementById("prevPage").addEventListener("click", () => { if (pageIndex > 0) { pageIndex--; renderLeadList(); } });
  document.getElementById("nextPage").addEventListener("click", () => {
    const { totalPages } = getPagedLeads();
    if (pageIndex < totalPages - 1) { pageIndex++; renderLeadList(); }
  });
  document.getElementById("resetFiltersBtn").addEventListener("click", resetFilters);
  document.getElementById("reloadBtn").addEventListener("click", loadLeads);
  document.getElementById("refreshLinksBtn").addEventListener("click", async () => {
    await loadLeads();
    if (activeLeadId) schedulePreviewRefresh();
  });
  document.getElementById("selectPageBtn").addEventListener("click", () => {
    getPagedLeads().page.filter(isLeadSendable).forEach((l) => selected.add(l.id));
    renderLeadList();
  });
  document.getElementById("selectAllBtn").addEventListener("click", () => {
    getVisibleLeads().filter(isLeadSendable).forEach((l) => selected.add(l.id));
    renderLeadList();
  });
  document.getElementById("clearBtn").addEventListener("click", () => { selected.clear(); renderLeadList(); });
  document.getElementById("dryRunBtn").addEventListener("click", () => runCampaign(true));
  document.getElementById("sendBtn").addEventListener("click", () => runCampaign(false));
  document.getElementById("testBtn").addEventListener("click", runTest);
  document.getElementById("suggestBtn").addEventListener("click", runSuggest);
  document.getElementById("presetBusiness").addEventListener("click", () => applyPreset("business_card"));
  document.getElementById("presetLive").addEventListener("click", () => applyPreset("live_demo"));
  document.getElementById("syncResendBtn").addEventListener("click", async () => {
    const r = await callApi("/api/admin/campaign/analytics/sync", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    if (r) showToast("Resend → Store synchronisiert");
  });
  document.getElementById("syncTwentyBtn").addEventListener("click", async () => {
    const r = await callApi("/api/admin/campaign/sync-last-contact", { method: "POST" });
    if (r) showToast("Store → Twenty synchronisiert");
  });
  setPreviewPlaceholder("Leads werden geladen…");
  loadLeads();
}

document.addEventListener("DOMContentLoaded", bindCampaignUi);
