import { html, reactive } from "/assets/vendor/arrow-core.js"
import {
  HELP_TEXT, LIVE_POLL_MS, LiveBuffer, READING_GUIDE, ZOOM_HALF_WINDOW_S,
  buildOverviewCharts, buildTrackingCharts, controllerName, eventRows, fmtDate, fmtDuration, fmtNum, fmtSpeed, keyNumbers,
  longStateName, sessionUrl, speedBandRows, speedUnit, statusLabel, timeAtClick, toSeries, tuneGroups, turnRows,
} from "/assets/components/tools/drive_plots_shared.mjs"

const ADVANCED_TERMS_KEY = "plotsShowAdvancedTerms"
const SESSIONS_POLL_MS = 5000
const SESSION_LIST_SHORT = 5

// Reactivity layout (arrow-core re-renders a block whenever a property it read changes, and a re-rendered block
// replaces its DOM, which swallows a tap that is in progress on one of its buttons):
//   - blocks that hold buttons read only slow-changing state (recActive, paused, showAdvancedTerms, selectedId…)
//   - everything fed by the 500 ms poll (live, latest, liveCharts) is read inside nested `inline()` slots, so only
//     those slots re-render on each sample batch.
const state = reactive({
  loading: true,
  error: "",
  notice: "",
  paused: false,
  showAdvancedTerms: false,
  showAllSessions: false,
  isMetric: false,
  lateralController: null,
  recActive: false,
  busy: false,
  live: null,
  liveCharts: [],
  latest: null,
  sessions: [],
  selectedId: "",
  detail: null,
  detailError: "",
  zoom: null,
})

const buffer = new LiveBuffer(60)
let initialized = false
let pollHandle = null
let lastSessionsFetch = 0
let sessionsJson = ""
let visibilityListenerAttached = false

const speed = () => speedUnit(state.isMetric)

function isPlotsRouteActive() {
  return window.location.pathname === "/plots"
}

async function fetchJson(url, init) {
  const response = await fetch(url, init)
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload.error || response.statusText || "Request failed")
  return payload
}

function rebuildLiveCharts() {
  state.liveCharts = buildTrackingCharts(buffer.view(), { advanced: state.showAdvancedTerms, speed: speed(),
                                                          controller: state.lateralController })
  state.latest = buffer.latest()
}

async function fetchLiveData() {
  const payload = await fetchJson(`/api/plots/live?since=${buffer.seq}`)
  const hadRecording = state.recActive
  state.live = payload
  state.error = ""
  state.loading = false
  state.isMetric = !!payload.isMetric
  state.lateralController = payload.lateralController || null
  state.recActive = !!payload.recording
  if (buffer.ingest(payload)) rebuildLiveCharts()
  // A recording that just ended (stopped here, elsewhere, or auto-stopped offroad) shows up in the list.
  if (hadRecording !== state.recActive || Date.now() - lastSessionsFetch > SESSIONS_POLL_MS) {
    fetchSessions().catch(() => {})
  }
}

async function fetchSessions() {
  lastSessionsFetch = Date.now()
  const payload = await fetchJson("/api/plots/sessions")
  const next = Array.isArray(payload.sessions) ? payload.sessions : []
  const json = JSON.stringify(next)
  if (json === sessionsJson) return
  sessionsJson = json
  state.sessions = next
  const selected = next.find((s) => s.id === state.selectedId)
  if (selected && state.detail && state.detail.meta?.status !== selected.status) {
    openSession(selected.id)
  }
}

function stopPolling() {
  if (!pollHandle) return
  clearTimeout(pollHandle)
  pollHandle = null
}

function ensurePolling() {
  if (pollHandle) return
  const poll = async () => {
    if (!isPlotsRouteActive()) {
      pollHandle = null
      return
    }
    if (document.visibilityState === "visible" && !state.paused) {
      try {
        await fetchLiveData()
      } catch (error) {
        state.error = error?.message || String(error)
        state.loading = false
      }
    }
    pollHandle = setTimeout(poll, LIVE_POLL_MS)
  }
  pollHandle = setTimeout(poll, LIVE_POLL_MS)
}

async function startRecording() {
  state.busy = true
  state.notice = ""
  try {
    await fetchJson("/api/plots/recording/start", { method: "POST" })
    await fetchLiveData()
  } catch (error) {
    state.error = error?.message || String(error)
  } finally {
    state.busy = false
  }
}

async function setAutoRecord(on) {
  state.busy = true
  try {
    const payload = await fetchJson("/api/plots/settings", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ auto_record: !!on }),
    })
    if (state.live) state.live = { ...state.live, settings: payload.settings }
  } catch (error) {
    state.error = error?.message || String(error)
  } finally {
    state.busy = false
  }
}

async function stopRecording() {
  state.busy = true
  try {
    const payload = await fetchJson("/api/plots/recording/stop", { method: "POST" })
    await fetchLiveData()
    const stopped = payload.stopped
    if (stopped?.discarded) {
      state.notice = "Nothing was recorded (openpilot was not running), so no drive was saved."
    } else {
      await fetchSessions()
      if (stopped?.id) openSession(stopped.id, { scroll: true })
    }
  } catch (error) {
    state.error = error?.message || String(error)
  } finally {
    state.busy = false
  }
}

async function openSession(id, { scroll = false } = {}) {
  state.selectedId = id
  state.detailError = ""
  state.zoom = null
  try {
    state.detail = await fetchJson(sessionUrl(id))
  } catch (error) {
    state.detail = null
    state.detailError = error?.message || String(error)
  }
  if (scroll) {
    requestAnimationFrame(() => document.querySelector(".plotDetail")?.scrollIntoView({ behavior: "smooth", block: "start" }))
  }
}

function closeSession() {
  state.selectedId = ""
  state.detail = null
  state.zoom = null
}

async function deleteSession(id) {
  if (!window.confirm("Delete this saved drive? This cannot be undone.")) return
  try {
    await fetchJson(sessionUrl(id), { method: "DELETE" })
    if (state.selectedId === id) closeSession()
    await fetchSessions()
  } catch (error) {
    state.detailError = error?.message || String(error)
  }
}

function zoomAt(event, chart) {
  const t = timeAtClick(event, chart.geo)
  if (t !== null) zoomTo(t)
}

// Full-resolution charts around t (seconds into the drive), from a chart tap or a moment in the list.
async function zoomTo(t, label = "") {
  if (!state.selectedId) return
  const start = Math.max(0, t - ZOOM_HALF_WINDOW_S)
  const end = start + 2 * ZOOM_HALF_WINDOW_S
  try {
    const payload = await fetchJson(`${sessionUrl(state.selectedId, "/window")}?start=${start.toFixed(1)}&end=${end.toFixed(1)}`)
    const series = toSeries(payload.columns, payload.rows)
    const controller = state.detail?.analysis?.controller || state.detail?.meta?.lateral_controller || null
    state.zoom = { start, end, label, charts: buildTrackingCharts(series, { advanced: state.showAdvancedTerms, tMin: start, tMax: end,
                                                                           speed: speed(), controller }) }
    requestAnimationFrame(() => document.querySelector(".plotZoom")?.scrollIntoView({ behavior: "smooth", block: "start" }))
  } catch (error) {
    state.detailError = error?.message || String(error)
  }
}

function togglePaused() {
  state.paused = !state.paused
  if (state.paused) {
    stopPolling()
    return
  }
  if (!isPlotsRouteActive()) return
  fetchLiveData().catch((error) => {
    state.error = error?.message || String(error)
  })
  ensurePolling()
}

function toggleAdvancedTerms() {
  state.showAdvancedTerms = !state.showAdvancedTerms
  try {
    localStorage.setItem(ADVANCED_TERMS_KEY, state.showAdvancedTerms ? "1" : "0")
  } catch (error) {
    console.warn("Failed to persist plots advanced terms preference", error)
  }
  rebuildLiveCharts()
}

// ---------------------------------------------------------------------------------------------------------------
// Charts

function ChartSvg(chart, onClick) {
  const g = chart.geo
  if (g.empty) return html`<div class="plotEmpty">Waiting for data...</div>`
  const [l0, l1, l2, l3] = g.slots
  // Nested html`` inside <svg> would land in the XHTML namespace, so the SVG has a fixed set of element slots.
  return html`
    <svg class="plotSvg ${onClick ? "plotSvgClickable" : ""}" viewBox="0 0 ${g.width} ${g.height}" preserveAspectRatio="none"
      role="img" aria-label="${chart.title}" @click="${(e) => onClick && onClick(e, chart)}">
      <path class="plotShade" d="${g.shadeD}"></path>
      <path class="plotGridLine" d="${g.gridD}"></path>
      <path class="plotZeroLine" d="${g.zeroD}"></path>
      <path class="plotLine ${l0.cls}" d="${l0.d}"></path>
      <path class="plotLine ${l1.cls}" d="${l1.d}"></path>
      <path class="plotLine ${l2.cls}" d="${l2.d}"></path>
      <path class="plotLine ${l3.cls}" d="${l3.d}"></path>
    </svg>
  `
}

const yShift = (pct) => (pct < 5 ? "0" : pct > 95 ? "-100%" : "-50%")
const xShift = (pct) => (pct < 3 ? "0" : pct > 97 ? "-100%" : "-50%")

function ChartCard(chart, onClick = null) {
  const g = chart.geo
  const yLabels = g.empty ? [] : g.grid.filter((_, j) => j % 2 === 0)
  return html`
    <section class="plotCard plotChartCard">
      <div class="plotCardHeader">
        <h2>${chart.title}</h2>
        ${chart.unit ? html`<span class="plotSource">${chart.unit}</span>` : ""}
      </div>
      <div class="plotLegend">
        ${chart.legend.map((l) => html`
          <span class="plotLegendItem"><i class="plotLegendLine ${l.cls}"></i>${l.label}${l.value ? `: ${l.value}` : ""}</span>
        `)}
      </div>
      <div class="plotSvgWrap">
        ${ChartSvg(chart, onClick)}
        ${yLabels.map((l) => html`<span class="plotYLabel" style="top:${l.pct}%; transform:translateY(${yShift(Number(l.pct))})">${l.label}</span>`)}
      </div>
      ${g.empty ? "" : html`
        <div class="plotXAxis">
          ${g.xTicks.map((x) => html`<span style="left:${x.pct}%; transform:translateX(${xShift(Number(x.pct))})">${x.label}</span>`)}
        </div>
      `}
      ${chart.note ? html`<p class="plotChartNote">${chart.note}</p>` : ""}
    </section>
  `
}

// ---------------------------------------------------------------------------------------------------------------
// Analysis

function TurnTables(m) {
  const tr = turnRows(m, speed())
  if (!tr || (!tr.bins.length && !tr.wobble.length)) return ""
  return html`
    ${tr.bins.length ? html`
      <p class="plotTableTitle">Tight turns (wheel past 45°), steering-wheel degrees</p>
      <table class="plotBandTable">
        <thead><tr><th>Speed</th><th>Time</th><th>Off by</th><th>Past</th><th>Behind</th><th>At limit</th></tr></thead>
        <tbody>
          ${tr.bins.map((b) => html`<tr><td>${b.label}</td><td>${b.time}</td><td>${b.err}</td><td>${b.past}</td><td>${b.trail}</td><td>${b.limit}</td></tr>`)}
        </tbody>
      </table>
      ${tr.scorecard ? html`<p class="plotTableNote">Leaves out the second after you let go. Counting it, as the agents' scorecard does: ${tr.scorecard}.</p>` : ""}
    ` : ""}
    ${tr.wobble.length ? html`
      <p class="plotTableTitle">Wheel wobble on near-straight road</p>
      <table class="plotBandTable">
        <thead><tr><th>Speed</th><th>Time</th><th>Wobble (RMS)</th></tr></thead>
        <tbody>${tr.wobble.map((b) => html`<tr><td>${b.label}</td><td>${b.time}</td><td>${b.rms}</td></tr>`)}</tbody>
      </table>
    ` : ""}
  `
}

function AnalysisBlock(title, axis, m, liveWindow = false) {
  if (!m) return ""
  const bands = liveWindow ? [] : speedBandRows(m, speed())
  return html`
    <div class="qualitySummaryRow">
      <p class="qualitySentence">${title}</p>
      <p class="plotSummary">${m.summary}</p>
      ${m.notes?.length ? html`<ul class="plotNotes">${m.notes.map((n) => html`<li>${n}</li>`)}</ul>` : ""}
      ${liveWindow ? "" : html`
        <div class="plotKeyGrid">
          ${keyNumbers(axis, m, speed()).map((k) => html`<span class="plotKeyLabel">${k.label}</span><span class="plotKeyValue">${k.value}</span>`)}
        </div>
      `}
      ${bands.length ? html`
        <table class="plotBandTable">
          <thead><tr><th>Speed</th><th>Engaged</th><th>Response</th><th>Error (RMS)</th><th>Bias</th></tr></thead>
          <tbody>
            ${bands.map((b) => html`<tr><td>${b.label}</td><td>${b.time}</td><td>${b.gain}</td><td>${b.rmse}</td><td>${b.bias}</td></tr>`)}
          </tbody>
        </table>
      ` : ""}
      ${!liveWindow && axis === "lateral" ? TurnTables(m) : ""}
    </div>
  `
}

// ---------------------------------------------------------------------------------------------------------------
// Blocks

function RecordingStatus() {
  const live = state.live
  const rec = live?.recording
  if (rec) {
    return html`<span class="plotRecording"><i class="plotRecDot"></i>Recording ${fmtDuration(rec.elapsed_s)} · ${rec.rows} samples</span>`
  }
  if (live && !live.isOnroad) {
    return html`<span class="plotMuted">The car is offroad; samples are captured once it is onroad.</span>`
  }
  return ""
}

function StatusGrid() {
  const live = state.live || {}
  const latest = state.latest
  return html`
    <div class="plotStatusGrid">
      <p><strong>Onroad:</strong> ${live.isOnroad ? "Yes" : "No"}</p>
      <p><strong>Last sample:</strong> ${live.sampleAgeSeconds == null ? "none yet" : `${fmtNum(live.sampleAgeSeconds, 1)} s ago`}</p>
      <p><strong>Speed:</strong> ${latest ? fmtSpeed(latest.v, speed()) : "—"}</p>
      ${state.lateralController ? html`<p><strong>Steering controller:</strong> ${controllerName(state.lateralController)}</p>` : ""}
      <p><strong>openpilot:</strong> ${!latest ? "—" : latest.enabled
        ? `engaged (steer ${latest.lat_active ? "on" : "off"}, long ${longStateName(latest.long_state)})` : "not engaged"}</p>
    </div>
    ${state.notice ? html`<p class="plotMuted">${state.notice}</p>` : ""}
    ${state.error ? html`<p class="plotError"><strong>Error:</strong> ${state.error}</p>` : ""}
    ${live.lastError ? html`<p class="plotError"><strong>Source error:</strong> ${live.lastError}</p>` : ""}
  `
}

function RecordingCard() {
  return html`
    <section class="plotCard plotStatusCard">
      <p class="plotDescription">
        With <strong>Record every drive</strong> on, recording starts by itself when the car goes onroad. Everything
        openpilot asks for and what the car does is saved at 20 Hz until 30 s after the car goes offroad (or you press
        Stop), then analyzed. Recordings live on the device; the oldest automatic ones are removed after 20.
      </p>
      <label class="plotToggle">
        <input type="checkbox" checked="${() => state.live?.settings?.auto_record !== false}" disabled="${() => state.busy}"
               @change="${(e) => setAutoRecord(e.target.checked)}">
        Record every drive, and copy the moments into the drive's logs for later review
      </label>
      <div class="plotActions">
        ${state.recActive
          ? html`<button class="plotButton plotButtonStop" disabled="${() => state.busy}" @click="${stopRecording}">Stop recording</button>`
          : html`<button class="plotButton" disabled="${() => state.busy}" @click="${startRecording}">Start recording</button>`}
        ${() => inline(RecordingStatus())}
      </div>
      ${() => inline(StatusGrid())}
    </section>
  `
}

function LiveAnalysis() {
  const live = state.live || {}
  const la = live.liveAnalysis
  return html`
    ${live.stale && !state.loading ? html`<p class="plotMuted">No live data — openpilot is not running or the car is offroad.</p>` : ""}
    <div class="qualitySummaryGrid">
      ${la ? AnalysisBlock("Steering", "lateral", la.lateral, true) : ""}
      ${la ? AnalysisBlock("Speed control", "longitudinal", la.longitudinal, true) : ""}
    </div>
  `
}

function LiveCharts() {
  return html`${state.liveCharts.map((c) => ChartCard(c))}`
}

function LiveSection() {
  return html`
    <section class="plotCard plotStatusCard">
      <div class="plotCardHeader">
        <h2>Live (last 30 s)</h2>
        <div class="plotActions plotActionsInline">
          <button class="plotButton" @click="${togglePaused}">${state.paused ? "Resume" : "Pause"}</button>
          <button class="plotButton" @click="${toggleAdvancedTerms}">${state.showAdvancedTerms ? "Hide controller terms" : "Show controller terms"}</button>
        </div>
      </div>
      ${() => inline(LiveAnalysis())}
      <p class="qualityMethodNote">${HELP_TEXT}</p>
    </section>
    <div class="plotCharts">${() => inline(LiveCharts())}</div>
  `
}

function SessionList() {
  const all = state.sessions
  const shown = state.showAllSessions ? all : all.slice(0, SESSION_LIST_SHORT)
  return html`
    <section class="plotCard plotStatusCard">
      <h2>Saved drives</h2>
      ${all.length ? html`
        <p class="plotMuted">Tap a drive to see its analysis and charts.</p>
        <div class="plotSessionList">
          ${shown.map((s) => html`
            <button class="plotSessionRow ${s.id === state.selectedId ? "selected" : ""}" @click="${() => openSession(s.id, { scroll: true })}">
              <span class="plotSessionHead">
                <strong>${fmtDate(s.started_at)}</strong>
                <span class="plotMuted">${s.duration_s == null ? "" : `${fmtDuration(s.duration_s)} · `}${statusLabel(s.status)}${s.stop_reason ? ` (${s.stop_reason})` : ""}</span>
              </span>
              ${s.lateral_summary ? html`<span class="plotSessionSummary">${s.lateral_summary}</span>` : ""}
              ${s.longitudinal_summary ? html`<span class="plotSessionSummary">${s.longitudinal_summary}</span>` : ""}
              ${s.error ? html`<span class="plotError">${s.error}</span>` : ""}
            </button>
          `)}
        </div>
        ${all.length > SESSION_LIST_SHORT ? html`
          <div class="plotActions">
            <button class="plotButton" @click="${() => { state.showAllSessions = !state.showAllSessions }}">
              ${state.showAllSessions ? "Show recent only" : `Show all ${all.length} drives`}
            </button>
          </div>
        ` : ""}
      ` : html`<p class="plotMuted">No saved drives yet. Start a recording before your next drive.</p>`}
    </section>
  `
}

function MomentsList(a, meta) {
  const rows = eventRows(a, meta, speed())
  return html`
    <div class="qualitySummaryRow plotMoments">
      <p class="qualitySentence">Moments to check</p>
      ${rows.length ? html`
        <p class="plotMuted">Tap a moment to open the charts there.</p>
        <div class="plotMomentList">
          ${rows.map((e) => html`
            <button class="plotMoment ${e.kind}" @click="${() => zoomTo(e.t, e.title)}">
              <span class="plotMomentHead"><strong>${e.title}</strong><span class="plotMuted">${e.clock ? `${e.clock} · ` : ""}${e.into} in</span></span>
              <span class="plotMomentDetail">${e.detail}</span>
            </button>
          `)}
        </div>
      ` : html`<p class="plotMuted">No hard brakes, overridden braking, take-overs or tight-turn overshoots this drive.</p>`}
    </div>
  `
}

function SessionDetail() {
  if (!state.selectedId) return ""
  const d = state.detail
  const a = d?.analysis
  const m = d?.meta || {}
  const overview = a ? buildOverviewCharts(a.overview, { speed: speed() }) : []
  const groups = tuneGroups(m)
  const tuneCount = groups.reduce((n, g) => n + g.rows.length, 0)
  const controller = a?.controller || m.lateral_controller
  return html`
    <section class="plotCard plotStatusCard plotDetail">
      <div class="plotCardHeader">
        <h2>Drive ${fmtDate(m.started_at)}</h2>
        <div class="plotActions plotActionsInline">
          ${m.status === "done" ? html`<a class="plotButton" href="${sessionUrl(state.selectedId, "/download")}">Download CSV</a>` : ""}
          ${m.status && m.status !== "recording" ? html`<button class="plotButton plotButtonStop" @click="${() => deleteSession(state.selectedId)}">Delete</button>` : ""}
          <button class="plotButton" @click="${closeSession}">Close</button>
        </div>
      </div>
      ${state.detailError ? html`<p class="plotError">${state.detailError}</p>` : ""}
      ${!d && !state.detailError ? html`<p class="plotMuted">Loading...</p>` : ""}
      ${d && !a ? html`<p class="plotMuted">${m.status === "recording" ? "Still recording." : m.status === "error" ? `Analysis failed: ${m.error || ""}` : "Analyzing..."}</p>` : ""}
      ${a ? html`
        <div class="plotStatusGrid">
          <p><strong>Duration:</strong> ${fmtDuration(a.duration_s)}</p>
          <p><strong>Disengagements:</strong> ${a.disengagements}</p>
          <p><strong>Car:</strong> ${m.car || "—"}</p>
          <p><strong>Software:</strong> ${m.git_branch || "—"} ${m.git_commit ? `@ ${String(m.git_commit).slice(0, 8)}` : ""}</p>
          ${controller ? html`<p><strong>Steering controller:</strong> ${controllerName(controller)}</p>` : ""}
        </div>
        ${a.takeaways?.length ? html`
          <div class="qualitySummaryRow plotTakeaways">
            <p class="qualitySentence">What stands out</p>
            <ul class="plotNotes plotTakeawayList">${a.takeaways.map((n) => html`<li>${n}</li>`)}</ul>
          </div>
        ` : ""}
        ${Array.isArray(a.events) ? MomentsList(a, m) : ""}
        <div class="qualitySummaryGrid">
          ${AnalysisBlock("Steering", "lateral", a.lateral)}
          ${AnalysisBlock("Speed control", "longitudinal", a.longitudinal)}
        </div>
        <details class="plotDetails">
          <summary>How to read these numbers</summary>
          <ul class="plotNotes">${READING_GUIDE.map((n) => html`<li>${n}</li>`)}</ul>
        </details>
        ${tuneCount ? html`
          <details class="plotDetails">
            <summary>Tune in effect for this drive (${tuneCount} settings)</summary>
            ${groups.map((g) => html`
              <p class="plotTableTitle">${g.title}</p>
              ${g.note ? html`<p class="plotMuted">${g.note}</p>` : ""}
              <div class="plotKeyGrid">
                ${g.rows.map((k) => html`<span class="plotKeyLabel">${k.label}</span><span class="plotKeyValue ${k.unused ? "plotUnused" : ""}">${k.value}</span>`)}
              </div>
            `)}
          </details>
        ` : ""}
        <p class="qualityMethodNote">${a.method}</p>
      ` : ""}
    </section>
    ${overview.length ? html`
      <p class="plotMuted">Tap a chart to zoom into ${2 * ZOOM_HALF_WINDOW_S} s at full resolution.</p>
      <div class="plotCharts">${overview.map((c) => ChartCard(c, zoomAt))}</div>
    ` : ""}
    ${state.zoom ? html`
      <section class="plotCard plotStatusCard plotZoom">
        <div class="plotCardHeader">
          <h2>${state.zoom.label ? `${state.zoom.label}: ` : "Zoom "}${fmtDuration(state.zoom.start)} – ${fmtDuration(state.zoom.end)}</h2>
          <button class="plotButton" @click="${() => { state.zoom = null }}">Close zoom</button>
        </div>
      </section>
      <div class="plotCharts">${state.zoom.charts.map((c) => ChartCard(c))}</div>
    ` : ""}
  `
}

// arrow-core keeps a rendered template when its static strings match and only re-runs function slots, so a
// block whose shape changes (empty list -> rows, recording -> idle) would keep the stale DOM. A root whose markup
// carries a fresh revision forces the block to re-render, the same trick bluetooth.js uses.
let renderRevision = 0
function fresh(block, cls = "plotBlock") {
  renderRevision += 1
  return html([`<div class="${cls}" data-rev="${renderRevision}">`, "</div>"], block)
}
const inline = (block) => fresh(block, "plotInline")

async function initialize() {
  try {
    state.showAdvancedTerms = localStorage.getItem(ADVANCED_TERMS_KEY) === "1"
  } catch (error) {
    state.showAdvancedTerms = false
  }

  try {
    await Promise.all([fetchLiveData(), fetchSessions()])
  } catch (error) {
    state.error = error?.message || String(error)
    state.loading = false
  } finally {
    ensurePolling()
  }

  if (!visibilityListenerAttached) {
    visibilityListenerAttached = true
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState !== "visible") {
        stopPolling()
        return
      }
      if (isPlotsRouteActive() && !state.paused) ensurePolling()
    })
  }
}

export function LivePlots() {
  if (!initialized) {
    initialized = true
    initialize()
  }
  if (!state.paused) {
    ensurePolling()
  }

  return html`
    <div class="plotsPage">
      <h1>Plots</h1>
      ${() => fresh(RecordingCard())}
      ${() => fresh(SessionList())}
      ${() => fresh(SessionDetail())}
      ${() => fresh(LiveSection())}
      ${() => state.loading ? html`<p>Loading live data...</p>` : ""}
    </div>
  `
}
