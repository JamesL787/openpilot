// Synthetic API and local assets only. No device settings are read or written.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const repo = process.env.GALAXY_REPO || path.resolve(__dirname, '../../../..')
const assets = path.join(repo, 'starpilot/system/the_galaxy/assets')
const fixture = `
import {createApp} from 'vue';
import {StarpilotAutoCarScreenPanel} from '/assets/mobile/js/components/StarpilotAutoCarScreenPanel.js';
import {GalaxySelect} from '/assets/mobile/js/components/GalaxySelect.js';
import {api} from '/assets/mobile/js/api.js';
import {Settings} from '/assets/mobile/js/views/Settings.js';
import {store} from '/assets/mobile/js/store.js';
window.saved = {onroad_view:'split',map_side:'right',map_orientation:'north_up',camera:true,blind_spot_monitors:true,
  blind_spot_min_speed_ms:0,sleep_device_screen:false,status_slots:['cpu','cpu','cpu','cpu','cpu','cpu']};
window.writes=[];window.failWrite=false;
api.getCarScreen=async()=>({settings:{...window.saved},status_metrics:[{value:'cpu',label:'CPU Usage'},{value:'temperature',label:'Temperature'}]});
api.setCarScreen=async(change)=>{window.writes.push(change);if(window.failWrite)throw new Error('Injected failure');Object.assign(window.saved,change);return{settings:{...window.saved}}};
api.getLayout=async()=>[{name:'Vehicle',params:[{key:'StarpilotAutoEnabled',label:'Enable Starpilot Auto',ui_type:'toggle',settings_tier:'simple'},
  {key:'ExampleVehicleSetting',label:'Example Vehicle Setting',ui_type:'toggle',settings_tier:'simple'}]}];
api.getParams=async()=>({StarpilotAutoEnabled:true,ExampleVehicleSetting:false});api.getDefaults=async()=>({});
api.getStarpilotAutoConnection=async()=>({status:{state:'idle',running:false,receiver_address:'AA:BB:CC:DD:EE:FF',receiver_name:'Family Car',configured_view:'car',connection:'wireless',auto_connect:true,auto_paused:false,error:'',stats:{}},devices:[{address:'AA:BB:CC:DD:EE:FF',name:'Family Car',paired:true,starpilot_auto:true}],offroad:true,setup_help:'Pair the Car while parked.',recovery_hint:'',devices_error:''});
api.starpilotAutoConnectionOp=async()=>api.getStarpilotAutoConnection();api.bluetoothOp=async()=>({});
api.getStarpilotAutoIdentity=async()=>({});api.updateParam=async({key,value})=>({[key]:value});
const fullSettings=new URLSearchParams(location.search).has('settings');
store.route='/settings/starpilot-auto';
createApp({components:{StarpilotAutoCarScreenPanel,Settings},template:fullSettings?'<Settings />':'<main style="max-width:1100px;margin:auto"><StarpilotAutoCarScreenPanel /></main>'})
.component('GalaxySelect',GalaxySelect).mount('#app');
`
;(async () => {
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_EXECUTABLE})
  try {
    const page = await browser.newPage()
    const errors=[]
    page.on('pageerror',error=>errors.push(error.message))
    await page.route('**/*', async route=>{
      const url=new URL(route.request().url())
      assert.equal(url.hostname,'offline.invalid')
      if(url.pathname==='/') return route.fulfill({contentType:'text/html',body:'<html data-theme="dark"><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/assets/mobile/css/material.css"><script type="importmap">{"imports":{"vue":"/assets/vendor/vue/vue.esm-browser.js"}}</script></head><body><div id="app"></div><div id="snackbar_wrapper"></div><script type="module" src="/fixture.js"></script></body></html>'})
      if(url.pathname==='/fixture.js') return route.fulfill({contentType:'text/javascript',body:fixture})
      const file=path.join(assets,url.pathname.slice('/assets/'.length))
      if(url.pathname.startsWith('/assets/') && fs.existsSync(file)) return route.fulfill({path:file})
      return route.fulfill({contentType:'application/json',body:'{}'})
    })
    for(const width of [320,390,600,800,1280,1920]) {
      await page.setViewportSize({width,height:900})
      await page.goto('http://offline.invalid/')
      await page.getByText('Show Road Camera',{exact:true}).waitFor()
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth),true,`horizontal overflow at ${width}`)
      assert.equal(await page.locator('.gx-row').evaluateAll(rows=>rows.every(row=>{
        const info=row.querySelector('.gx-row__info')?.getBoundingClientRect()
        const control=row.querySelector('.gx-switch,.gx-car-display__tabs')?.getBoundingClientRect()
        return !info || !control || info.right<=control.left+1 || info.bottom<=control.top+1 || control.bottom<=info.top+1
      })),true,`text/control overlap at ${width}`)
      await page.getByRole('button',{name:'Map',exact:true}).click()
      await page.waitForFunction(()=>window.saved.onroad_view==='map')
      assert.equal(await page.getByText('Show Road Camera',{exact:true}).count(),0)
      assert.equal(await page.getByText('Map Side',{exact:true}).count(),0)
      await page.getByLabel('Show Blind Spot Monitors',{exact:false}).uncheck()
      await page.waitForFunction(()=>!window.saved.blind_spot_monitors)
      assert.equal(await page.getByText('Blind Spot Minimum Speed',{exact:true}).count(),0)
      await page.getByRole('tab',{name:'Status Widgets'}).click()
      await page.getByRole('combobox',{name:'Status slot 1'}).click()
      await page.getByRole('option',{name:'Temperature'}).click()
      await page.waitForFunction(()=>window.saved.status_slots[0]==='temperature')
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth),true)
    }
    await page.getByRole('tab',{name:'Layout'}).click()
    await page.evaluate(()=>window.failWrite=true)
    await page.getByLabel('Turn Off Comma Display',{exact:false}).click()
    await page.waitForFunction(()=>!document.querySelector('input[type=checkbox]:checked'))
    assert.equal(await page.evaluate(()=>window.saved.sleep_device_screen),false)
    assert.deepEqual(errors,[])
    if(process.env.GALAXY_DOM_SCREENSHOT) {
      await page.setViewportSize({width:800,height:1000})
      await page.goto('http://offline.invalid/')
      await page.getByText('Show Road Camera',{exact:true}).waitFor()
      await page.screenshot({path:process.env.GALAXY_DOM_SCREENSHOT,fullPage:true})
    }
    await page.goto('http://offline.invalid/?settings')
    await page.getByText('Enable Starpilot Auto',{exact:true}).waitFor({timeout:10000}).catch(async error=>{
      throw new Error(`${error.message}\nPage errors: ${errors}\n${await page.locator('body').innerText()}`)
    })
    assert.equal(await page.getByText('Connection',{exact:true}).count(),1)
    assert.equal(await page.getByText('Layout',{exact:true}).count(),1)
    assert.equal(await page.getByText('Status Widgets',{exact:true}).count(),1)
    assert.equal(await page.getByText('Starpilot Auto Certificate',{exact:true}).count(),1)
    assert.equal(await page.getByText('Diagnostics',{exact:true}).count(),0)
    for(const width of [320,800,1920]) {
      await page.setViewportSize({width,height:900})
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth),true,`Settings overflow at ${width}`)
    }
    await page.getByRole('button',{name:'Vehicle',exact:true}).click()
    await page.getByText('Example Vehicle Setting',{exact:true}).waitFor()
    assert.equal(await page.getByText('Enable Starpilot Auto',{exact:true}).count(),0)
    await page.getByRole('button',{name:'Starpilot Auto',exact:true}).click()
    await page.getByText('Enable Starpilot Auto',{exact:true}).waitFor()
    assert.equal(await page.getByText('Connection',{exact:true}).count(),1)
    assert.equal(await page.getByText('Layout',{exact:true}).count(),1)
    assert.equal(await page.getByText('Status Widgets',{exact:true}).count(),1)
    assert.equal(await page.getByText('Diagnostics',{exact:true}).count(),0)
    assert.deepEqual(errors,[])
    console.log('Starpilot Auto controls: six widths, dependencies, switches, selection, save rollback, and Settings navigation passed.')
  } finally { await browser.close() }
})().catch(error=>{console.error(error);process.exitCode=1})
