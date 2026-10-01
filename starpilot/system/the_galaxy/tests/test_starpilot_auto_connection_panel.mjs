import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import { compile } from "../assets/vendor/vue/vue.esm-browser.js"

const source = readFileSync(new URL("../assets/mobile/js/components/StarpilotAutoConnectionPanel.js", import.meta.url), "utf8")
const settingsSource = readFileSync(new URL("../assets/mobile/js/views/Settings.js", import.meta.url), "utf8")
const api = {}
const notifications = []
const navigations = []
const usePolling = () => ({ start() {}, destroy() {} })
const panel = new Function("api", "showSnackbar", "usePolling", "navigate",
  source.replace(/^import .*\n/gm, "").replace("export const StarpilotAutoConnectionPanel =", "return"))(
  api, (...args) => notifications.push(args), usePolling, path => navigations.push(path))

function instance() {
  const state = { ...panel.data() }
  for (const [name, method] of Object.entries(panel.methods)) state[name] = method.bind(state)
  for (const [name, getter] of Object.entries(panel.computed)) {
    Object.defineProperty(state, name, { configurable: true, get: () => getter.call(state) })
  }
  return state
}

function payload(overrides = {}) {
  return {
    status: {
      state: "idle", running: false, receiver_address: "AA:BB:CC:DD:EE:FF", receiver_name: "Family Car",
      configured_view: "car", connection: "wireless", auto_connect: true, auto_paused: false, error: "", stats: {},
      ...overrides,
    },
    devices: [{ address: "AA:BB:CC:DD:EE:FF", name: "Family Car", paired: true, starpilot_auto: true }],
    offroad: true, setup_help: "Pair the Car while parked.", recovery_hint: "Try the Car again.", devices_error: "",
  }
}

test("the live payload drives connection status and car choices", async () => {
  const state = instance()
  api.getStarpilotAutoConnection = async () => payload()

  await state.refresh()

  assert.equal(state.loading, false)
  assert.equal(state.statusText, "Ready · Starts automatically next drive")
  assert.equal(state.autoConnectText, "On")
  assert.equal(state.cars[0].name, "Family Car")
  assert.equal(state.address(state.cars[0].address), "AA:BB:CC:DD:EE:FF")
  assert.equal(state.canConnect, true)
})

test("USB can connect without a paired Car and hides wireless-only controls", () => {
  const state = instance()
  state.apply({ ...payload({ connection: "wired", receiver_address: "", receiver_name: "" }), devices: [] })

  assert.equal(state.wired, true)
  assert.equal(state.connection, "wired")
  assert.equal(state.canConnect, true)
  assert.match(panel.template, /v-if="!wired" class="gx-row"/)
})

test("connection controls call the matching daemon operations", async () => {
  const state = instance()
  state.apply(payload())
  const calls = []
  api.starpilotAutoConnectionOp = async (operation, body) => { calls.push([operation, body]); return payload() }

  await state.toggleConnection()
  await state.setAutoConnect(false)
  await state.setConnection("wired")
  await state.setDisplay("mirror")
  await state.selectCar({ target: { value: "AA:BB:CC:DD:EE:FF" } })

  assert.deepEqual(calls, [
    ["start", {}],
    ["set_auto_connect", { enabled: false }],
    ["set_connection", { connection: "wired" }],
    ["set_view", { view: "mirror" }],
  ])
})

test("pairing opens a daemon window, starts scanning, and moves to Bluetooth", async () => {
  const state = instance()
  state.apply(payload())
  const calls = []
  api.starpilotAutoConnectionOp = async (operation, body) => { calls.push([operation, body]); return payload() }
  api.bluetoothOp = async (operation, body) => { calls.push([`bluetooth:${operation}`, body]) }

  await state.pairNewCar()

  assert.deepEqual(calls, [["prepare_pairing", {}], ["bluetooth:scan", undefined]])
  assert.equal(navigations.at(-1), "/bluetooth")
  assert.match(notifications.at(-1)[0], /Pairing is ready/)
})

test("errors appear below Connect and failed operations remain retryable", async () => {
  const state = instance()
  state.apply(payload({ state: "error", error: "Car rejected authentication" }))
  assert.equal(state.statusText, "Error: Car rejected authentication")

  api.starpilotAutoConnectionOp = async () => { throw new Error("Service stopped") }
  assert.equal(await state.toggleConnection(), false)
  assert.equal(state.error, "Service stopped")
  assert.deepEqual(notifications.at(-1), ["Service stopped", "error"])
})

test("Connect remains the first row and retries when the service is unavailable", async () => {
  const state = instance()
  state.loading = false
  state.error = "Turn on Bluetooth"
  api.getStarpilotAutoConnection = async () => payload()

  assert.equal(state.statusText, "Error: Turn on Bluetooth")
  assert.equal(state.canConnect, true)
  await state.toggleConnection()
  assert.equal(state.status.receiver_name, "Family Car")
  assert.equal(state.error, "")
  assert.ok(panel.template.indexOf("{{ running ? 'Disconnect' : 'Connect' }}") < panel.template.indexOf("Auto Connect"))
})

test("the panel and its Settings section compile and expose every comma control", () => {
  globalThis.document = { createElement: () => ({
    set innerHTML(value) {
      this.textContent = value
      this.children = [{ getAttribute: () => value.match(/foo="(.*)">/s)?.[1] }]
    },
  }) }
  assert.equal(typeof compile(panel.template), "function")
  for (const label of ["Connect", "Car", "Auto Connect", "Link Type", "Display", "Pair a New Car", "Setup Help", "Last Error"]) {
    assert.match(panel.template, new RegExp(label))
  }
  assert.match(settingsSource, /<GalaxySection title="Connection"/)
  assert.match(settingsSource, /<StarpilotAutoConnectionPanel \/>/)
})
