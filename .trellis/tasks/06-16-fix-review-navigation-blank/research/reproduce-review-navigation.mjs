import { spawn } from 'node:child_process'
import { rm } from 'node:fs/promises'
import { setTimeout as sleep } from 'node:timers/promises'

const origin = process.argv[2] || 'http://127.0.0.1:5174'
const port = 9400 + Math.floor(Math.random() * 400)
const userDataDir = `/tmp/xhs-review-cdp-${process.pid}`

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

const events = []
let ws
let nextId = 1
const pending = new Map()

function apiEnvelope(data) {
  return {
    success: true,
    data,
    error: null,
    timestamp: new Date().toISOString(),
    request_id: 'codex-review-nav',
  }
}

function jsonResponse(requestId, data) {
  return {
    requestId,
    responseCode: 200,
    responseHeaders: [
      { name: 'content-type', value: 'application/json' },
      { name: 'access-control-allow-origin', value: '*' },
    ],
    body: Buffer.from(JSON.stringify(apiEnvelope(data))).toString('base64'),
  }
}

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
    }, 10000)
  })
}

async function snapshot(label) {
  const result = await send('Runtime.evaluate', {
    expression: `(() => {
      const app = document.getElementById('app')
      const body = document.body
      return {
        label: ${JSON.stringify(label)},
        url: location.href,
        readyState: document.readyState,
        appLength: app ? app.outerHTML.length : -1,
        appText: app ? app.innerText.slice(0, 1200) : null,
        bodyText: body ? body.innerText.slice(0, 1200) : null,
        hasViteOverlay: !!document.querySelector('vite-error-overlay'),
      }
    })()`,
    returnByValue: true,
  })
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text || 'Runtime.evaluate failed')
  }
  return result.result.value
}

async function waitForAppText(pattern, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs
  let last = await snapshot('wait')
  while (Date.now() < deadline) {
    last = await snapshot('wait')
    if (pattern.test(last.appText || '') || pattern.test(last.bodyText || '')) return last
    await sleep(250)
  }
  return last
}

async function navigate(path) {
  await send('Runtime.evaluate', {
    expression: `import('/src/router/index.ts').then((m) => m.default.push(${JSON.stringify(path)}))`,
    awaitPromise: true,
    returnByValue: true,
  })
  await sleep(1000)
  return snapshot(path)
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
      args: event.params.args?.map((arg) => arg.value ?? arg.description).slice(0, 8),
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

try {
  const wsUrl = await waitForPageTarget()
  ws = new WebSocket(wsUrl)

  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true })
    ws.addEventListener('error', reject, { once: true })
  })

  ws.addEventListener('message', async (message) => {
    const msg = JSON.parse(message.data)
    if (msg.id && pending.has(msg.id)) {
      const request = pending.get(msg.id)
      pending.delete(msg.id)
      if (msg.error) request.reject(new Error(JSON.stringify(msg.error)))
      else request.resolve(msg.result)
      return
    }

    if (msg.method === 'Fetch.requestPaused') {
      const url = msg.params.request.url
      const requestId = msg.params.requestId
      try {
        if (url.includes('/api/auth/validate')) {
          await send('Fetch.fulfillRequest', jsonResponse(requestId, { valid: true, user: { id: 'admin', username: 'admin' }, expires_at: null }))
        } else if (url.includes('/api/workflow/list')) {
          await send('Fetch.fulfillRequest', jsonResponse(requestId, {
            workflows: [{
              thread_id: 'thread-review-1',
              account_id: 'default',
              status: 'awaiting_review',
              phase: 'reviewing',
              label: 'Codex review fixture',
              workflow_mode: 'trend',
              created_at: '2026-06-16T10:00:00Z',
              updated_at: '2026-06-16T10:05:00Z',
            }],
            total: 1,
            limit: 50,
            offset: 0,
          }))
        } else if (url.includes('/api/workflow/status/thread-review-1')) {
          await send('Fetch.fulfillRequest', jsonResponse(requestId, {
            thread_id: 'thread-review-1',
            status: 'awaiting_review',
            phase: 'reviewing',
            content_plan: { selected_topic: '测试选题' },
            copy_content: {
              selected_title: '测试标题',
              body_text: '测试正文',
              hashtags: ['测试', '小红书'],
            },
            visual_plan: {
              layout_style: 'clean',
              cover_prompt: 'simple cover',
              color_palette: ['#f43f5e', '#14b8a6'],
            },
          }))
        } else if (url.includes('/api/review/pending/thread-review-1')) {
          await send('Fetch.fulfillRequest', jsonResponse(requestId, {
            status: 'awaiting_review',
            content_plan: { selected_topic: '测试选题' },
            copy_content: {
              selected_title: '测试标题',
              body_text: '测试正文',
              hashtags: ['测试', '小红书'],
            },
            visual_plan: {
              layout_style: 'clean',
              cover_prompt: 'simple cover',
              color_palette: ['#f43f5e', '#14b8a6'],
            },
            version_history: [],
          }))
        } else {
          await send('Fetch.continueRequest', { requestId })
        }
      } catch (error) {
        events.push({ method: 'Fetch.handlerError', params: { url, error: String(error) } })
      }
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
  await send('Network.enable')
  await send('Fetch.enable', {
    patterns: [{ urlPattern: `${origin}/api/*`, requestStage: 'Request' }],
  })
  await send('Page.enable')

  await send('Page.navigate', { url: `${origin}/start` })
  await sleep(500)
  await send('Runtime.evaluate', {
    expression: `localStorage.setItem('auth_token', 'codex-token'); localStorage.setItem('auth_user', JSON.stringify({ id: 'admin', username: 'admin' }))`,
    returnByValue: true,
  })
  await send('Page.navigate', { url: `${origin}/review` })

  const reviewLoaded = await waitForAppText(/Codex review fixture|内容审核|Content Review/, 12000)
  const dashboard = await navigate('/dashboard')
  const analytics = await navigate('/analytics')
  const history = await navigate('/history')

  console.log(JSON.stringify({
    origin,
    snapshots: {
      reviewLoaded,
      dashboard,
      analytics,
      history,
    },
    events: events.map((event) => ({
      method: event.method,
      params: summarizeEvent(event),
    })),
    stderrTail: stderr.slice(-8),
  }, null, 2))
} catch (error) {
  console.error(JSON.stringify({
    error: error instanceof Error ? error.message : String(error),
    events: events.map((event) => ({
      method: event.method,
      params: summarizeEvent(event),
    })),
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
