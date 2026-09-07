// Isolated, disposable Chrome session; never attaches to the user's browser.
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const label = process.argv[2] || 'measurement';
const out = resolve('outputs/performance');
await mkdir(out, { recursive: true });
const html = await readFile('dashboard/dist/index.html');
const server = createServer((request, response) => {
  if (request.url !== '/') { response.writeHead(404); response.end(); return; }
  response.setHeader('Content-Type', 'text/html; charset=utf-8');
  response.end(html);
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const url = process.env.DASHBOARD_URL || `http://127.0.0.1:${server.address().port}/`;
const profile = resolve(out, `chrome-${label}-${Date.now()}`);
const chromePath = process.env.CHROME_PATH || (process.platform === 'win32'
  ? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
  : process.platform === 'darwin' ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : '/usr/bin/google-chrome');
const chrome = spawn(chromePath, [
  '--headless=new', '--no-first-run', '--no-default-browser-check', '--disable-extensions',
  ...(process.env.CI ? ['--no-sandbox'] : []),
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
], { windowsHide: true, stdio: 'ignore' });
let launchError;
chrome.on('error', error => { launchError = error; });
let ws;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
try {
  let port;
  for (let i = 0; i < 100; i++) {
    if (launchError) throw launchError;
    try { port = Number((await readFile(`${profile}/DevToolsActivePort`, 'utf8')).split('\n')[0]); break; }
    catch { await delay(100); }
  }
  if (!port) throw new Error('Chrome debugging port unavailable');
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`, {signal:AbortSignal.timeout(10000)})).json();
  ws = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let id = 0;
  const pending = new Map();
  const errors = [];
  ws.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const item = pending.get(message.id); pending.delete(message.id);
      if (message.error) item.reject(new Error(JSON.stringify(message.error))); else item.resolve(message.result);
    } else if (message.method === 'Runtime.exceptionThrown') errors.push(JSON.stringify(message.params.exceptionDetails));
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`CDP timeout: ${method}`)), 30000);
    pending.set(++id, { resolve: value => {clearTimeout(timer); resolve(value);}, reject: error => {clearTimeout(timer); reject(error);} });
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async expression => {
    const value = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (value.exceptionDetails) throw new Error(value.exceptionDetails.text);
    return value.result.value;
  };
  await send('Page.enable'); await send('Runtime.enable'); await send('Performance.enable');
  await send('Emulation.setCPUThrottlingRate', { rate: 4 });
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `
    localStorage.setItem('mlb-dashboard-workspace-v1','fantasy');
    window.__perf = {longTasks: []};
    new PerformanceObserver(list => list.getEntries().forEach(e => window.__perf.longTasks.push(e.duration))).observe({type:'longtask', buffered:true});
  ` });
  const start = performance.now();
  await send('Page.navigate', { url });
  let ready = false;
  for (let i = 0; i < 200; i++) {
    ready = await evaluate(`Boolean(document.querySelector('#mlb-workspace-fantasy'))`);
    if (ready) break;
    await delay(100);
  }
  if (!ready) throw new Error('Dashboard did not render');
  const readyMs = performance.now() - start;
  await delay(1200);
  const initial = await send('Performance.getMetrics');
  const interactions = [];
  for (const selector of ['#mlb-workspace-compare']) {
    interactions.push(await evaluate(`(async () => {
      const button = document.querySelector(${JSON.stringify(selector)});
      if (!button) return {selector:${JSON.stringify(selector)}, missing:true};
      const started = performance.now(); button.click();
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      return {selector:${JSON.stringify(selector)}, durationMs:performance.now()-started};
    })()`));
    await delay(150);
  }
  const state = await evaluate(`({paints:performance.getEntriesByType('paint').map(e=>({name:e.name,startTime:e.startTime})),longTasks:window.__perf.longTasks,comparisonSelects:document.querySelectorAll('.mlb-comparison select').length,body:document.body.innerText.slice(-1800),heading:document.querySelector('h1')?.textContent,tabs:[...document.querySelectorAll('.mlb-workspace-nav button')].map(e=>({id:e.id,label:e.textContent})),overflow:document.documentElement.scrollWidth>innerWidth})`);
  await writeFile(`${out}/${label}-desktop.png`, Buffer.from((await send('Page.captureScreenshot', { format: 'png' })).data, 'base64'));
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await delay(400);
  const mobile = await evaluate(`({overflow:document.documentElement.scrollWidth>innerWidth,width:innerWidth})`);
  await writeFile(`${out}/${label}-mobile.png`, Buffer.from((await send('Page.captureScreenshot', { format: 'png' })).data, 'base64'));
  await send('Emulation.setDeviceMetricsOverride', { width:1440, height:1000, deviceScaleFactor:1, mobile:false });
  const hitters = await evaluate(`(async()=>{
    const tick=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    document.querySelector('#mlb-workspace-hitters')?.click(); await tick();
    if(!document.querySelector('#hitter-priority')) return {rendered:false};
    const change=(selector,value)=>{const el=document.querySelector(selector);el.value=value;el.dispatchEvent(new Event('change',{bubbles:true}));};
    const before=document.querySelectorAll('[data-hitter-id]').length;
    const checks=[...document.querySelectorAll('.hitters-days input')];
    for(const box of checks)if(box.checked)box.click(); await tick();
    const emptyDaysClearShortlist=document.querySelectorAll('[data-hitter-id]').length===0;
    for(const box of document.querySelectorAll('.hitters-days input'))if(!box.checked)box.click(); await tick();
    change('#hitter-priority','speed');await tick();
    const speedFirst=document.querySelector('[data-hitter-id]')?.dataset.hitterId||null;
    const inspected=document.querySelector('#hitter-detail-select').value;
    change('#hitter-mark-pool','available');await tick();
    change('#hitter-pool-filter','available');await tick();
    const personalPoolWorks=[...document.querySelectorAll('[data-hitter-id]')].every(e=>e.dataset.hitterId===inspected);
    const saved=JSON.parse(localStorage.getItem('mlb-fantasy-hitter-pool-v1')||'{}')[inspected]==='available';
    const importField=document.querySelector('#hitter-import-names');
    const importName=document.querySelector('#hitter-detail-select').selectedOptions[0].textContent.split(' · ')[0];
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(importField,importName);
    importField.dispatchEvent(new Event('input',{bubbles:true}));await tick();
    const importWorks=!document.querySelector('#hitter-import-apply').disabled;
    document.querySelector('#hitter-import-apply').click();await tick();
    change('#hitter-pool-filter','all');change('#hitter-priority','balanced');await tick();
    const candidate=document.querySelector('#hitter-detail-select').value;
    const baseline=[...document.querySelector('#hitter-incumbent').options].find(o=>o.value&&o.value!==candidate);
    if(baseline)change('#hitter-incumbent',baseline.value);await tick();
    document.querySelector('.mlb-language-switch button:last-child')?.click();await tick();
    return {rendered:true,before,emptyDaysClearShortlist,speedFirst,personalPoolWorks,saved,importWorks,
      comparisonSelected:!!baseline, chinese:document.querySelector('#mlb-workspace-hitters').textContent.includes('打者決策'),
      overflow:document.documentElement.scrollWidth>innerWidth};
  })()`);
  await writeFile(`${out}/${label}-hitters-desktop.png`, Buffer.from((await send('Page.captureScreenshot', {format:'png'})).data,'base64'));
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await delay(400);
  hitters.mobileOverflow = await evaluate('document.documentElement.scrollWidth>innerWidth');
  await writeFile(`${out}/${label}-hitters-mobile.png`, Buffer.from((await send('Page.captureScreenshot', {format:'png'})).data,'base64'));
  const layout = [];
  for (const width of [1440, 1024, 390]) {
    await send('Emulation.setDeviceMetricsOverride', {width,height:1000,deviceScaleFactor:1,mobile:width<600});
    for (const workspace of ['hitters','pitch-lab']) {
      await evaluate(`document.querySelector('#mlb-workspace-${workspace}').click()`);
      await delay(250);
      layout.push(await evaluate(`(() => {
        const rect=e=>e.getBoundingClientRect();
        const searches=[...document.querySelectorAll('.mlb-hitters .search-field')].map(e=>{
          const a=rect(e), b=rect(e.querySelector('input'));
          return b.top>=a.top && b.bottom<=a.bottom+1 && b.right<=a.right;
        });
        const notes=[...document.querySelectorAll('.mlb-metric-strip .data-metric-delta')].map(e=>e.scrollWidth<=e.clientWidth+1);
        return {width:innerWidth,workspace:'${workspace}',searches,notes,overflow:document.documentElement.scrollWidth>innerWidth};
      })()`));
      await evaluate(`(document.querySelector('${workspace==='hitters'?'.mlb-hitters .search-field':'.mlb-metric-strip'}'))?.scrollIntoView({block:'center'})`);
      await writeFile(`${out}/${label}-${workspace}-${width}.png`,Buffer.from((await send('Page.captureScreenshot',{format:'png'})).data,'base64'));
    }
  }
  const result = { layout, label, url, htmlBytes:process.env.DASHBOARD_URL ? null : html.length, cpuThrottle:4, readyMs, initialMetrics:Object.fromEntries(initial.metrics.map(m=>[m.name,m.value])), interactions, state, mobile, hitters, errors };
  await writeFile(`${out}/${label}.json`, JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
  await send('Browser.close').catch(()=>{});
  assert.ok(layout.every(x=>!x.overflow && x.searches.every(Boolean) && x.notes.every(Boolean)), 'Search inputs and metric notes must fit their containers');
  assert.deepEqual(errors, [], 'Compare must not throw a browser exception');
  assert.equal(state.comparisonSelects, 3, 'Compare must render all three pitcher selectors');
  assert.equal(state.tabs.length, 5, 'Workspace navigation must remain available');
  assert.equal(state.overflow, false, 'Desktop page must not overflow horizontally');
  assert.equal(mobile.overflow, false, 'Mobile page must not overflow horizontally');
  assert.equal(hitters.rendered, true, 'Hitters must render with official evidence');
  assert.equal(hitters.emptyDaysClearShortlist, true, 'No empty roster days must mean no automatic shortlist');
  assert.equal(hitters.personalPoolWorks && hitters.saved, true, 'Personal availability labels must filter and persist');
  assert.equal(hitters.importWorks, true, 'Pasted player names must enable the matched-player import');
  assert.equal(hitters.comparisonSelected && hitters.chinese, true, 'Replacement comparison and Chinese must work');
  assert.equal(hitters.overflow || hitters.mobileOverflow, false, 'Hitters must fit desktop and mobile');
} finally {
  ws?.close(); chrome.kill(); server.close();
}
