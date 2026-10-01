import { api, showSnackbar } from "../api.js"

function carName(session) {
  const car = session.car || {}
  const name = [car.car_make, car.car_model].filter(Boolean).join(" ")
  return name || car.bluetooth_name || "Unknown car"
}

function download(url, name = "") {
  const link = document.createElement("a")
  link.href = url
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
}

function started(session) {
  const date = new Date(session.started)
  return Number.isNaN(date.getTime()) ? "Unknown time" : date.toLocaleString()
}

export const StarpilotAutoDiagnosticsPanel = {
  name: "StarpilotAutoDiagnosticsPanel",
  data() {
    return { sessions: [], loading: false, error: "", open: "", reports: {}, loadingReport: "" }
  },
  created() { this.load() },
  methods: {
    carName,
    started,
    outcomeClass(session) {
      if (session.outcome === "projected") return "gx-car-diag__outcome--ok"
      return session.outcome.startsWith("failed") ? "gx-car-diag__outcome--error" : ""
    },
    downloadAll() {
      download("/api/starpilot_auto/diagnostics/bundle")
      showSnackbar("Download started...")
    },
    downloadLog(session) { download(`/api/starpilot_auto/diagnostics/${encodeURIComponent(session.name)}?format=log`, session.name) },
    async load() {
      if (this.loading) return
      this.loading = true
      this.error = ""
      try {
        this.sessions = (await api.getStarpilotAutoDiagnostics()).sessions || []
        // A log still being written changes after its report was read: read the open one again.
        this.reports = {}
        const open = this.sessions.find(session => session.name === this.open)
        this.open = ""
        if (open) await this.toggle(open)
      } catch (e) {
        this.error = e?.message || "Could not read the Starpilot Auto logs."
      } finally {
        this.loading = false
      }
    },
    async toggle(session) {
      if (this.open === session.name) { this.open = ""; return }
      this.open = session.name
      if (this.reports[session.name]) return
      this.loadingReport = session.name
      try {
        const result = await api.getStarpilotAutoDiagnosticsReport(session.name)
        this.reports = { ...this.reports, [session.name]: result.text }
      } catch (e) {
        showSnackbar(e?.message || "Could not read that report.", "error")
        if (this.open === session.name) this.open = ""
      } finally {
        this.loadingReport = ""
      }
    },
    async copy(name) {
      const text = this.reports[name] || ""
      try {
        if (navigator.clipboard?.writeText && window.isSecureContext) await navigator.clipboard.writeText(text)
        else { const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove() }
        showSnackbar("Report copied to clipboard.")
      } catch (e) {
        showSnackbar("Could not copy the report.", "error")
      }
    },
  },
  template: `
    <div class="gx-car-display">
      <p class="gx-row__desc">Each connection to a car is logged. If a car won't connect, download everything and include it in your report. Certificates and Wi-Fi passwords are never included.</p>
      <div class="gx-car-display__tabs">
        <button type="button" class="gx-btn" @click="downloadAll"><i class="bi bi-file-earmark-zip"></i> Download All</button>
        <button type="button" class="gx-btn gx-btn--tonal" :disabled="loading" @click="load">
          <i class="bi" :class="loading ? 'bi-arrow-repeat gx-spin' : 'bi-arrow-clockwise'"></i> Refresh</button>
      </div>
      <div v-if="error" class="gx-row">
        <div class="gx-row__info"><span class="gx-row__label">Could not load the logs</span><span class="gx-row__desc">{{ error }}</span></div>
      </div>
      <p v-else-if="!loading && !sessions.length" class="gx-row__desc">No connections have been logged yet.</p>
      <div v-for="session in sessions" :key="session.name" class="gx-car-diag__session">
        <div class="gx-row">
          <div class="gx-row__info">
            <span class="gx-row__label">{{ carName(session) }} <span class="gx-car-diag__transport">{{ session.transport === 'wired' ? 'USB' : 'Wireless' }}</span></span>
            <span class="gx-row__desc">{{ started(session) }}</span>
            <span class="gx-row__desc gx-car-diag__outcome" :class="outcomeClass(session)">{{ session.outcome }}</span>
          </div>
          <div class="gx-car-display__tabs">
            <button type="button" class="gx-btn gx-btn--tonal" :aria-expanded="open === session.name" @click="toggle(session)">
              <i class="bi" :class="loadingReport === session.name ? 'bi-arrow-repeat gx-spin' : 'bi-card-text'"></i> Report</button>
            <button type="button" class="gx-btn gx-btn--tonal" :aria-label="'Download log ' + session.name" @click="downloadLog(session)"><i class="bi bi-download"></i> Log</button>
          </div>
        </div>
        <div v-if="open === session.name && reports[session.name]" class="gx-car-diag__report">
          <pre>{{ reports[session.name] }}</pre>
          <button type="button" class="gx-btn gx-btn--tonal" @click="copy(session.name)"><i class="bi bi-clipboard"></i> Copy</button>
        </div>
      </div>
    </div>
  `,
}
