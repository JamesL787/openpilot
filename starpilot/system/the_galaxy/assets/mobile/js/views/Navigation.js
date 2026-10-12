import { NavigationDestinationPanel } from "../components/NavigationDestinationPanel.js?v=nav-route-prefs-1"
import { MapsPanel } from "../components/MapsPanel.js?v=offline-download-4"
import { NavigationKeysPanel } from "../components/NavigationKeysPanel.js"
import { NavigationSettingsPanel } from "../components/NavigationSettingsPanel.js?v=nav-settings-3"
import { SpeedLimitsPanel } from "../components/SpeedLimitsPanel.js"
import { StarpilotAutoOfflinePanel } from "../components/StarpilotAutoOfflinePanel.js?v=offline-layout-8"
import { GalaxySection } from "../components/GalaxySection.js"
import { GalaxyTabs } from "../components/GalaxyTabs.js"
import { useTabRouting } from "../composables.js"

const TABS = {
  nav: "Destination",
  settings: "Settings",
  maps: "Offline Maps",
  keys: "App Keys",
  speeds: "Speed Limits",
}

export const Navigation = {
  name: "Navigation",
  components: {
    NavigationDestinationPanel, NavigationSettingsPanel, MapsPanel, NavigationKeysPanel, SpeedLimitsPanel, GalaxyTabs,
    StarpilotAutoOfflinePanel, GalaxySection,
  },
  data() { return { TABS } },
  setup() {
    return useTabRouting("/navigation", {
      nav: "", settings: "settings", maps: "maps", keys: "keys", speeds: "speeds",
    })
  },
  template: `
    <template v-if="tab === 'nav'">
      <div class="gx-navigation-view">
        <NavigationDestinationPanel />
        <div class="gx-navigation-tabs"><GalaxyTabs :items="TABS" :active="tab" @select="selectTab" /></div>
      </div>
    </template>
    <div v-else class="gx-view">
      <h2 style="margin-top:0;">Navigation & Maps</h2>
      <GalaxyTabs :items="TABS" :active="tab" @select="selectTab" />
      <template v-if="tab === 'maps'">
        <div style="display:grid; gap:12px;">
          <GalaxySection title="Speed Limit &amp; Curve Data" icon="bi-speedometer2">
            <div style="padding: var(--sp-3);">
              <MapsPanel />
            </div>
          </GalaxySection>
          <GalaxySection title="Offline Maps for Starpilot Auto" icon="bi-cloud-arrow-down">
            <div style="padding: var(--sp-3);">
              <StarpilotAutoOfflinePanel />
            </div>
          </GalaxySection>
        </div>
      </template>
      <template v-if="tab === 'settings'"><NavigationSettingsPanel /></template>
      <template v-if="tab === 'keys'"><NavigationKeysPanel /></template>
      <template v-if="tab === 'speeds'"><SpeedLimitsPanel /></template>
    </div>
  `,
}
