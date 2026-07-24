/** HTTP client for XhsGrowthAgent API. */
import { config } from "./config.js";
import type { HealthResponse } from "./types.js";

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

/** Longer budget for RQGM evaluation POSTs (10-dim LLM panel, 60–120s). */
const EVALUATION_TIMEOUT_MS = 180_000;

function timeoutFor(path: string): number {
  if (path.startsWith("/evaluation/run") || path.startsWith("/evaluation/note") || path.startsWith("/free/evaluate")) {
    return EVALUATION_TIMEOUT_MS;
  }
  return config.timeout;
}

async function request(
  method: "GET" | "POST" | "DELETE",
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
    signal: AbortSignal.timeout(timeoutFor(path)),
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

/** DELETE request to XhsGrowthAgent API. Returns unwrapped data. */
export async function del(path: string): Promise<unknown> {
  return request("DELETE", path);
}
