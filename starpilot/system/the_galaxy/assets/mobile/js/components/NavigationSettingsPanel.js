import { api, showSnackbar } from "../api.js"
import { applyParamChange } from "../params.js"
import { SettingTree } from "./SettingTree.js?v=starpilot-auto-uploads-1"
import { GalaxySection } from "./GalaxySection.js"

// Navigation toggles shown on the Navigation tab. Labels and descriptions come from
// device_settings_layout.json (the single source of setting text); writes go through
// the same api.updateParam (PUT /api/params) path as the Settings view.
export const NAV_SETTING_KEYS = [
  "NavigationUI",
  "NavDesiresAllowed",
  "NavLanePositioningAllowed",
  "NavExitAutoKeep",
  "NavPassingSuggest",
  "TurnDesires",
  "VASMEnabled",
  "NavLongitudinalAllowed",
  "NavOffRampSlowdown",
  "NavJamSlowdown",
  "NavTrafficReroute",
  "ClearNavOnOffroad",
  "ClearNavOnOffroadTimeoutMinutes",
]

// Layout parents that are not shown here but still gate the setting in code.
const CODE_GATES = {
  NavExitAutoKeep: { key: "NavLanePositioningAllowed", message: "Turn on Route Lane Positioning to use this." },
  TurnDesires: { key: "LateralTune", message: "Turn on Lateral Tuning in Settings to use this." },
  NavLongitudinalAllowed: { key: "LongitudinalTune", message: "Turn on Longitudinal Tuning in Settings to use this." },
  NavOffRampSlowdown: { key: "LongitudinalTune", message: "Turn on Longitudinal Tuning in Settings to use this." },
  NavJamSlowdown: { key: "LongitudinalTune", message: "Turn on Longitudinal Tuning in Settings to use this." },
}

export const ROUTE_PREFERENCE_ROWS = [
  { key: "avoid_tolls", label: "Avoid tolls" },
  { key: "avoid_highways", label: "Avoid highways" },
  { key: "avoid_ferries", label: "Avoid ferries" },
  { key: "prefer_eco", label: "Prefer fuel-efficient routes" },
]

export const NavigationSettingsPanel = {
  name: "NavigationSettingsPanel",
  components: { SettingTree, GalaxySection },
  data() {
    return {
      loading: true,
      error: "",
      params: [],
      values: {},
      expanded: { NavDesiresAllowed: true, ClearNavOnOffroad: true },
      routePreferences: { avoid_tolls: false, avoid_highways: false, avoid_ferries: false, prefer_eco: false },
      savingPreference: "",
      ROUTE_PREFERENCE_ROWS,
    }
  },
  async mounted() {
    await this.load()
  },
  methods: {
    async load() {
      this.loading = true
      this.error = ""
      try {
        const [layout, values, preferences] = await Promise.all([
          api.getLayout(),
          api.getParams(),
          api.getNavigationPreferences().catch(() => null),
        ])
        const byKey = new Map()
        for (const section of layout || []) {
          for (const p of section.params || []) {
            if (NAV_SETTING_KEYS.includes(p.key) && !byKey.has(p.key)) byKey.set(p.key, p)
          }
        }
        // Re-root params whose layout parent is not on this page so they render at the top level.
        this.params = NAV_SETTING_KEYS.filter((k) => byKey.has(k)).map((k) => {
          const p = byKey.get(k)
          return NAV_SETTING_KEYS.includes(p.parent_key) ? p : { ...p, parent_key: null }
        })
        this.values = values || {}
        const prefs = preferences?.routePreferences
        if (prefs && typeof prefs === "object") this.routePreferences = { ...this.routePreferences, ...prefs }
      } catch (e) {
        this.error = e?.message || "Could not load navigation settings."
      } finally {
        this.loading = false
      }
    },
    onParamChange(patch) {
      this.values = applyParamChange(this.values, patch)
    },
    toggleManage(key) {
      this.expanded = { ...this.expanded, [key]: !this.expanded[key] }
    },
    lockReason(param) {
      if (param?.requires_offroad && this.values.IsOnroad) return "This setting can only be changed while parked."
      if (param?.requires_nonempty_key) {
        const val = this.values[param.requires_nonempty_key]
        if (!val || val === "{}") return param.disabled_reason || "Required configuration missing."
      }
      const gate = CODE_GATES[param?.key]
      if (gate && !this.values[gate.key]) return gate.message
      return ""
    },
    async togglePreference(key, event) {
      const next = !!event?.target?.checked
      const prev = !!this.routePreferences[key]
      this.routePreferences = { ...this.routePreferences, [key]: next }
      this.savingPreference = key
      try {
        const saved = await api.setNavigationPreferences(this.routePreferences)
        const prefs = saved?.routePreferences
        if (prefs && typeof prefs === "object") this.routePreferences = { ...this.routePreferences, ...prefs }
        showSnackbar("Route preferences saved. They apply to the next route you start.")
      } catch (e) {
        this.routePreferences = { ...this.routePreferences, [key]: prev }
        showSnackbar(e?.message || "Could not save route preferences.", "error")
      } finally {
        this.savingPreference = ""
      }
    },
  },
  template: `
    <div class="gx-navigation-settings" style="display:grid; gap:12px;">
      <div v-if="loading" class="gx-row__desc" style="padding: var(--sp-3);">Loading navigation settings…</div>
      <div v-else-if="error" class="gx-row__desc" style="padding: var(--sp-3);">{{ error }}</div>
      <template v-else>
        <GalaxySection title="Navigation Settings" icon="bi-signpost-split">
          <SettingTree :params="params" :values="values" :expanded="expanded" :lock-reason="lockReason"
            @change="onParamChange" @manage="toggleManage" />
          <div class="gx-row gx-navigation-exit-info">
            <div class="gx-row__info">
              <span class="gx-row__label">How exit lane changes work</span>
              <span class="gx-row__desc">With Route Lane Positioning on, turning on the blinker toward a highway exit confirms the lane change. It is blocked while blind spot monitoring or V-ASM sees a car on that side. If the exit needs more lanes, each further lane change also needs a steering nudge toward the exit.</span>
            </div>
          </div>
        </GalaxySection>
        <GalaxySection title="Default Route Preferences" icon="bi-sliders">
          <div v-for="row in ROUTE_PREFERENCE_ROWS" :key="row.key" class="gx-row" :data-pref-key="row.key">
            <div class="gx-row__info">
              <span class="gx-row__label">{{ row.label }}</span>
            </div>
            <label class="gx-switch">
              <input type="checkbox" :checked="!!routePreferences[row.key]" :disabled="savingPreference !== ''"
                @change="togglePreference(row.key, $event)" />
              <span class="gx-switch__track"></span>
              <span class="gx-switch__thumb"></span>
            </label>
          </div>
          <div class="gx-row__desc" style="padding: 0 var(--sp-3) var(--sp-3);">Saved as defaults for new routes. The route pills on the Destination tab change them for the active route.</div>
        </GalaxySection>
      </template>
    </div>
  `,
}
