// Jetlink's big models (comma commits a Jetson or Mac runs over USB), from /api/models/jetlink. Separate from Active Big:
// those are StarPilot's chestnut builds, these are jetlink's own catalog. Only models this fork has validated can be picked.
// Ported from peterfork/Jetlink-Port (773a57f634) and adapted.
export const JetlinkModelsCard = {
  name: "JetlinkModelsCard",
  props: { isOnroad: { type: Boolean, default: false } },
  data() {
    return { data: null, error: "", busy: false, timer: null }
  },
  computed: {
    models() { return (this.data && this.data.models) || [] },
    defaultSelected() { return !this.models.some((m) => m.selected) },
    locked() { return this.busy || this.isOnroad || !!(this.data && this.data.isOnroad) },
  },
  mounted() { this.load() },
  beforeUnmount() { clearTimeout(this.timer) },
  methods: {
    async request(options) {
      const response = await fetch("/api/models/jetlink", options)
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`)
      this.data = payload
      this.error = ""
    },
    async load() {
      clearTimeout(this.timer)
      try { await this.request() } catch (e) { this.error = e.message }
      this.timer = setTimeout(() => this.load(), 5000)
    },
    async select(ref) {
      this.busy = true
      try {
        await this.request({ method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ref }) })
      } catch (e) { this.error = e.message } finally { this.busy = false }
    },
    stateLabel(state) {
      return state === "ready" ? "Built on host" : state === "downloaded" ? "Downloaded" : "Not downloaded"
    },
  },
  template: `
    <section class="gx-card">
      <div class="gx-section__header">
        <i class="bi bi-usb-symbol"></i>
        <span class="gx-section__title">Jetlink Big Models</span>
        <span class="gx-chip">{{ models.length }}</span>
      </div>
      <div style="padding: 0 var(--sp-4) var(--sp-4);">
        <div v-if="error" class="gx-alert gx-alert--warn" style="border:none; margin:0 0 8px;">
          <i class="bi bi-exclamation-triangle-fill gx-alert__icon"></i>
          <div class="gx-alert__body"><span>{{ error }}</span></div>
        </div>
        <div v-if="data && !data.available" class="gx-row" style="border-top:none;">Jetlink is not available on this build.</div>
        <template v-else-if="data">
          <div class="gx-row" style="border-top:none; flex-wrap:wrap; gap:6px;">
            <span class="gx-chip">Link: {{ (data.mode || "off").toUpperCase() }}</span>
            <span class="gx-chip">Host: {{ data.present ? "Connected" : "Not connected" }}</span>
            <span class="gx-chip">Running: {{ data.activeModel || "none built yet" }}</span>
            <span v-if="data.progress && data.progress.msg" class="gx-chip">{{ data.progress.stage }}: {{ data.progress.msg }}</span>
          </div>
          <div v-if="data.mode === 'off'" class="gx-alert gx-alert--info" style="border:none; margin:0 0 8px;">
            <i class="bi bi-info-circle gx-alert__icon"></i>
            <div class="gx-alert__body"><span>Turn Jetlink on in Settings to use these.</span></div>
          </div>
          <div v-if="data.reason" class="gx-alert gx-alert--warn" style="border:none; margin:0 0 8px;">
            <i class="bi bi-exclamation-triangle-fill gx-alert__icon"></i>
            <div class="gx-alert__body"><span>{{ data.reason }}</span></div>
          </div>
          <div class="gx-row" style="border-top:none;">
            <span class="gx-row__label" style="flex:1;">Default ({{ data.defaultModel || "jetlink default" }})</span>
            <span v-if="defaultSelected" class="gx-chip">Selected</span>
            <button v-else type="button" class="gx-btn gx-btn--tonal" :disabled="locked" @click="select('')">Use Default</button>
          </div>
          <div v-for="m in models" :key="m.ref" class="gx-row">
            <span class="gx-row__label" style="flex:1;">{{ m.name }}<br><small>{{ m.ref.slice(0, 10) }} · {{ stateLabel(m.state) }}<template v-if="m.supported === false"> · Not validated</template></small></span>
            <span v-if="m.selected" class="gx-chip">Selected</span>
            <button v-else type="button" class="gx-btn" :disabled="locked || m.supported === false" @click="select(m.ref)">Select</button>
          </div>
          <div v-if="!models.length" class="gx-row">No Jetlink catalog yet. Press Refresh to fetch it.</div>
        </template>
      </div>
    </section>
  `,
}
