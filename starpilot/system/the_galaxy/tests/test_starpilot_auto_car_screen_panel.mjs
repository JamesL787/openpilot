import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import { compile } from "../assets/vendor/vue/vue.esm-browser.js"

const source = readFileSync(new URL("../assets/mobile/js/components/StarpilotAutoCarScreenPanel.js", import.meta.url), "utf8")
const settingsSource = readFileSync(new URL("../assets/mobile/js/views/Settings.js", import.meta.url), "utf8")
const api = {}
const notifications = []
const panel = new Function("api", "showSnackbar",
  source.replace(/^import .*\n/gm, "").replace("export const StarpilotAutoCarScreenPanel =", "return"))(
  api, (...args) => notifications.push(args))

function instance() {
  const state = { ...panel.data() }
  for (const [name, method] of Object.entries(panel.methods)) state[name] = method.bind(state)
  return state
}

async function withoutRetryDelay(action) {
  const originalSetTimeout = globalThis.setTimeout
  globalThis.setTimeout = (callback) => { callback(); return 0 }
  try {
    await action()
  } finally {
    globalThis.setTimeout = originalSetTimeout
  }
}

test("a transient enable race retries and loads the layout", async () => {
  const state = instance()
  let requests = 0
  api.getCarScreen = async () => {
    requests++
    if (requests === 1) throw new Error("Enable Starpilot Auto first")
    return { settings: { onroad_view: "split", map_side: "right", camera: true } }
  }

  await withoutRetryDelay(() => state.load())

  assert.equal(requests, 2)
  assert.equal(state.loading, false)
  assert.equal(state.error, "")
  assert.equal(state.settings.onroad_view, "split")
})

test("a persistent failure stops loading and exposes a retryable error", async () => {
  const state = instance()
  let requests = 0
  api.getCarScreen = async () => { requests++; throw new Error("Connection lost") }

  await withoutRetryDelay(() => state.load())

  assert.equal(requests, 3)
  assert.equal(state.loading, false)
  assert.equal(state.settings, null)
  assert.equal(state.error, "Connection lost")
  assert.deepEqual(notifications.at(-1), ["Connection lost", "error"])
})

test("the panel template compiles with loading, error, and retry states", () => {
  globalThis.document = { createElement: () => ({
    set innerHTML(value) {
      this.textContent = value
      this.children = [{ getAttribute: () => value.match(/foo="(.*)">/s)?.[1] }]
    },
  }) }
  assert.equal(typeof compile(panel.template), "function")
})

test("the Starpilot Auto master toggle has a dedicated settings section", () => {
  assert.match(settingsSource, /s\.name === "Starpilot Auto" && p\.key === "StarpilotAutoEnabled"/)
  const settingsTree = settingsSource.indexOf("<SettingTree")
  const starpilotAutoSection = settingsSource.indexOf('title="Starpilot Auto"')
  assert.ok(settingsTree >= 0 && starpilotAutoSection > settingsTree)
  assert.match(settingsSource.slice(settingsTree, starpilotAutoSection), /<\/div>\s*<GalaxySection/)
  assert.match(settingsSource.slice(starpilotAutoSection), /:param="starpilotAutoParam\(activeSection\)"/)
  assert.match(settingsSource, /<GalaxySection title="Layout"/)
  assert.match(settingsSource, /<StarpilotAutoCarScreenPanel section="layout"/)
  assert.match(settingsSource, /<GalaxySection title="Status Widgets"/)
  assert.match(settingsSource, /<StarpilotAutoCarScreenPanel section="widgets"/)
  assert.doesNotMatch(settingsSource, /<GalaxySection title="Car Display"/)
  assert.doesNotMatch(settingsSource, /StarpilotAutoDiagnosticsPanel|<GalaxySection title="Diagnostics"/)
})

test("embedded sections hide the internal tabs while standalone use keeps them", () => {
  assert.deepEqual(panel.props.section.validator("layout"), true)
  assert.deepEqual(panel.props.section.validator("widgets"), true)
  assert.deepEqual(panel.props.section.validator("other"), false)
  assert.match(panel.template, /v-if="!section" class="gx-car-display__tabs"/)
  assert.match(panel.template, /\(section \|\| tab\) === 'layout'/)
})

test("blind-spot controls convert the displayed unit back to metres per second", () => {
  const state = instance()
  state.isMetric = false
  state.speedFactor = panel.computed.speedFactor.call(state)
  let change
  state.update = (value) => { change = value }

  state.updateBlindSpotSpeed({ target: { value: "30" } })

  assert.ok(Math.abs(change.blind_spot_min_speed_ms - 13.4112) < 0.001)
  assert.match(panel.template, /Show Blind Spot Monitors/)
  assert.match(panel.template, /Blind Spot Minimum Speed/)
})

test("C4 screen sleep uses the existing car-screen settings API", async () => {
  const state = instance()
  state.settings = { sleep_device_screen: false, camera: true }
  api.setCarScreen = async (change) => {
    assert.deepEqual(change, { sleep_device_screen: true })
    return { settings: { ...state.settings, ...change } }
  }
  await state.update({ sleep_device_screen: true })
  assert.equal(state.settings.sleep_device_screen, true)
  assert.equal(state.settings.camera, true)
  assert.match(panel.template, /Turn Off Comma Display/)
  assert.match(panel.template, /Tap the comma to wake/)
})

test("turning the C4 screen sleep off warns about CPU and cancelling keeps it on", async () => {
  const state = instance()
  state.settings = { sleep_device_screen: true, sleep_wake_events: ["StandbyWakeWarningAlert"] }
  const changes = []
  state.update = (change) => { changes.push(change) }
  const prompts = []
  const originalWindow = globalThis.window
  try {
    globalThis.window = { confirm: (message) => { prompts.push(message); return false } }
    const target = { checked: false }
    state.updateSleep({ target })
    assert.equal(target.checked, true, "a cancelled warning snaps the switch back")
    assert.deepEqual(changes, [])
    assert.match(prompts[0], /additional CPU/)

    globalThis.window.confirm = () => true
    state.updateSleep({ target: { checked: false } })
    assert.deepEqual(changes, [{ sleep_device_screen: false }])

    prompts.length = 0
    state.updateSleep({ target: { checked: true } })
    assert.deepEqual(changes.at(-1), { sleep_device_screen: true })
    assert.equal(prompts.length, 0, "turning it back off needs no warning")
  } finally {
    globalThis.window = originalWindow
  }
})

test("wake choices save in a stable order and the status column position per layout", () => {
  const state = instance()
  state.settings = { sleep_wake_events: ["StandbyWakeWarningAlert"] }
  let change
  state.update = (value) => { change = value }
  state.updateWakeEvent("StandbyWakeTurnSignal", { target: { checked: true } })
  assert.deepEqual(change, { sleep_wake_events: ["StandbyWakeWarningAlert", "StandbyWakeTurnSignal"] })
  state.updateWakeEvent("StandbyWakeWarningAlert", { target: { checked: false } })
  assert.deepEqual(change, { sleep_wake_events: [] })
  assert.ok(!state.wakeEvents.some(item => item.value === "StandbyWakeCriticalAlert"), "critical alerts always wake")
  assert.deepEqual(state.statusPositions.map(item => [item.view, item.positions]),
    [["split", ["left", "center", "right"]], ["driving", ["left", "right"]], ["map", ["left", "right"]]])
  assert.match(panel.template, /Show Current Speed/)
  assert.match(panel.template, /status_position_/)
  assert.doesNotThrow(() => compile(panel.template))
})
