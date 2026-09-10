import { html, reactive } from "/assets/vendor/arrow-core.js"

const state = reactive({
  loading: true,
  saving: false,
  error: "",
  message: "",
  chestnutReady: false,
  isOnroad: false,
  configuration: { enabled: false, lateralModel: "", longitudinalModel: "" },
  runtime: {},
  download: {},
  models: [],
  summary: {},
  manifest: { version: "unknown", shortcomings: [], opportunities: [] },
})

let initialized = false
let pollHandle = null
let selectionDirty = false

function modelById(modelId) {
  return state.models.find(model => model.value === modelId)
}

function modelLabel(modelId) {
  return modelById(modelId)?.label || modelId || "not selected"
}

function readyModels() {
  return state.models.filter(model => model.modelLabArtifactAvailable)
}

function candidateModels(role) {
  const ready = readyModels()
  if (role !== "longitudinal") return ready
  const lateral = modelById(state.configuration.lateralModel)
  if (!lateral) return ready
  return ready.filter(model => model.value !== lateral.value)
}

function selectionError() {
  if (!state.chestnutReady) return "Connect a firmware-ready Chestnut first."
  if (state.isOnroad) return "Park before changing the laboratory pair."
  const lateral = modelById(state.configuration.lateralModel)
  const longitudinal = modelById(state.configuration.longitudinalModel)
  if (!lateral || !longitudinal) return "Choose two small models with published Chestnut artifacts."
  if (lateral.value === longitudinal.value) return "Lateral and longitudinal models must be different."
  if (!lateral.modelLabArtifactAvailable || !longitudinal.modelLabArtifactAvailable) {
    return "Both models need a precompiled AMD artifact in the manifest."
  }
  if (!lateral.modelLabArtifactInstalled || !longitudinal.modelLabArtifactInstalled) {
    return "Prepare both precompiled AMD artifacts first."
  }
  return ""
}

function applyPayload(payload) {
  const draftSelection = {
    lateralModel: state.configuration.lateralModel,
    longitudinalModel: state.configuration.longitudinalModel,
  }
  state.chestnutReady = Boolean(payload?.chestnutReady)
  state.isOnroad = Boolean(payload?.isOnroad)
  state.configuration = {
    enabled: Boolean(payload?.configuration?.enabled),
    lateralModel: selectionDirty
      ? draftSelection.lateralModel
      : String(payload?.configuration?.lateralModel || ""),
    longitudinalModel: selectionDirty
      ? draftSelection.longitudinalModel
      : String(payload?.configuration?.longitudinalModel || ""),
  }
  state.runtime = payload?.runtime && typeof payload.runtime === "object" ? payload.runtime : {}
  state.download = payload?.download && typeof payload.download === "object" ? payload.download : {}
  state.models = Array.isArray(payload?.models) ? payload.models : []
  state.summary = payload?.summary && typeof payload.summary === "object" ? payload.summary : {}
  state.manifest = payload?.manifest && typeof payload.manifest === "object"
    ? payload.manifest
    : { version: "unknown", shortcomings: [], opportunities: [] }
  state.error = String(payload?.configurationError || "")

  const ready = readyModels()
  if (!modelById(state.configuration.lateralModel) && ready.length > 0) {
    state.configuration.lateralModel = ready[0].value
  }
  if (!modelById(state.configuration.longitudinalModel) && ready.length > 1) {
    state.configuration.longitudinalModel = ready.find(model => (
      model.value !== state.configuration.lateralModel
    ))?.value || ""
  }
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, { cache: "no-store", ...options })
  let payload = {}
  try {
    payload = await response.json()
  } catch {
  }
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`)
  return payload
}

async function refresh() {
  try {
    applyPayload(await requestJson("/api/model-laboratory"))
  } catch (error) {
    state.error = error?.message || String(error)
  } finally {
    state.loading = false
    setTimeout(bindControls, 0)
  }
}

async function save(enabled) {
  if (state.saving) return
  if (enabled) {
    const error = selectionError()
    if (error) {
      state.error = error
      return
    }
  }

  state.saving = true
  state.error = ""
  state.message = ""
  try {
    const payload = await requestJson("/api/model-laboratory", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled,
        lateralModel: state.configuration.lateralModel,
        longitudinalModel: state.configuration.longitudinalModel,
      }),
    })
    selectionDirty = false
    applyPayload(payload)
    state.message = String(payload.message || "Model Laboratory configuration saved.")
  } catch (error) {
    state.error = error?.message || String(error)
  } finally {
    state.saving = false
  }
}

async function prepareModel(modelId) {
  if (state.saving || !modelId) return
  state.saving = true
  state.error = ""
  state.message = ""
  try {
    const payload = await requestJson("/api/model-laboratory/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: modelId }),
    })
    state.message = String(payload.message || "Chestnut artifact download queued.")
    await refresh()
  } catch (error) {
    state.error = error?.message || String(error)
  } finally {
    state.saving = false
  }
}

function bindControls() {
  const lateral = document.getElementById("ml-lateral-model")
  const longitudinal = document.getElementById("ml-longitudinal-model")
  const enable = document.getElementById("ml-enable")
  const disable = document.getElementById("ml-disable")
  const refreshButton = document.getElementById("ml-refresh")
  document.querySelectorAll("[data-ml-download]").forEach(button => {
    if (button.dataset.bound === "1") return
    button.dataset.bound = "1"
    button.addEventListener("click", () => prepareModel(button.dataset.mlDownload))
  })

  if (lateral) {
    lateral.value = state.configuration.lateralModel
    if (lateral.dataset.bound !== "1") {
      lateral.dataset.bound = "1"
      lateral.addEventListener("change", event => {
        selectionDirty = true
        state.configuration.lateralModel = event.target.value
        const long = modelById(state.configuration.longitudinalModel)
        const lat = modelById(event.target.value)
        if (long && lat && long.value === lat.value) {
          state.configuration.longitudinalModel = candidateModels("longitudinal")[0]?.value || ""
          if (longitudinal) longitudinal.value = state.configuration.longitudinalModel
        }
      })
    }
  }
  if (longitudinal) {
    longitudinal.value = state.configuration.longitudinalModel
    if (longitudinal.dataset.bound !== "1") {
      longitudinal.dataset.bound = "1"
      longitudinal.addEventListener("change", event => {
        selectionDirty = true
        state.configuration.longitudinalModel = event.target.value
      })
    }
  }
  if (enable && enable.dataset.bound !== "1") {
    enable.dataset.bound = "1"
    enable.addEventListener("click", () => save(true))
  }
  if (disable && disable.dataset.bound !== "1") {
    disable.dataset.bound = "1"
    disable.addEventListener("click", () => save(false))
  }
  if (refreshButton && refreshButton.dataset.bound !== "1") {
    refreshButton.dataset.bound = "1"
    refreshButton.addEventListener("click", refresh)
  }
}

function ensurePolling() {
  if (pollHandle) return
  const poll = async () => {
    if (window.location.pathname !== "/model_laboratory") {
      pollHandle = null
      return
    }
    await refresh()
    pollHandle = setTimeout(poll, 5000)
  }
  pollHandle = setTimeout(poll, 5000)
}

function renderModel(model) {
  const artifactStatus = model.modelLabArtifactInstalled
    ? "AMD ready"
    : model.modelLabArtifactAvailable ? "AMD download needed" : "AMD not published"
  return html`
    <div class="ml-model">
      <div>
        <strong>${model.label}</strong>
        <div class="ml-muted">${model.value} · ${model.series || "Unknown series"}</div>
      </div>
      <div class="ml-chips">
        <span class="ml-chip">${model.version || "unknown version"}</span>
        <span class="ml-chip">${model.modelSize || "small"}</span>
        <span class="${`ml-chip ${model.modelLabArtifactInstalled ? "ml-chip-good" : "ml-chip-warning"}`}">
          ${artifactStatus}
        </span>
        ${model.modelLabArtifactAvailable && !model.modelLabArtifactInstalled ? html`
          <button class="ml-button" data-ml-download="${model.value}" disabled="${() => state.saving || state.isOnroad}">
            Prepare for Chestnut
          </button>
        ` : ""}
      </div>
    </div>
  `
}

export function ModelLaboratory() {
  if (!initialized) {
    initialized = true
    refresh()
  }
  ensurePolling()
  setTimeout(bindControls, 0)

  return html`
    <div class="ml-wrapper">
      <header class="ml-hero">
        <div>
          <h2>Model Laboratory</h2>
          <p>Use the lateral judgment of one small model and the longitudinal judgment of another.</p>
        </div>
        <div class="ml-chips">
          <span class="${() => `ml-chip ${state.chestnutReady ? "ml-chip-good" : "ml-chip-warning"}`}">
            ${() => state.chestnutReady ? "Chestnut ready" : "Chestnut required"}
          </span>
          <span class="${() => `ml-chip ${state.isOnroad ? "ml-chip-warning" : "ml-chip-good"}`}">
            ${() => state.isOnroad ? "Onroad · locked" : "Parked · configurable"}
          </span>
        </div>
      </header>

      ${() => state.error ? html`<div class="ml-alert ml-alert-error">${state.error}</div>` : ""}
      ${() => state.message ? html`<div class="ml-alert ml-alert-good">${state.message}</div>` : ""}
      ${() => state.loading ? html`<div class="ml-card">Loading laboratory status…</div>` : ""}

      ${() => !state.loading ? html`
        <section class="ml-card">
          <div class="ml-card-heading">
            <div>
              <h3>Compose a pair</h3>
              <p>Both precompiled small models stay resident and run every camera frame on Chestnut's AMD GPU.</p>
            </div>
            <span class="${() => `ml-state ${state.configuration.enabled ? "is-enabled" : ""}`}">
              ${() => state.configuration.enabled ? "Enabled" : "Disabled"}
            </span>
          </div>

          <div class="ml-pair">
            <label>
              <span>Lateral model</span>
              <small>Path shape, curvature, lane geometry, and driving desire</small>
              <select id="ml-lateral-model" class="ml-select">
                <option value="">Choose a model</option>
                ${() => candidateModels("lateral").map(model => html`
                  <option value="${model.value}">
                    ${model.label} · ${model.version}
                  </option>
                `)}
              </select>
            </label>
            <div class="ml-plus">+</div>
            <label>
              <span>Longitudinal model</span>
              <small>Speed, acceleration, stopping, leads, and scene confidence</small>
              <select id="ml-longitudinal-model" class="ml-select">
                <option value="">Choose a model</option>
                ${() => candidateModels("longitudinal").map(model => html`
                  <option value="${model.value}">
                    ${model.label} · ${model.version}
                  </option>
                `)}
              </select>
            </label>
          </div>

          <div class="ml-preview">
            <b>${() => modelLabel(state.configuration.lateralModel)}</b>
            <span>steers</span>
            <i class="bi bi-arrow-left-right"></i>
            <b>${() => modelLabel(state.configuration.longitudinalModel)}</b>
            <span>paces</span>
          </div>

          ${() => selectionError() ? html`<p class="ml-validation">${selectionError()}</p>` : ""}
          <div class="ml-actions">
            <button id="ml-enable" class="ml-button ml-button-primary" disabled="${() => state.saving || Boolean(selectionError())}">
              Enable for next drive
            </button>
            <button id="ml-disable" class="ml-button" disabled="${() => state.saving || state.isOnroad || !state.configuration.enabled}">
              Disable
            </button>
            <button id="ml-refresh" class="ml-button" disabled="${() => state.saving}">Refresh</button>
          </div>
        </section>

        <section class="ml-card">
          <div class="ml-card-heading">
            <div>
              <h3>Runtime</h3>
              <p>The configuration activates when modeld starts for a drive.</p>
            </div>
            <span class="${() => `ml-state ${state.runtime?.active ? "is-enabled" : ""}`}">
              ${() => state.runtime?.active ? "Pair active" : state.runtime?.requested ? "Pair requested" : "Inactive"}
            </span>
          </div>
          <div class="ml-runtime-grid">
            <div><span>Lateral</span><b>${() => modelLabel(state.runtime?.lateralModel)}</b></div>
            <div><span>Longitudinal</span><b>${() => modelLabel(state.runtime?.longitudinalModel)}</b></div>
          </div>
          ${() => state.runtime?.error ? html`<div class="ml-alert ml-alert-error">${state.runtime.error}</div>` : ""}
          <p class="ml-muted">Both roles evaluate the same frame at 20 Hz. A runtime failure suppresses that frame and falls back to the built-in QCOM model.</p>
        </section>

        <section class="ml-card">
          <div class="ml-card-heading">
            <div>
              <h3>Available models</h3>
              <p>${() => `${state.summary.ready || 0} ready to pair · ${Math.max((state.summary.published || 0) - (state.summary.ready || 0), 0)} available to download.`}</p>
            </div>
          </div>
          <div class="ml-model-list">${() => readyModels().map(renderModel)}</div>
          <div class="ml-note">
            Model Manager downloads the manifest's precompiled AMD variants. Nothing is compiled on the comma.
            A normal installed model may still need its separate Chestnut artifact.
          </div>
        </section>

      ` : ""}
    </div>
  `
}
