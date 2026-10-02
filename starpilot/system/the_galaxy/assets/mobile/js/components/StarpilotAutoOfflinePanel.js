import { api, showSnackbar } from "../api.js"
import { usePolling } from "../composables.js"
import { GxNotice } from "./GxNotice.js"
import {
  circlePolygon,
  coverageToGeoJson,
  directionsToRoutes,
  formatBytes,
  formatDistance,
  formatDuration,
  itemBounds,
  itemStatus,
  itemsToGeoJson,
  radiusLabel,
  serviceNotice,
} from "./auto_offline_helpers.js?v=auto-offline-3"
import { getMapboxSearchContext } from "../../../components/navigation/navigation_utilities.js?v=nav-route-selection-1"

// Map colors: what the map shows. Both are always downloaded, and no choice has traffic.
const MAP_THEME_OPTIONS = [
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
  { value: "auto", label: "Light & dark (automatic)" },
]

const MAPBOX_STYLE = "mapbox://styles/frogsgomoo/cmcfv151j000o01rcdxebhl76"
const EMPTY = { type: "FeatureCollection", features: [] }

let mapboxLoadPromise = null
function loadMapboxGL() {
  if (mapboxLoadPromise) return mapboxLoadPromise
  mapboxLoadPromise = new Promise((resolve, reject) => {
    if (window.mapboxgl) return resolve(window.mapboxgl)
    const link = document.createElement("link")
    link.rel = "stylesheet"
    link.href = "https://api.mapbox.com/mapbox-gl-js/v3.0.1/mapbox-gl.css"
    document.head.appendChild(link)
    const script = document.createElement("script")
    script.src = "https://api.mapbox.com/mapbox-gl-js/v3.0.1/mapbox-gl.js"
    script.onload = () => resolve(window.mapboxgl)
    script.onerror = () => reject(new Error("Failed to load Mapbox GL"))
    document.head.appendChild(script)
  })
  return mapboxLoadPromise
}

function newSessionToken() {
  return window.crypto?.randomUUID ? window.crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2)
}

// A place search box using the same Mapbox Search Box calls as the Destination tab.
const PlaceSearch = {
  name: "PlaceSearch",
  props: {
    token: { type: String, default: "" },
    position: { type: Object, default: null },
    placeholder: { type: String, default: "Search a place or address" },
    selected: { type: Object, default: null },
    disabled: { type: Boolean, default: false },
  },
  emits: ["select", "clear"],
  data() { return { query: "", suggestions: [], searching: false, request: 0, timer: null, sessionToken: newSessionToken() } },
  watch: {
    selected: { immediate: true, handler(place) { if (place) this.query = place.name || "" } },
    disabled(value) { if (value) this.suggestions = [] },
  },
  beforeUnmount() { clearTimeout(this.timer) },
  methods: {
    context(query) {
      const context = getMapboxSearchContext(query, this.position, navigator.languages || [navigator.language])
      if (this.position) context.proximity = `${this.position.longitude},${this.position.latitude}`
      return context
    },
    onInput(event) {
      if (this.disabled) return
      this.query = String(event?.target?.value ?? this.query)
      if (this.selected) this.$emit("clear")
      clearTimeout(this.timer)
      this.request += 1
      const value = this.query.trim()
      if (value.length < 3 || !this.token) {
        this.suggestions = []
        return
      }
      this.timer = setTimeout(() => this.search(value), 350)
    },
    async search(value) {
      const request = ++this.request
      this.searching = true
      try {
        const payload = await api.mapboxSuggest(value, this.token, this.sessionToken, this.context(value))
        if (request === this.request) this.suggestions = Array.isArray(payload?.suggestions) ? payload.suggestions : []
      } catch (e) {
        if (request === this.request) this.suggestions = []
      } finally {
        if (request === this.request) this.searching = false
      }
    },
    async choose(place) {
      this.suggestions = []
      const name = String(place?.name || "").trim() || this.query.trim()
      try {
        let coordinates = place?.geometry?.coordinates
        if (!coordinates && place?.mapbox_id) {
          const payload = await api.mapboxRetrieve(place.mapbox_id, this.token, this.sessionToken)
          coordinates = payload?.features?.[0]?.geometry?.coordinates
        }
        if (!Array.isArray(coordinates)) throw new Error("no coordinates")
        this.sessionToken = newSessionToken()
        this.$emit("select", { latitude: Number(coordinates[1]), longitude: Number(coordinates[0]), name })
      } catch (e) {
        showSnackbar("Could not find that place's location.", "error")
      }
    },
  },
  template: `
    <div style="position:relative; flex:1; min-width:200px;">
      <input class="gx-field" style="width:100%;" type="search" :value="query" :placeholder="placeholder" :disabled="!token || disabled" @input="onInput" />
      <div v-if="suggestions.length" class="gx-card" style="position:absolute; left:0; right:0; top:100%; z-index:5; margin-top:4px; max-height:260px; overflow:auto;">
        <button v-for="place in suggestions" :key="place.mapbox_id || place.name" type="button" class="gx-row"
          style="width:100%; border:none; background:transparent; color:inherit; cursor:pointer; text-align:left;" @click="choose(place)">
          <div class="gx-row__info">
            <span class="gx-row__label">{{ place.name }}</span>
            <span class="gx-row__desc">{{ place.place_formatted || place.full_address || '' }}</span>
          </div>
        </button>
      </div>
    </div>
  `,
}

// The zooms the car map actually draws; lower ones are only coarse fill-in tiles saved alongside them.
const COVERAGE_ZOOMS = [
  { zoom: 13, label: "Regional" },
  { zoom: 14, label: "Road" },
  { zoom: 15, label: "City" },
  { zoom: 16, label: "Street" },
]

export const StarpilotAutoOfflinePanel = {
  name: "StarpilotAutoOfflinePanel",
  components: { GxNotice, PlaceSearch },
  data() {
    return {
      summary: null,
      loaded: false,
      error: "",
      busy: "",
      mapReady: false,
      coverageEnabled: true,
      coverageZoom: 16,
      coverage: null,
      coverageError: "",
      coverageRequest: 0,
      coverageLoading: false,
      pickOnMap: false,
      areaPoint: null,
      areaRadiusKm: 10,
      areaRadiusInitialized: false,
      areaZoom: null,
      areaEstimate: null,
      areaLoading: false,
      areaError: "",
      areaRequest: 0,
      cacheSettingBusy: false,
      mapThemeOptions: MAP_THEME_OPTIONS,
      routeFrom: null,
      routeTo: null,
      routes: [],
      routeIndex: 0,
      routeEstimate: null,
      routeError: "",
      routeRequest: 0,
      findingRoute: false,
    }
  },
  created() {
    this.map = null
    this.marker = null
    this.poll = usePolling(() => this.refresh(), { interval: 3000 })
    this.poll.start()
  },
  beforeUnmount() {
    this.coverageRequest += 1
    clearTimeout(this.coverageTimer)
    clearTimeout(this.areaTimer)
    this.areaRequest += 1
    this.routeRequest += 1
    this.poll?.destroy()
    this.map?.remove()
    this.map = null
  },
  computed: {
    metric() { return !!this.summary?.isMetric },
    token() { return String(this.summary?.mapboxPublic || "").trim() },
    position() { return this.summary?.position || null },
    items() { return this.summary?.items || [] },
    // A download is already queued or running: block starting another so they run one at a time.
    downloadActive() {
      if (!this.summary?.service_running) return false
      return this.items.some((item) => ["queued", "downloading"].includes(item.state))
    },
    notice() { return serviceNotice(this.summary) },
    storageLabel() {
      if (!this.summary) return "Checking..."
      return `${formatBytes(this.summary.offline_bytes)} of ${formatBytes(this.summary.max_bytes)}`
    },
    mapboxUsageLabel() {
      const usage = this.summary?.usage
      if (!usage) return "Checking..."
      const tiles = Number(usage.tiles || 0).toLocaleString()
      const free = Number(usage.free_tiles || 200000).toLocaleString()
      const routes = Number(usage.directions || 0)
      return `${tiles} of ${free} free tiles` + (routes ? ` • ${routes.toLocaleString()} route lookups` : "")
    },
    downloaderLabel() {
      if (!this.summary) return "Checking..."
      if (!this.summary.service_running) return "Not running"
      if (this.items.some((item) => item.state === "downloading")) return "Downloading"
      if (this.items.some((item) => item.state === "waiting_wifi")) return "Waiting for Wi-Fi"
      if (this.items.some((item) => item.state === "queued")) return "Queued"
      if (this.items.some((item) => ["incomplete", "storage_full", "no_space"].includes(item.state))) return "Needs attention"
      return "Idle"
    },
    activeRouteLabel() {
      const route = this.summary?.route || {}
      const total = Number(route.total) || 0
      if (!total) return "No route set"
      const remaining = Number(route.remaining) || 0
      return remaining > 0 ? `Saving · ${Math.floor(((total - remaining) / total) * 100)}%` : "Saved for offline"
    },
    selectedRoute() { return this.routes[this.routeIndex] || null },
    areaRadiusMin() { return Number(this.summary?.areaRadius?.min_km) || 1 },
    areaRadiusMax() { return Number(this.summary?.areaRadius?.max_km) || 150 },
    areaZooms() { return this.summary?.areaZooms || [14, 15, 16] },
    coverageZooms() { return COVERAGE_ZOOMS },
  },
  watch: {
    items() { this.drawSaved() },
    coverageZoom() { this.scheduleCoverage() },
    coverageEnabled() { this.scheduleCoverage() },
  },
  methods: {
    async refresh() {
      try {
        this.summary = await api.getAutoOffline()
        if (!this.areaRadiusInitialized) {
          this.areaRadiusKm = Number(this.summary?.areaRadius?.default_km) || 10
          this.areaRadiusInitialized = true
        }
        this.error = ""
        if (!this.coverageLoading) this.refreshCoverage()
      } catch (e) {
        this.error = e?.message || "Could not read the offline maps."
      } finally {
        this.loaded = true
      }
      if (this.token && !this.map) {
        await this.$nextTick()
        this.setupMap()
      }
    },

    // ── map ────────────────────────────────────────────────────────────────
    async setupMap() {
      if (this.map || !this.$refs.map || !this.token) return
      try {
        const mapboxgl = await loadMapboxGL()
        mapboxgl.accessToken = this.token
        const center = this.position || { latitude: 39.5, longitude: -98.35 }
        this.map = new mapboxgl.Map({
          container: this.$refs.map,
          style: MAPBOX_STYLE,
          center: [center.longitude, center.latitude],
          zoom: this.position ? 9 : 3,
          attributionControl: false,
        })
        this.map.on("load", () => {
          for (const [id, data] of [["auto-coverage", EMPTY], ["auto-areas", EMPTY], ["auto-selection", EMPTY], ["auto-routes", EMPTY], ["auto-candidates", EMPTY]]) {
            this.map.addSource(id, { type: "geojson", data })
          }
          this.map.addLayer({ id: "auto-coverage-fill", type: "fill", source: "auto-coverage",
            paint: { "fill-color": ["case", ["get", "saved"], "#34c778", "#4096ff"], "fill-opacity": 0.3 } })
          this.map.addLayer({ id: "auto-coverage-line", type: "line", source: "auto-coverage",
            paint: { "line-color": ["case", ["get", "saved"], "#34c778", "#4096ff"], "line-width": 1 } })
          this.map.addLayer({ id: "auto-areas-fill", type: "fill", source: "auto-areas", paint: { "fill-color": "#9d72ff", "fill-opacity": 0.14 } })
          this.map.addLayer({ id: "auto-areas-line", type: "line", source: "auto-areas", paint: { "line-color": "#9d72ff", "line-width": 2 } })
          this.map.addLayer({ id: "auto-selection-fill", type: "fill", source: "auto-selection", paint: { "fill-color": "#f5b642", "fill-opacity": 0.18 } })
          this.map.addLayer({ id: "auto-selection-line", type: "line", source: "auto-selection", paint: { "line-color": "#f5b642", "line-width": 3 } })
          this.map.addLayer({ id: "auto-routes-line", type: "line", source: "auto-routes", paint: { "line-color": "#4096ff", "line-width": 4 } })
          this.map.addLayer({
            id: "auto-candidates-line", type: "line", source: "auto-candidates",
            paint: { "line-color": ["case", ["get", "selected"], "#34c778", "#8a93a6"], "line-width": ["case", ["get", "selected"], 5, 3] },
          })
          this.mapReady = true
          this.refreshCoverage()
          this.drawSaved()
          this.drawAreaSelection()
          this.drawCandidates()
        })
        this.map.on("moveend", () => this.scheduleCoverage())
        this.map.on("click", (event) => {
          if (!this.pickOnMap) return
          this.pickOnMap = false
          this.chooseAreaPoint({ latitude: event.lngLat.lat, longitude: event.lngLat.lng, name: "" }, false)
        })
      } catch (e) {
        this.error = e?.message || "Could not load the map."
      }
    },
    scheduleCoverage() {
      this.coverageRequest += 1
      this.coverageLoading = false
      this.coverage = null
      this.coverageError = ""
      this.map?.getSource("auto-coverage")?.setData(EMPTY)
      clearTimeout(this.coverageTimer)
      this.coverageTimer = setTimeout(() => this.refreshCoverage(), 250)
    },
    async refreshCoverage() {
      if (!this.mapReady || !this.map || !this.coverageEnabled) return
      const request = ++this.coverageRequest
      const bounds = this.map.getBounds()
      this.coverageLoading = true
      try {
        const coverage = await api.getAutoOfflineCoverage({ zoom: this.coverageZoom,
          west: bounds.getWest(), south: bounds.getSouth(), east: bounds.getEast(), north: bounds.getNorth() })
        if (request !== this.coverageRequest) return
        this.coverage = coverage
        this.coverageError = ""
        this.map.getSource("auto-coverage")?.setData(coverageToGeoJson(coverage))
      } catch (e) {
        if (request !== this.coverageRequest) return
        this.coverage = null
        this.map?.getSource("auto-coverage")?.setData(EMPTY)
        this.coverageError = e?.message || "Could not load downloaded tile coverage."
      } finally {
        if (request === this.coverageRequest) this.coverageLoading = false
      }
    },
    drawSaved() {
      if (!this.mapReady) return
      const { areas, routes } = itemsToGeoJson(this.items)
      this.map.getSource("auto-areas")?.setData(areas)
      this.map.getSource("auto-routes")?.setData(routes)
    },
    drawCandidates() {
      if (!this.mapReady) return
      const features = this.routes.map((route, index) => ({
        type: "Feature",
        properties: { selected: index === this.routeIndex },
        geometry: { type: "LineString", coordinates: route.points.map(([lat, lon]) => [lon, lat]) },
      }))
      features.sort((a, b) => Number(a.properties.selected) - Number(b.properties.selected))
      this.map.getSource("auto-candidates")?.setData({ type: "FeatureCollection", features })
    },
    drawAreaSelection() {
      if (!this.mapReady) return
      const features = this.areaPoint ? [{
        type: "Feature", properties: {},
        geometry: { type: "Polygon", coordinates: [circlePolygon(this.areaPoint.latitude, this.areaPoint.longitude, this.areaRadiusKm)] },
      }] : []
      this.map.getSource("auto-selection")?.setData({ type: "FeatureCollection", features })
    },
    showPoint(point, recenter = true) {
      if (!this.map || !window.mapboxgl) return
      this.marker?.remove()
      this.marker = new window.mapboxgl.Marker({ color: "#9d72ff" }).setLngLat([point.longitude, point.latitude]).addTo(this.map)
      this.drawAreaSelection()
      if (recenter) {
        const [west, south, east, north] = itemBounds({ latitude: point.latitude, longitude: point.longitude, radius_km: this.areaRadiusKm })
        this.map.fitBounds([[west, south], [east, north]], { padding: 45, maxZoom: 14 })
      }
    },
    focus(item) {
      if (!this.map) return
      const [west, south, east, north] = itemBounds(item)
      this.map.fitBounds([[west, south], [east, north]], { padding: 40, maxZoom: 13 })
      this.$refs.map?.scrollIntoView?.({ behavior: "smooth", block: "center" })
    },

    // ── areas ──────────────────────────────────────────────────────────────
    useCurrentLocation() {
      if (!this.position) {
        showSnackbar("The comma doesn't have a location yet.", "error")
        return
      }
      this.chooseAreaPoint({ ...this.position, name: "" })
    },
    async chooseAreaPoint(point, recenter = true) {
      if (this.busy) return
      this.pickOnMap = false
      this.areaPoint = point
      this.showPoint(point, recenter)
      await this.estimateArea()
      const isSelected = () => this.areaPoint?.latitude === point.latitude && this.areaPoint?.longitude === point.longitude
      if (!isSelected() || point.name || !this.token) return
      try {
        const payload = await api.mapboxReverseCity(point.latitude, point.longitude, this.token)
        const name = payload?.features?.[0]?.properties?.name
        if (isSelected() && name) this.areaPoint = { ...point, name }
      } catch (e) { /* keep the coordinates as the name */ }
    },
    setAreaRadius(event) {
      const value = Number(event?.target?.value)
      this.areaRadiusKm = Math.min(this.areaRadiusMax, Math.max(this.areaRadiusMin, Number.isFinite(value) ? value : 10))
      this.drawAreaSelection()
      this.scheduleAreaEstimate()
    },
    setCoverageZoom(event) {
      const value = Number(event?.target?.value)
      if (COVERAGE_ZOOMS.some((level) => level.zoom === value)) this.coverageZoom = value
    },
    setAreaZoom(event) {
      const value = Number(event?.target?.value)
      this.areaZoom = this.areaZooms.includes(value) ? value : null
      this.scheduleAreaEstimate()
    },
    scheduleAreaEstimate() {
      if (!this.areaPoint) return
      clearTimeout(this.areaTimer)
      this.areaRequest += 1
      this.areaEstimate = null
      this.areaError = ""
      this.areaLoading = true
      this.areaTimer = setTimeout(() => this.estimateArea(), 250)
    },
    async estimateArea() {
      if (!this.areaPoint) return
      clearTimeout(this.areaTimer)
      const request = ++this.areaRequest
      this.areaEstimate = null
      this.areaError = ""
      this.areaLoading = true
      try {
        const payload = await api.estimateAutoOffline({
          latitude: this.areaPoint.latitude, longitude: this.areaPoint.longitude, radius_km: this.areaRadiusKm,
          max_zoom: this.areaZoom,
        })
        if (request !== this.areaRequest) return
        if (!payload?.area) throw new Error("No area estimate returned. Try again.")
        this.areaEstimate = payload.area
      } catch (e) {
        if (request === this.areaRequest) this.areaError = e?.message || "Could not size that area. Try again."
      } finally {
        if (request === this.areaRequest) this.areaLoading = false
      }
    },
    areaName() {
      const point = this.areaPoint
      return point?.name || (point ? `${point.latitude.toFixed(3)}, ${point.longitude.toFixed(3)}` : "")
    },
    async saveArea() {
      if (!this.areaPoint || !this.areaEstimate || this.busy || this.downloadActive) return
      this.busy = "area"
      try {
        await api.addAutoOfflineArea({
          name: this.areaName(), latitude: this.areaPoint.latitude, longitude: this.areaPoint.longitude,
          radius_km: this.areaRadiusKm, max_zoom: this.areaZoom,
        })
        showSnackbar(`Saving ${radiusLabel(this.areaRadiusKm, this.metric)} around ${this.areaName()} for offline use.`)
        this.areaRequest += 1
        this.areaPoint = null
        this.areaEstimate = null
        this.marker?.remove()
        this.map?.getSource("auto-selection")?.setData(EMPTY)
        await this.refresh()
      } catch (e) {
        showSnackbar(e?.message || "Could not save the area.", "error")
      } finally {
        this.busy = ""
      }
    },
    async setSaveViewedCache(event) {
      if (!this.summary || this.cacheSettingBusy) return
      const enabled = !!event?.target?.checked
      const previous = !!this.summary.save_viewed_cache
      this.summary = { ...this.summary, save_viewed_cache: enabled }
      this.cacheSettingBusy = true
      try {
        const result = await api.setAutoOfflineSettings({ save_viewed_cache: enabled })
        this.summary = { ...this.summary, save_viewed_cache: !!result.save_viewed_cache }
      } catch (e) {
        this.summary = { ...this.summary, save_viewed_cache: previous }
        showSnackbar(e?.message || "Could not update the save-as-you-drive setting.", "error")
      } finally {
        this.cacheSettingBusy = false
      }
    },
    async setMapTheme(event) {
      if (!this.summary || this.cacheSettingBusy) return
      const theme = String(event?.target?.value || "")
      const previous = this.summary.map_theme || "auto"
      if (!MAP_THEME_OPTIONS.some((option) => option.value === theme) || theme === previous) return
      this.summary = { ...this.summary, map_theme: theme }
      this.cacheSettingBusy = true
      try {
        const result = await api.setAutoOfflineSettings({ map_theme: theme })
        this.summary = { ...this.summary, map_theme: result.map_theme }
      } catch (e) {
        this.summary = { ...this.summary, map_theme: previous }
        showSnackbar(e?.message || "Could not change the map colors.", "error")
      } finally {
        this.cacheSettingBusy = false
      }
    },

    // ── routes ─────────────────────────────────────────────────────────────
    clearRoutes() {
      this.routeRequest += 1
      this.routeError = ""
      this.routes = []
      this.routeIndex = 0
      this.routeEstimate = null
      this.drawCandidates()
    },
    async findRoutes() {
      const from = this.routeFrom || (this.position ? { ...this.position, name: "Current location" } : null)
      if (!from) {
        showSnackbar("Choose where the route starts; the comma has no location yet.", "error")
        return
      }
      if (!this.routeTo) return
      this.findingRoute = true
      this.clearRoutes()
      try {
        this.routes = directionsToRoutes(await api.mapboxDirections(from, this.routeTo, this.token))
        if (!this.routes.length) throw new Error("No route found between those places.")
        this.drawCandidates()
        const lons = this.routes.flatMap((r) => r.points.map((p) => p[1]))
        const lats = this.routes.flatMap((r) => r.points.map((p) => p[0]))
        this.map?.fitBounds([[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]], { padding: 40 })
        await this.estimateRoute()
      } catch (e) {
        showSnackbar(e?.message || "Route search failed.", "error")
      } finally {
        this.findingRoute = false
      }
    },
    async selectRoute(index) {
      this.routeIndex = index
      this.drawCandidates()
      await this.estimateRoute()
    },
    async estimateRoute() {
      const request = ++this.routeRequest
      const route = this.selectedRoute
      this.routeError = ""
      this.routeEstimate = null
      if (!route) return
      try {
        const estimate = await api.estimateAutoOffline({ points: route.points })
        if (request === this.routeRequest) this.routeEstimate = estimate
      } catch (e) {
        if (request === this.routeRequest) this.routeError = e?.message || "Could not size that route."
      }
    },
    async saveRoute() {
      const route = this.selectedRoute
      if (!route || this.busy || this.downloadActive) return
      this.busy = "route"
      try {
        await api.addAutoOfflineRoute({
          name: this.routeTo?.name || "Saved route",
          origin_name: this.routeFrom?.name || "Current location",
          points: route.points, distance_m: route.distance_m, duration_s: route.duration_s,
        })
        showSnackbar(`${this.routeTo?.name || "The route"} will be available offline once it downloads.`)
        this.clearRoutes()
        this.routeTo = null
        await this.refresh()
      } catch (e) {
        showSnackbar(e?.message || "Could not save the route.", "error")
      } finally {
        this.busy = ""
      }
    },

    // ── saved items ────────────────────────────────────────────────────────
    status(item) { return itemStatus(item, Date.now() / 1000) },
    describe(item) {
      if (item.kind === "route") {
        const parts = [item.origin_name ? `From ${item.origin_name}` : "", formatDistance(item.distance_m, this.metric), item.duration_s ? formatDuration(item.duration_s) : ""]
        return parts.filter(Boolean).join(" · ")
      }
      const detail = ({ 16: "Street detail", 15: "City detail", 14: "Road detail", 13: "Regional" })[item.max_zoom] || ""
      return [`${radiusLabel(item.radius_km, this.metric)} around`, detail].filter(Boolean).join(" · ")
    },
    async act(item, action) {
      this.busy = item.id
      try {
        await api.autoOfflineAction(item.id, action)
        await this.refresh()
      } catch (e) {
        showSnackbar(e?.message || "That didn't work.", "error")
      } finally {
        this.busy = ""
      }
    },
    async remove(item) {
      if (!window.confirm(`Delete the offline map for ${item.name}? Tiles another saved area or route still uses are kept.`)) return
      this.busy = item.id
      try {
        await api.deleteAutoOffline(item.id)
        await this.refresh()
      } catch (e) {
        showSnackbar(e?.message || "Could not delete it.", "error")
      } finally {
        this.busy = ""
      }
    },
    formatBytes,
    formatDistance,
    formatDuration,
    radiusLabel,
  },
  template: `
    <div style="display:grid; gap:10px;">
      <GxNotice v-if="error" tone="danger" :text="error" style="margin:0;" />

      <p style="margin:0; color:var(--text-muted); font-size:var(--fs-sm);">
        Saved areas and active routes are kept offline for the comma and car screen, and refresh on Wi-Fi every {{ summary?.refresh_days || 90 }} days.
      </p>

      <section class="gx-card" style="margin:0;">
        <div class="gx-row" style="border:none; padding:10px var(--sp-3); align-items:flex-start;">
          <div class="gx-row__info">
            <span class="gx-row__label">Save Maps as You Drive</span>
            <span class="gx-row__desc">While the comma is connected, tiles opened by navigation and the car screen are saved into the same pinned offline storage as downloaded areas. They share the 3 GB limit and are not evicted by the temporary cache. Turning this off stops saving new tiles and keeps ones already saved.</span>
          </div>
          <label class="gx-switch" style="flex:none; margin-top:2px;">
            <input type="checkbox" aria-label="Save maps as you drive" :checked="!!summary?.save_viewed_cache" :disabled="!summary || cacheSettingBusy" @change="setSaveViewedCache" />
            <span class="gx-switch__track"></span><span class="gx-switch__thumb"></span>
          </label>
        </div>
        <div class="gx-row" style="border:none; padding:10px var(--sp-3); align-items:flex-start;">
          <div class="gx-row__info">
            <span class="gx-row__label">Map Colors</span>
            <span class="gx-row__desc">No traffic is shown: saved maps would show the traffic from the day they were downloaded. Light & dark switches at sunrise and sunset where the car is. Saved areas download in both colors, so switching here or on the car's map never needs a download.</span>
          </div>
          <GalaxySelect class="gx-field" style="flex:none; min-width:170px;" :value="summary?.map_theme || 'auto'" :disabled="!summary || cacheSettingBusy" @change="setMapTheme" aria-label="Map colors">
            <option v-for="option in mapThemeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </GalaxySelect>
        </div>
      </section>

      <div style="display:flex; flex-wrap:wrap; align-items:center; gap:6px 14px; font-size:var(--fs-sm); color:var(--text-muted); padding:2px 0;">
        <span>Downloader: <strong style="color:var(--text);">{{ downloaderLabel }}</strong></span>
        <span style="opacity:0.3;">•</span>
        <span>Storage: <strong style="color:var(--text);">{{ storageLabel }}</strong></span>
        <span style="opacity:0.3;">•</span>
        <span title="Map tiles and route lookups this comma requested from Mapbox this month (UTC). Searches and maps in The Galaxy are not included.">Mapbox this month: <strong style="color:var(--text);">{{ mapboxUsageLabel }}</strong></span>
        <span style="opacity:0.3;">•</span>
        <span>Current Route: <strong style="color:var(--text);">{{ summary ? activeRouteLabel : 'Checking...' }}</strong></span>
      </div>

      <GxNotice v-if="notice" :tone="notice.tone" :text="notice.text" style="margin:0;" />
      <GxNotice v-if="loaded && summary && !token" tone="warn"
        text="Add a Mapbox public key in the App Keys tab to search places and draw the map." style="margin:0;" />

      <section class="gx-card" style="margin:0; overflow:hidden;">
        <div class="gx-section__header" style="min-height:42px; padding:8px var(--sp-3);">
          <i class="bi bi-bounding-box-circles" style="font-size:1.15rem;"></i>
          <span class="gx-section__title" style="font-size:var(--fs-base);">Save an Area</span>
        </div>
        <div style="padding:var(--sp-2) var(--sp-3) var(--sp-3); display:grid; gap:8px;">
          <!-- Layout stays put: the map sits right under the place buttons and never moves, and the
               area options below it are always present, so choosing a point or dragging the radius
               only changes values and the circle on the map. -->
          <p style="margin:0; color:var(--text-muted); font-size:var(--fs-xs);">
            Choose a centre, then set the radius. Smaller radii include full street detail; larger ones cover highways.
          </p>
          <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
            <button type="button" class="gx-btn gx-btn--tonal" style="min-height:36px; padding:0 12px;" :disabled="!position || downloadActive" @click="useCurrentLocation"><i class="bi bi-crosshair"></i> Current Location</button>
            <button type="button" class="gx-btn gx-btn--tonal" style="min-height:36px; padding:0 12px;" :disabled="!mapReady || downloadActive" @click="pickOnMap = !pickOnMap">
              <i class="bi bi-pin-map"></i> {{ pickOnMap ? 'Cancel' : 'Pick on Map' }}
            </button>
            <PlaceSearch :token="token" :position="position" :disabled="downloadActive" placeholder="Or search a city or place" @select="chooseAreaPoint($event)" />
          </div>

          <div v-if="token" style="position:relative;">
            <div ref="map" style="height:280px; border-radius:var(--radius-md); overflow:hidden;"></div>
            <div v-if="pickOnMap" class="gx-note" style="position:absolute; top:8px; left:8px; right:8px; margin:0; pointer-events:none; text-align:center;">
              Tap the map where the area should be centred.
            </div>
          </div>

          <template v-if="token">
            <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
              <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
                <input type="checkbox" v-model="coverageEnabled" /> Show downloaded tiles
              </label>
              <label style="display:flex; align-items:center; gap:8px;" :style="coverageEnabled ? '' : 'opacity:.5;'">
                <span class="gx-row__label">Tile detail</span>
                <GalaxySelect class="gx-field" style="min-width:170px;" :value="coverageZoom" :disabled="!coverageEnabled" @change="setCoverageZoom" aria-label="Downloaded tile detail level">
                  <option v-for="level in coverageZooms" :key="level.zoom" :value="level.zoom">{{ level.label }} (zoom {{ level.zoom }})</option>
                </GalaxySelect>
              </label>
            </div>
            <div class="gx-row__desc" style="min-height:2.7em;">
              <template v-if="coverageEnabled">
                <span style="display:block;"><span style="color:#34c778;">■ Saved offline</span> · <span style="color:#4096ff;">■ Temporary cache</span></span>
                <span style="display:block;">
                  <template v-if="coverageError">{{ coverageError }}</template>
                  <template v-else-if="coverage">{{ coverage.tiles.length.toLocaleString() }} saved tiles in view at zoom {{ coverage.zoom }}.{{ coverage.truncated ? ' Zoom in to see them all.' : '' }}</template>
                  <template v-else>Checking downloaded tiles...</template>
                </span>
              </template>
              <template v-else>Turn on to see which map tiles are saved on the comma, at the chosen detail level.</template>
            </div>
          </template>

          <div style="display:grid; gap:8px; border-top:1px solid var(--glass-border, rgba(127,127,127,.15)); padding-top:10px;">
            <div class="gx-row__label" :style="areaPoint ? '' : 'color:var(--text-muted);'">
              {{ areaPoint ? 'Around ' + areaName() : 'No centre chosen yet' }}
            </div>
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:8px 16px; align-items:end;">
              <label style="display:grid; gap:5px;">
                <span class="gx-row__desc" style="margin:0;">Radius: <strong style="color:var(--text);">{{ radiusLabel(areaRadiusKm, metric) }}</strong></span>
                <input type="range" :min="areaRadiusMin" :max="areaRadiusMax" step="1" :value="areaRadiusKm" :disabled="downloadActive" @input="setAreaRadius" aria-label="Offline area radius" style="width:100%; accent-color:var(--primary);" />
              </label>
              <label style="display:grid; gap:5px;" title="Higher zoom shows more streets but needs many more tiles. Lower zooms are saved with it, so the map still works zoomed out.">
                <span class="gx-row__desc" style="margin:0;">Most detailed zoom</span>
                <GalaxySelect class="gx-field gx-field--full" :value="areaZoom ?? ''" :disabled="downloadActive" @change="setAreaZoom" aria-label="Most detailed zoom to download">
                  <option value="">Auto (based on radius)</option>
                  <option v-for="zoom in areaZooms" :key="zoom" :value="zoom">{{ ({14: 'Road', 15: 'City', 16: 'Street'})[zoom] || 'Zoom ' + zoom }} (zoom {{ zoom }})</option>
                </GalaxySelect>
              </label>
            </div>
            <div style="display:flex; align-items:center; gap:8px; min-height:40px;">
              <span class="gx-row__desc" role="status" style="margin:0; flex:1;" :style="areaError ? 'color:var(--error);' : ''">
                <template v-if="!areaPoint">Choose a centre to size the download. The yellow circle on the map shows the area.</template>
                <template v-else-if="areaError">{{ areaError }}</template>
                <template v-else-if="areaLoading || !areaEstimate">Sizing up the area...</template>
                <template v-else-if="areaEstimate.fits">
                  <span style="display:block;"><strong style="color:var(--text);">{{ areaEstimate.detail }} (zoom {{ areaEstimate.max_zoom }})</strong></span>
                  <span style="display:block;">About {{ formatBytes(areaEstimate.bytes) }} · {{ areaEstimate.tiles.toLocaleString() }} tiles</span>
                </template>
                <template v-else>Too large for the offline storage left. Try a smaller radius or zoom.</template>
              </span>
              <button v-if="areaError" type="button" class="gx-btn gx-btn--tonal" style="min-height:34px; padding:0 12px;" @click="estimateArea">Retry</button>
              <button v-else type="button" class="gx-btn gx-btn--tonal" style="min-height:34px; padding:0 12px;"
                :disabled="!areaPoint || !areaEstimate || !areaEstimate.fits || !!busy || downloadActive" @click="saveArea">{{ busy === 'area' ? 'Adding...' : 'Download' }}</button>
            </div>
          </div>
        </div>
      </section>

      <section class="gx-card" style="margin:0;">
        <div class="gx-section__header" style="min-height:42px; padding:8px var(--sp-3);">
          <i class="bi bi-signpost-split" style="font-size:1.15rem;"></i>
          <span class="gx-section__title" style="font-size:var(--fs-base);">Save a Specific Route</span>
        </div>
        <div style="padding:var(--sp-2) var(--sp-3) var(--sp-3); display:grid; gap:8px;">
          <div style="display:flex; align-items:center; gap:8px;">
            <span style="min-width:42px; font-size:var(--fs-sm); font-weight:var(--fw-medium); color:var(--text-muted);">From</span>
            <PlaceSearch :token="token" :position="position" :selected="routeFrom" :disabled="downloadActive"
              :placeholder="position ? 'Current location' : 'Search where you start'"
              @select="routeFrom = $event; clearRoutes()" @clear="routeFrom = null; clearRoutes()" />
          </div>
          <div style="display:flex; align-items:center; gap:8px;">
            <span style="min-width:42px; font-size:var(--fs-sm); font-weight:var(--fw-medium); color:var(--text-muted);">To</span>
            <PlaceSearch :token="token" :position="position" :selected="routeTo" :disabled="downloadActive" placeholder="Search your destination"
              @select="routeTo = $event; clearRoutes()" @clear="routeTo = null; clearRoutes()" />
          </div>
          <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:2px;">
            <button type="button" class="gx-btn gx-btn--tonal" style="min-height:36px; padding:0 14px;" :disabled="!routeTo || findingRoute || !token || downloadActive" @click="findRoutes">
              <i class="bi bi-search"></i> {{ findingRoute ? 'Finding routes...' : 'Find Routes' }}
            </button>
          </div>
          <div v-if="routes.length" style="display:grid; gap:4px; margin-top:4px;">
            <label v-for="(route, index) in routes" :key="route.id" class="gx-row" style="border:none; min-height:0; padding:6px 8px; cursor:pointer; gap:8px; border-radius:var(--radius-md);">
              <input type="radio" name="auto-offline-route" :checked="index === routeIndex" @change="selectRoute(index)" style="accent-color:var(--primary);" />
              <div class="gx-row__info">
                <span class="gx-row__label">{{ route.label }}</span>
                <span class="gx-row__desc" style="margin-top:2px;">{{ formatDuration(route.duration_s) }} · {{ formatDistance(route.distance_m, metric) }}</span>
              </div>
            </label>
            <div style="display:flex; align-items:center; flex-wrap:wrap; gap:8px; padding:4px 0;">
              <span class="gx-row__desc" style="margin:0; flex:1;">
                <template v-if="routeEstimate">
                  <span style="display:block;">About {{ formatBytes(routeEstimate.bytes) }} · {{ routeEstimate.tiles.toLocaleString() }} tiles</span>
                  <span style="display:block;">With street detail at every turn and the destination.</span>
                </template>
                <template v-else-if="!routeError">Sizing the route...</template>
              </span>
              <button type="button" class="gx-btn" style="min-height:36px; padding:0 14px;" :disabled="!routeEstimate || !routeEstimate.fits || busy === 'route' || downloadActive" @click="saveRoute">
                <i class="bi bi-download"></i> {{ busy === 'route' ? 'Saving...' : 'Make Available Offline' }}
              </button>
            </div>
            <GxNotice v-if="routeError" tone="danger" :text="routeError" style="margin:0;" />
            <button v-if="routeError" type="button" class="gx-btn gx-btn--tonal" @click="estimateRoute">Retry sizing</button>
            <GxNotice v-if="routeEstimate && !routeEstimate.fits" tone="warn" text="Not enough offline storage left for this route. Delete an area or route first." style="margin:0;" />
          </div>
        </div>
      </section>

      <section class="gx-card" style="margin:0;">
        <div class="gx-section__header" style="min-height:42px; padding:8px var(--sp-3);">
          <i class="bi bi-hdd-stack" style="font-size:1.15rem;"></i>
          <span class="gx-section__title" style="font-size:var(--fs-base);">Downloads &amp; Saved Maps</span>
          <span class="gx-section__count">{{ items.length }}</span>
        </div>
        <div v-if="!items.length" class="gx-empty" style="margin:0; padding:var(--sp-3);">Nothing saved yet. Save an area around home or make a trip's route available offline.</div>
        <article v-for="item in items" :key="item.id" class="gx-row gx-offline-row" @click="focus(item)">
          <div class="gx-row__info">
            <span class="gx-row__label">
              <i class="bi" :class="item.kind === 'route' ? 'bi-signpost-split' : 'bi-bounding-box-circles'" style="color:var(--primary);"></i>
              {{ item.name }}
            </span>
            <span class="gx-row__desc gx-offline-row__details">{{ describe(item) }}</span>
            <span class="gx-row__desc gx-offline-row__status" :class="{ 'gx-offline-row__status--danger': status(item).tone === 'danger' }">{{ status(item).text }}</span>
            <span v-if="status(item).progress !== null" class="gx-offline-row__progress" role="progressbar" :aria-label="item.name + ' download'" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="Math.floor(status(item).progress * 100)">
              <span :style="'width:' + Math.round(status(item).progress * 100) + '%;'"></span>
            </span>
          </div>
          <div class="gx-row__actions">
            <button v-if="status(item).canDownloadNow" type="button" class="gx-btn gx-btn--tonal gx-btn--icon" title="Download now using the comma's current connection" :disabled="busy === item.id || downloadActive" @click.stop="act(item, 'download_now')"><i class="bi bi-cloud-arrow-down-fill"></i></button>
            <button v-if="status(item).canUpdate" type="button" class="gx-btn gx-btn--tonal gx-btn--icon" title="Update" :disabled="busy === item.id || downloadActive" @click.stop="act(item, 'update')"><i class="bi bi-arrow-clockwise"></i></button>
            <button v-if="status(item).canDelete" type="button" class="gx-btn gx-btn--danger gx-btn--icon" title="Delete" :disabled="busy === item.id" @click.stop="remove(item)"><i class="bi bi-trash"></i></button>
          </div>
        </article>
      </section>
    </div>
  `,
}
