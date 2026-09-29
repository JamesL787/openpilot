import { api, showSnackbar } from "../api.js"
import { usePolling } from "../composables.js"
import { GalaxyConfirm } from "../components/GalaxyModal.js"
import {
  HELP_TEXT, LIVE_POLL_MS, LiveBuffer, READING_GUIDE, ZOOM_HALF_WINDOW_S,
  buildOverviewCharts, buildTrackingCharts, controllerName, eventRows, fmtDate, fmtDuration, fmtNum, fmtSpeed, keyNumbers,
  clampRange, longStateName, panRange, rangeSelect, sessionUrl, speedBandRows, speedUnit, statusLabel, toSeries, tuneGroups, turnRows,
  zoomBand, zoomRange,
} from "/assets/components/tools/drive_plots_shared.mjs"

const ADVANCED_TERMS_KEY = "plotsShowAdvancedTerms"
const SESSIONS_POLL_MS = 5000
const SESSION_LIST_SHORT = 5
const MUTED = "color: var(--text-muted); font-size: var(--fs-xs, 0.8rem);"

// One chart: SVG geometry from drive_plots_shared.buildChart, drawn without a canvas so it scales with the card.
const PlotChart = {
  name: "PlotChart",
  // tappable: a tap emits pick(t). selectable: a sideways drag emits range(t0, t1), ctrl+wheel/pinch emits wheelzoom(f, t).
  // zoom: the zoomed stretch {start, end}, drawn as a band on a whole-drive chart.
  props: {
    chart: { type: Object, required: true },
    tappable: { type: Boolean, default: false },
    selectable: { type: Boolean, default: false },
    zoom: { type: Object, default: null },
  },
  emits: ["pick", "range", "wheelzoom"],
  created() {
    this.gestures = rangeSelect(() => this.chart.geo, {
      onTap: (t) => this.tappable && this.$emit("pick", t),
      onRange: (a, b) => this.$emit("range", a, b),
      onWheelZoom: (f, t) => this.$emit("wheelzoom", f, t),
    })
  },
  computed: {
    yLabels() { return this.chart.geo.empty ? [] : this.chart.geo.grid.filter((g, j) => j % 2 === 0) },
    band() { return zoomBand(this.zoom, this.chart.geo) },
    interactive() { return this.tappable || this.selectable },
  },
  methods: {
    on(kind, e) {
      if (this.selectable) this.gestures[kind](e)
      else if (kind === "up" && this.tappable) this.gestures.up(e)
      else if (kind === "down" && this.tappable) this.gestures.down(e)
    },
    // Labels at the very edge would be clipped if centered on their tick.
    yStyle(l) {
      const p = Number(l.pct)
      return { position: "absolute", left: "4px", top: `${p}%`, transform: `translateY(${p < 5 ? "0" : p > 95 ? "-100%" : "-50%"})`,
               fontSize: "10px", color: "var(--text-muted)", pointerEvents: "none" }
    },
    xStyle(x) {
      const p = Number(x.pct)
      return { position: "absolute", left: `${p}%`, transform: `translateX(${p < 3 ? "0" : p > 97 ? "-100%" : "-50%"})`,
               fontSize: "10px", color: "var(--text-muted)", whiteSpace: "nowrap" }
    },
  },
  template: `
    <section class="gx-card" style="overflow:hidden;">
      <div class="gx-section__header">
        <i class="bi bi-activity"></i>
        <span class="gx-section__title">{{ chart.title }}</span>
        <span v-if="chart.unit" style="margin-left:auto; color: var(--text-muted); font-size: var(--fs-xs, 0.8rem);">{{ chart.unit }}</span>
      </div>
      <div style="padding: var(--sp-2) var(--sp-3) var(--sp-3);">
        <div style="display:flex; gap:12px; flex-wrap:wrap; margin-bottom: var(--sp-2);">
          <span v-for="item in chart.legend" :key="item.label" style="display:inline-flex; align-items:center; gap:4px; font-size: var(--fs-xs, 0.8rem);">
            <i :style="{ width: '12px', height: '3px', borderRadius: '2px', display: 'inline-block', background: item.color }"></i>
            {{ item.label }}<template v-if="item.value">: {{ item.value }}</template>
          </span>
        </div>
        <div v-if="chart.geo.empty" class="gx-empty">Waiting for data...</div>
        <div v-else>
          <div style="position:relative;">
            <svg :viewBox="'0 0 ' + chart.geo.width + ' ' + chart.geo.height" preserveAspectRatio="none"
                 :style="{ width: '100%', height: '180px', display: 'block', cursor: interactive ? 'crosshair' : 'default',
                           touchAction: interactive ? 'pan-y' : 'auto', userSelect: 'none', WebkitUserSelect: 'none',
                           background: 'rgba(0,0,0,0.25)', borderRadius: '6px' }"
                 role="img" :aria-label="chart.title" @pointerdown="on('down', $event)" @pointermove="on('move', $event)"
                 @pointerup="on('up', $event)" @pointercancel="on('cancel', $event)" @wheel="on('wheel', $event)">
              <rect v-for="(s, i) in chart.geo.shade" :key="'s' + i" :x="s.x" y="0" :width="s.w" :height="chart.geo.height" fill="rgba(255,255,255,0.08)"></rect>
              <line v-for="(l, i) in chart.geo.grid" :key="'g' + i" x1="0" :y1="l.y" :x2="chart.geo.width" :y2="l.y"
                    :stroke="l.zero ? 'rgba(255,255,255,0.35)' : 'rgba(255,255,255,0.08)'" :stroke-dasharray="l.zero ? '6 6' : null"
                    vector-effect="non-scaling-stroke"></line>
              <line v-for="(x, i) in chart.geo.xTicks" :key="'x' + i" :x1="x.x" y1="0" :x2="x.x" :y2="chart.geo.height"
                    stroke="rgba(255,255,255,0.08)" vector-effect="non-scaling-stroke"></line>
              <path v-for="p in chart.geo.paths" :key="p.key" :d="p.d" fill="none" :stroke="p.color" stroke-width="2"
                    stroke-linejoin="round" vector-effect="non-scaling-stroke"></path>
            </svg>
            <div v-if="band" :style="{ position: 'absolute', top: 0, height: '180px', left: band.left + '%', width: band.width + '%',
                                       pointerEvents: 'none', background: 'rgba(122,162,247,0.14)',
                                       borderLeft: '1px solid rgba(122,162,247,0.7)', borderRight: '1px solid rgba(122,162,247,0.7)' }"></div>
            <span v-for="(l, i) in yLabels" :key="'yl' + i" :style="yStyle(l)">{{ l.label }}</span>
          </div>
          <div style="position:relative; height:14px; margin-top:2px;">
            <span v-for="(x, i) in chart.geo.xTicks" :key="'xl' + i" :style="xStyle(x)">{{ x.label }}</span>
          </div>
        </div>
        <p v-if="chart.note" style="margin: var(--sp-2) 0 0; color: var(--text-muted); font-size: var(--fs-xs, 0.8rem); line-height:1.5;">{{ chart.note }}</p>
      </div>
    </section>
  `,
}

export const Plots = {
  name: "Plots",
  components: { PlotChart },
  props: { embedded: { type: Boolean, default: false } },
  data() {
    return {
      loading: true,
      error: "",
      notice: "",
      paused: false,
      showAdvancedTerms: false,
      showAllSessions: false,
      showTune: false,
      showGuide: false,
      busy: false,
      live: null,
      latest: null,
      liveCharts: [],
      sessions: [],
      selectedId: "",
      detail: null,
      detailError: "",
      zoom: null,
    }
  },
  created() {
    this.buffer = new LiveBuffer(60)
    this.lastSessionsFetch = 0
    this.helpText = HELP_TEXT
    this.readingGuide = READING_GUIDE
    this.zoomSeconds = 2 * ZOOM_HALF_WINDOW_S
    this.zoomRequest = 0
    this.muted = MUTED
    try {
      this.showAdvancedTerms = localStorage.getItem(ADVANCED_TERMS_KEY) === "1"
    } catch (e) { this.showAdvancedTerms = false }
    this.poll = usePolling(() => this.load(), { interval: LIVE_POLL_MS, enabled: () => !this.paused })
    this.poll.start()
    this.loadSessions().catch(() => {})
  },
  beforeUnmount() { this.poll?.destroy() },
  computed: {
    speed() { return speedUnit(!!this.live?.isMetric) },
    lateralController() { return this.live?.lateralController || null },
    recording() { return this.live?.recording || null },
    statusRows() {
      const live = this.live || {}
      const s = this.latest
      return [
        { label: "Onroad", value: live.isOnroad ? "Yes" : "No" },
        { label: "Last sample", value: live.sampleAgeSeconds == null ? "none yet" : `${fmtNum(live.sampleAgeSeconds, 1)} s ago` },
        { label: "Speed", value: s ? fmtSpeed(s.v, this.speed) : "—" },
        { label: "openpilot", value: !s ? "—" : s.enabled ? `engaged (steer ${s.lat_active ? "on" : "off"}, long ${longStateName(s.long_state)})` : "not engaged" },
        ...(this.lateralController ? [{ label: "Steering controller", value: controllerName(this.lateralController) }] : []),
      ]
    },
    liveBlocks() {
      const la = this.live?.liveAnalysis
      if (!la) return []
      return [
        { title: "Steering", m: la.lateral },
        { title: "Speed control", m: la.longitudinal },
      ]
    },
    visibleSessions() { return this.showAllSessions ? this.sessions : this.sessions.slice(0, SESSION_LIST_SHORT) },
    detailMeta() { return this.detail?.meta || {} },
    analysis() { return this.detail?.analysis || null },
    detailBlocks() {
      const a = this.analysis
      if (!a) return []
      return [
        { title: "Steering", m: a.lateral, numbers: keyNumbers("lateral", a.lateral, this.speed), bands: speedBandRows(a.lateral, this.speed),
          turns: turnRows(a.lateral, this.speed) },
        { title: "Speed control", m: a.longitudinal, numbers: keyNumbers("longitudinal", a.longitudinal, this.speed),
          bands: speedBandRows(a.longitudinal, this.speed), turns: null },
      ]
    },
    tuneGroups() { return tuneGroups(this.detailMeta) },
    tuneCount() { return this.tuneGroups.reduce((n, g) => n + g.rows.length, 0) },
    driveLength() { return this.analysis?.duration_s ?? this.detailMeta.duration_s ?? Infinity },
    detailController() { return this.analysis?.controller || this.detailMeta.lateral_controller || null },
    moments() { return this.analysis && Array.isArray(this.analysis.events) ? eventRows(this.analysis, this.detailMeta, this.speed) : null },
    software() {
      const m = this.detailMeta
      if (!m.git_branch && !m.git_commit) return "—"
      return `${m.git_branch || ""}${m.git_commit ? ` @ ${String(m.git_commit).slice(0, 8)}` : ""}`.trim()
    },
    overviewCharts() { return this.analysis ? buildOverviewCharts(this.analysis.overview, { speed: this.speed }) : [] },
    downloadUrl() { return this.selectedId ? sessionUrl(this.selectedId, "/download") : "" },
  },
  methods: {
    fmtDate,
    fmtDuration,
    controllerName,
    statusLabel,
    async setAutoRecord(on) {
      this.busy = true
      try {
        const payload = await api.setPlotsSettings({ auto_record: !!on })
        if (this.live) this.live = { ...this.live, settings: payload?.settings }
      } catch (e) {
        this.error = e?.message || "Failed to save the setting"
      } finally {
        this.busy = false
      }
    },
    rebuildLive() {
      this.liveCharts = buildTrackingCharts(this.buffer.view(), { advanced: this.showAdvancedTerms, speed: this.speed,
                                                                 controller: this.lateralController })
      this.latest = this.buffer.latest()
    },
    async load() {
      try {
        const payload = await api.getPlotsLive(this.buffer.seq)
        const hadRecording = !!this.live?.recording
        this.live = payload && typeof payload === "object" ? payload : this.live
        this.error = ""
        this.loading = false
        if (this.buffer.ingest(payload)) this.rebuildLive()
        if (hadRecording !== !!payload?.recording || Date.now() - this.lastSessionsFetch > SESSIONS_POLL_MS) {
          this.loadSessions().catch(() => {})
        }
      } catch (e) {
        this.error = e?.message || "Failed to load live plot data"
        this.loading = false
        throw e
      }
    },
    async loadSessions() {
      this.lastSessionsFetch = Date.now()
      const payload = await api.getPlotsSessions()
      this.sessions = Array.isArray(payload?.sessions) ? payload.sessions : []
      const selected = this.sessions.find((s) => s.id === this.selectedId)
      if (selected && this.detail && this.detail.meta?.status !== selected.status) this.openSession(selected.id)
    },
    async startRecording() {
      this.busy = true
      this.notice = ""
      try {
        await api.startPlotsRecording()
        showSnackbar("Recording started.")
        await this.load()
      } catch (e) {
        showSnackbar(e?.message || "Could not start recording", "error")
      } finally {
        this.busy = false
      }
    },
    async stopRecording() {
      this.busy = true
      try {
        const payload = await api.stopPlotsRecording()
        await this.load()
        if (payload?.stopped?.discarded) {
          this.notice = "Nothing was recorded (openpilot was not running), so no drive was saved."
          showSnackbar("Nothing was recorded.", "error")
        } else {
          showSnackbar("Recording stopped. Analyzing the drive...")
          await this.loadSessions()
          if (payload?.stopped?.id) this.openSession(payload.stopped.id, { scroll: true })
        }
      } catch (e) {
        showSnackbar(e?.message || "Could not stop recording", "error")
      } finally {
        this.busy = false
      }
    },
    async openSession(id, { scroll = false } = {}) {
      this.selectedId = id
      this.detailError = ""
      this.closeZoom()
      this.showTune = false
      try {
        this.detail = await api.getPlotsSession(id)
      } catch (e) {
        this.detail = null
        this.detailError = e?.message || String(e)
      }
      if (scroll) this.$nextTick(() => this.$refs.detail?.scrollIntoView({ behavior: "smooth", block: "start" }))
    },
    closeSession() {
      this.selectedId = ""
      this.detail = null
      this.closeZoom()
    },
    async deleteSession(id) {
      const ok = await GalaxyConfirm({ title: "Delete saved drive?", message: "This cannot be undone.", confirmLabel: "Delete", danger: true })
      if (!ok) return
      try {
        await api.deletePlotsSession(id)
        if (this.selectedId === id) this.closeSession()
        await this.loadSessions()
        showSnackbar("Drive deleted.")
      } catch (e) {
        showSnackbar(e?.message || "Delete failed", "error")
      }
    },
    // Full-resolution charts for [start, end] (seconds into the drive). A newer request wins over a slower older
    // one, so a quick run of pan/zoom presses settles on the last one pressed.
    async showRange(start, end, label = "") {
      if (!this.selectedId) return
      const r = clampRange(start, end, this.driveLength)
      const id = ++this.zoomRequest
      const opening = !this.zoom
      try {
        const payload = await api.getPlotsSessionWindow(this.selectedId, r.start, r.end)
        if (id !== this.zoomRequest) return
        const series = toSeries(payload.columns, payload.rows)
        this.zoom = { start: r.start, end: r.end, label, charts: buildTrackingCharts(series, { advanced: this.showAdvancedTerms,
                      tMin: r.start, tMax: r.end, speed: this.speed, controller: this.detailController }) }
        if (opening) this.$nextTick(() => this.$refs.zoom?.scrollIntoView({ behavior: "smooth", block: "start" }))
      } catch (e) {
        if (id === this.zoomRequest) this.detailError = e?.message || String(e)
      }
    },
    // A minute around t, from a chart tap or a moment in the list.
    zoomAt(t, label = "") {
      return this.showRange(t - ZOOM_HALF_WINDOW_S, t + ZOOM_HALF_WINDOW_S, label)
    },
    closeZoom() {
      this.zoomRequest++
      this.zoom = null
    },
    zoomBy(factor, at = null) {
      if (!this.zoom) return
      const r = zoomRange(this.zoom, factor, this.driveLength, at)
      this.showRange(r.start, r.end, this.zoom.label)
    },
    panBy(frac) {
      if (!this.zoom) return
      const r = panRange(this.zoom, frac, this.driveLength)
      this.showRange(r.start, r.end, this.zoom.label)
    },
    overviewWheel(f, t) {
      if (this.zoom) this.zoomBy(f, t)
      else this.zoomAt(t)
    },
    togglePaused() {
      this.paused = !this.paused
      if (this.paused) return
      this.load().catch((e) => {
        this.error = e?.message || "Failed to resume live data"
      })
      if (this.poll) this.poll.start()
    },
    toggleAdvancedTerms() {
      this.showAdvancedTerms = !this.showAdvancedTerms
      try {
        localStorage.setItem(ADVANCED_TERMS_KEY, this.showAdvancedTerms ? "1" : "0")
      } catch (e) { console.warn("Failed to persist plots advanced terms preference", e) }
      this.rebuildLive()
    },
  },
  template: `
    <div class="gx-view">
      <h2 v-if="!embedded" style="margin-top:0;">Plots</h2>

      <section class="gx-card">
        <div class="gx-section__header">
          <i class="bi bi-record-circle"></i>
          <span class="gx-section__title">Drive recording</span>
        </div>
        <div style="padding: var(--sp-3);">
          <p style="color: var(--text-muted); line-height:1.6; margin:0 0 var(--sp-3);">
            With Record every drive on, recording starts by itself when the car goes onroad. What openpilot asks for and
            what the car does is saved at 20 Hz until 30 s after the car goes offroad (or you press Stop), then analyzed.
            Recordings stay on the device; the oldest automatic ones are removed after 20.
          </p>
          <label style="display:flex; gap:8px; align-items:center; margin:0 0 var(--sp-3); cursor:pointer;">
            <input type="checkbox" :checked="live?.settings?.auto_record !== false" :disabled="busy"
                   @change="setAutoRecord($event.target.checked)">
            <span>Record every drive, and copy the moments into the drive's logs for later review</span>
          </label>
          <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
            <button v-if="recording" type="button" class="gx-btn gx-btn--danger" :disabled="busy" @click="stopRecording">
              <i class="bi bi-stop-fill"></i> Stop recording
            </button>
            <button v-else type="button" class="gx-btn" :disabled="busy" @click="startRecording">
              <i class="bi bi-record-fill"></i> Start recording
            </button>
            <span v-if="recording" style="display:inline-flex; align-items:center; gap:6px; font-weight: var(--fw-bold, 600);">
              <i class="bi bi-circle-fill" style="color:#e05577; font-size:10px;"></i>
              {{ fmtDuration(recording.elapsed_s) }} · {{ recording.rows }} samples
            </span>
            <span v-else-if="live && !live.isOnroad" :style="muted">
              Offroad; samples are captured once the car is onroad.
            </span>
          </div>
          <p v-if="notice" :style="muted + ' margin: var(--sp-2) 0 0;'">{{ notice }}</p>

          <div v-if="loading" class="gx-loading" style="margin-top: var(--sp-3);">Loading live data...</div>
          <div v-if="error" class="gx-alert gx-alert--warn" style="border:none; margin: var(--sp-3) 0 0;">
            <i class="bi bi-exclamation-triangle-fill gx-alert__icon"></i>
            <div class="gx-alert__body"><strong>Error:</strong> <span>{{ error }}</span></div>
          </div>
          <div v-if="live?.lastError" class="gx-alert gx-alert--warn" style="margin: var(--sp-3) 0 0;">
            <i class="bi bi-exclamation-triangle gx-alert__icon"></i>
            <div class="gx-alert__body"><strong>Source error:</strong> <span>{{ live.lastError }}</span></div>
          </div>

          <div style="margin-top: var(--sp-3);">
            <div v-for="(row, i) in statusRows" :key="row.label" class="gx-row" :style="i === 0 ? 'border-top:none;' : ''">
              <span class="gx-row__label">{{ row.label }}</span><span class="gx-row__value">{{ row.value }}</span>
            </div>
          </div>
        </div>
      </section>

      <section class="gx-card" style="margin-top: var(--sp-3);">
        <div class="gx-section__header">
          <i class="bi bi-collection"></i>
          <span class="gx-section__title">Saved drives</span>
        </div>
        <div v-if="!sessions.length" class="gx-empty">No saved drives yet. Start a recording before your next drive.</div>
        <p v-else :style="muted + ' margin: var(--sp-2) var(--sp-3) 0;'">Tap a drive to see its analysis and charts.</p>
        <button v-for="s in visibleSessions" :key="s.id" type="button" class="gx-row"
                :style="{ display: 'block', width: '100%', textAlign: 'left', background: s.id === selectedId ? 'rgba(122,162,247,0.12)' : 'transparent', border: 'none', color: 'inherit', cursor: 'pointer' }"
                @click="openSession(s.id, { scroll: true })">
          <span style="display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap;">
            <strong>{{ fmtDate(s.started_at) }}</strong>
            <span :style="muted">
              {{ s.duration_s == null ? '' : fmtDuration(s.duration_s) + ' · ' }}{{ statusLabel(s.status) }}{{ s.stop_reason ? ' (' + s.stop_reason + ')' : '' }}
            </span>
          </span>
          <span v-if="s.lateral_summary" style="display:block; font-size: var(--fs-xs, 0.8rem); margin-top:2px;">{{ s.lateral_summary }}</span>
          <span v-if="s.longitudinal_summary" style="display:block; font-size: var(--fs-xs, 0.8rem);">{{ s.longitudinal_summary }}</span>
          <span v-if="s.error" style="display:block; font-size: var(--fs-xs, 0.8rem); color:#e05577;">{{ s.error }}</span>
        </button>
        <div v-if="sessions.length > 5" style="padding: var(--sp-2) var(--sp-3) var(--sp-3);">
          <button type="button" class="gx-btn gx-btn--tonal" @click="showAllSessions = !showAllSessions">
            {{ showAllSessions ? 'Show recent only' : 'Show all ' + sessions.length + ' drives' }}
          </button>
        </div>
      </section>

      <section v-if="selectedId" ref="detail" class="gx-card" style="margin-top: var(--sp-3);">
        <div class="gx-section__header">
          <i class="bi bi-clipboard-data"></i>
          <span class="gx-section__title">Drive {{ fmtDate(detailMeta.started_at) }}</span>
        </div>
        <div style="padding: var(--sp-3);">
          <div style="display:flex; gap:8px; flex-wrap:wrap; margin-bottom: var(--sp-3);">
            <a v-if="detailMeta.status === 'done'" class="gx-btn gx-btn--tonal" :href="downloadUrl"><i class="bi bi-download"></i> CSV</a>
            <button v-if="detailMeta.status && detailMeta.status !== 'recording'" type="button" class="gx-btn gx-btn--tonal" @click="deleteSession(selectedId)">
              <i class="bi bi-trash"></i> Delete
            </button>
            <button type="button" class="gx-btn gx-btn--tonal" @click="closeSession"><i class="bi bi-x-lg"></i> Close</button>
          </div>
          <div v-if="detailError" class="gx-alert gx-alert--warn" style="margin:0 0 var(--sp-2);">
            <i class="bi bi-exclamation-triangle gx-alert__icon"></i>
            <div class="gx-alert__body"><span>{{ detailError }}</span></div>
          </div>
          <div v-if="!detail && !detailError" class="gx-loading">Loading...</div>
          <p v-else-if="detail && !analysis" style="color: var(--text-muted); margin:0;">
            {{ detailMeta.status === 'recording' ? 'Still recording.' : detailMeta.status === 'error' ? 'Analysis failed: ' + (detailMeta.error || '') : 'Analyzing...' }}
          </p>
          <template v-if="analysis">
            <div class="gx-row" style="border-top:none;"><span class="gx-row__label">Duration</span><span class="gx-row__value">{{ fmtDuration(analysis.duration_s) }}</span></div>
            <div class="gx-row"><span class="gx-row__label">Disengagements</span><span class="gx-row__value">{{ analysis.disengagements }}</span></div>
            <div class="gx-row"><span class="gx-row__label">Car</span><span class="gx-row__value">{{ detailMeta.car || '—' }}</span></div>
            <div class="gx-row"><span class="gx-row__label">Software</span><span class="gx-row__value" style="overflow-wrap:anywhere;">{{ software }}</span></div>
            <div v-if="detailController" class="gx-row"><span class="gx-row__label">Steering controller</span><span class="gx-row__value">{{ controllerName(detailController) }}</span></div>
            <div v-if="analysis.takeaways && analysis.takeaways.length" style="margin-top: var(--sp-3); padding: var(--sp-2) var(--sp-3); border:1px solid rgba(122,162,247,0.5); border-radius:8px;">
              <p style="margin:0; font-weight: var(--fw-bold, 600);">What stands out</p>
              <ul style="margin: 4px 0 0; padding-left: 1.2em; line-height:1.5; font-size: var(--fs-sm, 0.9rem);">
                <li v-for="n in analysis.takeaways" :key="n">{{ n }}</li>
              </ul>
            </div>
            <div v-if="moments" style="margin-top: var(--sp-3);">
              <p style="margin:0; font-weight: var(--fw-bold, 600);">Moments to check</p>
              <p v-if="!moments.length" :style="muted + ' margin: 2px 0 0;'">No hard brakes, overridden braking, take-overs or tight-turn overshoots this drive.</p>
              <template v-else>
                <p :style="muted + ' margin: 2px 0 var(--sp-2);'">Tap a moment to open the charts there.</p>
                <div style="display:grid; gap:6px; max-height: 420px; overflow-y:auto;">
                  <button v-for="(e, i) in moments" :key="'m' + i" type="button" @click="zoomAt(e.t, e.title)"
                          :style="{ textAlign: 'left', padding: '8px 10px', borderRadius: '8px', cursor: 'pointer', color: 'inherit',
                                    background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.1)',
                                    borderLeft: '3px solid ' + (e.kind === 'brake' ? '#f7768e' : '#7aa2f7') }">
                    <span style="display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap;">
                      <strong style="font-size: var(--fs-sm, 0.9rem);">{{ e.title }}</strong>
                      <span :style="muted">{{ e.clock ? e.clock + ' · ' : '' }}{{ e.into }} in</span>
                    </span>
                    <span style="display:block; font-size: var(--fs-xs, 0.8rem); line-height:1.5; margin-top:2px;">{{ e.detail }}</span>
                  </button>
                </div>
              </template>
            </div>
            <div v-for="b in detailBlocks" :key="b.title" style="margin-top: var(--sp-3);">
              <p style="margin:0; font-weight: var(--fw-bold, 600);">{{ b.title }}</p>
              <p style="margin:2px 0 0;">{{ b.m.summary }}</p>
              <ul v-if="b.m.notes && b.m.notes.length" style="margin: 4px 0 0; padding-left: 1.2em; color: var(--text-muted); font-size: var(--fs-xs, 0.8rem); line-height:1.5;">
                <li v-for="n in b.m.notes" :key="n">{{ n }}</li>
              </ul>
              <div v-for="k in b.numbers" :key="k.label" class="gx-row">
                <span class="gx-row__label">{{ k.label }}</span><span class="gx-row__value">{{ k.value }}</span>
              </div>
              <table v-if="b.bands.length" style="border-collapse:collapse; font-size: var(--fs-xs, 0.8rem); margin-top: var(--sp-2); width:100%;">
                <thead><tr style="color: var(--text-muted); text-align:left;"><th>Speed</th><th>Engaged</th><th>Response</th><th>Error</th><th>Bias</th></tr></thead>
                <tbody>
                  <tr v-for="row in b.bands" :key="row.label">
                    <td>{{ row.label }}</td><td>{{ row.time }}</td><td>{{ row.gain }}</td><td>{{ row.rmse }}</td><td>{{ row.bias }}</td>
                  </tr>
                </tbody>
              </table>
              <template v-if="b.turns && b.turns.bins.length">
                <p :style="muted + ' margin: var(--sp-2) 0 2px;'">Tight turns (wheel past 45°), steering-wheel degrees</p>
                <table style="border-collapse:collapse; font-size: var(--fs-xs, 0.8rem); width:100%;">
                  <thead><tr style="color: var(--text-muted); text-align:left;"><th>Speed</th><th>Time</th><th>Off by</th><th>Past</th><th>Behind</th><th>Limit</th></tr></thead>
                  <tbody>
                    <tr v-for="row in b.turns.bins" :key="row.label">
                      <td>{{ row.label }}</td><td>{{ row.time }}</td><td>{{ row.err }}</td><td>{{ row.past }}</td><td>{{ row.trail }}</td><td>{{ row.limit }}</td>
                    </tr>
                  </tbody>
                </table>
                <p v-if="b.turns.scorecard" :style="muted + ' margin: 2px 0 0; font-size: var(--fs-xs, 0.8rem);'">Leaves out the second after you let go. Counting it, as the agents' scorecard does: {{ b.turns.scorecard }}.</p>
              </template>
              <template v-if="b.turns && b.turns.wobble.length">
                <p :style="muted + ' margin: var(--sp-2) 0 2px;'">Wheel wobble on near-straight road</p>
                <table style="border-collapse:collapse; font-size: var(--fs-xs, 0.8rem); width:100%;">
                  <thead><tr style="color: var(--text-muted); text-align:left;"><th>Speed</th><th>Time</th><th>Wobble (RMS)</th></tr></thead>
                  <tbody>
                    <tr v-for="row in b.turns.wobble" :key="row.label"><td>{{ row.label }}</td><td>{{ row.time }}</td><td>{{ row.rms }}</td></tr>
                  </tbody>
                </table>
              </template>
            </div>
            <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top: var(--sp-3);">
              <button type="button" class="gx-btn gx-btn--tonal" @click="showGuide = !showGuide">
                <i class="bi bi-question-circle"></i> {{ showGuide ? 'Hide guide' : 'How to read these numbers' }}
              </button>
              <button v-if="tuneCount" type="button" class="gx-btn gx-btn--tonal" @click="showTune = !showTune">
                <i class="bi bi-sliders"></i> {{ showTune ? 'Hide tune' : 'Tune for this drive (' + tuneCount + ')' }}
              </button>
            </div>
            <ul v-if="showGuide" style="margin: var(--sp-2) 0 0; padding-left: 1.2em; color: var(--text-muted); font-size: var(--fs-xs, 0.8rem); line-height:1.5;">
              <li v-for="n in readingGuide" :key="n">{{ n }}</li>
            </ul>
            <div v-if="showTune" style="margin-top: var(--sp-2);">
              <template v-for="g in tuneGroups" :key="g.title">
                <p style="margin: var(--sp-2) 0 0; font-weight: var(--fw-bold, 600);">{{ g.title }}</p>
                <p v-if="g.note" :style="muted + ' margin: 2px 0 0; line-height:1.5;'">{{ g.note }}</p>
                <div v-for="k in g.rows" :key="k.label" class="gx-row">
                  <span class="gx-row__label">{{ k.label }}</span>
                  <span class="gx-row__value" :style="{ overflowWrap: 'anywhere', opacity: k.unused ? 0.55 : 1 }">{{ k.value }}</span>
                </div>
              </template>
            </div>
            <p :style="muted + ' margin: var(--sp-3) 0 0; line-height:1.6;'">{{ analysis.method }}</p>
          </template>
        </div>
      </section>

      <template v-if="selectedId && overviewCharts.length">
        <p :style="muted + ' margin: var(--sp-3) 0 0;'">Drag sideways across a chart to zoom into that stretch, or tap for {{ zoomSeconds }} s around a spot.</p>
        <div style="display:grid; gap: var(--sp-3); margin-top: var(--sp-2);">
          <PlotChart v-for="c in overviewCharts" :key="'o' + c.id" :chart="c" tappable selectable :zoom="zoom"
                     @pick="zoomAt" @range="(a, b) => showRange(a, b)" @wheelzoom="overviewWheel"></PlotChart>
        </div>
      </template>

      <template v-if="zoom">
        <div ref="zoom" style="margin-top: var(--sp-3);">
          <strong>{{ zoom.label ? zoom.label + ':' : 'Zoom' }} {{ fmtDuration(zoom.start) }} – {{ fmtDuration(zoom.end) }}</strong>
          <div style="display:flex; flex-wrap:wrap; gap:8px; margin-top: var(--sp-2);">
            <button type="button" class="gx-btn gx-btn--tonal" aria-label="Earlier" @click="panBy(-0.5)"><i class="bi bi-chevron-left"></i></button>
            <button type="button" class="gx-btn gx-btn--tonal" aria-label="Zoom out" @click="zoomBy(2)"><i class="bi bi-zoom-out"></i></button>
            <button type="button" class="gx-btn gx-btn--tonal" aria-label="Zoom in" @click="zoomBy(0.5)"><i class="bi bi-zoom-in"></i></button>
            <button type="button" class="gx-btn gx-btn--tonal" aria-label="Later" @click="panBy(0.5)"><i class="bi bi-chevron-right"></i></button>
            <button type="button" class="gx-btn gx-btn--tonal" @click="closeZoom"><i class="bi bi-x-lg"></i> Close zoom</button>
          </div>
          <p :style="muted + ' margin: var(--sp-2) 0 0;'">Drag across a chart below to zoom in further.</p>
        </div>
        <div style="display:grid; gap: var(--sp-3); margin-top: var(--sp-2);">
          <PlotChart v-for="c in zoom.charts" :key="'z' + c.id" :chart="c" selectable
                     @range="(a, b) => showRange(a, b, zoom.label)" @wheelzoom="zoomBy"></PlotChart>
        </div>
      </template>

      <section class="gx-card" style="margin-top: var(--sp-3);">
        <div class="gx-section__header">
          <i class="bi bi-graph-up-arrow"></i>
          <span class="gx-section__title">Live (last {{ live?.liveWindowSeconds || 30 }} s)</span>
        </div>
        <div style="padding: var(--sp-3);">
          <p v-if="live?.stale && !loading" style="color: var(--text-muted); margin:0 0 var(--sp-2);">
            No live data — openpilot is not running or the car is offroad.
          </p>
          <div v-for="b in liveBlocks" :key="b.title" style="margin-bottom: var(--sp-2);">
            <p style="margin:0; font-weight: var(--fw-bold, 600);">{{ b.title }}</p>
            <p style="margin:2px 0 0;">{{ b.m.summary }}</p>
            <ul v-if="b.m.notes && b.m.notes.length" style="margin: 4px 0 0; padding-left: 1.2em; color: var(--text-muted); font-size: var(--fs-xs, 0.8rem); line-height:1.5;">
              <li v-for="n in b.m.notes" :key="n">{{ n }}</li>
            </ul>
          </div>
          <p :style="muted + ' margin: var(--sp-2) 0 0; line-height:1.6;'">{{ helpText }}</p>
          <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top: var(--sp-3);">
            <button type="button" class="gx-btn gx-btn--tonal" @click="togglePaused">
              <i class="bi" :class="paused ? 'bi-play-fill' : 'bi-pause-fill'"></i> {{ paused ? 'Resume' : 'Pause' }}
            </button>
            <button type="button" class="gx-btn gx-btn--tonal" @click="toggleAdvancedTerms">
              <i class="bi" :class="showAdvancedTerms ? 'bi-eye-slash' : 'bi-sliders'"></i>
              {{ showAdvancedTerms ? 'Hide controller terms' : 'Show controller terms' }}
            </button>
          </div>
        </div>
      </section>

      <div style="display:grid; gap: var(--sp-3); margin-top: var(--sp-3);">
        <PlotChart v-for="c in liveCharts" :key="'l' + c.id" :chart="c"></PlotChart>
      </div>
    </div>
  `,
}
