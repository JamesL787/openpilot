// Shared, DOM-free helpers for the Plots page (classic and mobile).
// The server (drive_plots.py) does all scoring; this file only buffers rows and turns them into SVG geometry.

export const LIVE_POLL_MS = 500
export const LIVE_VIEW_SECONDS = 30
export const ZOOM_HALF_WINDOW_S = 30
export const CHART_W = 1000
export const CHART_H = 220

export const LINE_COLORS = {
  desired: "#7aa2f7",
  actual: "#9ece6a",
  speed: "#e0af68",
  p: "#63b3ff",
  i: "#63d79d",
  d: "#f0b35e",
  f: "#d08bff",
  lead: "#f7768e",
}

const LONG_STATE_NAMES = ["off", "pid", "stopping", "starting"]

export function toNumber(value, fallback = 0) {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

export function fmtNum(value, digits = 2) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—"
  return Number(value).toFixed(digits)
}

export function fmtDuration(seconds) {
  const s = Math.max(0, Math.round(toNumber(seconds)))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h) return `${h}h ${String(m).padStart(2, "0")}m`
  if (m) return `${m}m ${String(sec).padStart(2, "0")}s`
  return `${sec}s`
}

export function fmtDate(epochSeconds) {
  const v = toNumber(epochSeconds, 0)
  if (!v) return "—"
  return new Date(v * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
}

// Speed display unit from the device's IsMetric setting; samples are stored in m/s.
export function speedUnit(isMetric) {
  return isMetric ? { factor: 3.6, unit: "km/h", floor: 20, distFactor: 1, distUnit: "m" }
    : { factor: 2.23694, unit: "mph", floor: 10, distFactor: 3.28084, distUnit: "ft" }
}
export const DEFAULT_SPEED = speedUnit(false)

export function fmtSpeed(ms, speed = DEFAULT_SPEED, digits = 0) {
  return `${fmtNum(toNumber(ms) * speed.factor, digits)} ${speed.unit}`
}

function speedRange(loMs, hiMs, speed) {
  const lo = Math.round(toNumber(loMs) * speed.factor)
  if (hiMs == null) return `${lo}+ ${speed.unit}`
  const hi = Math.round(toNumber(hiMs) * speed.factor)
  return lo === 0 ? `under ${hi} ${speed.unit}` : `${lo}–${hi} ${speed.unit}`
}

// "Standard (25–50 mph)": the band names match the Low speed / Standard / Highway tune sliders.
export function bandLabel(b, speed = DEFAULT_SPEED) {
  const range = speedRange(b.lo_ms, b.hi_ms, speed)
  return b.name ? `${b.name} (${range})` : range
}

// Which steering controller drove, in words, and whether the Lat*Scale speed-band sliders apply to it.
export const CONTROLLERS = {
  clarity_eps: { name: "James's controller", slidersUsed: false,
                 note: "Fixed P and I gains. The LatP / LatI / LatF speed-band sliders and the Honda PID scales are not used by this controller." },
  nrdr_pid: { name: "NRDR PID", slidersUsed: true,
              note: "Tuned by the LatP / LatI / LatF sliders for Low speed (under 25 mph), Standard (25–50) and Highway (50+)." },
}

export function controllerName(controller) {
  if (!controller) return ""
  return CONTROLLERS[controller]?.name || String(controller)
}

// The P line of the controller-terms chart, which is not the P that reached the wheel under James's controller.
export function termsNote(controller) {
  if (controller !== "clarity_eps") return ""
  return "James's controller: the P line is before its fixed speed-band scale (about ×1.15–1.25), and the output is " +
    "filtered, so P + I + F reads a little below what reached the wheel."
}

export function longStateName(value) {
  return LONG_STATE_NAMES[Math.round(toNumber(value))] || "?"
}

// Column-major view of a {columns, rows} payload.
export function toSeries(columns, rows) {
  const out = {}
  const cols = Array.isArray(columns) ? columns : []
  cols.forEach((name, idx) => { out[name] = (rows || []).map((r) => toNumber(r[idx])) })
  return out
}

// Incremental 20 Hz buffer fed by /api/plots/live?since=<seq>.
export class LiveBuffer {
  constructor(keepSeconds = 60) {
    this.keepSeconds = keepSeconds
    this.reset()
  }

  reset() {
    this.columns = null
    this.rows = []
    this.seq = 0
  }

  // Returns true when new rows arrived.
  ingest(payload) {
    if (!payload || !Array.isArray(payload.columns)) return false
    const seq = toNumber(payload.seq, 0)
    // The recorder restarted (new process): its sequence numbers start over.
    if (seq < this.seq) this.reset()
    this.columns = payload.columns
    const rows = Array.isArray(payload.rows) ? payload.rows : []
    if (!rows.length) return false
    const seqIdx = this.columns.indexOf("seq")
    const fresh = seqIdx < 0 ? rows : rows.filter((r) => toNumber(r[seqIdx]) > this.seq)
    if (!fresh.length) return false
    this.rows.push(...fresh)
    this.seq = Math.max(this.seq, seq)
    const tIdx = this.columns.indexOf("t")
    const lastT = toNumber(this.rows[this.rows.length - 1][tIdx])
    let drop = 0
    while (drop < this.rows.length && toNumber(this.rows[drop][tIdx]) < lastT - this.keepSeconds) drop++
    if (drop) this.rows.splice(0, drop)
    return true
  }

  // Last `seconds` of data, with t relative to the newest sample (so the x axis reads -30 s .. 0 s).
  view(seconds = LIVE_VIEW_SECONDS) {
    if (!this.columns || !this.rows.length) return null
    const s = toSeries(this.columns, this.rows)
    const lastT = s.t[s.t.length - 1]
    const start = s.t.findIndex((t) => t >= lastT - seconds)
    const out = {}
    for (const [k, arr] of Object.entries(s)) out[k] = arr.slice(start)
    out.t = out.t.map((t) => t - lastT)
    return out
  }

  latest() {
    if (!this.columns || !this.rows.length) return null
    const row = this.rows[this.rows.length - 1]
    const out = {}
    this.columns.forEach((name, idx) => { out[name] = toNumber(row[idx]) })
    return out
  }
}

function niceHalfSpan(maxAbs, floor) {
  const raw = Math.max(floor, maxAbs * 1.15)
  const steps = [0.1, 0.2, 0.25, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50]
  return steps.find((s) => s >= raw) || Math.ceil(raw)
}

// Build SVG geometry for one chart.
//   t: x values (seconds). lines: [{key, values, color, cls, label}]. inactive: per-sample 0..1 (1 = in control)
//   used to shade where openpilot was not in control. opts: {floor, zeroBased, tMin, tMax, unit}
export function buildChart(t, lines, inactive, opts = {}) {
  const W = CHART_W
  const H = CHART_H
  const pad = 6
  const n = Array.isArray(t) ? t.length : 0
  if (n < 2) return { empty: true, width: W, height: H }
  const tMin = opts.tMin ?? t[0]
  const tMax = opts.tMax ?? t[n - 1]
  const tSpan = Math.max(1e-6, tMax - tMin)
  let maxAbs = 0
  let maxVal = 0
  for (const line of lines) {
    for (const v of line.values) {
      const x = toNumber(v)
      if (Math.abs(x) > maxAbs) maxAbs = Math.abs(x)
      if (x > maxVal) maxVal = x
    }
  }
  const floor = opts.floor ?? 1
  const zeroBased = !!opts.zeroBased
  const max = zeroBased ? niceHalfSpan(maxVal, floor) : niceHalfSpan(maxAbs, floor)
  const min = zeroBased ? 0 : -max
  const ySpan = max - min
  const xFor = (x) => ((x - tMin) / tSpan) * W
  const yFor = (v) => pad + ((max - Math.max(min, Math.min(max, toNumber(v)))) / ySpan) * (H - 2 * pad)

  // Down-sample to ~2 points per horizontal unit so long windows stay light.
  const stride = Math.max(1, Math.floor(n / (W * 2)))
  const paths = lines.map((line) => {
    // A null value is a gap (no car ahead, for example): the line breaks there instead of dropping to 0.
    let d = ""
    let pen = false
    for (let i = 0; i < n; i += stride) {
      const v = line.values[i]
      if (v === null || v === undefined) { pen = false; continue }
      d += `${pen ? "L" : "M"}${xFor(t[i]).toFixed(1)},${yFor(v).toFixed(1)}`
      pen = true
    }
    return { key: line.key, cls: line.cls || line.key, color: line.color, d }
  })

  // Shade contiguous runs where openpilot was not in control (activity < 0.5), and gaps in the data.
  const shade = []
  if (Array.isArray(inactive)) {
    let runStart = null
    for (let i = 0; i <= n; i++) {
      const off = i < n && toNumber(inactive[i]) < 0.5
      if (off && runStart === null) runStart = i
      if (!off && runStart !== null) {
        const x0 = xFor(t[Math.max(0, runStart - 1)])
        const x1 = xFor(t[Math.min(n - 1, i)])
        shade.push({ x: x0.toFixed(1), w: Math.max(1, x1 - x0).toFixed(1) })
        runStart = null
      }
    }
  }

  const grid = (zeroBased ? [max, max / 2, 0] : [max, max / 2, 0, -max / 2, -max]).map((v) => ({
    y: yFor(v).toFixed(1),
    zero: v === 0,
    label: fmtNum(v, ySpan < 1 ? 2 : 1),
    pct: ((yFor(v) / H) * 100).toFixed(2),
  }))

  const xTicks = []
  const tickStep = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600].find((s) => tSpan / s <= 6) || 7200
  for (let x = Math.ceil(tMin / tickStep) * tickStep; x <= tMax; x += tickStep) {
    xTicks.push({ x: xFor(x).toFixed(1), pct: ((xFor(x) / W) * 100).toFixed(2), label: fmtTick(x, tSpan) })
  }
  // Single-path forms (fixed element count) for renderers that cannot loop inside an <svg>.
  const shadeD = shade.map((s) => `M${s.x},0h${s.w}v${H}h-${s.w}Z`).join("")
  const gridD = grid.filter((l) => !l.zero).map((l) => `M0,${l.y}H${W}`).join("") + xTicks.map((x) => `M${x.x},0V${H}`).join("")
  const zeroD = grid.filter((l) => l.zero).map((l) => `M0,${l.y}H${W}`).join("")
  const slots = [0, 1, 2, 3].map((i) => paths[i] || { key: `empty${i}`, cls: "", color: "none", d: "" })
  return { empty: false, width: W, height: H, paths, slots, shade, shadeD, grid, gridD, zeroD, xTicks, min, max, tMin, tMax,
           unit: opts.unit || "" }
}

function fmtTick(x, span) {
  if (x <= 0 && span <= 120) return `${Math.round(x)}s`
  if (span <= 180) return `${Math.round(x)}s`
  const m = Math.floor(Math.abs(x) / 60)
  const s = Math.round(Math.abs(x) % 60)
  return `${x < 0 ? "-" : ""}${m}:${String(s).padStart(2, "0")}`
}

// Map a click on a chart's SVG to a time value on its x axis.
export function timeAtClick(event, chart) {
  const el = event.currentTarget
  if (!el || !chart || chart.empty) return null
  const rect = el.getBoundingClientRect()
  if (!rect.width) return null
  const frac = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
  return chart.tMin + frac * (chart.tMax - chart.tMin)
}

const LAT_LINES = (s) => [
  { key: "lat_des", values: s.lat_des, color: LINE_COLORS.desired, cls: "desired", label: "Requested" },
  { key: "lat_act", values: s.lat_act, color: LINE_COLORS.actual, cls: "actual", label: "Measured" },
]
const LONG_LINES = (s) => [
  { key: "long_des", values: s.long_des, color: LINE_COLORS.desired, cls: "desired", label: "Requested" },
  { key: "long_act", values: s.long_act, color: LINE_COLORS.actual, cls: "actual", label: "Measured" },
]

// Charts for a column-major series (live view or a zoomed window of a saved drive).
export function buildTrackingCharts(s, { advanced = false, tMin, tMax, speed = DEFAULT_SPEED, controller = null } = {}) {
  if (!s || !s.t || s.t.length < 2) return []
  const v = (s.v || []).map((x) => toNumber(x) * speed.factor)
  const charts = [
    { id: "lat", title: "Lateral acceleration", unit: "m/s²", lines: LAT_LINES(s), active: s.lat_active, floor: 0.5 },
    { id: "long", title: "Longitudinal acceleration", unit: "m/s²", lines: LONG_LINES(s), active: s.long_active, floor: 0.5 },
    { id: "v", title: "Speed", unit: speed.unit, lines: [{ key: "v", values: v, color: LINE_COLORS.speed, cls: "speed", label: "Speed" }],
      active: s.enabled, floor: speed.floor, zeroBased: true },
  ]
  const angOk = (s.ang_ok || []).some((x) => toNumber(x) > 0.5)
  if (angOk) {
    charts.splice(1, 0, { id: "ang", title: "Steering wheel angle", unit: "°", active: s.lat_active, floor: 5, digits: 1, lines: [
      { key: "ang_des", values: s.ang_des, color: LINE_COLORS.desired, cls: "desired", label: "Requested" },
      { key: "ang_act", values: s.ang_act, color: LINE_COLORS.actual, cls: "actual", label: "Measured" },
    ] })
  }
  const leadSrc = s.lead_src || []
  if (leadSrc.some((x) => toNumber(x) > 0.5)) {
    // Shaded, with a break in the line, where no car ahead was tracked.
    const dist = (s.lead_d || []).map((x, i) => (toNumber(leadSrc[i]) > 0.5 ? toNumber(x) * speed.distFactor : null))
    charts.push({ id: "lead", title: "Car ahead: distance", unit: speed.distUnit, active: leadSrc, floor: 20 * speed.distFactor,
                  zeroBased: true, digits: 0, lines: [{ key: "lead_d", values: dist, color: LINE_COLORS.lead, cls: "lead", label: "Distance" }] })
  }
  if (advanced) {
    charts.push(
      { id: "latTerms", title: "Steering controller terms", unit: "", active: s.lat_active, floor: 0.1, note: termsNote(controller), lines: [
        { key: "lat_p", values: s.lat_p, color: LINE_COLORS.p, cls: "p", label: "P" },
        { key: "lat_i", values: s.lat_i, color: LINE_COLORS.i, cls: "i", label: "I" },
        { key: "lat_d", values: s.lat_d, color: LINE_COLORS.d, cls: "d", label: "D" },
        { key: "lat_f", values: s.lat_f, color: LINE_COLORS.f, cls: "f", label: "F" },
      ] },
      { id: "longTerms", title: "Longitudinal controller terms", unit: "m/s²", active: s.long_active, floor: 0.1, lines: [
        { key: "long_up", values: s.long_up, color: LINE_COLORS.p, cls: "p", label: "P" },
        { key: "long_ui", values: s.long_ui, color: LINE_COLORS.i, cls: "i", label: "I" },
        { key: "long_uf", values: s.long_uf, color: LINE_COLORS.f, cls: "f", label: "FF" },
      ] },
    )
  }
  return charts.map((c) => ({
    ...c,
    legend: c.lines.map((l) => ({ label: l.label, cls: l.cls, color: l.color,
                                  value: fmtNum(l.values[l.values.length - 1], c.digits ?? (c.id === "v" ? 0 : 2)) })),
    geo: buildChart(s.t, c.lines, c.active, { floor: c.floor, zeroBased: c.zeroBased, unit: c.unit, tMin, tMax }),
  }))
}

// Whole-drive overview charts from analysis.overview (bucket averages).
export function buildOverviewCharts(ov, { speed = DEFAULT_SPEED } = {}) {
  if (!ov || !Array.isArray(ov.t) || ov.t.length < 2) return []
  const v = (ov.v || []).map((x) => toNumber(x) * speed.factor)
  const charts = [
    { id: "lat", title: "Lateral acceleration (whole drive)", unit: "m/s²", lines: LAT_LINES(ov), active: ov.lat_active, floor: 0.5 },
    { id: "long", title: "Longitudinal acceleration (whole drive)", unit: "m/s²", lines: LONG_LINES(ov), active: ov.long_active, floor: 0.5 },
    { id: "v", title: "Speed (whole drive)", unit: speed.unit, lines: [{ key: "v", values: v, color: LINE_COLORS.speed, cls: "speed", label: "Speed" }],
      active: null, floor: speed.floor, zeroBased: true },
  ]
  return charts.map((c) => ({
    ...c,
    legend: c.lines.map((l) => ({ label: l.label, cls: l.cls, color: l.color, value: "" })),
    geo: buildChart(ov.t, c.lines, c.active, { floor: c.floor, zeroBased: c.zeroBased, unit: c.unit }),
  }))
}

// Key numbers for one axis of an analysis result, in display order.
// Plain "less/more than planned" wording for a measured-minus-requested bias.
function biasText(b, lessWord, moreWord) {
  if (b == null) return "—"
  const v = Math.abs(toNumber(b))
  if (v < 0.005) return "matched the plan"
  return `${fmtNum(v)} m/s² ${b > 0 ? moreWord : lessWord}`
}

export function keyNumbers(axis, m, speed = DEFAULT_SPEED) {
  if (!m) return []
  const pct = (g) => (g == null ? "—" : `${Math.round(g * 100)}%`)
  const rows = [["Engaged time", m.engaged_s == null ? "—" : fmtDuration(m.engaged_s)]]
  if (m.status === "ok") {
    rows.push(["Typical error", `${fmtNum(m.rmse)} m/s²`])
    rows.push(["Worst 5% of the time", `${fmtNum(m.p95_abs_error)} m/s² or more`])
    rows.push(["Reaction delay", `${fmtNum(m.lag_s)} s`])
  }
  if (axis === "lateral") {
    if (m.status === "ok") {
      const source = m.curve_gain_source === "wheel angle" ? " (wheel angle)" : ""
      rows.push([`Curve response${source}`, m.curve_gain == null ? "no sustained curves" : `${pct(m.curve_gain)} of what was asked`])
      rows.push(["Wobble ratio", `${fmtNum(m.wobble_ratio)} (about 1 is steady)`])
      rows.push(["Straight-road lean", m.straight_bias == null ? "—" : Math.abs(m.straight_bias) < 0.005 ? "none"
        : `${fmtNum(Math.abs(m.straight_bias))} m/s² to the ${m.straight_bias > 0 ? "left" : "right"}`])
      rows.push(["Time at steering limit (curves)", m.saturated_curve_frac == null ? "—" : pct(m.saturated_curve_frac)])
    }
    if (m.turns) rows.push(["Tight low-speed turns", String(m.turns.count ?? 0)])
    const tk = m.takeovers
    if (tk && tk.count != null) {
      rows.push(["Times you took the wheel", `${tk.count} (${tk.short} brief, ${tk.long} held; ${tk.blinker} with the blinker on)`])
      if (tk.median_back_on_plan_s != null) rows.push(["Back on openpilot's line after you let go", `${fmtNum(tk.median_back_on_plan_s, 1)} s (typical)`])
      if (tk.median_release_overshoot_deg != null) rows.push(["Wheel swing after you let go", `${fmtNum(tk.median_release_overshoot_deg, 1)}° (typical)`])
    } else {
      rows.push(["Times you took the wheel", String(m.steer_overrides ?? 0)])
    }
    // lane_off is + = car left of the lane centre; offsets under 8 cm are inside lane centring's deadband.
    if (Array.isArray(m.lane_straight) && m.lane_straight.length) {
      const side = (x) => (x == null ? "—" : Math.abs(x) < 0.08 ? "centred" : `${fmtNum(Math.abs(x), 2)} m ${x > 0 ? "left" : "right"}`)
      rows.push(["Lane position on straights", m.lane_straight.map((b) => `${b.band}: ${side(b.median_m)}`).join(" · ")])
    }
  } else {
    if (m.status === "ok") {
      rows.push(["Overall response", m.gain == null ? "—" : `${pct(m.gain)} of what was asked`])
      // Bias is measured minus requested: while braking (negative request) a positive value means less braking.
      rows.push(["Braking", biasText(m.brake_bias, "more than planned", "less than planned")])
      rows.push(["Acceleration", biasText(m.accel_bias, "less than planned", "more than planned")])
      rows.push(["Smoothness (peak jerk)", m.jerk_p95 == null ? "—" : `${fmtNum(m.jerk_p95)} m/s³`])
    }
    rows.push(["Hard brakes", String(m.hard_brakes ?? 0)])
    rows.push(["Times you pressed the gas", String(m.gas_overrides ?? 0)])
  }
  return rows.map(([label, value]) => ({ label, value }))
}

// Per-speed-band rows: [{label, gain, rmse, bias, time}] for a small table under the key numbers.
export function speedBandRows(m, speed = DEFAULT_SPEED) {
  if (!m || !Array.isArray(m.speed_bands)) return []
  return m.speed_bands.map((b) => ({
    label: bandLabel(b, speed),
    time: fmtDuration(b.engaged_s),
    gain: b.gain == null ? "—" : `${Math.round(b.gain * 100)}%`,
    rmse: fmtNum(b.rmse),
    bias: b.bias == null ? "—" : `${b.bias > 0 ? "+" : ""}${fmtNum(b.bias)}`,
  }))
}

// Tight low-speed turns and near-straight wobble, in steering-wheel degrees, for two small tables.
export function turnRows(m, speed = DEFAULT_SPEED) {
  const t = m?.turns
  if (!t) return null
  const deg = (x) => (x == null ? "—" : `${fmtNum(x, 1)}°`)
  return {
    count: t.count ?? 0,
    bins: (t.bins || []).map((b, i) => ({
      label: speedRange(i === 0 ? 0 : b.lo_ms, b.hi_ms, speed),
      time: fmtDuration(b.time_s), err: deg(b.err), past: deg(b.past), trail: deg(b.trail),
      limit: b.at_limit == null ? "—" : `${Math.round(b.at_limit * 100)}%`,
    })),
    // lat_score's definition keeps the second after a grab; shown so the page and the agents' scorecard agree.
    scorecard: (t.bins || []).map((b, i) => b.scorecard &&
      `${speedRange(i === 0 ? 0 : b.lo_ms, b.hi_ms, speed)} off by ${deg(b.scorecard.err)} (${deg(b.scorecard.past)} past)`)
      .filter(Boolean).join("; "),
    wobble: (t.wobble || []).map((b) => ({ label: speedRange(b.lo_ms, b.hi_ms, speed), time: fmtDuration(b.time_s),
                                           rms: `${fmtNum(b.rms_deg, 2)}°` })),
  }
}

function leadText(lead, speed) {
  if (!lead) return "No car ahead was tracked."
  const src = lead.src === "radar" ? "radar" : "camera only"
  return `Car ahead: ${fmtNum(toNumber(lead.d) * speed.distFactor, 0)} ${speed.distUnit} away at ${fmtSpeed(lead.v, speed)} (${src}).`
}

function clockTime(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })
}

// "Moments to check": analysis.events as display rows. t counts from the first sample; the clock time comes from
// meta.first_sample_at (older recordings: started_at, marked approximate).
export function eventRows(analysis, meta = {}, speed = DEFAULT_SPEED) {
  const events = Array.isArray(analysis?.events) ? analysis.events : []
  const base = toNumber(meta?.first_sample_at, 0) || toNumber(meta?.started_at, 0)
  const approx = !toNumber(meta?.first_sample_at, 0)
  const acc = (x) => `${fmtNum(Math.abs(toNumber(x)), 1)} m/s²`
  // Radar-to-camera handoffs are routine, and an experimental-mode burst with long control off never reached the car
  // (Bob); both stay in the analysis and the drive's logs for the radar work.
  return events.filter((e) => e.kind !== "radar_acquired" && e.kind !== "radar_lost" &&
    !(e.kind === "exp_flipflop" && e.long_active === false)).map((e) => {
    let title = ""
    let detail = ""
    let kind = "steer"
    if (e.kind === "hard_brake" || e.kind === "firm_brake") {
      kind = "brake"
      title = e.kind === "hard_brake" ? "Hard brake" : "Firm brake"
      detail = `openpilot asked for up to ${acc(e.plan_min)} from ${fmtSpeed(e.v, speed)}; the car slowed at up to ${acc(e.a_min)}. ` +
        `${leadText(e.lead_at_peak || e.lead, speed)}` + (e.gas_after ? " You pressed the gas right after." : "")
    } else if (e.kind === "brake_no_lead") {
      kind = "brake"
      title = "Braked with no car ahead"
      detail = `openpilot asked for up to ${acc(e.plan_min)} at ${fmtSpeed(e.v, speed)} with no car ahead tracked ` +
        "(a curve, a stop, or a speed limit can do this)."
    } else if (e.kind === "camera_only_brake") {
      kind = "brake"
      title = "Braked for a car only the camera saw"
      detail = `openpilot asked for up to ${acc(e.plan_min)} at ${fmtSpeed(e.v, speed)}; the radar had no match. ${leadText(e.lead, speed)}`
    } else if (e.kind === "driver_brake_override") {
      kind = "brake"
      title = "You braked while openpilot was not braking hard"
      detail = `At ${fmtSpeed(e.v, speed)}. ${leadText(e.lead, speed)}`
    } else if (e.kind === "lead_appeared_close") {
      kind = "brake"
      title = "A car appeared close ahead"
      detail = `At ${fmtSpeed(e.v, speed)}. ${leadText(e.lead, speed)}` +
        (e.d_before != null ? ` The car tracked before was ${fmtNum(e.d_before, 0)} m away.` : "")
    } else if (e.kind === "lead_vanished_close") {
      kind = "brake"
      title = "A close car ahead disappeared"
      detail = `At ${fmtSpeed(e.v, speed)}. ${leadText(e.lead, speed)} It was dropped while still close.`
    } else if (e.kind === "lead_flicker") {
      kind = "brake"
      title = "The car ahead blinked in and out"
      detail = `At ${fmtSpeed(e.v, speed)}, a close car ahead appeared and vanished within a second. ${leadText(e.lead, speed)}`
    } else if (e.kind === "lead_jump") {
      kind = "brake"
      title = "The car ahead suddenly got closer"
      detail = `At ${fmtSpeed(e.v, speed)}: the tracked distance dropped from ${fmtNum(e.d_before, 0)} m in one step. ${leadText(e.lead, speed)}`
    } else if (e.kind === "track_id_swap") {
      kind = "brake"
      title = "Radar swapped the car ahead's track"
      detail = `At ${fmtSpeed(e.v, speed)}: track ${e.id_before} became ${e.id_after} at the same distance. ${leadText(e.lead, speed)}`
    } else if (e.kind === "gas_during_brake") {
      kind = "brake"
      title = "You pressed the gas while openpilot braked"
      detail = `openpilot was braking up to ${acc(e.plan_min)} at ${fmtSpeed(e.v, speed)}. ${leadText(e.lead, speed)} ` +
        "If there was no real slower car, this braking was not needed."
    } else if (e.kind === "steer_takeover") {
      title = e.tag === "short grab" ? "You grabbed the wheel briefly" : "You took the wheel"
      const parts = [`At ${fmtSpeed(e.v, speed)}`]
      if (e.hold_s != null) parts.push(`held ${fmtNum(e.hold_s, 1)} s`)
      if (e.push) parts.push(`pushing ${e.push}`)
      if (e.blinker) parts.push("blinker on")
      detail = `${parts.join(", ")}.`
      if (e.release_overshoot_deg != null) detail += ` After you let go the wheel swung ${fmtNum(e.release_overshoot_deg, 1)}° back past the plan`
      if (e.back_on_plan_s != null) detail += `${e.release_overshoot_deg != null ? " and" : " After you let go it"} was back on it in ${fmtNum(e.back_on_plan_s, 1)} s`
      if (e.release_overshoot_deg != null || e.back_on_plan_s != null) detail += "."
      // Kevin's live flags, in plain words.
      const flagText = { "FLICKER": "the steering faulted while you held it", "SNAPBACK": "you grabbed it again right after letting go",
        "GAP": "at a crawl you let go far from the plan", "NEAR-CUT": "you held just under the takeover limit",
        "FIGHT": `you pushed against openpilot's steering for ${fmtNum(e.fought_first_s, 1)} s before taking over` }
      const flags = (Array.isArray(e.flags) ? e.flags : []).filter((f) => flagText[f])
      if (flags.length) detail += ` Flagged: ${flags.map((f) => flagText[f]).join("; ")}.`
      if (e.held_against_request) {
        detail += ` You held the wheel against openpilot's steering for ${fmtNum(e.fought_first_s, 1)} s without taking over. ` +
          "A hand on the wheel reads like this whenever openpilot steers; context, not a problem."
      }
    } else if (e.kind === "turn_overshoot") {
      title = "Tight turn went past the request"
      detail = `${e.side === "left" ? "Left" : "Right"} turn at ${fmtSpeed(e.v, speed)}: ${fmtNum(e.peak_des, 0)}° asked, the wheel ` +
        `went ${fmtNum(e.overshoot, 0)}° past it (overshoot or a late unwind).`
    } else if (e.kind === "exp_flipflop") {
      kind = "brake"
      title = "Experimental mode switched back and forth"
      detail = `At ${fmtSpeed(e.v, speed)} it switched ${e.flips} times in ${fmtNum(e.burst_s, 1)} s, ending ${e.experimental_after ? "on" : "off"}` +
        (e.red_light ? " (a red light was seen)." : ".")
    } else if (e.kind === "false_red_light") {
      kind = "brake"
      title = "Red light seen, but the car kept going"
      detail = `A red light came on at ${fmtSpeed(e.v, speed)}; the car stayed above ${fmtSpeed(e.v_min_10s, speed)} for 10 s.`
    } else if (e.kind === "atarget_step") {
      kind = "brake"
      title = "Speed request jumped"
      detail = `At ${fmtSpeed(e.v, speed)} openpilot's requested acceleration jumped from ${fmtNum(e.a_before, 1)} to ` +
        `${fmtNum(e.a_after, 1)} m/s² in one step.`
    } else if (e.kind === "close_lead_cap") {
      kind = "brake"
      title = "Close-car brake cap kicked in"
      detail = `At ${fmtSpeed(e.v, speed)}, capped at ${acc(e.cl_cap)}. ${leadText(e.lead, speed)}`
    } else if (e.kind === "radar_coast_near") {
      kind = "brake"
      title = "Radar lost sight of a close car"
      detail = `At ${fmtSpeed(e.v, speed)} the radar coasted a car within ${fmtNum(toNumber(e.d_min) * speed.distFactor, 0)} ` +
        `${speed.distUnit} for ${fmtNum(e.coast_s, 1)} s.`
    } else if (e.kind === "unmeasured_lead_cap") {
      kind = "brake"
      title = "Braked for a car the radar was not measuring"
      detail = `At ${fmtSpeed(e.v, speed)} the close-car cap asked for up to ${acc(e.cl_cap_min)} for ${fmtNum(e.for_s, 1)} s ` +
        `while the radar only coasted a car ${fmtNum(toNumber(e.d) * speed.distFactor, 0)} ${speed.distUnit} ahead.`
    } else if (e.kind === "brake_overshoot") {
      kind = "brake"
      title = "The car braked harder than asked"
      detail = `At ${fmtSpeed(e.v, speed)} openpilot asked for ${acc(e.a_cmd_min)} and the car slowed at up to ${acc(e.a_ego_min)} ` +
        `(${fmtNum(e.over_max, 1)} m/s² past it for ${fmtNum(e.for_s, 1)} s). ${leadText(e.lead, speed)}`
    } else if (e.kind === "vrel_disagree") {
      kind = "brake"
      title = "Radar speed readings disagreed"
      detail = `At ${fmtSpeed(e.v, speed)} the car ahead's two speed readings differed by up to ${fmtNum(e.gap_max, 1)} m/s ` +
        `for ${fmtNum(e.for_s, 1)} s. ${leadText(e.lead, speed)}`
    } else if (e.kind === "radar_vs_model") {
      kind = "brake"
      title = "Radar and camera disagreed on the distance"
      detail = `At ${fmtSpeed(e.v, speed)} they differed by up to ${fmtNum(e.d_gap_max, 0)} m for ${fmtNum(e.for_s, 1)} s. ${leadText(e.lead, speed)}`
    } else if (e.kind === "overspeed_no_lead") {
      kind = "brake"
      title = "Went over the set speed with no car ahead"
      detail = `Up to ${fmtNum(toNumber(e.over_max) * speed.factor, 1)} ${speed.unit} over for ${fmtNum(e.for_s, 0)} s.`
    } else if (e.kind === "gf_clip") {
      kind = "brake"
      title = "Gas learner hit its limit"
      detail = `At ${fmtSpeed(e.v, speed)} the learned gas factor reached ${fmtNum(e.gl_gf_raw, 2)}.`
    } else if (e.kind === "fault_flicker") {
      title = "Steering dropped out for a moment"
      detail = `At ${fmtSpeed(e.v, speed)} a temporary steering fault lasted ${fmtNum(e.fault_s, 1)} s` +
        (e.steer_pressed ? " while you held the wheel." : ".")
    } else if (e.kind === "release_snap") {
      title = "Wheel pulled back fast after you let go"
      detail = `At ${fmtSpeed(e.v, speed)}` + (e.repress ? `; you grabbed it again ${fmtNum(e.repress_after_s, 1)} s later.` : ".")
    } else if (e.kind === "hwy_inside_cut") {
      title = "Cut the inside of a highway curve"
      detail = `${e.turn === "left" ? "Left" : "Right"} curve at ${fmtSpeed(e.v, speed)}: up to ${fmtNum(e.inside_max_m, 2)} m toward ` +
        `the inside for ${fmtNum(e.for_s, 0)} s.`
    } else if (e.kind === "hwy_wiggle") {
      title = "Wheel wiggled on a highway straight"
      detail = `At ${fmtSpeed(e.v, speed)} the steering torque swung back and forth at least 4 times in 3 s.`
    } else {
      title = String(e.kind || "Event")
    }
    const t = toNumber(e.t)
    return { t, kind, title, detail, into: fmtDuration(t), clock: base ? `${approx ? "~" : ""}${clockTime(base + t)}` : "" }
  })
}

// First match wins, so Radar (NrdrHondaEcuMatchedLong) is tested before Speed control.
const TUNE_GROUPS = [
  { title: "Speed control", test: (k) => /long|accel|brake|stop|start|follow|jerk|^EVTuning$|^Truck|^Trailer/i.test(k) },
  { title: "Radar", test: (k) => /radar|EcuMatchedLong/i.test(k) },
]
const TUNE_TEST_ORDER = [1, 0]
// Keys James's controller does not read (latcontrol_honda_eps.py docstring): the gain sliders and Honda PID scales.
const SLIDER_KEY = /^Lat[PIF]Scale(LowSpeed|Standard|Highway)$|^LatGainSchedule$|^HondaLateralPidK[pi]Scale$/

// The tune snapshot stored with a recording, grouped: [{title, note, rows: [{label, value, unused}]}].
// Under James's controller the speed-band sliders are marked unused rather than hidden.
export function tuneGroups(meta) {
  if (!meta) return []
  const controller = meta.lateral_controller
  const info = CONTROLLERS[controller]
  const steering = { title: "Steering", note: info ? `${info.name}. ${info.note}` : "", rows: [] }
  if (controller) steering.rows.push({ label: "Steering controller", value: controllerName(controller) })
  if (meta.lateral_tuning) steering.rows.push({ label: "Lateral tuning type", value: String(meta.lateral_tuning) })
  const groups = TUNE_GROUPS.map((g) => ({ title: g.title, note: "", rows: [] }))
  if (meta.openpilot_longitudinal != null) {
    groups[0].rows.push({ label: "openpilot longitudinal", value: meta.openpilot_longitudinal ? "on" : "off" })
  }
  const tune = meta.tune && typeof meta.tune === "object" ? meta.tune : {}
  for (const [k, v] of Object.entries(tune)) {
    if (v === null || v === undefined || v === "" || v === "missing") continue
    const unused = info && !info.slidersUsed && SLIDER_KEY.test(k)
    const row = { label: k, value: unused ? `${v} (not used)` : String(v), unused: !!unused }
    const idx = TUNE_TEST_ORDER.find((i) => TUNE_GROUPS[i].test(k)) ?? -1
    ;(idx >= 0 ? groups[idx].rows : steering.rows).push(row)
  }
  return [steering, ...groups].filter((g) => g.rows.length)
}

export function statusLabel(status) {
  return { recording: "Recording", analyzing: "Analyzing…", done: "Saved", error: "Analysis failed" }[status] || status || "?"
}

export function sessionUrl(id, suffix = "") {
  return `/api/plots/sessions/${encodeURIComponent(id)}${suffix}`
}

export const HELP_TEXT = "'Requested' is what openpilot asked for, 'Measured' is what the car did. Shaded areas are where openpilot " +
  "was not in control (disengaged, you were steering or pressing the gas); they are left out of the analysis. " +
  "Lateral 'measured' is computed from the steering angle through the vehicle model, so a wrong steer ratio shows up as a gain error; " +
  "the steering-wheel-angle chart compares the wheel itself and has no such bias."

// How to read the numbers, for the drive detail.
export const READING_GUIDE = [
  "Requested vs measured: openpilot asks for a certain side-to-side (steering) or forward (speed) acceleration; the car delivers some of it. The analysis compares the two.",
  "Typical error: how far the car was from what was asked, on average. Under 0.2 m/s² you will hardly feel it; over 0.4 m/s² you will.",
  "Reaction delay: how long the car takes to start following a change. It comes from the car and the actuator-delay setting; it is not something to chase to zero.",
  "Curve response: 100% means the car turned exactly as much as asked. Below about 90% it runs wide in curves (feedforward a little low); above about 110% it cuts in. When it says 'wheel angle' it compares the steering wheel itself, so the steer ratio cannot bias it.",
  "Tight turns: parking-lot and intersection turns under 25 mph with the wheel past 45°, in degrees of steering wheel. 'Past the request' is overshoot or a late unwind; 'behind' is the wheel catching up.",
  "Wheel wobble: quick back-and-forth of the wheel itself on near-straight road, in degrees. Lower is steadier; compare drives rather than reading one number.",
  "Moments to check: hard brakes, gas presses while openpilot braked, times you took the wheel and tight turns that went past the request, each with the car ahead at that moment. Tap one to open the charts there.",
  "Wobble ratio: quick back-and-forth steering compared with what the road needed. Around 1 is steady; above 1.5 is the ping-pong you can feel on straights (gain a little high, or friction/damping a little low).",
  "Straight-road lean: a constant lean to one side on straight roads. A small steering-offset change fixes this, not the gains.",
  "Braking and acceleration vs plan: whether the car did less or more than openpilot asked. 'Less braking than planned' means it arrives a little hot behind a slowing car.",
  "Speed table: the same numbers split into Low speed, Standard and Highway, the same bands as the steering sliders. A tune that is right at one speed and off at another shows up here.",
  "One drive is a hint, not a verdict. Look for the same finding across a few drives before changing anything.",
]

// ---------------------------------------------------------------------------------------------------------------
// Zooming: drag across a chart to pick a stretch, tap for a minute around a spot, then zoom/pan with buttons.

export const ZOOM_MIN_S = 4
export const ZOOM_MAX_S = 900
export const DRAG_MIN_PX = 6

// [start, end] kept inside the drive (0..total) and between ZOOM_MIN_S and ZOOM_MAX_S long.
export function clampRange(start, end, total = Infinity) {
  let a = Math.min(start, end)
  let b = Math.max(start, end)
  const limit = Number.isFinite(total) && total > 0 ? total : Infinity
  let span = Math.min(Math.max(b - a, ZOOM_MIN_S), ZOOM_MAX_S, limit)
  const mid = (a + b) / 2
  a = mid - span / 2
  b = mid + span / 2
  if (a < 0) { b -= a; a = 0 }
  if (b > limit) { a = Math.max(0, a - (b - limit)); b = limit }
  return { start: a, end: b }
}

// factor < 1 zooms in, > 1 zooms out, around `at` (default: the middle).
export function zoomRange(z, factor, total = Infinity, at = null) {
  const c = at === null ? (z.start + z.end) / 2 : at
  const f = (c - z.start) / Math.max(1e-9, z.end - z.start)
  const span = (z.end - z.start) * factor
  return clampRange(c - f * span, c + (1 - f) * span, total)
}

// frac of the current span: -0.5 is half a screen earlier.
export function panRange(z, frac, total = Infinity) {
  const span = z.end - z.start
  let a = z.start + frac * span
  if (a < 0) a = 0
  if (Number.isFinite(total) && total > 0 && a + span > total) a = Math.max(0, total - span)
  return { start: a, end: a + span }
}

// Where the zoomed stretch sits on a whole-drive chart, as CSS percentages; null when it is off the chart.
export function zoomBand(z, geo) {
  if (!z || !geo || geo.empty || !(geo.tMax > geo.tMin)) return null
  const pct = (t) => Math.max(0, Math.min(100, (100 * (t - geo.tMin)) / (geo.tMax - geo.tMin)))
  const left = pct(z.start)
  const width = pct(z.end) - left
  return width > 0 ? { left: left.toFixed(2), width: Math.max(0.4, width).toFixed(2) } : null
}

export const sameRange = (a, b) => !!a && !!b && Math.abs(a.start - b.start) < 0.05 && Math.abs(a.end - b.end) < 0.05

// One gesture at a time across all charts. A page whose re-render would replace a chart mid-drag (arrow-core does)
// holds its update with afterGesture(fn), which runs fn now, or as soon as the finger or button is lifted.
let gestureActive = false
let cancelActive = null
let afterGestureQueue = []
export function afterGesture(fn) {
  if (!gestureActive) return fn()
  afterGestureQueue.push(fn)
}
function endGesture() {
  gestureActive = false
  const q = afterGestureQueue
  afterGestureQueue = []
  q.forEach((fn) => fn())
}

function timeAtX(el, clientX, geo) {
  const rect = el.getBoundingClientRect()
  if (!rect.width || !geo || geo.empty) return null
  const frac = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
  return geo.tMin + frac * (geo.tMax - geo.tMin)
}

// Pointer handlers for one chart (mouse, pen and finger alike). A movement under DRAG_MIN_PX is a tap -> onTap(t);
// a drag draws a band and ends in onRange(t0, t1). While dragging only the DOM is touched, never app state: a
// re-render mid-gesture would replace the element and drop the gesture. The chart needs `touch-action: pan-y` so a
// sideways drag selects while an up/down swipe still scrolls the page (the browser then sends pointercancel).
// onWheelZoom(factor, t) is called for ctrl + wheel, which is also what a trackpad pinch sends.
export function rangeSelect(getGeo, { onTap = null, onRange = null, onWheelZoom = null } = {}) {
  let drag = null
  const clear = () => {
    drag?.detach()
    if (drag?.box) drag.box.remove()
    const had = !!drag
    drag = null
    if (had) {
      cancelActive = null
      endGesture()
    }
  }
  const place = () => {
    const rect = drag.el.getBoundingClientRect()
    const x0 = Math.max(rect.left, Math.min(rect.right, Math.min(drag.x0, drag.x1)))
    const x1 = Math.max(rect.left, Math.min(rect.right, Math.max(drag.x0, drag.x1)))
    const parent = drag.el.parentElement.getBoundingClientRect()
    drag.box.style.left = `${x0 - parent.left}px`
    drag.box.style.width = `${x1 - x0}px`
    drag.box.style.top = `${rect.top - parent.top}px`
    drag.box.style.height = `${rect.height}px`
  }
  return {
    down(e) {
      // A second finger (a pinch) cancels the drag, on whichever chart it started, rather than restarting it from
      // where that finger landed.
      if (!e.isPrimary) {
        cancelActive?.()
        return
      }
      if (e.button > 0) return
      cancelActive?.()
      clear()
      gestureActive = true
      cancelActive = clear
      // A press released off the chart before it became a drag (so before pointer capture), or lost with the window's
      // focus, never reaches the chart; without this the gesture would stay open and hold every zoom reply. Bubble
      // phase, so a release on the chart has already been handled (and has detached this) by the time it gets here.
      const id = e.pointerId
      const lost = (ev) => { if (!ev.pointerId || ev.pointerId === id) clear() }
      window.addEventListener("pointerup", lost)
      window.addEventListener("pointercancel", lost)
      window.addEventListener("blur", lost)
      const detach = () => {
        window.removeEventListener("pointerup", lost)
        window.removeEventListener("pointercancel", lost)
        window.removeEventListener("blur", lost)
      }
      drag = { el: e.currentTarget, id, x0: e.clientX, x1: e.clientX, box: null, detach }
    },
    move(e) {
      if (!drag || e.pointerId !== drag.id) return
      drag.x1 = e.clientX
      if (!drag.box && Math.abs(drag.x1 - drag.x0) >= DRAG_MIN_PX && onRange) {
        try { drag.el.setPointerCapture(e.pointerId) } catch { /* the pointer is already gone */ }
        const box = document.createElement("div")
        box.className = "plotBrush"
        Object.assign(box.style, { position: "absolute", pointerEvents: "none", background: "rgba(122,162,247,0.24)",
                                   borderLeft: "2px solid #7aa2f7", borderRight: "2px solid #7aa2f7", zIndex: "2" })
        drag.el.parentElement.appendChild(box)
        drag.box = box
      }
      if (drag.box) {
        e.preventDefault()
        place()
      }
    },
    up(e) {
      if (!drag || e.pointerId !== drag.id) return
      const d = drag
      clear()
      const geo = getGeo()
      if (!d.box) {
        const t = timeAtX(d.el, d.x0, geo)
        if (t !== null && onTap) onTap(t)
        return
      }
      const a = timeAtX(d.el, Math.min(d.x0, d.x1), geo)
      const b = timeAtX(d.el, Math.max(d.x0, d.x1), geo)
      if (a !== null && b !== null) onRange(a, b)
    },
    cancel() { clear() },
    wheel(e) {
      if (!onWheelZoom || !e.ctrlKey) return
      e.preventDefault()
      const t = timeAtX(e.currentTarget, e.clientX, getGeo())
      if (t !== null) onWheelZoom(e.deltaY > 0 ? 1.25 : 0.8, t)
    },
  }
}
