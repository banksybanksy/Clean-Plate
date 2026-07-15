/* SF Restaurant Health Scores: frontend (no dependencies). */
"use strict";

const $view = document.getElementById("view");
const $dataStatus = document.getElementById("data-status");

const STATUS = {
  "Pass": { cls: "pass", label: "Pass" },
  "Conditional Pass": { cls: "cond", label: "Conditional Pass" },
  "Closure": { cls: "closed", label: "Closure" },
};
function statusInfo(s) {
  return STATUS[s] || { cls: "none", label: "No rating recorded" };
}
function pill(status, big) {
  const info = statusInfo(status);
  return `<span class="pill ${info.cls}${big ? " big" : ""}">${info.label}</span>`;
}

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
function fmtDate(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}
function titleCase(s) {
  return String(s || "").replace(/\s+/g, " ").trim()
    .toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}
async function api(path, params) {
  const qs = params ? "?" + new URLSearchParams(params) : "";
  const resp = await fetch(path + qs);
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || resp.statusText);
  return data;
}

/* ---------------- cache status bar / refresh ---------------- */

let statusPollTimer = null;

async function loadStatus() {
  try {
    const s = await api("/api/status");
    renderDataStatus(s);
    if (s.refreshing) {
      clearTimeout(statusPollTimer);
      statusPollTimer = setTimeout(loadStatus, 1500);
    } else if (s.rows > 0 && $view.dataset.waitingForData === "1") {
      delete $view.dataset.waitingForData;
      route(); // data just arrived, re-render current view
    }
  } catch (e) {
    $dataStatus.textContent = "server unreachable";
  }
}

function renderDataStatus(s) {
  if (s.refreshing) {
    $dataStatus.innerHTML =
      `⏳ Refreshing from DataSF… <span class="muted">${esc(s.refresh_progress || "")}</span>`;
    return;
  }
  let text;
  if (!s.rows) {
    text = s.refresh_error
      ? `⚠️ refresh failed: ${esc(s.refresh_error)}`
      : "no data cached yet";
  } else {
    text = `${s.rows.toLocaleString()} records · refreshed ${fmtDate(s.last_refresh)}`;
    if (s.refresh_error) text = `⚠️ last refresh failed · ` + text;
  }
  $dataStatus.innerHTML =
    `${text}<button id="btn-refresh" title="Re-download the dataset from DataSF">Refresh</button>`;
  document.getElementById("btn-refresh").onclick = async (ev) => {
    ev.target.disabled = true;
    await fetch("/api/refresh", { method: "POST" });
    loadStatus();
  };
}

/* ---------------- router ---------------- */

function route() {
  const hash = location.hash || "#/";
  const parts = hash.slice(2).split("/").map(decodeURIComponent);
  document.querySelectorAll("[data-nav]").forEach(a => a.classList.remove("active"));
  window.scrollTo(0, 0);
  if (parts[0] === "r" && parts[1]) {
    viewDetail(parts[1]);
  } else if (parts[0] === "browse") {
    document.querySelector('[data-nav="browse"]').classList.add("active");
    viewBrowse(parts[1] || "");
  } else {
    document.querySelector('[data-nav="home"]').classList.add("active");
    viewHome();
  }
}
window.addEventListener("hashchange", route);

/* ---------------- home / search ---------------- */

async function viewHome() {
  $view.innerHTML = `
    <div class="hero">
      <div class="hero-food" aria-hidden="true">🌮🍜🥟🍕🥘</div>
      <h1>Should I eat here?</h1>
      <p>Check the kitchen before you check in. Official SF Public Health
         inspection results, served locally.</p>
    </div>
    <div class="searchbox">
      <span class="glass" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none"
             stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <circle cx="11" cy="11" r="7"/><path d="m20 20-3.8-3.8"/>
        </svg>
      </span>
      <input id="q" type="search" autocomplete="off" spellcheck="false"
             placeholder="Restaurant name, address, or neighborhood…" autofocus>
      <div class="suggestions" id="sugg" hidden></div>
    </div>
    <div class="legend">
      <span>${pill("Pass")} passed inspection</span>
      <span>${pill("Conditional Pass")} violations to fix, re-inspection due</span>
      <span>${pill("Closure")} ordered closed</span>
    </div>
    <div id="home-stats" class="loading">Loading…</div>
  `;
  wireSearch();

  try {
    const [s, hoods] = await Promise.all([api("/api/status"), api("/api/neighborhoods")]);
    if (!s.rows) {
      $view.dataset.waitingForData = "1";
      document.getElementById("home-stats").innerHTML =
        `<div class="loading">Downloading inspection data from DataSF. This page will
         populate automatically when it finishes.</div>`;
      return;
    }
    const top = hoods.neighborhoods.filter(h => h.neighborhood !== "(Unknown)");
    document.getElementById("home-stats").innerHTML = `
      <div class="stat-row">
        <div class="stat stat-a">
          <div class="stat-icon" aria-hidden="true">🍽️</div>
          <div class="stat-body">
            <div class="n" data-count="${s.restaurants}">0</div>
            <div class="l">kitchens tracked</div>
          </div>
        </div>
        <div class="stat stat-b">
          <div class="stat-icon" aria-hidden="true">📋</div>
          <div class="stat-body">
            <div class="n" data-count="${s.rows}">0</div>
            <div class="l">inspections since 2024</div>
          </div>
        </div>
        <div class="stat stat-c">
          <div class="stat-icon" aria-hidden="true">🗓️</div>
          <div class="stat-body">
            <div class="n">${fmtDate(s.newest_inspection)}</div>
            <div class="l">newest inspection</div>
          </div>
        </div>
      </div>
      <div class="section-title">Browse by neighborhood</div>
      <div class="hood-grid">
        ${top.map(h => `
          <a class="hood-card" href="#/browse/${encodeURIComponent(h.neighborhood)}">
            <div class="h-name">${esc(h.neighborhood)}</div>
            <div class="h-counts">
              <span>${h.restaurants} places</span>
              <span class="c-pass">${h.pass || 0} pass</span>
              ${h.conditional ? `<span class="c-cond">${h.conditional} cond.</span>` : ""}
              ${h.closure ? `<span class="c-closed">${h.closure} closed</span>` : ""}
            </div>
            ${ratioBar(h)}
          </a>`).join("")}
      </div>`;
    animateCounts();
  } catch (e) {
    document.getElementById("home-stats").innerHTML =
      `<div class="error-box">Could not load data: ${esc(e.message)}</div>`;
  }
}

function animateCounts() {
  const els = document.querySelectorAll(".n[data-count]");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  els.forEach(el => {
    const target = parseInt(el.dataset.count, 10) || 0;
    if (reduceMotion) { el.textContent = target.toLocaleString(); return; }
    const duration = 900;
    const start = performance.now();
    const tick = (now) => {
      const p = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3); // ease-out cubic
      el.textContent = Math.round(target * eased).toLocaleString();
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

/* Small stacked bar showing each neighborhood's status mix. Counts are in
   the text row above, so the bar is a supplementary encoding. */
function ratioBar(h) {
  const segs = [
    ["seg-pass", h.pass || 0, "Pass"],
    ["seg-cond", h.conditional || 0, "Conditional Pass"],
    ["seg-closed", h.closure || 0, "Closure"],
    ["seg-none", h.unrated || 0, "no rating"],
  ].filter(([, n]) => n > 0);
  const title = segs.map(([, n, label]) => `${n} ${label}`).join(" · ");
  return `<div class="ratio" title="${esc(title)}">
    ${segs.map(([cls, n]) => `<i class="${cls}" style="flex:${n}"></i>`).join("")}
  </div>`;
}

const SEARCH_HINTS = [
  "Try “tacos”…", "Try “Valencia St”…", "Try “dim sum”…",
  "Try “Sunset/Parkside”…", "Try “ramen”…", "Try “24th St”…",
  "Restaurant name, address, or neighborhood…",
];
let hintTimer = null;

function wireSearch() {
  const $q = document.getElementById("q");
  const $sugg = document.getElementById("sugg");
  let timer = null, sel = -1, current = [];

  clearInterval(hintTimer);
  let hintIdx = 0;
  hintTimer = setInterval(() => {
    if (!document.body.contains($q)) { clearInterval(hintTimer); return; }
    hintIdx = (hintIdx + 1) % SEARCH_HINTS.length;
    $q.placeholder = SEARCH_HINTS[hintIdx];
  }, 3200);
  $q.placeholder = SEARCH_HINTS[0];

  const close = () => { $sugg.hidden = true; sel = -1; };

  function renderSugg(results, query) {
    current = results;
    sel = -1;
    if (!query) { close(); return; }
    if (!results.length) {
      $sugg.innerHTML = `<div class="suggestion empty">No matches for “${esc(query)}”.
        It may not be in the 2024-present dataset.</div>`;
      $sugg.hidden = false;
      return;
    }
    $sugg.innerHTML = results.map((r, i) => `
      <div class="suggestion" data-i="${i}">
        <div>
          <div class="s-name">${esc(titleCase(r.dba))}</div>
          <div class="s-sub">${esc(titleCase(r.street_address))}${r.analysis_neighborhood ? " · " + esc(r.analysis_neighborhood) : ""}</div>
        </div>
        ${pill(r.status)}
      </div>`).join("");
    $sugg.hidden = false;
    $sugg.querySelectorAll(".suggestion[data-i]").forEach(el => {
      el.onmousedown = (ev) => { // mousedown fires before input blur
        ev.preventDefault();
        location.hash = `#/r/${encodeURIComponent(results[+el.dataset.i].permit_number)}`;
      };
    });
  }

  $q.addEventListener("input", () => {
    clearTimeout(timer);
    const q = $q.value.trim();
    if (q.length < 2) { close(); return; }
    timer = setTimeout(async () => {
      try {
        const data = await api("/api/search", { q });
        if ($q.value.trim() === data.query) renderSugg(data.results, data.query);
      } catch (e) { /* server briefly busy during refresh, ignore */ }
    }, 180);
  });
  $q.addEventListener("keydown", (ev) => {
    const items = $sugg.querySelectorAll(".suggestion[data-i]");
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      if (!items.length) return;
      ev.preventDefault();
      sel = ev.key === "ArrowDown"
        ? Math.min(sel + 1, items.length - 1) : Math.max(sel - 1, 0);
      items.forEach((el, i) => el.classList.toggle("sel", i === sel));
      items[sel].scrollIntoView({ block: "nearest" });
    } else if (ev.key === "Enter") {
      const pick = sel >= 0 ? current[sel] : current[0];
      if (pick) location.hash = `#/r/${encodeURIComponent(pick.permit_number)}`;
    } else if (ev.key === "Escape") {
      close();
    }
  });
  $q.addEventListener("blur", () => setTimeout(close, 150));
  $q.addEventListener("focus", () => { if (current.length && $q.value.trim().length >= 2) $sugg.hidden = false; });
}

/* ---------------- restaurant detail ---------------- */

async function viewDetail(permit) {
  $view.innerHTML = `<div class="loading">Loading…</div>`;
  let data;
  try {
    data = await api("/api/restaurant", { permit });
  } catch (e) {
    $view.innerHTML = `<a class="crumb" href="#/">← Search</a>
      <div class="error-box">Couldn’t load this restaurant: ${esc(e.message)}</div>`;
    return;
  }
  const r = data.restaurant;
  const info = statusInfo(r.status);
  const statusNotes = {
    pass: "Passed its most recent rated inspection.",
    cond: "Received a Conditional Pass: violations were found that must be corrected; a re-inspection follows.",
    closed: "Was ordered closed at its most recent rated inspection. Check the violations below and the inspection date; it may have been re-inspected and reopened since the last data refresh.",
    none: "No Pass/Conditional Pass/Closure rating has been recorded for this facility in the 2024-present dataset (some inspection types are not rated).",
  };

  $view.innerHTML = `
    <a class="crumb" href="#/">← Search</a>
    <div class="card st-${info.cls}">
      <div class="detail-head">
        <div>
          <h1>${esc(titleCase(r.dba))}</h1>
          <div class="addr">${esc(titleCase(r.street_address))}
            ${r.analysis_neighborhood ? `· <a href="#/browse/${encodeURIComponent(r.analysis_neighborhood)}">${esc(r.analysis_neighborhood)}</a>` : ""}
          </div>
          <div class="meta">${esc(r.permit_type || "")} · permit ${esc(r.permit_number)}</div>
        </div>
        <div class="status-block">
          ${pill(r.status, true)}
          <div class="when">${r.status_date
            ? `as of ${fmtDate(r.status_date)} (${esc(r.status_type || "inspection")})`
            : `latest visit ${fmtDate(r.latest_date)}`}</div>
        </div>
      </div>
      <div class="status-note">${statusNotes[info.cls]}</div>
    </div>

    <div class="section-title">Inspection history (${data.inspections.length})</div>
    <ul class="timeline">
      ${data.inspections.map(renderInspection).join("")}
    </ul>`;
}

function renderInspection(ins) {
  const info = statusInfo(ins.facility_rating_status);
  const nViol = ins.violations.length;
  const countLabel = ins.facility_rating_status
    ? (nViol ? `${nViol} violation ${nViol === 1 ? "item" : "items"}` : "no violations")
    : "not rated";
  const body = `
    ${nViol ? `<ul class="viols">${ins.violations.map(v => `
        <li class="${v.closure_notice ? "closure" : ""}">
          <div class="v-desc">${esc(v.description)}</div>
          ${v.codes.length ? `<div class="v-codes">${v.codes.map(c => `<span>${esc(c)}</span>`).join("")}</div>` : ""}
        </li>`).join("")}</ul>`
      : (ins.facility_rating_status
          ? `<div class="no-viols">✨ Clean plate! No violations recorded at this inspection.</div>`
          : `<div class="notes">No rating or violations recorded for this visit type.</div>`)}
    ${ins.inspection_notes ? `<div class="notes">${esc(ins.inspection_notes)}</div>` : ""}
    ${ins.suspension_notes ? `<div class="notes">${esc(ins.suspension_notes)}</div>` : ""}`;
  return `
    <li class="${info.cls}">
      <details>
        <summary>
          <span class="chev">▶</span>
          <span class="t-date">${fmtDate(ins.inspection_date)}</span>
          <span class="t-type">${esc(ins.inspection_type || "Visit")}</span>
          ${ins.facility_rating_status ? pill(ins.facility_rating_status) : ""}
          <span class="t-count">${countLabel}</span>
        </summary>
        ${body}
      </details>
    </li>`;
}

/* ---------------- browse ---------------- */

const browseState = { neighborhood: "", status: "", sort: "name", dir: "asc", offset: 0, rows: [] };

async function viewBrowse(neighborhood) {
  browseState.neighborhood = neighborhood || "";
  browseState.offset = 0;
  browseState.rows = [];
  $view.innerHTML = `
    <div class="filters">
      <select id="f-hood"><option value="">All neighborhoods</option></select>
      <select id="f-status">
        <option value="">Any status</option>
        <option value="Pass">Pass</option>
        <option value="Conditional Pass">Conditional Pass</option>
        <option value="Closure">Closure</option>
        <option value="none">No rating recorded</option>
      </select>
      <span class="count" id="f-count"></span>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th data-sort="name">Restaurant <span class="arrow"></span></th>
          <th data-sort="neighborhood">Neighborhood <span class="arrow"></span></th>
          <th data-sort="status">Status <span class="arrow"></span></th>
          <th data-sort="date">Last inspected <span class="arrow"></span></th>
          <th data-sort="violations" class="num">Violations* <span class="arrow"></span></th>
        </tr></thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
    <button class="load-more" id="more" hidden>Load more</button>
    <p class="muted" style="font-size:12.5px">* violation items at the most recent rated inspection.</p>
  `;

  try {
    const hoods = await api("/api/neighborhoods");
    const $hood = document.getElementById("f-hood");
    hoods.neighborhoods
      .slice()
      .sort((a, b) => a.neighborhood.localeCompare(b.neighborhood))
      .forEach(h => {
        const o = document.createElement("option");
        o.value = h.neighborhood;
        o.textContent = `${h.neighborhood} (${h.restaurants})`;
        $hood.appendChild(o);
      });
    $hood.value = browseState.neighborhood;
    if ($hood.value !== browseState.neighborhood) $hood.value = ""; // unknown hood in URL
  } catch (e) { /* dropdown stays minimal */ }

  document.getElementById("f-hood").onchange = (ev) => {
    location.hash = ev.target.value
      ? `#/browse/${encodeURIComponent(ev.target.value)}` : "#/browse";
  };
  document.getElementById("f-status").onchange = (ev) => {
    browseState.status = ev.target.value;
    browseState.offset = 0; browseState.rows = [];
    loadBrowseRows();
  };
  document.querySelectorAll("th[data-sort]").forEach(th => {
    th.onclick = () => {
      const key = th.dataset.sort;
      if (browseState.sort === key) {
        browseState.dir = browseState.dir === "asc" ? "desc" : "asc";
      } else {
        browseState.sort = key;
        browseState.dir = (key === "date" || key === "violations") ? "desc" : "asc";
      }
      browseState.offset = 0; browseState.rows = [];
      loadBrowseRows();
    };
  });
  document.getElementById("more").onclick = () => {
    browseState.offset += 200;
    loadBrowseRows(true);
  };
  loadBrowseRows();
}

async function loadBrowseRows(append) {
  const $rows = document.getElementById("rows");
  const $count = document.getElementById("f-count");
  const $more = document.getElementById("more");
  if (!append) $rows.innerHTML = `<tr><td colspan="5" class="loading">Loading…</td></tr>`;
  document.querySelectorAll("th[data-sort]").forEach(th => {
    th.querySelector(".arrow").textContent =
      th.dataset.sort === browseState.sort ? (browseState.dir === "asc" ? "▲" : "▼") : "";
  });
  try {
    const data = await api("/api/browse", {
      neighborhood: browseState.neighborhood,
      status: browseState.status,
      sort: browseState.sort,
      dir: browseState.dir,
      limit: 200,
      offset: browseState.offset,
    });
    browseState.rows = append ? browseState.rows.concat(data.results) : data.results;
    if (!browseState.rows.length) {
      $rows.innerHTML = `<tr><td colspan="5" class="loading">No restaurants match
        these filters${data.total === 0 && !browseState.status ? " (the cache may still be downloading)" : ""}.</td></tr>`;
    } else {
      $rows.innerHTML = browseState.rows.map(r => `
        <tr onclick="location.hash='#/r/${encodeURIComponent(r.permit_number)}'">
          <td><div class="rowname">${esc(titleCase(r.dba))}</div>
              <div class="rowsub">${esc(titleCase(r.street_address))}</div></td>
          <td>${esc(r.analysis_neighborhood || "-")}</td>
          <td>${pill(r.status)}</td>
          <td>${fmtDate(r.latest_date)}</td>
          <td class="num">${r.status == null ? "-" : (r.status_violations ?? 0)}</td>
        </tr>`).join("");
    }
    $count.textContent = `${data.total.toLocaleString()} restaurants`;
    $more.hidden = browseState.rows.length >= data.total;
  } catch (e) {
    $rows.innerHTML = `<tr><td colspan="5" class="error-box">Error: ${esc(e.message)}</td></tr>`;
  }
}

/* ---------------- boot ---------------- */
loadStatus();
route();
