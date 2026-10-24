import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { OnroadLayoutPage, validSnapshot, validDocument, widgetSize } from "../web/js/onroad-layout.js"

// Use the server's real registry so a UI gate cannot silently reject a newly exposed widget.
const data = JSON.parse(execFileSync(process.env.PYTHON || "python3", ["-c", `
import json
from openpilot.starpilot.ui.onroad_customization import customization_metadata, default_document
print(json.dumps(dict(document=default_document(), defaults=default_document(), metadata=customization_metadata(),
                     revision="native", editable=True, valid=True, activeProfile="large", supportedProfiles=["large"])))
`], { encoding: "utf8" }))
assert.equal(validSnapshot(data), true)
for (const version of [9, 11]) {
  assert.equal(validSnapshot({ ...data, document: { ...data.document, version } }), false)
  assert.equal(validSnapshot({ ...data, defaults: { ...data.defaults, version } }), false)
}
const vm = { ...OnroadLayoutPage.setup({ mode: "local", unauthorized() {} }), $emit() {}, $refs: {} }
for (const [key, getter] of Object.entries(OnroadLayoutPage.computed)) Object.defineProperty(vm, key, { get: () => getter.call(vm) })
for (const [key, method] of Object.entries(OnroadLayoutPage.methods)) vm[key] = method.bind(vm)
for (const feed of [vm.artFeed, vm.backdropFeed]) {
  feed.start = () => { feed.active = true }
  feed.update = () => {}
  feed.stop = () => { feed.active = false }
}
vm.state.data = data
vm.state.draft = structuredClone(data.document)
vm.state.status = "ready"
assert.equal(data.document.layouts.large.nav_card.enabled, true, "the native turn card stays on after an upgrade")
assert(!vm.inactiveWidgets.some(widget => widget.id === "nav_card"))
vm.changePosition("nav_card", 100, 300)
assert.equal(validDocument(vm.state.draft, data.metadata), true)
for (const id of ["nav_map", "stopped_timer", "jetlink_status"]) {
  assert(vm.inactiveWidgets.some(widget => widget.id === id))
  vm.add(id)
  assert.equal(vm.layout[id].enabled, true)
  vm.changePosition(id, 100, 300)
  assert.equal(vm.layout[id].x, 100)
  assert.equal(validDocument(vm.state.draft, data.metadata), true)
}
vm.state.selected = "nav_map"
vm.boxInput("width", { target: { value: "900" } })
vm.boxInput("height", { target: { value: "500" } })
vm.opacityInput({ target: { value: "35" } })
assert.deepEqual(widgetSize(vm.selectedWidget, vm.selectedPosition), [900, 500])
assert.equal(vm.layout.nav_map.opacity, 35)
assert.equal(validDocument(vm.state.draft, data.metadata), true)
vm.state.selected = "jetlink_status"
vm.opacityInput({ target: { value: "40" } })
assert.equal(vm.layout.jetlink_status.opacity, 40)
assert.equal(validDocument(vm.state.draft, data.metadata), true)
vm.state.selected = "nav_map"
vm.remove("nav_map")
assert.equal(vm.layout.nav_map.enabled, false)
vm.undo()
assert.equal(vm.layout.nav_map.enabled, true)
assert.equal(vm.layout.nav_map.opacity, 35)
assert.equal(validSnapshot({ ...data, document: vm.state.draft }), true)
console.log("Native Big widgets: real metadata, optional add/move/remove, map resize/opacity and undo passed")
