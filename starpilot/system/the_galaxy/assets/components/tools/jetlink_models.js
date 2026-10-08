import { html, reactive } from "/assets/vendor/arrow-core.js";

// Jetlink's big models: comma commits a Jetson or Mac runs over USB, from jetlink's own catalog (/api/models/jetlink).
// Separate from Active Big, which is StarPilot's chestnut builds. A model can only be picked once this fork has validated it
// (starpilot/jetlink_adapter/profiles.py): the rest are listed, marked "Not validated", and the server refuses them.
// Ported from peterfork/Jetlink-Port (773a57f634) and adapted.
// The payload stays a plain object outside reactive(); the templates track a
// revision counter that every response bumps.
const jl = reactive({ busy: false, error: "", rev: 0 });
let data = null;
let pollHandle = null;

const POLL_MS = 5000;

async function request(options) {
  try {
    const response = await fetch("/api/models/jetlink", options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    data = payload;
    jl.error = "";
    jl.rev += 1;
  } catch (error) {
    jl.error = error.message || String(error);
  }
}

function poll() {
  pollHandle = null;
  if (!document.querySelector(".mm-jetlink")) return;
  request().finally(() => { if (!pollHandle) pollHandle = setTimeout(poll, POLL_MS); });
}

async function select(ref) {
  jl.busy = true;
  await request({ method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ref }) });
  jl.busy = false;
}

const current = () => (jl.rev, data);
const models = () => (current() && current().models) || [];
const locked = () => jl.busy || !!(current() && current().isOnroad);

function stateChip(state) {
  if (state === "ready") return html`<span class="mm-chip mm-chip-egpu">Built on host</span>`;
  return html`<span class="mm-chip">${state === "downloaded" ? "Downloaded" : "Not downloaded"}</span>`;
}

// arrow keeps a reused template's plain values and re-runs only its function
// expressions, so everything a poll can change is read live from the payload
const field = name => (current() || {})[name];
const row = ref => models().find(m => m.ref === ref) || {};
const isSelected = ref => ref ? !!row(ref).selected : !models().some(m => m.selected);

function statusRow() {
  return html`
    <div class="mm-row">
      <div class="mm-row-main">
        <div class="mm-row-title"><span>Link</span></div>
        <div class="mm-row-meta">
          <span class="mm-chip">Link: ${() => (field("mode") || "off").toUpperCase()}</span>
          <span class="mm-chip">Host: ${() => field("present") ? "Connected" : "Not connected"}</span>
          <span class="mm-chip mm-chip-egpu">Running: ${() => field("activeModel") || "none built yet"}</span>
          ${() => { const p = field("progress"); return p && p.msg ? html`<span class="mm-chip">${p.stage}: ${p.msg}</span>` : ""; }}
          ${() => field("reason") ? html`<span class="mm-chip mm-chip-warning">${field("reason")}</span>` : ""}
          ${() => field("mode") === "off" ? html`<span class="mm-chip mm-chip-warning">Turn Jetlink on in Settings</span>` : ""}
        </div>
      </div>
    </div>
  `;
}

function modelRow(title, ref) {
  return html`
    <div class="mm-row">
      <div class="mm-row-main">
        <div class="mm-row-title"><span>${title}</span></div>
        <div class="mm-row-meta">
          ${ref ? html`<span class="mm-chip">${ref.slice(0, 10)}</span>` : ""}
          ${() => ref ? stateChip(row(ref).state) : ""}
          ${() => ref && row(ref).supported === false ? html`<span class="mm-chip mm-chip-warning">Not validated</span>` : ""}
          ${() => isSelected(ref) ? html`<span class="mm-chip mm-chip-active">Selected</span>` : ""}
        </div>
      </div>
      <div class="mm-row-actions">
        ${() => isSelected(ref) ? "" : html`<button class="mm-btn ${ref ? "mm-btn-primary" : "mm-btn-secondary"}" @click="${() => select(ref)}" disabled="${() => locked() || (ref && row(ref).supported === false)}">${ref ? "Select" : "Use Default"}</button>`}
      </div>
    </div>
  `;
}

function body() {
  const d = current();
  if (!d) return jl.error ? "" : html`<div class="mm-empty">Loading Jetlink...</div>`.key("loading");
  if (!d.available) return html`<div class="mm-empty">Jetlink is not available on this build.</div>`.key("unavailable");
  return html`
    ${statusRow()}
    ${() => modelRow(`Default (${field("defaultModel") || "jetlink default"})`, "").key(`default:${field("defaultModel")}`)}
    ${() => models().map(m => modelRow(m.name, m.ref).key(`${m.ref}:${m.name}`))}
    ${() => models().length ? "" : html`<div class="mm-empty">No Jetlink catalog yet. Press Refresh to fetch it.</div>`}
  `.key("available");
}

export function JetlinkModels() {
  if (!pollHandle) {
    request();
    pollHandle = setTimeout(poll, POLL_MS);
  }
  return html`
    <section class="mm-series mm-jetlink">
      <header class="mm-series-header">
        <h3>Jetlink Big Models</h3>
        <span>${() => models().length}</span>
      </header>
      <div class="mm-series-body">
        ${() => jl.error ? html`<div class="mm-error">${jl.error}</div>` : ""}
        ${() => body()}
      </div>
    </section>
  `;
}
