import { api, showSnackbar } from "../api.js"

const VIEWS = [
  { value: "split", label: "Split", desc: "The driving view and the navigation map side by side." },
  { value: "driving", label: "Driving", desc: "The StarPilot driving view fills the car screen." },
  { value: "map", label: "Map", desc: "The map fills the screen, with the status border, your speed and alerts on top." },
]

const MAP_ORIENTATIONS = [
  { value: "north_up", label: "North Up", desc: "Keeps street names upright and rotates only the vehicle marker." },
  { value: "heading_up", label: "Heading Up", desc: "Keeps the direction of travel toward the top; raster street names rotate with the map." },
]

const STATUS_POSITIONS = [
  { view: "split", label: "Split", positions: ["left", "center", "right"] },
  { view: "driving", label: "Driving", positions: ["left", "right"] },
  { view: "map", label: "Map", positions: ["left", "right"] },
]

const POSITION_LABELS = { left: "Left", center: "Between", right: "Right" }

// Critical / takeover alerts always wake the comma display and are not a choice.
const WAKE_EVENTS = [
  { value: "StandbyWakeWarningAlert", label: "Warning alerts" },
  { value: "StandbyWakeInfoAlert", label: "Informational alerts" },
  { value: "StandbyWakeEngage", label: "Engagement" },
  { value: "StandbyWakeDisengage", label: "Disengagement" },
  { value: "StandbyWakeTurnSignal", label: "Turn signals" },
  { value: "StandbyWakeButton", label: "Steering wheel or Bluetooth button" },
]

const DISPLAY_ON_WARNING = "Keep the comma display on while Starpilot Auto is connected? The comma then draws its own screen as well as the car's, which uses additional CPU."

export const StarpilotAutoCarScreenPanel = {
  name: "StarpilotAutoCarScreenPanel",
  props: {
    isMetric: { type: Boolean, default: false },
    section: { type: String, default: "", validator: value => ["", "layout", "widgets"].includes(value) },
  },
  data() {
    return { settings: null, statusMetrics: [], tab: "layout", loading: false, error: "", saving: false, views: VIEWS, mapOrientations: MAP_ORIENTATIONS,
      statusPositions: STATUS_POSITIONS, positionLabels: POSITION_LABELS, wakeEvents: WAKE_EVENTS }
  },
  created() { this.load() },
  computed: {
    showsDriving() { return this.settings && this.settings.onroad_view !== "map" },
    showsMap() { return this.settings && this.settings.onroad_view !== "driving" },
    isSplit() { return this.settings && this.settings.onroad_view === "split" },
    selectedView() { return this.views.find(view => view.value === this.settings?.onroad_view) || this.views[0] },
    blindSpotEnabled() { return this.settings?.blind_spot_monitors !== false },
    speedFactor() { return this.isMetric ? 3.6 : 2.2369362921 },
    speedUnit() { return this.isMetric ? "km/h" : "mph" },
    blindSpotMinSpeed() { return Math.round((this.settings?.blind_spot_min_speed_ms || 0) * this.speedFactor) },
  },
  methods: {
    async load() {
      if (this.loading) return
      this.loading = true
      this.error = ""
      try {
        // The panel mounts as soon as the master toggle changes locally. Its first
        // request can beat the toggle's PUT to the device and receive a transient 403.
        for (let attempt = 0; attempt < 3; attempt++) {
          try {
            const response = await api.getCarScreen()
            this.settings = response.settings
            this.statusMetrics = response.status_metrics
            return
          } catch (e) {
            if (attempt === 2) throw e
            await new Promise(resolve => setTimeout(resolve, attempt === 0 ? 250 : 750))
          }
        }
      } catch (e) {
        this.error = e?.message || "Could not read the car screen settings."
        showSnackbar(this.error, "error")
      } finally {
        this.loading = false
      }
    },
    async update(change) {
      if (!this.settings || this.saving) return
      const previous = this.settings
      this.settings = { ...this.settings, ...change }
      this.saving = true
      try {
        this.settings = (await api.setCarScreen(change)).settings
      } catch (e) {
        this.settings = previous
        showSnackbar(e?.message || "Could not save the car screen settings.", "error")
      } finally {
        this.saving = false
      }
    },
    updateBlindSpotSpeed(event) {
      const raw = String(event.target.value ?? "").trim()
      const value = Number(raw)
      const maximum = this.isMetric ? 200 : 125
      if (raw && Number.isFinite(value)) {
        this.update({ blind_spot_min_speed_ms: Math.min(maximum, Math.max(0, value)) / this.speedFactor })
      }
    },
    updateSleep(event) {
      if (!event.target.checked && !window.confirm(DISPLAY_ON_WARNING)) {
        event.target.checked = true
        return
      }
      this.update({ sleep_device_screen: event.target.checked })
    },
    wakes(value) { return (this.settings?.sleep_wake_events || []).includes(value) },
    updateWakeEvent(value, event) {
      const chosen = new Set((this.settings.sleep_wake_events || []).filter(item => item !== value))
      if (event.target.checked) chosen.add(value)
      this.update({ sleep_wake_events: this.wakeEvents.map(item => item.value).filter(item => chosen.has(item)) })
    },
    updateStatusSlot(index, event) {
      const status_slots = [...this.settings.status_slots]
      status_slots[index] = event.target.value
      this.update({ status_slots })
    },
  },
  template: `
    <div class="gx-car-display">
      <p class="gx-row__desc">Car screen only. These settings control the Starpilot Auto view in your Car.</p>
      <div v-if="!section" class="gx-car-display__tabs" role="tablist" aria-label="Car Display">
        <button type="button" role="tab" class="gx-btn" :class="tab === 'layout' ? '' : 'gx-btn--tonal'"
          :aria-selected="tab === 'layout'" @click="tab = 'layout'">Layout</button>
        <button type="button" role="tab" class="gx-btn" :class="tab === 'widgets' ? '' : 'gx-btn--tonal'"
          :aria-selected="tab === 'widgets'" @click="tab = 'widgets'">Status Widgets</button>
      </div>
      <div v-if="loading" class="gx-loading">Loading...</div>
      <div v-else-if="error" class="gx-row">
        <div class="gx-row__info"><span class="gx-row__label">Could not load settings</span><span class="gx-row__desc">{{ error }}</span></div>
        <button type="button" class="gx-btn gx-btn--tonal" @click="load">Retry</button>
      </div>
      <template v-else-if="settings">
        <template v-if="(section || tab) === 'layout'">
          <div class="gx-row">
            <div class="gx-row__info"><span class="gx-row__label">Driving Layout</span><span class="gx-row__desc">{{ selectedView.desc }}</span></div>
            <div class="gx-car-display__tabs"><button v-for="view in views" :key="view.value" type="button" class="gx-btn"
              :class="settings.onroad_view === view.value ? '' : 'gx-btn--tonal'" :aria-pressed="settings.onroad_view === view.value" :disabled="saving"
              @click="update({ onroad_view: view.value })">{{ view.label }}</button></div>
          </div>
          <div v-if="isSplit" class="gx-row">
            <div class="gx-row__info"><span class="gx-row__label">Map Side</span><span class="gx-row__desc">Which half of the car display shows the map.</span></div>
            <div class="gx-car-display__tabs"><button v-for="side in ['left', 'right']" :key="side" type="button" class="gx-btn"
              :class="settings.map_side === side ? '' : 'gx-btn--tonal'" :aria-pressed="settings.map_side === side" :disabled="saving"
              @click="update({ map_side: side })">{{ side === 'left' ? 'Left' : 'Right' }}</button></div>
          </div>
          <div v-if="showsDriving" class="gx-row">
            <div class="gx-row__info"><span class="gx-row__label">Directions Side</span><span class="gx-row__desc">Where the next-turn card sits on the driving view when the map is not beside it.</span></div>
            <div class="gx-car-display__tabs"><button v-for="side in ['left', 'right']" :key="side" type="button" class="gx-btn"
              :class="settings.directions_side === side ? '' : 'gx-btn--tonal'" :aria-pressed="settings.directions_side === side" :disabled="saving"
              @click="update({ directions_side: side })">{{ side === 'left' ? 'Left' : 'Right' }}</button></div>
          </div>
          <div v-if="showsMap" class="gx-row">
            <div class="gx-row__info"><span class="gx-row__label">Map Orientation</span><span class="gx-row__desc">Keep north or your direction of travel at the top.</span></div>
            <div class="gx-car-display__tabs"><button v-for="orientation in mapOrientations" :key="orientation.value" type="button" class="gx-btn"
              :class="settings.map_orientation === orientation.value ? '' : 'gx-btn--tonal'" :aria-pressed="settings.map_orientation === orientation.value" :disabled="saving"
              @click="update({ map_orientation: orientation.value })">{{ orientation.label }}</button></div>
          </div>
          <label v-if="showsDriving" class="gx-row">
            <div class="gx-row__info"><span class="gx-row__label">Show Road Camera</span><span class="gx-row__desc">Keep speed, driving status and alerts visible when the camera is hidden.</span></div>
            <span class="gx-switch"><input type="checkbox" :checked="settings.camera" :disabled="saving" @change="update({ camera: $event.target.checked })" />
              <span class="gx-switch__track"></span><span class="gx-switch__thumb"></span></span>
          </label>
          <label v-if="showsDriving" class="gx-row">
            <div class="gx-row__info"><span class="gx-row__label">Show Current Speed</span><span class="gx-row__desc">The speed readout at the top of the driving view.</span></div>
            <span class="gx-switch"><input type="checkbox" :checked="settings.show_current_speed !== false" :disabled="saving" @change="update({ show_current_speed: $event.target.checked })" />
              <span class="gx-switch__track"></span><span class="gx-switch__thumb"></span></span>
          </label>
          <div class="gx-row__label gx-car-display__heading">Blind Spots</div>
          <label class="gx-row">
            <div class="gx-row__info"><span class="gx-row__label">Show Blind Spot Monitors</span><span class="gx-row__desc">Show blind-spot borders, lane warnings and configured side cameras.</span></div>
            <span class="gx-switch"><input type="checkbox" :checked="blindSpotEnabled" :disabled="saving" @change="update({ blind_spot_monitors: $event.target.checked })" />
              <span class="gx-switch__track"></span><span class="gx-switch__thumb"></span></span>
          </label>
          <label v-if="blindSpotEnabled" class="gx-row">
            <div class="gx-row__info"><span class="gx-row__label">Blind Spot Minimum Speed</span><span class="gx-row__desc">Set 0 to show monitors at every speed.</span></div>
            <div class="gx-car-display__tabs"><input class="gx-field" type="number" min="0" :max="isMetric ? 200 : 125" step="1"
              :value="blindSpotMinSpeed" :disabled="saving" @change="updateBlindSpotSpeed" style="width:90px;" /><span>{{ speedUnit }}</span></div>
          </label>
          <div class="gx-row__label gx-car-display__heading">Comma Display</div>
          <label class="gx-row">
            <div class="gx-row__info"><span class="gx-row__label">Turn Off Comma Display</span><span class="gx-row__desc">After the screen timeout while Starpilot Auto is connected. Tap the comma to wake it; connection loss and critical alerts always wake it. Keeping it on uses additional CPU. On by default on comma four; off by default on comma 3X.</span></div>
            <span class="gx-switch"><input type="checkbox" :checked="settings.sleep_device_screen" :disabled="saving" @change="updateSleep" />
              <span class="gx-switch__track"></span><span class="gx-switch__thumb"></span></span>
          </label>
          <template v-if="settings.sleep_device_screen">
            <div class="gx-row__label gx-car-display__heading">Wake Comma Display For</div>
            <label v-for="wake in wakeEvents" :key="wake.value" class="gx-row">
              <div class="gx-row__info"><span class="gx-row__label">{{ wake.label }}</span></div>
              <span class="gx-switch"><input type="checkbox" :checked="wakes(wake.value)" :disabled="saving" @change="updateWakeEvent(wake.value, $event)" />
                <span class="gx-switch__track"></span><span class="gx-switch__thumb"></span></span>
            </label>
          </template>
        </template>
        <template v-else>
          <label class="gx-row">
            <div class="gx-row__info"><span class="gx-row__label">Show Status Column</span><span class="gx-row__desc">Choose the seven stats in the status column. A slot can also show the StarPilot logo or stay blank.</span></div>
            <span class="gx-switch"><input type="checkbox" :checked="settings.show_status_column !== false" :disabled="saving" @change="update({ show_status_column: $event.target.checked })" />
              <span class="gx-switch__track"></span><span class="gx-switch__thumb"></span></span>
          </label>
          <div v-for="layout in statusPositions" v-show="settings.show_status_column !== false" :key="layout.view" class="gx-row">
            <div class="gx-row__info"><span class="gx-row__label">{{ layout.label }} Position</span><span v-if="layout.positions.includes('center')" class="gx-row__desc">Between puts it between the driving view and the map.</span></div>
            <div class="gx-car-display__tabs"><button v-for="position in layout.positions" :key="position" type="button" class="gx-btn"
              :class="settings['status_position_' + layout.view] === position ? '' : 'gx-btn--tonal'" :aria-pressed="settings['status_position_' + layout.view] === position" :disabled="saving"
              @click="update({ ['status_position_' + layout.view]: position })">{{ positionLabels[position] }}</button></div>
          </div>
          <label v-for="(metric, index) in settings.status_slots" v-show="settings.show_status_column !== false" :key="index" class="gx-row">
            <span class="gx-row__label">Slot {{ index + 1 }}</span>
            <GalaxySelect class="gx-field gx-car-display__metric" :value="metric" :disabled="saving"
              :aria-label="'Status slot ' + (index + 1)" @change="updateStatusSlot(index, $event)">
              <option v-for="option in statusMetrics" :key="option.value" :value="option.value">{{ option.label }}</option>
            </GalaxySelect>
          </label>
        </template>
        <p class="gx-row__desc">Changes apply within a second while connected, or the next time Starpilot Auto connects.</p>
      </template>
    </div>
  `,
}
