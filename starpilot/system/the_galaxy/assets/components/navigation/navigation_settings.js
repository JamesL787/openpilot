import { html, reactive } from "/assets/vendor/arrow-core.js";

// Navigation settings shown on the classic Navigation page. Labels and descriptions come from
// device_settings_layout.json (the single source of setting text). Writes use the same
// PUT /api/params endpoint as the Device Settings page; route preference defaults use
// /api/navigation/preferences through the caller's toggleRoutePreference.
export const LAYOUT_URL = "/assets/components/tools/device_settings_layout.json?v=nav-settings-4";

export const NAV_SETTING_KEYS = [
  "NavigationUI",
  "NavDesiresAllowed",
  "NavLanePositioningAllowed",
  "NavExitAutoKeep",
  "NavPassingSuggest",
  "NavExitOnlyWarn",
  "NavKeepRightReminder",
  "TurnDesires",
  "VASMEnabled",
  "NavLongitudinalAllowed",
  "NavOffRampSlowdown",
  "NavJamSlowdown",
  "NavTrafficReroute",
  "ClearNavOnOffroad",
  "ClearNavOnOffroadTimeoutMinutes",
];

// Boolean attributes must be bound as functions: arrow-core removes an attribute only when a
// function binding returns false; a static false renders as the string "false" (still set).
// Shown only while their on-page parent is on.
const ON_PAGE_PARENT = {
  NavLanePositioningAllowed: "NavDesiresAllowed",
  NavExitAutoKeep: "NavLanePositioningAllowed",
  NavPassingSuggest: "VASMEnabled",
  NavKeepRightReminder: "VASMEnabled",
  NavOffRampSlowdown: "NavLongitudinalAllowed",
  NavJamSlowdown: "NavLongitudinalAllowed",
  ClearNavOnOffroadTimeoutMinutes: "ClearNavOnOffroad",
};

// Layout parents that are not on this page but still gate the setting in code.
const CODE_GATES = {
  TurnDesires: { key: "LateralTune", message: "Turn on Lateral Tuning in Device Settings to use this." },
  NavLongitudinalAllowed: { key: "LongitudinalTune", message: "Turn on Longitudinal Tuning in Device Settings to use this." },
  NavOffRampSlowdown: { key: "LongitudinalTune", message: "Turn on Longitudinal Tuning in Device Settings to use this." },
  NavJamSlowdown: { key: "LongitudinalTune", message: "Turn on Longitudinal Tuning in Device Settings to use this." },
};

const ROUTE_PREFERENCE_ROWS = [
  { key: "avoid_tolls", label: "Avoid tolls" },
  { key: "avoid_highways", label: "Avoid highways" },
  { key: "avoid_ferries", label: "Avoid ferries" },
  { key: "prefer_eco", label: "Prefer fuel-efficient routes" },
];

export const EXIT_LANE_CHANGE_INFO = "With Route Lane Positioning on, turning on the blinker toward a highway exit confirms the lane change. It is blocked while blind spot monitoring or V-ASM sees a car on that side. If the exit needs more lanes, each further lane change also needs a steering nudge toward the exit.";

const navSettingsState = reactive({
  status: "idle",
  error: "",
  meta: {},
  values: {},
  saving: "",
});

async function loadNavSettings() {
  navSettingsState.status = "loading";
  navSettingsState.error = "";
  try {
    const [layoutRes, valuesRes] = await Promise.all([
      fetch(LAYOUT_URL, { cache: "no-store" }),
      fetch("/api/params/all"),
    ]);
    if (!layoutRes.ok || !valuesRes.ok) throw new Error("Could not load navigation settings.");
    const layout = await layoutRes.json();
    const values = await valuesRes.json();
    const meta = {};
    for (const section of layout || []) {
      for (const p of section.params || []) {
        if (NAV_SETTING_KEYS.includes(p.key) && !meta[p.key]) meta[p.key] = p;
      }
    }
    navSettingsState.meta = meta;
    navSettingsState.values = values || {};
    navSettingsState.status = "ready";
  } catch (err) {
    navSettingsState.error = err?.message || "Could not load navigation settings.";
    navSettingsState.status = "error";
  }
}

function lockReason(param) {
  const values = navSettingsState.values;
  if (param?.requires_offroad && values.IsOnroad) return "This setting can only be changed while parked.";
  if (param?.requires_nonempty_key) {
    const val = values[param.requires_nonempty_key];
    if (!val || val === "{}") return param.disabled_reason || "Required configuration missing.";
  }
  const gate = CODE_GATES[param?.key];
  if (gate && !values[gate.key]) return gate.message;
  return "";
}

function isVisible(key) {
  const parent = ON_PAGE_PARENT[key];
  return !parent || !!navSettingsState.values[parent];
}

async function writeParam(key, value, inputEl) {
  const previous = navSettingsState.values[key];
  navSettingsState.saving = key;
  navSettingsState.values = { ...navSettingsState.values, [key]: value };
  try {
    const res = await fetch("/api/params", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, value }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || data.message || "Failed to update parameter");
    const updated = data.updated && typeof data.updated === "object" ? data.updated : {};
    navSettingsState.values = { ...navSettingsState.values, ...updated };
    showSnackbar(data.message || `Parameter '${key}' updated.`);
  } catch (err) {
    navSettingsState.values = { ...navSettingsState.values, [key]: previous };
    if (inputEl) {
      if (inputEl.type === "checkbox") inputEl.checked = !!previous;
      else inputEl.value = previous ?? "";
    }
    showSnackbar(err?.message || "Network error — is the device reachable?", "error");
  } finally {
    navSettingsState.saving = "";
  }
}

function onNumericChange(param, e) {
  const raw = Number(e.target.value);
  const min = Number.isFinite(Number(param.min)) ? Number(param.min) : -Infinity;
  const max = Number.isFinite(Number(param.max)) ? Number(param.max) : Infinity;
  if (!Number.isFinite(raw)) {
    e.target.value = navSettingsState.values[param.key] ?? "";
    return;
  }
  const value = Math.round(Math.min(max, Math.max(min, raw)));
  e.target.value = value;
  void writeParam(param.key, value, e.target);
}

function settingRow(key) {
  return html`${() => {
    const param = navSettingsState.meta[key];
    if (!param || !isVisible(key)) return "";
    const reason = lockReason(param);
    const isChild = !!ON_PAGE_PARENT[key];
    const control = param.ui_type === "numeric"
      ? html`<input type="number" class="ds-text-input nav-settings-number" id="nav-setting-${key}" aria-label="${param.label}"
          min="${param.min ?? ""}" max="${param.max ?? ""}" step="${param.step ?? 1}"
          value="${() => navSettingsState.values[key] ?? ""}" disabled="${() => reason !== "" || navSettingsState.saving !== ""}"
          @change="${e => onNumericChange(param, e)}" />`
      : html`<input type="checkbox" class="ds-toggle" id="nav-setting-${key}" aria-label="${param.label}"
          checked="${() => !!navSettingsState.values[key]}" disabled="${() => reason !== "" || navSettingsState.saving !== ""}"
          @change="${e => writeParam(key, !!e.target.checked, e.target)}" />`;
    return html`
      <div class="${"ds-row nav-settings-row" + (isChild ? " ds-child-modifier" : "")}" data-setting-key="${key}">
        <div class="ds-row-info">
          <div class="ds-row-text">
            <div class="ds-row-heading"><span class="ds-row-label">${param.label}</span></div>
            ${param.description ? html`<div class="ds-row-desc">${param.description}</div>` : ""}
            ${reason ? html`<div class="ds-row-desc"><strong>Locked:</strong> ${reason}</div>` : ""}
          </div>
        </div>
        ${control}
      </div>
    `;
  }}`;
}

function preferenceRow(row, getRoutePreferences, toggleRoutePreference) {
  return html`
    <div class="ds-row nav-settings-row" data-pref-key="${row.key}">
      <div class="ds-row-info">
        <div class="ds-row-text">
          <div class="ds-row-heading"><span class="ds-row-label">${row.label}</span></div>
        </div>
      </div>
      <input type="checkbox" class="ds-toggle" id="nav-pref-${row.key}" aria-label="${row.label}"
        checked="${() => !!getRoutePreferences()?.[row.key]}"
        @change="${() => toggleRoutePreference(row.key)}" />
    </div>
  `;
}

export function NavigationSettings({ getRoutePreferences, toggleRoutePreference, onClose }) {
  if (navSettingsState.status === "idle") void loadNavSettings();
  return html`
    <div class="navigation-settings-panel">
      <section class="ds-section">
        <div class="ds-section-header ds-static-header">
          <i class="bi bi-signpost-split"></i>
          <span class="ds-section-title">Navigation Settings</span>
          ${onClose ? html`<button type="button" class="navigation-settings-close" aria-label="Close navigation settings" @click="${onClose}"><i class="bi bi-x-lg"></i></button>` : ""}
        </div>
        <div class="ds-section-body">
          ${() => {
            if (navSettingsState.status === "loading" || navSettingsState.status === "idle") return html`<div class="ds-row"><span class="ds-row-desc">Loading navigation settings…</span></div>`;
            if (navSettingsState.status === "error") return html`<div class="ds-row"><span class="ds-row-desc">${navSettingsState.error}</span></div>`;
            return "";
          }}
          ${NAV_SETTING_KEYS.map(settingRow)}
          <div class="ds-row nav-settings-row nav-settings-exit-info">
            <div class="ds-row-info">
              <div class="ds-row-text">
                <div class="ds-row-heading"><span class="ds-row-label">How exit lane changes work</span></div>
                <div class="ds-row-desc">${EXIT_LANE_CHANGE_INFO}</div>
              </div>
            </div>
          </div>
        </div>
      </section>
      <section class="ds-section">
        <div class="ds-section-header ds-static-header">
          <i class="bi bi-sliders"></i>
          <span class="ds-section-title">Default Route Preferences</span>
        </div>
        <div class="ds-section-body">
          ${ROUTE_PREFERENCE_ROWS.map(row => preferenceRow(row, getRoutePreferences, toggleRoutePreference))}
          <div class="ds-row"><span class="ds-row-desc">Saved as defaults for new routes. Changing one while navigating re-sends the active route with the new preference.</span></div>
        </div>
      </section>
    </div>
  `;
}
