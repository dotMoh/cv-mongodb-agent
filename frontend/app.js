// Outage Router page. Talks to frontend/server.py, which calls the agent/ package.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
let token = null;
let heatPts = [];
let unitRisk = {};
let sys = {};

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({ error: `Server error ${res.status}` }));
  if (!res.ok || data.error) throw new Error(data.error || `Server error ${res.status}`);
  return data;
}
const user = () => $("user").value;
const memory = () => $("memory").checked;
const postJSON = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

// =============================================================== plant drawing (viewBox 1000 x 640)
// Zones must match ZONE_POS / UNIT_X in server.py (x = fraction of width, y = fraction of height).
const UNITS = ["U1", "U2", "U3", "U4"];
const W = 1000, H = 900;
const Y = (f) => Math.round(f * H);
function drawPlant() {
  const s = [];
  const label = (x, y, t, size = 18, anchor = "start") => `<text x="${x}" y="${y}" font-size="${size}" fill="#5f6368" text-anchor="${anchor}">${t}</text>`;
  s.push(`<rect x="0" y="0" width="${W}" height="${H}" fill="#fafbfa"/>`);
  s.push(`<rect x="0" y="0" width="${W}" height="48" fill="#e9eeec"/>` + label(14, 32, "Lake water intake", 22));
  // shared turbine hall
  s.push(`<rect x="16" y="${Y(0.68)}" width="968" height="${Y(0.16)}" rx="8" fill="#f0f2f1" stroke="#111" stroke-width="2.5"/>`);
  s.push(label(28, Y(0.68) + 28, "Turbine hall", 20));
  UNITS.forEach((u, i) => {
    const cx = 125 + 250 * i, ry = Y(0.27);
    // cooling water line from the lake
    s.push(`<line x1="${cx + 100}" y1="48" x2="${cx + 100}" y2="${Y(0.68)}" stroke="#c9d3cd" stroke-width="4" stroke-dasharray="8 6"/>`);
    // reactor building + core
    s.push(`<circle cx="${cx}" cy="${ry}" r="80" fill="#fff" stroke="#111" stroke-width="3"/>`);
    s.push(`<circle cx="${cx}" cy="${ry}" r="40" fill="none" stroke="#00843d" stroke-width="4"/>`);
    s.push(`<circle cx="${cx}" cy="${ry}" r="9" fill="#00843d"/>`);
    // heat exchangers (steam generators)
    const hy = Y(0.47);
    for (let k = 0; k < 3; k++) s.push(`<rect x="${cx - 104 + k * 20}" y="${hy - 45}" width="15" height="90" rx="7.5" fill="#fff" stroke="#111" stroke-width="2"/>`);
    s.push(`<path d="M${cx - 50} ${ry + 60} L${cx - 78} ${hy - 45}" stroke="#111" stroke-width="2.5"/>`);
    s.push(label(cx - 75, hy + 72, "Heat exch.", 18, "middle"));
    // pumps and valves
    const py = Y(0.52);
    s.push(`<path d="M${cx + 45} ${ry + 66} L${cx + 45} ${py} L${cx + 85} ${py} L${cx + 85} ${Y(0.68)}" fill="none" stroke="#111" stroke-width="2.5"/>`);
    s.push(`<circle cx="${cx + 45}" cy="${py}" r="12" fill="#fff" stroke="#111" stroke-width="2.5"/>`);
    s.push(`<path d="M${cx + 73} ${py + 40} l24 16 l0 -16 l-24 16 z" fill="#fff" stroke="#111" stroke-width="2"/>`);
    s.push(label(cx + 60, py + 90, "Pumps, valves", 18, "middle"));
    // turbine + generator
    const ty = Y(0.76);
    s.push(`<rect x="${cx - 95}" y="${ty - 30}" width="150" height="60" rx="6" fill="#fff" stroke="#111" stroke-width="2"/>`);
    s.push(`<path d="M${cx - 88} ${ty} L${cx - 38} ${ty - 22} L${cx - 38} ${ty + 22} Z" fill="none" stroke="#111" stroke-width="2"/>`);
    s.push(`<circle cx="${cx + 18}" cy="${ty}" r="19" fill="none" stroke="#111" stroke-width="2"/>`);
    // switchyard
    const ey = Y(0.88);
    s.push(`<rect x="${cx + 35}" y="${ey - 38}" width="80" height="76" rx="4" fill="#fff" stroke="#111" stroke-width="2"/>`);
    s.push(`<path d="M${cx + 45} ${ey + 25} L${cx + 62} ${ey - 22} L${cx + 79} ${ey + 25} M${cx + 79} ${ey + 25} L${cx + 96} ${ey - 22} L${cx + 106} ${ey + 10}" fill="none" stroke="#111" stroke-width="1.8"/>`);
    s.push(label(cx - 40, ey + 8, "Switchyard", 18, "middle"));
    // unit label + risk badge
    s.push(`<text x="${cx}" y="${Y(0.115)}" font-size="34" font-weight="800" text-anchor="middle" fill="#111">${u}</text>`);
    const r = unitRisk[u];
    if (r != null) s.push(`<rect x="${cx - 50}" y="${Y(0.115) + 10}" width="100" height="32" rx="16" fill="${r >= 60 ? "#111" : r >= 30 ? "#00843d" : "#e6f4ea"}"/>` +
      `<text x="${cx}" y="${Y(0.115) + 33}" font-size="19" font-weight="700" text-anchor="middle" fill="${r >= 30 ? "#fff" : "#005a2b"}">${r}% risk</text>`);
  });
  $("plant-svg").innerHTML = s.join("");
}

// =============================================================== heatmap (yellow to red)
const STOPS = [[0.0, [255, 247, 168]], [0.3, [255, 230, 0]], [0.55, [255, 176, 0]], [0.78, [255, 106, 0]], [1.0, [215, 25, 28]]];
const PALETTE = (() => {
  const p = new Uint8ClampedArray(256 * 3);
  for (let i = 0; i < 256; i++) {
    const t = i / 255;
    let k = 0; while (k < STOPS.length - 2 && t > STOPS[k + 1][0]) k++;
    const [t0, c0] = STOPS[k], [t1, c1] = STOPS[k + 1];
    const f = Math.min(1, Math.max(0, (t - t0) / (t1 - t0)));
    for (let j = 0; j < 3; j++) p[i * 3 + j] = c0[j] + (c1[j] - c0[j]) * f;
  }
  return p;
})();

function drawHeat() {
  const cv = $("heat"), box = $("plant");
  const dpr = window.devicePixelRatio || 1;
  const w = box.clientWidth, h = box.clientHeight;
  if (!w || !h) return;
  cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  const ctx = cv.getContext("2d");
  ctx.clearRect(0, 0, cv.width, cv.height);
  const r = 0.065 * cv.width;
  for (const p of heatPts) {
    const x = p[0] * cv.width, y = p[1] * cv.height;
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, "rgba(0,0,0,1)"); g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.globalAlpha = Math.max(0.15, Math.min(1, p[2])) * 0.9;
    ctx.fillStyle = g;
    ctx.fillRect(x - r, y - r, 2 * r, 2 * r);
  }
  ctx.globalAlpha = 1;
  const img = ctx.getImageData(0, 0, cv.width, cv.height), d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const a = d[i + 3];
    if (!a) continue;
    const c = Math.min(255, a) * 3;
    d[i] = PALETTE[c]; d[i + 1] = PALETTE[c + 1]; d[i + 2] = PALETTE[c + 2];
    d[i + 3] = Math.min(225, 50 + a);
  }
  ctx.putImageData(img, 0, 0);
}
window.addEventListener("resize", drawHeat);

$("plant").addEventListener("mousemove", (e) => {
  const box = $("plant").getBoundingClientRect(), tip = $("tip");
  const mx = e.clientX - box.left, my = e.clientY - box.top;
  const near = heatPts.filter((p) => Math.hypot(p[0] * box.width - mx, p[1] * box.height - my) < 22);
  if (!near.length) { tip.hidden = true; return; }
  tip.innerHTML = near.slice(0, 4).map((p) => esc(p[3])).join("<br>");
  tip.style.left = Math.min(mx + 14, box.width - 270) + "px";
  tip.style.top = (my + 14) + "px";
  tip.hidden = false;
});
$("plant").addEventListener("mouseleave", () => { $("tip").hidden = true; });

function setHeat(points, units) {
  heatPts = points || [];
  unitRisk = units || {};
  drawPlant();
  drawHeat();
}

// =============================================================== analysis
function render(d) {
  token = d.token;
  const s = d.summary;
  $("status").innerHTML = `${esc(d.file)}: ${s.tasks} tasks, ${s.critical} on the critical path, ${s.span_hours} h`;
  $("issues").innerHTML = (d.ambiguities || []).map((a) => `<li>${esc(a)}</li>`).join("");
  const o = d.overall;
  $("riskbox").hidden = false;
  $("memtag").className = `memtag ${d.memory ? "on" : "off"}`;
  $("memtag").textContent = d.memory ? "memory on" : "memory off";
  $("pct").textContent = `${o.risk_pct}%`;
  $("cls").className = `cls ${o.classification}`;
  $("cls").textContent = String(o.classification).toUpperCase();
  $("riskinfo").textContent = `${o.tasks_at_risk} tasks at risk, about ${o.total_delay_exposure_days} days of delay exposure. ` +
    `Confidence: ${o.confidence}. ${o.note || ""}`;

  const c = d.compare;
  $("vs-on").textContent = `${c.on.risk_pct}%`;
  $("vs-off").textContent = `${c.off.risk_pct}%`;
  $("vs-on-sub").textContent = `${c.on.classification}, ${c.on.tasks_at_risk} tasks flagged, ${c.on.lessons_used ?? 0} lessons used`;
  $("vs-off-sub").textContent = `${c.off.classification}, ${c.off.tasks_at_risk} tasks flagged, no lessons consulted`;
  $("vs-rows").innerHTML = c.tasks.map((t) => `<tr><td>${esc(t.task)}</td><td class="n">${t.on}%</td><td class="n off">${t.off}%</td><td>${esc(t.cite)}</td></tr>`).join("");

  $("risks").innerHTML = d.risks.length ? d.risks.map((r) => `
    <div class="risk ${esc(r.classification)}">
      <div class="top"><span>${esc(r.task)}</span><span>${r.risk_pct}%</span></div>
      <div class="meter"><div style="width:${r.risk_pct}%"></div></div>
      <div class="muted">${r.delay_days} d possible delay · ${r.lessons} past lesson${r.lessons === 1 ? "" : "s"} · ${esc(r.cite)}</div>
      <div>${esc(r.mitigation)}</div>
    </div>`).join("") :
    `<div class="risk">${d.memory ? "No sufficiently similar historical outage lessons found." : "Memory is off, so no past lessons were consulted and nothing is flagged. Turn memory on to compare."}</div>`;
  $("hidden").textContent = d.hidden ? `${d.hidden} restricted lessons hidden for this role.` : "";
  setHeat(d.heat, d.units);
}
function fail(e) { $("status").innerHTML = `<span class="error">${esc(e.message)}</span>`; }

async function refresh() {
  try {
    if (token) render(await postJSON("/api/reassess", { token, user: user(), memory: memory() }));
    else setHeat((await api(`/api/heat?user=${user()}&memory=${memory() ? 1 : 0}`)).heat, {});
  } catch (e) { fail(e); }
}

async function upload(file) {
  $("status").textContent = `Reading ${file.name}...`;
  $("answer").hidden = true;
  try {
    render(await api(`/api/analyze?name=${encodeURIComponent(file.name)}&user=${user()}&memory=${memory() ? 1 : 0}`, { method: "POST", body: file }));
    loadAudit();
  } catch (e) { fail(e); }
}

$("file").addEventListener("change", (e) => e.target.files[0] && upload(e.target.files[0]));
const drop = $("drop");
["dragover", "dragenter"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("over")));
drop.addEventListener("drop", (e) => { e.preventDefault(); e.dataTransfer.files[0] && upload(e.dataTransfer.files[0]); });

$("sample").addEventListener("click", async () => {
  $("status").textContent = "Loading sample...";
  try { render(await api(`/api/sample?user=${user()}&memory=${memory() ? 1 : 0}`)); loadAudit(); } catch (e) { fail(e); }
});

$("user").addEventListener("change", () => { $("answer").hidden = true; refresh(); loadGov(); loadAudit(); });
$("memory").addEventListener("change", () => {
  $("memlabel").textContent = memory() ? "Memory on" : "Memory off";
  $("answer").hidden = true;
  refresh();
});

$("ask").addEventListener("click", async () => {
  const q = $("q").value.trim();
  if (!q) return;
  const btn = $("ask"), box = $("answer");
  if (!token) { box.hidden = false; box.innerHTML = `<span class="error">Upload a schedule first.</span>`; return; }
  btn.disabled = true; btn.textContent = sys.llm?.reachable ? "Thinking..." : "Checking past outages...";
  try {
    const a = await postJSON("/api/ask", { token, user: user(), question: q, memory: memory() });
    const cited = (a.lessons_cited || []).map((l) => `${l.lesson_id} v${l.version}: ${l.title}`);
    const src = a.source === "ollama" ? `Generated locally by ${sys.llm?.model || "Ollama"}` :
      a.source === "anthropic" ? "Generated by Claude" : "Rule-based answer (no language model running)";
    box.innerHTML = esc(a.answer) + (cited.length ? `\n\nLessons cited:\n${cited.map(esc).join("\n")}` : "") +
      `<span class="src">${esc(src)}${a.memory ? "" : " · memory off"}</span>`;
  } catch (e) { box.innerHTML = `<span class="error">${esc(e.message)}</span>`; }
  box.hidden = false; btn.disabled = false; btn.textContent = "Ask";
  loadAudit();
});

// =============================================================== governance
let can = [];
function govMsg(text, err = false) {
  const m = $("govmsg");
  m.textContent = text; m.className = `govmsg${err ? " err" : ""}`; m.hidden = false;
}
async function govAction(path, body) {
  try {
    const r = await postJSON(path, { user: user(), ...body });
    govMsg(r.ok);
  } catch (e) { govMsg(e.message, true); }
  await Promise.all([loadGov(), loadAudit(), refresh()]);
}

function btn(label, act, lid, cls = "ghost") {
  return `<button class="${cls} small" data-act="${act}" data-lid="${esc(lid)}">${label}</button>`;
}

async function loadGov() {
  try {
    const v = await api(`/api/lessons?user=${user()}`);
    can = v.can;
    const role = $("user").selectedOptions[0].textContent;
    $("govnote").textContent = `${role}: ${v.lessons.length} lessons visible` + (v.hidden ? `, ${v.hidden} hidden by access policy.` : ".") +
      (can.includes("approve") ? " You can approve drafts, correct lessons (a new version is kept) and forget them." :
       can.includes("add") ? " You can add draft lessons; a lead must approve them before they are used. Lead-only buttons are refused and logged." :
       " Read only. Any change you try is refused and logged.");
    $("addbox").hidden = !can.includes("add");
    $("lessons").innerHTML = v.lessons.map((l) => {
      const acts = [btn("History", "history", l.lesson_id)];
      if (l.status === "draft") acts.unshift(btn("Approve", "approve", l.lesson_id, can.includes("approve") ? "" : "ghost"));
      if (l.status === "approved" || l.status === "draft") {
        acts.push(btn("Correct", "correct", l.lesson_id));
        acts.push(btn("Forget", "forget", l.lesson_id, "danger"));
      }
      const exp = l.days_to_expiry != null ? `<div class="muted">expires in ${l.days_to_expiry} d</div>` : "";
      return `<tr class="${esc(l.status)}" data-lid="${esc(l.lesson_id)}">
        <td><b>${esc(l.lesson_id)}</b> v${l.version}</td>
        <td><span class="badge ${esc(l.status)}">${esc(l.status)}</span>${exp}</td>
        <td>${esc(l.unit)}</td>
        <td>${esc(l.title)}${l.change_reason ? `<div class="muted">Corrected: ${esc(l.change_reason)}</div>` : ""}</td>
        <td>${l.delay_days ?? ""} d</td>
        <td>${esc(l.sensitivity)}</td>
        <td class="acts">${acts.join("")}</td></tr>`;
    }).join("");
    window._lessons = Object.fromEntries(v.lessons.map((l) => [l.lesson_id, l]));
  } catch (e) { govMsg(e.message, true); }
}

function closeExtra() { document.querySelectorAll("tr.edit").forEach((r) => r.remove()); }

$("lessons").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-act]");
  if (!b) return;
  const lid = b.dataset.lid, act = b.dataset.act, row = b.closest("tr");
  if (act === "approve") return govAction("/api/lesson/approve", { lesson_id: lid });
  if (act === "forget") {
    if (!b.classList.contains("armed")) {
      b.classList.add("armed"); b.textContent = "Confirm forget";
      setTimeout(() => { b.classList.remove("armed"); b.textContent = "Forget"; }, 4000);
      return;
    }
    return govAction("/api/lesson/forget", { lesson_id: lid, confirm: true, reason: "Forgotten from the Outage Router page" });
  }
  closeExtra();
  if (act === "history") {
    try {
      const h = await api(`/api/history?user=${user()}&lesson_id=${encodeURIComponent(lid)}`);
      row.insertAdjacentHTML("afterend", `<tr class="edit"><td colspan="7"><b>Version history of ${esc(lid)}</b><ol class="versions">` +
        h.versions.map((v) => `<li>v${v.version} <span class="badge ${esc(v.status)}">${esc(v.status)}</span> ${esc(v.title)} (${v.delay_days} d)` +
          `${v.change_reason ? ` · reason: ${esc(v.change_reason)}` : ""}${v.created_by ? ` · by ${esc(v.created_by)}` : ""}</li>`).join("") +
        `</ol></td></tr>`);
    } catch (err) { govMsg(err.message, true); }
    loadAudit();
    return;
  }
  if (act === "correct") {
    const l = window._lessons[lid] || {};
    row.insertAdjacentHTML("afterend", `<tr class="edit"><td colspan="7"><div class="form">
      <b>Correct ${esc(lid)} (creates v${(l.version || 1) + 1}, keeps v${l.version || 1})</b>
      <input id="c-title" value="${esc(l.title)}">
      <input id="c-rec" value="${esc(l.recommendation)}" placeholder="Recommendation">
      <div class="row"><input id="c-delay" type="number" step="0.5" min="0" value="${l.delay_days ?? ""}" placeholder="Delay (days)">
        <input id="c-reason" placeholder="Reason for the correction (required)"></div>
      <div><button id="c-save" class="small">Save new version</button> <button id="c-cancel" class="ghost small">Cancel</button></div>
    </div></td></tr>`);
    $("c-cancel").onclick = closeExtra;
    $("c-save").onclick = () => govAction("/api/lesson/correct", { lesson_id: lid, reason: $("c-reason").value,
      changes: { title: $("c-title").value, recommendation: $("c-rec").value, delay_days: $("c-delay").value } });
  }
});

$("add").addEventListener("click", () => govAction("/api/lesson/add", {
  title: $("add-title").value, issue: $("add-issue").value, recommendation: $("add-rec").value,
  unit: $("add-unit").value, delay_days: $("add-delay").value, sensitivity: $("add-sens").value,
}).then(() => { ["add-title", "add-issue", "add-rec", "add-delay"].forEach((id) => { $(id).value = ""; }); }));

$("reset").addEventListener("click", () => govAction("/api/reset", {}));

async function loadAudit() {
  try {
    const a = await api(`/api/audit?user=${user()}&limit=30`);
    $("auditnote").textContent = a.scope === "everyone" ? "Every action by every user, newest first." : "Your own actions, newest first. Leads see everyone's.";
    $("audit").innerHTML = a.entries.map((e) => `<li>
      <span class="act ${e.allowed ? "" : "denied"}">${e.allowed ? "" : "DENIED "}${esc(e.action)}</span>
      ${e.lesson_id ? `${esc(e.lesson_id)}${e.version ? " v" + e.version : ""}` : ""} · ${esc(e.user_id)}
      ${e.detail ? `<div class="muted">${esc(e.detail)}</div>` : ""}
      <div class="when">${esc(String(e.ts || "").replace("T", " ").slice(0, 19))} UTC</div></li>`).join("") || `<li class="muted">Nothing yet.</li>`;
  } catch (e) { $("auditnote").textContent = e.message; }
}

async function loadStatus() {
  try {
    sys = await api("/api/status");
    const chat = !sys.llm.reachable ? (sys.llm.provider === "anthropic" ? "Chat: rule-based fallback (ANTHROPIC_API_KEY not set)" : "Chat: rule-based fallback") :
      sys.llm.provider === "anthropic" ? "Chat: Claude" :
      `Chat: ${sys.llm.model} running locally${sys.llm.installed === false ? " (model not pulled yet)" : ""}`;
    $("sys").textContent = `Data: ${sys.data_source === "mongo" ? "MongoDB Atlas" : "demo data (mock)"} · Search: ${sys.embeddings === "minilm" ? "MiniLM vector search" : "lexical similarity"} · ${chat}`;
    $("reset").hidden = !sys.can_reset;
  } catch (e) { $("sys").textContent = e.message; }
}

drawPlant();
refresh();
loadGov();
loadAudit();
loadStatus();
