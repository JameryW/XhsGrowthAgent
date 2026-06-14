import { spawn } from 'node:child_process'
import { rm } from 'node:fs/promises'
import { setTimeout as sleep } from 'node:timers/promises'

const url = process.argv[2] || 'http://127.0.0.1:5174/'
const waitMs = Number(process.argv[3] || 6000)
const port = 9300 + Math.floor(Math.random() * 500)
const userDataDir = `/tmp/xhs-cdp-${process.pid}`

const chrome = spawn('chromium-browser', [
  '--headless',
  '--disable-gpu',
  '--no-sandbox',
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${userDataDir}`,
  'about:blank',
], {
  stdio: ['ignore', 'ignore', 'pipe'],
})

const stderr = []
let chromeExited = false
chrome.stderr.on('data', (buf) => {
  const text = String(buf).trim()
  if (text) stderr.push(text)
})
chrome.on('exit', () => {
  chromeExited = true
})

async function fetchJson(path) {
  const res = await fetch(`http://127.0.0.1:${port}${path}`)
  if (!res.ok) throw new Error(`CDP ${path} returned ${res.status}`)
  return res.json()
}

async function waitForPageTarget() {
  const deadline = Date.now() + 8000
  while (Date.now() < deadline) {
    try {
      const list = await fetchJson('/json/list')
      const page = list.find((item) => item.type === 'page' && item.webSocketDebuggerUrl)
      if (page) return page.webSocketDebuggerUrl
    } catch {
      // Chrome may still be starting.
    }
    await sleep(100)
  }
  throw new Error('Timed out waiting for CDP page target')
}

const events = []
let ws
let nextId = 1
const pending = new Map()

async function snapshotApp() {
  const snapshot = await send('Runtime.evaluate', {
    expression: `(() => {
      const app = document.getElementById('app')
      return {
        url: location.href,
        readyState: document.readyState,
        appLength: app ? app.outerHTML.length : -1,
        appText: app ? app.innerText.slice(0, 1000) : null,
        appOuterStart: app ? app.outerHTML.slice(0, 2000) : null,
        bodyText: document.body.innerText.slice(0, 1000),
        resources: performance.getEntriesByType('resource')
          .map((entry) => ({
            name: entry.name,
            initiatorType: entry.initiatorType,
            startTime: Math.round(entry.startTime),
            duration: Math.round(entry.duration),
          }))
          .sort((a, b) => b.duration - a.duration)
          .slice(0, 12),
      }
    })()`,
    returnByValue: true,
  })
  if (snapshot.exceptionDetails) {
    throw new Error(snapshot.exceptionDetails.exception?.description || snapshot.exceptionDetails.text || 'Runtime.evaluate failed')
  }
  if (!snapshot.result || !('value' in snapshot.result)) {
    throw new Error(`Runtime.evaluate returned no value: ${JSON.stringify(snapshot)}`)
  }
  return snapshot.result.value
}

function send(method, params = {}) {
  const id = nextId++
  ws.send(JSON.stringify({ id, method, params }))
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject })
    setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id)
        reject(new Error(`CDP timeout: ${method}`))
      }
    }, 8000)
  })
}

try {
  const wsUrl = await waitForPageTarget()
  ws = new WebSocket(wsUrl)

  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true })
    ws.addEventListener('error', reject, { once: true })
  })

  ws.addEventListener('message', (message) => {
    const msg = JSON.parse(message.data)
    if (msg.id && pending.has(msg.id)) {
      const request = pending.get(msg.id)
      pending.delete(msg.id)
      if (msg.error) request.reject(new Error(JSON.stringify(msg.error)))
      else request.resolve(msg.result)
      return
    }

    if ([
      'Runtime.consoleAPICalled',
      'Runtime.exceptionThrown',
      'Log.entryAdded',
      'Network.loadingFailed',
    ].includes(msg.method)) {
      events.push(msg)
    }
  })

  await send('Runtime.enable')
  await send('Log.enable')
  await send('Page.enable')
  await send('Page.navigate', { url })

  const deadline = Date.now() + waitMs
  let snapshot = await snapshotApp()
  while (
    Date.now() < deadline &&
    events.every((event) => event.method !== 'Runtime.exceptionThrown') &&
    (snapshot.appLength <= 20 || snapshot.bodyText.trim() === '跳转到主内容')
  ) {
    await sleep(250)
    snapshot = await snapshotApp()
  }

  console.log(JSON.stringify({
    url,
    snapshot,
    events: events.map((event) => ({
      method: event.method,
      params: summarizeEvent(event),
    })),
    stderrTail: stderr.slice(-8),
  }, null, 2))
} catch (error) {
  console.error(JSON.stringify({
    error: error instanceof Error ? error.message : String(error),
    stderrTail: stderr.slice(-12),
  }, null, 2))
  process.exitCode = 1
} finally {
  if (ws) ws.close()
  chrome.kill('SIGTERM')
  for (let i = 0; i < 20 && !chromeExited; i += 1) {
    await sleep(100)
  }
  await rm(userDataDir, { recursive: true, force: true })
}

function summarizeEvent(event) {
  if (event.method === 'Runtime.exceptionThrown') {
    const details = event.params.exceptionDetails
    return {
      text: details?.text,
      url: details?.url,
      lineNumber: details?.lineNumber,
      columnNumber: details?.columnNumber,
      exception: details?.exception?.description || details?.exception?.value,
    }
  }
  if (event.method === 'Runtime.consoleAPICalled') {
    return {
      type: event.params.type,
      args: event.params.args?.map((arg) => arg.value ?? arg.description).slice(0, 5),
    }
  }
  if (event.method === 'Log.entryAdded') {
    const entry = event.params.entry
    return {
      source: entry.source,
      level: entry.level,
      text: entry.text,
      url: entry.url,
    }
  }
  if (event.method === 'Network.loadingFailed') {
    return event.params
  }
  return event.params
}
