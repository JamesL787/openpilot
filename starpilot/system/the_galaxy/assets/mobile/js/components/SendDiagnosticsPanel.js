import { api, showSnackbar } from "../api.js"

const BUSY = ["preparing", "sending"]
const POLL_MS = 1500

function download(url) {
  const link = document.createElement("a")
  link.href = url
  link.download = ""
  document.body.appendChild(link)
  link.click()
  link.remove()
}

export const SendDiagnosticsPanel = {
  name: "SendDiagnosticsPanel",
  data() {
    return { note: "", drives: 1, status: {}, starting: false, timer: null, pendingDownload: false }
  },
  computed: {
    busy() { return this.starting || BUSY.includes(this.status.state) },
    driveChoices() {
      const available = Math.min(3, this.status.drives_available ?? 3)
      return Array.from({ length: available + 1 }, (_, count) => count)
    },
    canDownloadLast() { return ["ready", "sent", "send_failed"].includes(this.status.state) },
    stateClass() {
      if (this.status.state === "sent") return "gx-car-diag__outcome--ok"
      return ["error", "send_failed"].includes(this.status.state) ? "gx-car-diag__outcome--error" : ""
    },
  },
  created() { this.refresh() },
  beforeUnmount() { clearTimeout(this.timer) },
  methods: {
    driveLabel(count) {
      if (count === 0) return "No drives (fastest)"
      return count === 1 ? "Last drive" : `Last ${count} drives`
    },
    async refresh() {
      clearTimeout(this.timer)
      try {
        this.status = await api.getDiagnosticsStatus()
      } catch (e) {
        this.status = { state: "error", message: e?.message || "Could not reach the comma." }
      }
      if (!this.status.offroad && this.drives > 0) this.drives = 0
      if (BUSY.includes(this.status.state)) this.timer = setTimeout(() => this.refresh(), POLL_MS)
      else if (this.pendingDownload && this.status.state === "ready") {
        this.pendingDownload = false
        download("/api/diagnostics/download")
      } else if (this.status.state === "sent") showSnackbar(this.status.message)
    },
    async start(action) {
      this.starting = true
      try {
        this.status = await api.startDiagnostics({ action, note: this.note, drives: Number(this.drives) })
        this.pendingDownload = action === "download"
      } catch (e) {
        showSnackbar(e?.message || "Could not start.", "error")
      } finally {
        this.starting = false
      }
      this.refresh()
    },
    downloadLast() { download("/api/diagnostics/download") },
  },
  template: `
    <section class="gx-card">
      <div class="gx-section__header">
        <i class="bi bi-send"></i>
        <span class="gx-section__title">Report a problem</span>
      </div>
      <div style="padding: var(--sp-4); display:grid; gap:12px;">
        <p class="gx-row__desc" style="margin:0;">Something went wrong with Starpilot Auto, Bluetooth pairing or a drive? Describe what happened and send the logs. They include Starpilot Auto and Bluetooth pairing logs and a short health report for recent drives. No passwords, certificates, camera video or GPS track.</p>
        <textarea class="gx-field" rows="3" maxlength="1000" v-model="note" :disabled="busy"
          placeholder="What happened, and roughly when? (e.g. 'Starpilot Auto took 3 tries to connect after I started the car')"></textarea>
        <label class="gx-row__desc" style="display:grid; gap:4px;">Include drive reports
          <select class="gx-field" v-model.number="drives" :disabled="busy">
            <option v-for="count in driveChoices" :key="count" :value="count" :disabled="count > 0 && status.offroad === false">{{ driveLabel(count) }}</option>
          </select>
        </label>
        <p v-if="status.offroad === false" class="gx-row__desc" style="margin:0;">The car is on: drive reports are available once it's turned off.</p>
        <div class="gx-car-display__tabs">
          <button v-if="status.send_available" type="button" class="gx-btn" :disabled="busy" @click="start('send')">
            <i class="bi" :class="busy && status.action === 'send' ? 'bi-arrow-repeat gx-spin' : 'bi-send'"></i> Send report</button>
          <button type="button" class="gx-btn gx-btn--tonal" :disabled="busy" @click="start('download')">
            <i class="bi" :class="busy && status.action === 'download' ? 'bi-arrow-repeat gx-spin' : 'bi-download'"></i> Download</button>
        </div>
        <p v-if="status.state && status.state !== 'idle'" class="gx-row__desc gx-car-diag__outcome" :class="stateClass" style="margin:0;">{{ status.message }}</p>
        <button v-if="status.state === 'send_failed' || (canDownloadLast && !pendingDownload && status.action === 'download')" type="button"
          class="gx-btn gx-btn--tonal" style="justify-self:start;" @click="downloadLast"><i class="bi bi-file-earmark-zip"></i> Download the file</button>
      </div>
    </section>
  `,
}
