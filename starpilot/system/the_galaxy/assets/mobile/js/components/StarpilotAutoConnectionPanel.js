import { api, showSnackbar } from "../api.js"
import { usePolling } from "../composables.js"
import { navigate } from "../store.js"

function address(value) { return String(value || "").toUpperCase() }

export const StarpilotAutoConnectionPanel = {
  name: "StarpilotAutoConnectionPanel",
  data() {
    return {
      status: null, devices: [], offroad: false, setupHelp: "", recoveryHint: "",
      devicesError: "", error: "", loading: true, busy: "",
    }
  },
  created() { this.poll = usePolling(() => this.refresh(), { interval: 2500 }); this.poll.start() },
  beforeUnmount() { this.poll?.destroy() },
  computed: {
    running() { return !!this.status?.running },
    wired() { return this.status?.connection === "wired" },
    connection() { return this.wired ? "wired" : "wireless" },
    display() { return this.status?.configured_view === "mirror" ? "mirror" : "car" },
    canConnect() { return this.status ? (this.running || this.wired || !!this.status.receiver_address) : !!this.error },
    canChangeLink() { return !!this.status && !this.running && !this.busy },
    selectedCar() { return address(this.status?.receiver_address) },
    cars() {
      const cars = this.devices.filter(device => device?.paired !== false).map(device => ({ ...device }))
      const current = this.selectedCar
      if (current && !cars.some(device => address(device.address) === current)) {
        cars.push({ address: this.status.receiver_address, name: this.status.receiver_name || this.status.receiver_address, paired: true, starpilot_auto: true })
      }
      return cars.sort((a, b) => Number(!!b.starpilot_auto) - Number(!!a.starpilot_auto) || String(a.name || a.address).localeCompare(String(b.name || b.address)))
    },
    statusText() {
      const status = this.status
      if (this.error) return `Error: ${this.error}`
      if (!status) return this.loading ? "Starting…" : "Starpilot Auto service unavailable"
      if (status.error) return `Error: ${status.error}`
      if (status.state === "streaming") return `Projecting · ${Number(status.stats?.fps || 0).toFixed(0)} fps`
      if (status.state === "suspended") return "Connected · Car is showing its own screen"
      if (status.state === "backoff") return `Retrying in ${Math.max(0, Math.round(Number(status.retry_in || 0)))} seconds`
      if (status.state === "waiting_for_usb") return "Waiting for the car's Starpilot Auto USB port"
      if (status.state === "idle") {
        if (!this.wired && !status.receiver_name) return "Choose a Car"
        if (status.auto_connect) return status.auto_paused ? "Paused until the next drive" : "Ready · Starts automatically next drive"
        return "Off"
      }
      return [status.label || status.state, status.detail].filter(Boolean).join(" · ")
    },
    autoConnectText() { return this.status?.auto_connect ? "On" : "Off" },
  },
  methods: {
    address,
    apply(payload) {
      this.status = payload?.status || null
      this.devices = Array.isArray(payload?.devices) ? payload.devices : []
      this.offroad = !!payload?.offroad
      this.setupHelp = String(payload?.setup_help || "")
      this.recoveryHint = String(payload?.recovery_hint || "")
      this.devicesError = String(payload?.devices_error || "")
      this.error = ""
    },
    async refresh() {
      if (this.busy) return
      try {
        this.apply(await api.getStarpilotAutoConnection())
      } catch (e) {
        this.error = e?.message || "Starpilot Auto service unavailable"
      } finally {
        this.loading = false
      }
    },
    async request(operation, body = {}) {
      if (this.busy) return false
      this.busy = operation
      try {
        this.apply(await api.starpilotAutoConnectionOp(operation, body))
        return true
      } catch (e) {
        this.error = e?.message || "Starpilot Auto operation failed"
        showSnackbar(this.error, "error")
        return false
      } finally {
        this.busy = ""
        this.loading = false
      }
    },
    toggleConnection() { return this.status ? this.request(this.running ? "stop" : "start") : this.refresh() },
    setAutoConnect(enabled) { return this.request("set_auto_connect", { enabled }) },
    setConnection(connection) {
      if (connection === this.connection) return
      return this.request("set_connection", { connection })
    },
    setDisplay(view) {
      if (view === this.display) return
      return this.request("set_view", { view })
    },
    selectCar(event) {
      const chosen = this.cars.find(device => address(device.address) === address(event.target.value))
      if (!chosen || address(chosen.address) === this.selectedCar) return
      return this.request("select_receiver", { address: chosen.address, name: chosen.name || chosen.address })
    },
    async pairNewCar() {
      if (!this.offroad || this.busy) return
      if (!await this.request("prepare_pairing")) return
      try {
        await api.bluetoothOp("scan")
      } catch (e) {
        showSnackbar(e?.message || "Pairing is ready, but Bluetooth scan could not start.", "error")
      }
      showSnackbar("Pairing is ready. Add a device on the Car, then select it here.")
      navigate("/bluetooth")
    },
  },
  template: `
    <div class="gx-car-display gx-starpilot-auto-connection">
      <div class="gx-row">
        <div class="gx-row__info"><span class="gx-row__label">{{ running ? 'Disconnect' : 'Connect' }}</span><span class="gx-row__desc">{{ statusText }}</span></div>
        <button type="button" class="gx-btn" :class="running ? 'gx-btn--danger' : ''" :disabled="loading || !canConnect || !!busy" @click="toggleConnection">
          {{ !status && error ? 'Retry' : busy === 'start' ? 'Connecting…' : busy === 'stop' ? 'Disconnecting…' : running ? 'Disconnect' : 'Connect' }}
        </button>
      </div>

      <label v-if="!wired" class="gx-row">
        <div class="gx-row__info"><span class="gx-row__label">Car</span><span class="gx-row__desc">Choose the paired Car that receives Starpilot Auto.</span></div>
        <select class="gx-field gx-starpilot-auto-connection__car" :value="selectedCar" :disabled="running || !!busy" aria-label="Car" @change="selectCar">
          <option value="">Choose a Car</option>
          <option v-for="car in cars" :key="car.address" :value="address(car.address)">{{ car.name || car.address }}{{ car.starpilot_auto ? '' : ' · compatibility unknown' }}</option>
        </select>
      </label>

      <label class="gx-row">
        <div class="gx-row__info"><span class="gx-row__label">Auto Connect</span><span class="gx-row__desc">{{ autoConnectText }} · Reconnects when the Car and comma are ready.</span></div>
        <span class="gx-switch"><input type="checkbox" :checked="!!status?.auto_connect" :disabled="!status || !!busy" aria-label="Auto Connect" @change="setAutoConnect($event.target.checked)" />
          <span class="gx-switch__track"></span><span class="gx-switch__thumb"></span></span>
      </label>

      <div class="gx-row">
        <div class="gx-row__info"><span class="gx-row__label">Link Type</span><span class="gx-row__desc">Disconnect before changing how the comma connects to the Car.</span></div>
        <div class="gx-car-display__tabs" role="group" aria-label="Link Type">
          <button v-for="option in [{value:'wireless',label:'Wireless'},{value:'wired',label:'USB'}]" :key="option.value" type="button" class="gx-btn"
            :class="connection === option.value ? '' : 'gx-btn--tonal'" :aria-pressed="connection === option.value" :disabled="!canChangeLink" @click="setConnection(option.value)">{{ option.label }}</button>
        </div>
      </div>

      <div class="gx-row">
        <div class="gx-row__info"><span class="gx-row__label">Display</span><span class="gx-row__desc">Choose what appears on the Car screen. Changes apply on the next connection.</span></div>
        <div class="gx-car-display__tabs" role="group" aria-label="Display">
          <button v-for="option in [{value:'car',label:'Car Layout'},{value:'mirror',label:'Mirror'}]" :key="option.value" type="button" class="gx-btn"
            :class="display === option.value ? '' : 'gx-btn--tonal'" :aria-pressed="display === option.value" :disabled="!status || !!busy" @click="setDisplay(option.value)">{{ option.label }}</button>
        </div>
      </div>

      <div v-if="!wired" class="gx-row">
        <div class="gx-row__info"><span class="gx-row__label">Pair a New Car</span><span class="gx-row__desc">{{ offroad ? 'Opens Bluetooth and makes the comma ready for the Car.' : 'Park and go offroad to pair a new Car.' }}</span></div>
        <button type="button" class="gx-btn gx-btn--tonal" :disabled="!offroad || !!busy" @click="pairNewCar">Pair</button>
      </div>

      <details class="gx-row gx-row--stack">
        <summary><span class="gx-row__label">Setup Help</span></summary>
        <span class="gx-row__desc">{{ setupHelp || 'Connection setup instructions will appear when the Starpilot Auto service is ready.' }}</span>
      </details>
      <details v-if="status?.error" class="gx-row gx-row--stack">
        <summary><span class="gx-row__label">Last Error</span></summary>
        <span class="gx-row__desc">{{ recoveryHint }} {{ status.error }}</span>
      </details>
      <span v-if="devicesError && !wired" class="gx-row__desc">Car list: {{ devicesError }}</span>
    </div>
  `,
}
