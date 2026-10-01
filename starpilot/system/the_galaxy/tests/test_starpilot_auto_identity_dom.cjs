// Render the real identity card and exercise its HTTP API with synthetic responses.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const assets = path.resolve(__dirname, '../assets')
const fixture = `
import {createApp} from 'vue';
import {StarpilotAutoIdentityPanel} from '/assets/mobile/js/components/StarpilotAutoIdentityPanel.js';
createApp({components:{StarpilotAutoIdentityPanel},template:'<div id="update-notice"></div><h2>Starpilot Auto toggles</h2><StarpilotAutoIdentityPanel update-notice-target="#update-notice" />'}).mount('#app');
`
;(async () => {
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_EXECUTABLE})
  try {
    const page = await browser.newPage()
    const errors = [], posts = [], checks = []
    let recommendation = {}, packageVersion = ''
    let job = {state:'idle'}, installed = false, fail = false
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      assert.equal(url.hostname, 'offline.invalid')
      if (url.pathname === '/') return route.fulfill({contentType:'text/html', body:'<html data-theme="dark"><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/assets/mobile/css/material.css"><script type="importmap">{"imports":{"vue":"/assets/vendor/vue/vue.esm-browser.js"}}</script></head><body><div id="app"></div><script type="module" src="/fixture.js"></script></body></html>'})
      if (url.pathname === '/fixture.js') return route.fulfill({contentType:'text/javascript', body:fixture})
      if (url.pathname.startsWith('/api/')) {
        if (url.searchParams.get('check_updates') === '1') checks.push(url.pathname)
        if (route.request().method() === 'POST') {
          posts.push(url.pathname)
          if (fail) return route.fulfill({status:409, contentType:'application/json', body:JSON.stringify({error:'Download unavailable; try manual installation.'})})
          job = {state:'running',stage:'resolving'}
        }
        return route.fulfill({contentType:'application/json', body:JSON.stringify({installed,expires:'2026-12-23',days_left:80,job,
          recommendation,package_version:packageVersion})})
      }
      const file = path.join(assets, url.pathname.slice('/assets/'.length))
      if (url.pathname.startsWith('/assets/') && fs.existsSync(file)) return route.fulfill({path:file})
      return route.fulfill({status:404,body:''})
    })
    for (const width of [320, 800]) {
      await page.setViewportSize({width,height:900})
      await page.goto('http://offline.invalid/')
      const button = page.getByRole('button', {name:'Install recommended version'})
      await button.click()
      await page.getByText('Checking the recommended version…', {exact:true}).waitFor()
      assert.equal(await button.isDisabled(), true)
      for (const [stage, text] of [['checking_package','Verifying the download checksum…'], ['unpacking','Unpacking the app…']]) {
        job = {state:'running', stage}
        await page.getByText(text, {exact:true}).waitFor()
      }
      job = {state:'done',message:'Identity installed.'}; installed = true
      await page.getByText('Identity installed.', {exact:true}).waitFor()
      await page.locator('summary').filter({hasText:'Manual installation'}).click()
      assert.equal(await page.getByRole('button', {name:'Renew from File'}).isEnabled(), true)
      assert.equal(await page.locator('input[type=file]').getAttribute('accept'), '.apk,.xapk,.apkm,application/vnd.android.package-archive')
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
      fail = true
      await button.click()
      await page.getByText('Download unavailable; try manual installation.', {exact:true}).waitFor()
      assert.equal(await button.isEnabled(), true)
      fail = false
      await page.getByText("On this phone or computer, upload the XAPK or APK from an APK mirror. Make sure it is the app itself, not a mirror's store installer.", {exact:true}).waitFor()
      const upload = page.waitForResponse(response => new URL(response.url()).pathname === '/api/starpilot_auto/identity/upload')
      await page.locator('input[type=file]').setInputFiles({name:'starpilot-auto.xapk',mimeType:'application/zip',buffer:Buffer.from('synthetic app package')})
      await upload
      assert.equal(posts.at(-1), '/api/starpilot_auto/identity/upload')
      job = {state:'idle'}
    }
    assert.equal(checks.length, 2, 'one check per page entry, none from progress polling')
    recommendation = {version:'17.10.1',updateAvailable:true}; packageVersion = '17.6.663454'
    await page.goto('http://offline.invalid/')
    await page.getByText('Update to Starpilot Auto certificate available', {exact:true}).waitFor()
    assert.equal(await page.locator('#update-notice').getByRole('button', {name:'Update certificate',exact:true}).count(), 1)
    assert.equal(await page.evaluate(() => document.querySelector('#update-notice').getBoundingClientRect().bottom <= document.querySelector('h2').getBoundingClientRect().top), true)
    await page.getByRole('button', {name:'Update certificate',exact:true}).click()
    assert.equal(posts.at(-1), '/api/starpilot_auto/identity/recommended')
    recommendation = {version:'17.10.1',updateAvailable:false}; packageVersion = '17.10.1'
    job = {state:'done',message:'Identity installed.'}
    await page.getByRole('button', {name:'Install recommended version',exact:true}).waitFor()
    assert.equal(await page.getByText('Update to Starpilot Auto certificate available', {exact:true}).count(), 0)
    assert.equal(checks.length, 3)
    assert(posts.includes('/api/starpilot_auto/identity/recommended'))
    assert.deepEqual(errors, [])
    console.log('Identity card: recommended install, progress, failure recovery, manual options and responsive layout passed')
  } finally {
    await browser.close()
  }
})().catch(error => { console.error(error); process.exitCode = 1 })
