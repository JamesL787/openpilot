// Plots zooming, driven in a real browser against a synthetic 20-minute drive (no device, no route data):
// a sideways drag zooms to the dragged stretch, a tap zooms to a minute, the buttons zoom and pan inside the drive,
// the zoomed stretch shows on the whole-drive charts, and an up/down swipe is left to the page (touch-action pan-y).
// Run: PLAYWRIGHT_MODULE=/path/to/node_modules/playwright/index.mjs node tests/test_plots_zoom_browser.mjs
// (EVIDENCE=<dir> also saves a screenshot of each page just after the first drag.)
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const root = fileURLToPath(new URL('../', import.meta.url))
import { clampRange, panRange, zoomBand, zoomRange, ZOOM_MAX_S, ZOOM_MIN_S } from '../assets/components/tools/drive_plots_shared.mjs'

// --- zoom arithmetic (no browser needed) ---
assert.deepEqual(clampRange(-10, 50, 1200), { start: 0, end: 60 })
assert.deepEqual(clampRange(1180, 1240, 1200), { start: 1140, end: 1200 })
assert.deepEqual(clampRange(30, 10, 1200), { start: 10, end: 30 }, 'a right-to-left drag is the same stretch')
assert.equal(clampRange(100, 100.5, 1200).end - clampRange(100, 100.5, 1200).start, ZOOM_MIN_S)
{ const r = clampRange(0, 5000, 7200); assert.equal(r.end - r.start, ZOOM_MAX_S, 'a very long drag is capped, centred') }
assert.deepEqual(clampRange(0, 60, 20), { start: 0, end: 20 }, 'a drive shorter than the window')
assert.deepEqual(zoomRange({ start: 100, end: 160 }, 0.5, 1200), { start: 115, end: 145 })
assert.deepEqual(zoomRange({ start: 100, end: 160 }, 0.5, 1200, 100), { start: 100, end: 130 }, 'zooms around the pointer')
assert.deepEqual(zoomRange({ start: 0, end: 60 }, 2, 1200), { start: 0, end: 120 }, 'zooming out at the start stays inside')
assert.deepEqual(panRange({ start: 1150, end: 1190 }, 0.5, 1200), { start: 1160, end: 1200 })
assert.deepEqual(panRange({ start: 10, end: 70 }, -0.5, 1200), { start: 0, end: 60 })
assert.deepEqual(zoomBand({ start: 300, end: 600 }, { tMin: 0, tMax: 1200 }), { left: '25.00', width: '25.00' })
assert.equal(zoomBand(null, { tMin: 0, tMax: 1200 }), null)

const pwModule = process.env.PLAYWRIGHT_MODULE || 'playwright'
let chromium
try {
  ({ chromium } = await import(pwModule))
} catch {
  console.log('zoom arithmetic ok; playwright not found, browser part skipped')
  process.exit(0)
}

const DUR = 1200
const ID = '20260929080000'
const overview = { t: [], v: [], lat_active: [], long_active: [], lat_des: [], lat_act: [], long_des: [], long_act: [] }
for (let t = 0; t <= DUR; t += 2) {
  overview.t.push(t); overview.v.push(20 + 5 * Math.sin(t / 60)); overview.lat_active.push(1); overview.long_active.push(1)
  overview.lat_des.push(Math.sin(t / 20)); overview.lat_act.push(Math.sin(t / 20)); overview.long_des.push(0.2 * Math.cos(t / 30))
  overview.long_act.push(0.2 * Math.cos(t / 30))
}
const detail = {
  meta: { id: ID, status: 'done', duration_s: DUR, started_at: '2026-09-29T08:00:00', car: 'SYNTHETIC' },
  analysis: { duration_s: DUR, disengagements: 0, overview, events: [], lateral: {}, longitudinal: {}, takeaways: [], method: '' },
}
// The recorder's own column list, so the zoomed charts see every column they read.
const src = readFileSync(root + 'drive_plots.py', 'utf8')
const COLUMNS = [...src.slice(src.indexOf('\nCOLUMNS = ['), src.indexOf(']', src.indexOf('\nCOLUMNS = ['))).matchAll(/"([a-z0-9_]+)"/g)].map((m) => m[1])
assert.ok(COLUMNS.length > 20 && COLUMNS[0] === 't', 'read COLUMNS from drive_plots.py')
const WAVE = new Set(['lat_des', 'lat_act', 'long_des', 'long_act', 'ang', 'ang_des'])
function windowRows(start, end) {
  const rows = []
  for (let t = start; t <= end; t += 0.05) {
    rows.push(COLUMNS.map((c) => (c === 't' ? t : c === 'v' ? 20 : c.endsWith('_active') || c === 'enabled' ? 1 : WAVE.has(c) ? Math.sin(t) : 0)))
  }
  return rows
}

const MIME = { js: 'text/javascript', mjs: 'text/javascript', css: 'text/css', woff2: 'font/woff2', woff: 'font/woff' }
const browser = await chromium.launch({ executablePath: process.env.BROWSER_EXECUTABLE || undefined, args: ['--no-sandbox'] })
const failures = []
try {
  for (const surface of ['desktop', 'mobile']) {
    const mobile = surface === 'mobile'
    const context = await browser.newContext({ viewport: mobile ? { width: 390, height: 844 } : { width: 1280, height: 900 },
                                               hasTouch: mobile, isMobile: mobile })
    const windows = []
    let delayMs = 0 // like the device, where a window read waits for the one-at-a-time lock
    const page = await context.newPage()
    page.on('pageerror', (e) => failures.push(`${surface}: ${e.message}`))
    await context.route('**/*', async (route) => {
      const url = new URL(route.request().url())
      if (url.origin !== 'http://galaxy.invalid') return route.abort()
      const p = url.pathname
      if (p === '/api/plots/live') return route.fulfill({ json: { recording: null, samples: [], seq: 0, columns: COLUMNS } })
      if (p === '/api/plots/sessions') return route.fulfill({ json: { sessions: [{ ...detail.meta }] } })
      if (p === '/api/plots/settings') return route.fulfill({ json: { auto_record: false } })
      if (p === `/api/plots/sessions/${ID}`) return route.fulfill({ json: detail })
      if (p === `/api/plots/sessions/${ID}/window`) {
        const start = Number(url.searchParams.get('start')); const end = Number(url.searchParams.get('end'))
        windows.push([start, end])
        if (delayMs) await new Promise((r) => setTimeout(r, delayMs))
        return route.fulfill({ json: { columns: COLUMNS, rows: windowRows(start, end) } })
      }
      if (p.startsWith('/api/')) return route.fulfill({ json: {} })
      if (p === '/plots') {
        const mount = mobile
          ? `import {createApp} from 'vue';import {Plots} from '/assets/mobile/js/views/Plots.js';createApp(Plots).mount('#app');`
          : `import {html} from '/assets/vendor/arrow-core.js';import {LivePlots} from '/assets/components/tools/plots.js';html\`\${()=>LivePlots()}\`(document.querySelector('#app'));`
        const css = mobile ? '/assets/mobile/css/material.css' : '/assets/components/tools/plots.css'
        return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head><meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="${css}">
          <script type="importmap">{"imports":{"vue":"/assets/vendor/vue/vue.esm-browser.js"}}</script>
          <style>body{background:#101420;color:#e9eaf2;font:14px system-ui;margin:16px}</style></head>
          <body><main id="app"></main><script type="module">${mount}</script></body></html>` })
      }
      const file = root + p.replace(/^\//, '')
      if (!existsSync(file)) return route.fulfill({ status: 404, body: '' })
      return route.fulfill({ body: readFileSync(file), contentType: MIME[p.split('.').pop()] || 'application/octet-stream' })
    })
    await page.goto('http://galaxy.invalid/plots')
    await page.getByText('20m 00s').first().click()
    const svgs = page.locator('svg[aria-label="Speed (whole drive)"]')
    await svgs.first().waitFor()
    const svg = svgs.first()
    await svg.scrollIntoViewIfNeeded()
    let box = await svg.boundingBox()
    const tAt = (frac) => frac * DUR
    const xAt = (frac) => box.x + frac * box.width
    let y = box.y + box.height / 2

    // Drag from 25 % to 50 % of the drive: the zoom should cover 300 s .. 600 s.
    await page.mouse.move(xAt(0.25), y)
    await page.mouse.down()
    for (let f = 0.26; f <= 0.5; f += 0.02) await page.mouse.move(xAt(f), y)
    await page.mouse.move(xAt(0.5), y)
    await page.mouse.up()
    await page.waitForFunction(() => document.body.innerText.includes('Close zoom'))
    let [s, e] = windows.at(-1)
    assert.ok(Math.abs(s - tAt(0.25)) < 8 && Math.abs(e - tAt(0.5)) < 8, `${surface}: drag asked for ${s}..${e}`)
    assert.equal(await page.locator('.plotBrush').count(), 0, `${surface}: the drag box is removed after the drag`)

    // The whole-drive charts show where the zoom is.
    const band = mobile ? svg.locator('xpath=..').locator('div[style*="122, 162, 247"], div[style*="122,162,247"]')
                        : svg.locator('xpath=..').locator('.plotZoomBand')
    assert.equal(await band.count(), 1, `${surface}: zoom band drawn on the overview`)
    const bb = await band.boundingBox()
    assert.ok(Math.abs((bb.x - box.x) / box.width - 0.25) < 0.02, `${surface}: band starts at 25 %`)

    if (process.env.EVIDENCE) await page.screenshot({ path: `${process.env.EVIDENCE}/plots-zoom-${surface}.png`, fullPage: true })

    // Zoom in, pan later, zoom out: each stays inside the drive and the last press wins.
    const btn = (label) => mobile ? page.locator(`button[aria-label="${label}"]`) : page.locator(`button[title="${label}"]`)
    await btn('Zoom in').click()
    await page.waitForTimeout(150);
    [s, e] = windows.at(-1)
    assert.ok(Math.abs(s - 375) < 2 && Math.abs(e - 525) < 2, `${surface}: zoom in asked for ${s}..${e}`)
    for (let i = 0; i < 12; i++) await btn('Later').click()
    await page.waitForTimeout(200);
    [s, e] = windows.at(-1)
    assert.ok(e <= DUR + 0.1 && Math.abs(e - s - 150) < 1, `${surface}: panning stops at the end of the drive (${s}..${e})`)

    // A tap (no movement) on the overview is still a minute around that spot.
    await svg.scrollIntoViewIfNeeded()
    box = await svg.boundingBox()
    y = box.y + box.height / 2
    await page.mouse.click(xAt(0.1), y)
    await page.waitForTimeout(200);
    [s, e] = windows.at(-1)
    assert.ok(Math.abs(s - (tAt(0.1) - 30)) < 8 && Math.abs(e - s - 60) < 0.5, `${surface}: tap asked for ${s}..${e}`)

    // A drag inside a zoomed chart zooms further in.
    const zoomed = page.locator('svg[aria-label]:not([aria-label*="whole drive"])').last()
    await zoomed.scrollIntoViewIfNeeded()
    const zb = await zoomed.boundingBox()
    const n = windows.length
    await page.mouse.move(zb.x + zb.width * 0.2, zb.y + zb.height / 2)
    await page.mouse.down()
    for (let f = 0.22; f <= 0.6; f += 0.04) await page.mouse.move(zb.x + zb.width * f, zb.y + zb.height / 2)
    await page.mouse.up()
    await page.waitForTimeout(200)
    assert.ok(windows.length > n, `${surface}: drag on a zoomed chart asked for a narrower window`);
    [s, e] = windows.at(-1)
    assert.ok(e - s < 60 && e - s >= 4, `${surface}: narrower window ${s}..${e}`)

    // Slow replies from here on (Steve's review of 46e3bfd9).
    delayMs = 600
    const settle = () => page.waitForTimeout(delayMs + 300)
    const zoomTitle = () => (mobile ? page.locator('div:has(> strong)').last() : page.locator('.plotZoom h2')).innerText()
    await btn('Zoom out').click()
    await settle()
    // 1. Quick presses add up: three "earlier" presses while the first read is still out move three half-screens,
    //    and each press asks for a different range (no repeated reads under the device lock).
    const base = windows.at(-1)
    const span = base[1] - base[0]
    const n1 = windows.length
    for (let i = 0; i < 3; i++) await btn('Earlier').click()
    await settle()
    const asked = windows.slice(n1)
    assert.equal(asked.length, new Set(asked.map((w) => w.join())).size, `${surface}: no repeated reads ${JSON.stringify(asked)}`)
    assert.ok(Math.abs(windows.at(-1)[0] - Math.max(0, base[0] - 1.5 * span)) < 1, `${surface}: three presses ${JSON.stringify(asked)} from ${base}`)
    //    A press that cannot change anything (zoom out at the widest allowed span) asks for nothing.
    for (let i = 0; i < 6; i++) await btn('Zoom out').click()
    await settle()
    const n3 = windows.length
    await btn('Zoom out').click()
    await settle()
    assert.equal(windows.length, n3, `${surface}: zoom out at the limit asks for nothing`)
    // 2. A reply that lands during a drag does not lose the drag.
    await svg.scrollIntoViewIfNeeded()
    box = await svg.boundingBox()
    y = box.y + box.height / 2
    await btn('Zoom in').click()
    await page.mouse.move(xAt(0.6), y)
    await page.mouse.down()
    for (let f = 0.62; f <= 0.8; f += 0.02) { await page.mouse.move(xAt(f), y); await page.waitForTimeout(60) }
    await page.mouse.move(xAt(0.8), y)
    await page.waitForTimeout(delayMs) // the zoom-in reply lands now, mid-drag
    await page.mouse.up()
    await settle();
    [s, e] = windows.at(-1)
    assert.ok(Math.abs(s - tAt(0.6)) < 8 && Math.abs(e - tAt(0.8)) < 8, `${surface}: drag survived a reply (${s}..${e})`)
    const title = await zoomTitle()
    assert.ok(title.includes('4m 00s'), `${surface}: the drag's range is what shows, with its length: ${title}`)
    delayMs = 0

    // Phones: a sideways drag is ours, an up/down swipe belongs to the page.
    const ta = await svg.evaluate((el) => getComputedStyle(el).touchAction)
    assert.equal(ta, 'pan-y', `${surface}: touch-action`)
    if (mobile) {
      // A finger dragged sideways across the whole-drive chart selects; a finger dragged down scrolls the page.
      const cdp = await context.newCDPSession(page)
      const touch = async (type, x, yy) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x, y: yy }] })
      await svg.scrollIntoViewIfNeeded()
      box = await svg.boundingBox()
      y = box.y + box.height / 2
      const before = windows.length
      await touch('touchStart', xAt(0.4), y)
      for (let f = 0.42; f <= 0.7; f += 0.02) await touch('touchMove', xAt(f), y)
      await touch('touchMove', xAt(0.7), y)
      await touch('touchEnd')
      await page.waitForTimeout(300)
      assert.ok(windows.length > before, 'mobile: finger drag asked for a window');
      [s, e] = windows.at(-1)
      assert.ok(Math.abs(s - tAt(0.4)) < 8 && Math.abs(e - tAt(0.7)) < 8, `mobile: finger drag asked for ${s}..${e}`)
      await svg.scrollIntoViewIfNeeded()
      box = await svg.boundingBox()
      const scroll0 = await page.evaluate(() => window.scrollY)
      const nv = windows.length
      const x = xAt(0.3)
      await touch('touchStart', x, box.y + box.height - 10)
      for (let k = 1; k <= 12; k++) await touch('touchMove', x, box.y + box.height - 10 - 15 * k)
      await touch('touchEnd')
      await page.waitForTimeout(400)
      const scroll1 = await page.evaluate(() => window.scrollY)
      assert.ok(scroll1 > scroll0 + 50, `mobile: a vertical swipe scrolls the page (${scroll0} -> ${scroll1})`)
      assert.equal(windows.length, nv, 'mobile: a vertical swipe does not zoom')
      // 3. A second finger cancels the drag instead of restarting it where that finger landed.
      await svg.scrollIntoViewIfNeeded()
      box = await svg.boundingBox()
      y = box.y + box.height / 2
      const nf = windows.length
      const pts = (...xs) => xs.map((x, i) => ({ x, y, id: i + 1 }))
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: pts(xAt(0.3)) })
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: pts(xAt(0.35)) })
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: pts(xAt(0.35), xAt(0.55)) })
      for (let k = 1; k <= 5; k++) {
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: pts(xAt(0.35 - 0.02 * k), xAt(0.55 + 0.04 * k)) })
      }
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
      await page.waitForTimeout(300)
      assert.equal(windows.length, nf, `mobile: a two-finger spread zooms nothing ${JSON.stringify(windows.slice(nf))}`)
      assert.equal(await page.locator('.plotBrush').count(), 0)
    }
    await context.close()
    console.log(`${surface}: drag, tap, band, buttons and nested drag ok`)
  }
} finally {
  await browser.close()
}
assert.deepEqual(failures, [])
console.log('plots zoom browser test ok')
