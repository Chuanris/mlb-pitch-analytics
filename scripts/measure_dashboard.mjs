// Isolated, disposable Chrome session; never attaches to the user's browser.
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';

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
const url = `http://127.0.0.1:${server.address().port}/`;
const profile = resolve(out, `chrome-${label}-${Date.now()}`);
const chrome = spawn('C:/Program Files/Google/Chrome/Application/chrome.exe', [
  '--headless=new', '--no-first-run', '--no-default-browser-check', '--disable-extensions',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
], { windowsHide: true, stdio: 'ignore' });
let ws;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
try {
  let port;
  for (let i = 0; i < 100; i++) {
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
    } else if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text);
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
  for (const selector of ['#mlb-workspace-models','#mlb-workspace-pitch-lab','#mlb-workspace-fantasy', '.mlb-language-switch button:last-child','.mlb-language-switch button:first-child']) {
    interactions.push(await evaluate(`(async () => {
      const button = document.querySelector(${JSON.stringify(selector)});
      if (!button) return {selector:${JSON.stringify(selector)}, missing:true};
      const started = performance.now(); button.click();
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      return {selector:${JSON.stringify(selector)}, durationMs:performance.now()-started};
    })()`));
    await delay(150);
  }
  const state = await evaluate(`({paints:performance.getEntriesByType('paint').map(e=>({name:e.name,startTime:e.startTime})),longTasks:window.__perf.longTasks,heading:document.querySelector('h1')?.textContent,tabs:[...document.querySelectorAll('.mlb-workspace-nav button')].map(e=>({id:e.id,label:e.textContent})),overflow:document.documentElement.scrollWidth>innerWidth})`);
  await writeFile(`${out}/${label}-desktop.png`, Buffer.from((await send('Page.captureScreenshot', { format: 'png' })).data, 'base64'));
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await delay(400);
  const mobile = await evaluate(`({overflow:document.documentElement.scrollWidth>innerWidth,width:innerWidth})`);
  await writeFile(`${out}/${label}-mobile.png`, Buffer.from((await send('Page.captureScreenshot', { format: 'png' })).data, 'base64'));
  const result = { label, htmlBytes:html.length, cpuThrottle:4, readyMs, initialMetrics:Object.fromEntries(initial.metrics.map(m=>[m.name,m.value])), interactions, state, mobile, errors };
  await writeFile(`${out}/${label}.json`, JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
  await send('Browser.close').catch(()=>{});
} finally {
  ws?.close(); chrome.kill(); server.close();
}
