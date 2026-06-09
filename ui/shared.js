/* global window, document, fetch, localStorage, setTimeout */

function adminNav(activePath) {
  const links = [
    { href: "/admin", label: "Performance", path: "/admin" },
    { href: "/admin/campaign", label: "E-Mail-Kampagne", path: "/admin/campaign" },
    { href: "/admin/campaign/analytics", label: "Kampagnen-Analyse", path: "/admin/campaign/analytics" },
    { href: "/admin/lead", label: "Lead Intake", path: "/admin/lead" },
  ];
  const items = links.map((l) => {
    const cls = l.path === activePath ? ' class="active"' : "";
    return `<a href="${l.href}"${cls}>${l.label}</a>`;
  }).join("");
  return `<nav class="nav">${items}<button type="button" id="logoutBtn">Logout</button></nav>`;
}

function bindLogout() {
  const btn = document.getElementById("logoutBtn");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    await fetch("/api/admin/logout", { method: "POST", credentials: "same-origin" });
    window.location.replace("/admin/login");
  });
}

async function callApi(url, options = {}) {
  const res = await fetch(url, { credentials: "same-origin", ...options });
  if (res.status === 401) {
    const next = encodeURIComponent(window.location.pathname);
    window.location.replace(`/admin/login?next=${next}`);
    return null;
  }
  return { status: res.status, body: await res.json().catch(() => ({})) };
}

function setPageLoading(active) {
  const el = document.getElementById("pageLoader");
  if (!el) return;
  el.classList.toggle("active", Boolean(active));
  el.setAttribute("aria-hidden", active ? "false" : "true");
}

function setMetricCardLoading(cardIds, loading) {
  for (const id of cardIds) {
    const card = document.getElementById(id);
    if (!card) continue;
    card.classList.toggle("loading", Boolean(loading));
  }
}

function setMetricBadge(id, state, label) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = `metricBadge ${state || ""}`.trim();
  el.textContent = label || "";
}

function setMetricValue(valueId, value, metaText, keepSpinner, metaId) {
  const valueEl = document.getElementById(valueId);
  if (valueEl) {
    valueEl.innerHTML = keepSpinner
      ? '<span class="spinner" aria-hidden="true"></span>'
      : escapeHtml(value ?? "—");
  }
  const metaEl = metaId
    ? document.getElementById(metaId)
    : (document.getElementById(`${valueId}Cwv`) || document.getElementById(`${valueId}Meta`));
  if (metaEl && metaText != null) metaEl.textContent = metaText;
}

function showToast(message, ms = 2800) {
  let el = document.getElementById("adminToast");
  if (!el) {
    el = document.createElement("div");
    el.id = "adminToast";
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(el._hideTimer);
  el._hideTimer = setTimeout(() => el.classList.remove("show"), ms);
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function parseClarityInsights(body) {
  if (!body || !body.configured) {
    return { configured: false, sessions: null, scrollDepth: null, frustration: null, topUrls: [] };
  }
  const metrics = {};
  const topUrls = [];
  const data = body.data;
  const rows = Array.isArray(data) ? data : (data && Array.isArray(data.data) ? data.data : []);
  for (const block of rows) {
    const name = String(block.metricName || block.name || "").toLowerCase();
    const values = block.information || block.data || [];
    if (name.includes("session") || name.includes("traffic")) {
      const total = values.reduce((s, v) => {
        const url = v.URL || v.Url || v.url || "";
        if (name.includes("traffic") && url && url !== "null") return s + Number(v.totalSessionCount || v.sessions || v.count || 0);
        if (!name.includes("traffic")) return s + Number(v.totalSessionCount || v.sessions || v.count || 0);
        return s;
      }, 0);
      if (total) metrics.sessions = total;
    }
    if (name.includes("scroll") && !name.includes("excessive")) {
      let depthSum = 0;
      let depthCount = 0;
      for (const v of values) {
        const depth = v.averageScrollDepth ?? v.scrollDepth;
        const url = String(v.URL || v.Url || v.url || "");
        if (depth == null || !url || url.includes("Electron") || url.includes("127.0.0.1")) continue;
        depthSum += Number(depth);
        depthCount += 1;
      }
      if (depthCount) metrics.scrollDepth = Math.round(depthSum / depthCount);
    }
    if (name.includes("dead") || name.includes("rage") || name.includes("quickback")) {
      const n = values.reduce((s, v) => s + Number(v.totalSessionCount || v.count || 0), 0);
      metrics.frustration = (metrics.frustration || 0) + n;
    }
    if (name.includes("traffic") || name.includes("url") || name.includes("page")) {
      for (const v of values) {
        const url = v.URL || v.Url || v.url || v.pageUrl || "";
        if (!url || url === "null") continue;
        topUrls.push({ url, count: Number(v.totalSessionCount || v.sessions || v.count || 0) });
      }
      topUrls.sort((a, b) => b.count - a.count);
      topUrls.splice(5);
    }
  }
  return { configured: true, ...metrics, topUrls };
}

function formatCwvRow(strategy, data) {
  if (!data) return "";
  return `
    <tr><td>${escapeHtml(strategy)}</td>
        <td>${data.score ?? "—"}</td>
        <td>${escapeHtml(data.fcp || "—")}</td>
        <td>${escapeHtml(data.lcp || "—")}</td>
        <td>${escapeHtml(data.tbt || "—")}</td>
        <td>${escapeHtml(data.cls || "—")}</td></tr>`;
}

const SEGMENT_LABELS = {
  hot: "Hot",
  warm: "Warm",
  mild: "Mild",
  cold: "Cold",
  not_sent: "Nicht gesendet",
  bounced: "Bounced",
  unsubscribed: "Abgemeldet",
  complained: "Beschwerde",
};

function scoreRating(score) {
  const n = Number(score);
  if (Number.isNaN(n)) return { state: "neutral", label: "—", hint: "Kein Score verfügbar." };
  if (n >= 90) return { state: "good", label: "Sehr gut", hint: "Die Seite lädt schnell — Ranking- und Conversion-Vorteil." };
  if (n >= 50) return { state: "warn", label: "Verbesserbar", hint: "Nutzer spüren Verzögerung — gezielt bei LCP und Blocking-Time ansetzen." };
  return { state: "bad", label: "Kritisch", hint: "Hohe Absprungrate wahrscheinlich — Performance als Priorität behandeln." };
}

function parseMetricMs(raw) {
  if (!raw || raw === "—") return null;
  const s = String(raw).trim().toLowerCase().replace(",", ".");
  const num = parseFloat(s);
  if (Number.isNaN(num)) return null;
  if (s.includes("ms")) return num;
  if (s.includes("s")) return num * 1000;
  return num;
}

function parseMetricCls(raw) {
  if (!raw || raw === "—") return null;
  const num = parseFloat(String(raw).trim().replace(",", "."));
  return Number.isNaN(num) ? null : num;
}

const CWV_GUIDE = {
  fcp: {
    label: "FCP — First Contentful Paint",
    explain: "Wann der Nutzer das erste sichtbare Element sieht. Gefühlte Ladegeschwindigkeit.",
    good: "≤ 1,8 s",
    tips: ["Kritisches CSS inline oder früh laden", "Schriftarten mit font-display: swap", "Render-blockierendes JS verzögern"],
  },
  lcp: {
    label: "LCP — Largest Contentful Paint",
    explain: "Wann das größte sichtbare Element (Hero, Bild, Headline) fertig ist. Wichtigster Google-Ranking-Faktor.",
    good: "≤ 2,5 s",
    tips: ["Hero-Bild komprimieren und in modernem Format (WebP/AVIF)", "CDN oder Edge-Caching nutzen", "Server-Response-Time (TTFB) senken"],
  },
  tbt: {
    label: "TBT — Total Blocking Time",
    explain: "Wie lange JavaScript die Interaktion blockiert. Proxy für schlechte UX auf dem Handy.",
    good: "≤ 200 ms",
    tips: ["JS-Bundles verkleinern und splitten", "Third-Party-Skripte (Analytics, Chat) lazy laden", "Lange Tasks im Main Thread aufbrechen"],
  },
  cls: {
    label: "CLS — Cumulative Layout Shift",
    explain: "Wie stark sich Layout beim Laden verschiebt (z. B. springende Buttons).",
    good: "≤ 0,1",
    tips: ["Breite/Höhe für Bilder und Embeds setzen", "Keine Banner über bestehendem Content einblenden", "Web-Fonts mit reserviertem Platz laden"],
  },
};

function cwvRating(key, raw) {
  if (key === "cls") {
    const v = parseMetricCls(raw);
    if (v == null) return { state: "neutral", label: "—" };
    if (v <= 0.1) return { state: "good", label: "Gut" };
    if (v <= 0.25) return { state: "warn", label: "Mittel" };
    return { state: "bad", label: "Schlecht" };
  }
  const ms = parseMetricMs(raw);
  if (ms == null) return { state: "neutral", label: "—" };
  const limits = { fcp: [1800, 3000], lcp: [2500, 4000], tbt: [200, 600] };
  const [good, warn] = limits[key] || [0, 0];
  if (ms <= good) return { state: "good", label: "Gut" };
  if (ms <= warn) return { state: "warn", label: "Mittel" };
  return { state: "bad", label: "Schlecht" };
}

function renderCwvDetailTable(mobile, desktop) {
  const keys = ["fcp", "lcp", "tbt", "cls"];
  const rows = keys.map((key) => {
    const guide = CWV_GUIDE[key];
    const mob = mobile?.[key] || "—";
    const desk = desktop?.[key] || "—";
    const mobR = cwvRating(key, mob);
    const deskR = cwvRating(key, desk);
    const tips = guide.tips.map((t) => `<li>${escapeHtml(t)}</li>`).join("");
    return `
      <tr>
        <td>
          <strong>${escapeHtml(guide.label)}</strong>
          <div class="metricExplain">${escapeHtml(guide.explain)}</div>
          <div class="metricExplain muted">Ziel: ${escapeHtml(guide.good)}</div>
        </td>
        <td><span class="cwvVal ${mobR.state}">${escapeHtml(mob)}</span> <span class="cwvTag ${mobR.state}">${escapeHtml(mobR.label)}</span></td>
        <td><span class="cwvVal ${deskR.state}">${escapeHtml(desk)}</span> <span class="cwvTag ${deskR.state}">${escapeHtml(deskR.label)}</span></td>
        <td><ul class="tipList compact">${tips}</ul></td>
      </tr>`;
  }).join("");
  return rows;
}

function clarityAssessment(ins) {
  if (!ins.configured) return { state: "neutral", summary: "Clarity ist nicht angebunden.", tips: ["CLARITY_TOKEN und CLARITY_PROJECT_ID in .env setzen"] };
  const tips = [];
  let summary = "";
  if ((ins.sessions || 0) < 10) {
    summary = "Wenig Traffic in den letzten 3 Tagen — Aussagen noch unsicher.";
    tips.push("Mehr Besucher über SEO, Ads oder Kampagnen bringen, dann Muster erkennbar.");
  } else {
    summary = `${ins.sessions} Sessions — genug Daten für erste Interpretation.`;
  }
  if (ins.scrollDepth != null && ins.scrollDepth < 40) {
    tips.push("Geringe Scrolltiefe: Hero/Value Proposition prüfen — kommt der Nutzen früh genug?");
  } else if (ins.scrollDepth != null) {
    tips.push("Gute Scrolltiefe — Inhalte werden gelesen. CTA-Platzierung auf langen Seiten prüfen.");
  }
  if ((ins.frustration || 0) > 5) {
    tips.push("Frustrations-Signale (Rage Clicks, Quick Backs): UX-Probleme — Klickziele, Ladezeit und Formulare testen.");
  } else {
    tips.push("Wenig Frustration — Interaktion wirkt stabil.");
  }
  tips.push("Details und Heatmaps direkt in Microsoft Clarity öffnen.");
  return { state: (ins.frustration || 0) > 10 ? "warn" : "good", summary, tips };
}

function gscMetricHints(clicks, impressions, ctr, position) {
  const tips = [];
  let summary = `${clicks} Klicks aus ${impressions} Impressionen in 7 Tagen.`;
  if (impressions > 0 && ctr < 2) {
    tips.push("CTR unter 2 %: Title und Meta-Description überarbeiten — klarer Nutzen, konkrete Keywords.");
  } else if (ctr >= 2) {
    tips.push("CTR solide — Snippet spricht Suchintention an. Top-Queries als Vorlage für neue Seiten nutzen.");
  }
  if (position > 20) {
    tips.push("Ø Position > 20: Content vertiefen, interne Verlinkung stärken, technische SEO prüfen.");
  } else if (position <= 10) {
    tips.push("Gute Sichtbarkeit auf Seite 1–2 — Fokus-Keywords ausbauen und Conversion optimieren.");
  }
  tips.push("Top-Queries mit Landingpages abgleichen — fehlende Seiten gezielt erstellen.");
  return { summary, tips };
}

function renderSimpleTable(rows, labelKey) {
  if (!rows?.length) return '<p class="muted">Keine Daten für diesen Zeitraum.</p>';
  const body = rows.map((row) => `
    <tr>
      <td>${escapeHtml(row.key || "—")}</td>
      <td>${row.clicks ?? 0}</td>
      <td>${row.impressions ?? 0}</td>
      <td>${row.ctr ?? 0}%</td>
      <td>${row.position ?? "—"}</td>
    </tr>`).join("");
  return `<table class="data"><thead><tr><th>${escapeHtml(labelKey)}</th><th>Klicks</th><th>Impr.</th><th>CTR</th><th>Pos.</th></tr></thead><tbody>${body}</tbody></table>`;
}

function applyScoreClass(el, score) {
  if (!el) return;
  const rating = scoreRating(score);
  el.classList.remove("scoreGood", "scoreWarn", "scoreBad", "scoreNeutral");
  el.classList.add(
    rating.state === "good" ? "scoreGood"
      : rating.state === "warn" ? "scoreWarn"
        : rating.state === "bad" ? "scoreBad" : "scoreNeutral"
  );
  return rating;
}

const BEHAVIOR_GUIDE = [
  { segment: "hot", text: "Mehrfach geklickt oder starke Clarity-Signale — persönlich anrufen oder individuelles Follow-up." },
  { segment: "warm", text: "Geöffnet oder leichte Interaktion — kurzes, konkretes Follow-up per E-Mail." },
  { segment: "mild", text: "Schwaches Signal — erst später erneut kontaktieren, kein Druck." },
  { segment: "cold", text: "Kein Engagement — nicht erneut mailen; ggf. anderer Kanal." },
  { segment: "bounced", text: "Adresse unzustellbar — nicht erneut senden, E-Mail prüfen." },
  { segment: "unsubscribed", text: "Abgemeldet — kein weiterer Versand." },
  { segment: "complained", text: "Spam-Beschwerde — sofort stoppen, Status dokumentieren." },
];
