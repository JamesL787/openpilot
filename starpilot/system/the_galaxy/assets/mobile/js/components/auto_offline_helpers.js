// Pure helpers for the Starpilot Auto offline maps panel; covered by tests/test_auto_offline_helpers.py.

export function formatBytes(bytes) {
  const size = Math.max(0, Number(bytes) || 0)
  if (size >= 1024 ** 3) return `${(size / 1024 ** 3).toFixed(1)} GB`
  if (size >= 1024 ** 2) return `${Math.round(size / 1024 ** 2)} MB`
  return `${Math.round(size / 1024)} KB`
}

export function formatDistance(meters, metric) {
  const m = Math.max(0, Number(meters) || 0)
  if (metric) return m >= 10000 ? `${Math.round(m / 1000)} km` : `${(m / 1000).toFixed(1)} km`
  const miles = m / 1609.344
  return miles >= 10 ? `${Math.round(miles)} mi` : `${miles.toFixed(1)} mi`
}

export function formatDuration(seconds) {
  const minutes = Math.max(1, Math.round((Number(seconds) || 0) / 60))
  return minutes >= 60 ? `${Math.floor(minutes / 60)} h ${minutes % 60} min` : `${minutes} min`
}

export function radiusLabel(km, metric) {
  return metric ? `${Math.round(km)} km` : `${Math.round(km * 0.621371)} mi`
}

export function presetDetailDescription(preset, metric) {
  const radius = radiusLabel(preset?.radius_km, metric)
  switch (preset?.max_zoom) {
    case 16:
      return `Full street-level detail: local roads, street names, alleys and turns within a ${radius} radius.`
    case 15:
      return `City & metro detail: city streets, avenues and neighborhood connectors within a ${radius} radius.`
    case 14:
      return `Road network: major thoroughfares, state routes and county highways within a ${radius} radius.`
    case 13:
      return `Regional highways: interstates, freeways and major transit corridors within a ${radius} radius.`
    default:
      return `${preset?.detail || 'Map detail'} within a ${radius} radius.`
  }
}

function ageText(completedAt, now) {
  const days = Math.floor(Math.max(0, now - completedAt) / 86400)
  if (days === 0) return "today"
  return days === 1 ? "yesterday" : `${days} days ago`
}

// What a saved area or route is doing, in words, plus which actions make sense.
export function itemStatus(item, now) {
  const total = Number(item?.total) || 0
  const done = Number(item?.done) || 0
  const progress = total > 0 ? Math.min(1, done / total) : 0
  const percent = `${Math.floor(progress * 100)}%`
  const state = item?.state || "queued"
  const base = { tone: "info", progress: null, canDownloadNow: false, canUpdate: true, canDelete: true }
  switch (state) {
    case "complete":
      return { ...base, tone: "ok", text: `Saved · ${formatBytes(item.bytes)} · updated ${ageText(Number(item.completed_at) || 0, now)}` }
    case "downloading":
      return { ...base, progress, canUpdate: false, text: `Downloading ${percent} · ${done.toLocaleString("en-US")} of ${total.toLocaleString("en-US")} tiles` }
    case "waiting_wifi":
      return {
        ...base, progress: total ? progress : null, canUpdate: false, canDownloadNow: !item.allow_metered,
        text: item.metered_wifi ? `Waiting · the comma's Wi-Fi is marked metered (${percent} done)` : `Waiting for Wi-Fi (${percent} done)`,
      }
    case "incomplete":
      return { ...base, tone: "warn", text: "Partly saved · the comma retries within an hour" }
    case "storage_full":
      return { ...base, tone: "danger", canUpdate: false, text: "Offline storage is full · delete something to make room" }
    case "no_space":
      return { ...base, tone: "danger", canUpdate: false, text: "The comma is low on free space" }
    case "removing":
      return { ...base, canUpdate: false, canDelete: false, text: "Removing…" }
    default:
      return { ...base, canUpdate: false, text: "Queued · downloads on Wi-Fi" }
  }
}

export function serviceNotice(summary) {
  if (!summary) return null
  if (!summary.service_running) {
    return { tone: "warn", text: "The comma's map downloader isn't running. Restart the comma after installing this update." }
  }
  if (summary.offline) return { tone: "warn", text: "The comma has no internet connection right now. Saved maps keep working; downloads resume when it reconnects." }
  return null
}

// A GeoJSON ring approximating a circle, for drawing saved areas.
export function circlePolygon(latitude, longitude, radiusKm, steps = 64) {
  const ring = []
  const latRadius = radiusKm / 110.574
  const lonRadius = radiusKm / (111.32 * Math.cos((latitude * Math.PI) / 180))
  for (let i = 0; i <= steps; i++) {
    const angle = (2 * Math.PI * i) / steps
    ring.push([+(longitude + lonRadius * Math.cos(angle)).toFixed(6), +(latitude + latRadius * Math.sin(angle)).toFixed(6)])
  }
  return ring
}

// Mapbox Directions (geojson geometry) to routes the comma can save: [lat, lon] points.
export function directionsToRoutes(payload) {
  const routes = Array.isArray(payload?.routes) ? payload.routes : []
  return routes
    .map((route, index) => ({
      id: index === 0 ? "main" : `alt-${index}`,
      label: index === 0 ? "Fastest" : `Alternative ${index}`,
      distance_m: Number(route?.distance) || 0,
      duration_s: Number(route?.duration) || 0,
      points: (route?.geometry?.coordinates || [])
        .filter((c) => Array.isArray(c) && c.length >= 2 && Number.isFinite(c[0]) && Number.isFinite(c[1]))
        .map(([lon, lat]) => [lat, lon]),
    }))
    .filter((route) => route.points.length >= 2)
}

// Map features for saved items: circles for areas, lines for routes.
export function itemsToGeoJson(items) {
  const areas = []
  const routes = []
  for (const item of items || []) {
    if (item.state === "removing") continue
    if (item.kind === "route" && Array.isArray(item.points)) {
      routes.push({ type: "Feature", properties: { id: item.id, name: item.name }, geometry: { type: "LineString", coordinates: item.points.map(([lat, lon]) => [lon, lat]) } })
    } else if (item.radius_km > 0) {
      areas.push({ type: "Feature", properties: { id: item.id, name: item.name }, geometry: { type: "Polygon", coordinates: [circlePolygon(item.latitude, item.longitude, item.radius_km)] } })
    }
  }
  return { areas: { type: "FeatureCollection", features: areas }, routes: { type: "FeatureCollection", features: routes } }
}

// [west, south, east, north] around an item, for fitting the map to it.
export function itemBounds(item) {
  if (item?.kind === "route" && Array.isArray(item.points) && item.points.length) {
    const lats = item.points.map((p) => p[0])
    const lons = item.points.map((p) => p[1])
    return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)]
  }
  const ring = circlePolygon(item.latitude, item.longitude, item.radius_km || 1, 16)
  const lons = ring.map((c) => c[0])
  const lats = ring.map((c) => c[1])
  return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)]
}

// Exact Web Mercator tile footprints, not the requested area boundaries.
export function coverageToGeoJson(coverage) {
  const n = 2 ** coverage.zoom
  const longitude = (x) => x / n * 360 - 180
  const latitude = (y) => Math.atan(Math.sinh(Math.PI * (1 - 2 * y / n))) * 180 / Math.PI
  return { type: "FeatureCollection", features: (coverage.tiles || []).map(([x, y, saved]) => ({
    type: "Feature", properties: { saved, zoom: coverage.zoom },
    geometry: { type: "Polygon", coordinates: [[
      [longitude(x), latitude(y)], [longitude(x + 1), latitude(y)],
      [longitude(x + 1), latitude(y + 1)], [longitude(x), latitude(y + 1)],
      [longitude(x), latitude(y)],
    ]] },
  })) }
}
