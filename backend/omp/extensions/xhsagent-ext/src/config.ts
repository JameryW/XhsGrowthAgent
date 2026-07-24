/** Extension configuration — reads from environment variables. */
export const config = {
  /** XhsGrowthAgent API base URL. */
  apiBase: process.env.XHS_AGENT_API_BASE || "http://localhost:8889",
  /** Shared service token for trusted in-mesh API calls (omp bridge peer). */
  serviceToken: process.env.XHS_SERVICE_TOKEN || "",
  /** Request timeout in milliseconds. */
  timeout: 30_000,
  /** SSE reconnect timeout in milliseconds. */
  sseTimeout: 300_000,
};
