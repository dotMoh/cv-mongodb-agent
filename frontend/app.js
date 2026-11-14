// Outage Router page. Talks to frontend/server.py, which calls the agent/ package.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
let token = null;

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({ error: `Server error ${res.status}` }));
  if (!res.ok || data.error) throw new Error(data.error || `Server error ${res.status}`);
  return data;
}
const user = () => $("user").value;
const postJSON = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

// ---- map ----
const map = L.map("map").setView([43.8098, -79.0668], 15);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" }).addTo(map);
const heat = L.heatLayer([], { radius: 45, blur: 28, maxZoom: 17, max: 1,
  gradient: { 0.2: "#b9e4c5", 0.5: "#4caf6e", 0.75: "#00843d", 1.0: "#111111" } }).addTo(map);
const dots = L.layerGroup().addTo(map);
function drawHeat(points) {
  heat.setLatLngs(points.map((p) => [p[0], p[1], p[2]]));
  dots.clearLayers();
  points.forEach((p) => L.circleMarker([p[0], p[1]], { radius: 4, color: "#111", weight: 1, fillOpacity: 0.6 }).bindTooltip(esc(p[3])).addTo(dots));
}

// ---- render ----
function render(d) {
  token = d.token;
  const s = d.summary;
  $("status").innerHTML = `${esc(d.file)}: ${s.tasks} tasks, ${s.critical} on the critical path, ${s.span_hours} h`;
  $("issues").innerHTML = (d.ambiguities || []).map((a) => `<li>${esc(a)}</li>`).join("");
  const o = d.overall;
  $("riskbox").hidden = false;
  $("pct").textContent = `${o.risk_pct}%`;
  $("cls").className = `cls ${o.classification}`;
  $("cls").textContent = String(o.classification).toUpperCase();
  $("riskinfo").textContent = `${o.tasks_at_risk} tasks at risk, about ${o.total_delay_exposure_days} days of delay exposure. ` +
    `Confidence: ${o.confidence}. ${o.note || "An indicative estimate from similar past lessons, not a validated statistical model."}`;
  $("risks").innerHTML = d.risks.length ? d.risks.map((r) => `
    <div class="risk ${esc(r.classification)}">
      <div class="top"><span>${esc(r.task)}</span><span>${r.risk_pct}%</span></div>
      <div class="meter"><div style="width:${r.risk_pct}%"></div></div>
      <div class="muted">${r.delay_days} d possible delay · ${r.lessons} past lesson${r.lessons === 1 ? "" : "s"} · ${esc(r.cite)}</div>
      <div>${esc(r.mitigation)}</div>
    </div>`).join("") : `<div class="risk">No sufficiently similar historical outage lessons found.</div>`;
  $("hidden").textContent = d.hidden ? `${d.hidden} restricted lessons hidden for this role.` : "";
  drawHeat(d.heat);
}
function fail(e) { $("status").innerHTML = `<span class="error">${esc(e.message)}</span>`; }

async function upload(file) {
  $("status").textContent = `Reading ${file.name}...`;
  $("answer").hidden = true;
  try {
    render(await api(`/api/analyze?name=${encodeURIComponent(file.name)}&user=${user()}`, { method: "POST", body: file }));
  } catch (e) { fail(e); }
}

$("file").addEventListener("change", (e) => e.target.files[0] && upload(e.target.files[0]));
const drop = $("drop");
["dragover", "dragenter"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("over")));
drop.addEventListener("drop", (e) => { e.preventDefault(); e.dataTransfer.files[0] && upload(e.dataTransfer.files[0]); });

$("sample").addEventListener("click", async () => {
  $("status").textContent = "Loading sample...";
  try { render(await api(`/api/sample?user=${user()}`)); } catch (e) { fail(e); }
});

$("user").addEventListener("change", async () => {
  $("answer").hidden = true;
  try {
    if (token) render(await postJSON("/api/reassess", { token, user: user() }));
    else drawHeat((await api(`/api/heat?user=${user()}`)).heat);
  } catch (e) { fail(e); }
});

$("ask").addEventListener("click", async () => {
  const q = $("q").value.trim();
  if (!q) return;
  const btn = $("ask"), box = $("answer");
  btn.disabled = true; btn.textContent = "Checking past outages...";
  try {
    const a = await postJSON("/api/ask", { token, user: user(), question: q });
    box.textContent = a.answer + (a.lessons_cited?.length ? `\n\nLessons cited: ${a.lessons_cited.join(", ")}` : "");
  } catch (e) { box.innerHTML = `<span class="error">${esc(e.message)}</span>`; }
  box.hidden = false; btn.disabled = false; btn.textContent = "Ask";
});

api(`/api/heat?user=${user()}`).then((d) => drawHeat(d.heat)).catch(() => {});
