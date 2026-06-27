/** HTTP + SSE client for XhsGrowthAgent API. */
import { config } from "./config.js";
import type { HealthResponse, SSEEvent } from "./types.js";

const BASE = `${config.apiBase}/api`;

// ── API envelope type ───────────────────────────────────────────────────
interface ApiEnvelope {
  success: boolean;
  data?: unknown;
  error?: { code: string; message: string; details?: Record<string, unknown> };
}

// ── API connectivity check ──────────────────────────────────────────────

let _apiAvailable: boolean | null = null;

/** Check if the XhsGrowthAgent API is reachable. */
export async function checkApiHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/system/health`, {
      signal: AbortSignal.timeout(5_000),
    });
    if (!res.ok) return false;
    const envelope = (await res.json()) as ApiEnvelope;
    // Health endpoint wraps data in envelope; extract status from data
    const data = envelope.data as HealthResponse | undefined;
    const status = data?.status || (envelope as any).status;
    _apiAvailable = status === "ok" || status === "degraded" || status === "warning";
    return _apiAvailable;
  } catch {
    _apiAvailable = false;
    return false;
  }
}

/** Get cached API availability (null = not checked yet). */
export function getApiAvailability(): boolean | null {
  return _apiAvailable;
}

// ── HTTP helpers ────────────────────────────────────────────────────────

async function request(
  method: "GET" | "POST",
  path: string,
  params?: Record<string, unknown>,
): Promise<unknown> {
  const url =
    method === "GET" && params
      ? `${BASE}${path}?${new URLSearchParams(params as Record<string, string>)}`
      : `${BASE}${path}`;

  const res = await fetch(url, {
    method,
    headers: method === "POST" ? { "Content-Type": "application/json" } : undefined,
    body: method === "POST" && params ? JSON.stringify(params) : undefined,
    signal: AbortSignal.timeout(config.timeout),
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${method} ${path} failed: ${res.status} ${res.statusText}${body ? ` — ${body}` : ""}`);
  }

  const envelope = (await res.json()) as ApiEnvelope;

  // Unwrap the unified envelope: { success, data, error }
  if (!envelope.success) {
    const errMsg = envelope.error?.message || "Unknown API error";
    throw new Error(errMsg);
  }
  return envelope.data;
}

/** GET request to XhsGrowthAgent API. Returns unwrapped data. */
export async function get(path: string, params?: Record<string, unknown>): Promise<unknown> {
  return request("GET", path, params);
}

/** POST request to XhsGrowthAgent API. Returns unwrapped data. */
export async function post(path: string, body?: Record<string, unknown>): Promise<unknown> {
  return request("POST", path, body);
}

// ── SSE helper ──────────────────────────────────────────────────────────

/** SSE event types sent by the backend (from EventType enum). */
const SSE_EVENT_TYPES = [
  "workflow_started",
  "workflow_completed",
  "workflow_error",
  "phase_changed",
  "agent_started",
  "agent_completed",
  "review_requested",
  "progress_update",
] as const;

/** Subscribe to SSE stream for a workflow. Backend sends named events
 *  (e.g. `event: phase_changed`), not anonymous messages.
 *  Returns a cleanup function to close the connection. */
export function subscribeSSE(
  threadId: string,
  onUpdate: (event: SSEEvent) => void,
  onError?: (err: Error) => void,
): { close: () => void; promise: Promise<void> } {
  const url = `${BASE}/workflow/stream/${threadId}`;
  let closed = false;
  let es: EventSource | null = null;
  let resolveRef: ((value: void) => void) | null = null;

  const promise = new Promise<void>((resolve) => {
    resolveRef = resolve;
    es = new EventSource(url);

    // Backend sends named events: event: phase_changed, event: progress_update, etc.
    // We must use addEventListener for each type; onmessage only catches unnamed events.
    for (const eventType of SSE_EVENT_TYPES) {
      es.addEventListener(eventType, (msg: MessageEvent) => {
        if (closed) return;
        try {
          const data = JSON.parse(msg.data) as SSEEvent["data"];
          onUpdate({ event: eventType, data });
        } catch {
          // ignore malformed SSE data
        }
      });
    }

    // Also listen for unnamed events as fallback
    es.onmessage = (msg) => {
      if (closed) return;
      try {
        const data = JSON.parse(msg.data) as SSEEvent["data"];
        onUpdate({ event: "message", data });
      } catch {
        // ignore malformed SSE data
      }
    };

    es.onerror = () => {
      if (closed) return;
      if (es!.readyState === EventSource.CLOSED) {
        onError?.(new Error(`SSE connection closed for workflow ${threadId}`));
      }
      // Don't reject — EventSource auto-reconnects on transient errors.
      // Only the close() method resolves the promise.
    };
  });

  return {
    close: () => {
      if (closed) return;
      closed = true;
      es?.close();
      resolveRef?.();
    },
    promise,
  };
}
