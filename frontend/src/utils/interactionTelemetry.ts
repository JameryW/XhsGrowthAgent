/**
 * Small privacy-safe interaction hook for public UX experiments.
 *
 * The frontend emits a browser event for the host shell/analytics adapter and
 * only sends a beacon when an endpoint is explicitly configured. Payloads are
 * intentionally limited to categorical context; no content, account, or
 * complete thread identifiers are ever sent.
 */
export type InteractionEventName =
  | 'showcase_view'
  | 'showcase_filter_change'
  | 'showcase_workflow_open'
  | 'showcase_detail_retry'
  | 'showcase_primary_cta_click'
  | 'replay_view'
  | 'replay_checkpoint_select'
  | 'replay_phase_select'
  | 'replay_checkpoint_link_copy'
  | 'replay_back'
  | 'replay_primary_cta_click'
  | 'replay_load_error'

type InteractionValue = string | number | boolean
type InteractionProperties = Record<string, InteractionValue | undefined>

const allowedKeys = new Set([
  'source',
  'viewport',
  'status',
  'mode',
  'phase',
  'step',
  'restored',
  'error_type',
])

function viewportCategory(): 'mobile' | 'desktop' {
  if (typeof window === 'undefined') return 'desktop'
  return window.matchMedia?.('(max-width: 767px)').matches ? 'mobile' : 'desktop'
}

function safeProperties(properties: InteractionProperties): Record<string, InteractionValue> {
  return Object.fromEntries(
    Object.entries(properties).filter(([key, value]) => allowedKeys.has(key) && value !== undefined),
  ) as Record<string, InteractionValue>
}

export function trackInteraction(name: InteractionEventName, properties: InteractionProperties = {}): void {
  if (typeof window === 'undefined') return
  const detail = {
    event: name,
    viewport: viewportCategory(),
    ...safeProperties(properties),
  }
  window.dispatchEvent(new CustomEvent('xhs:interaction', { detail }))

  const endpoint = import.meta.env.VITE_TELEMETRY_ENDPOINT
  if (endpoint && navigator.sendBeacon) {
    navigator.sendBeacon(endpoint, JSON.stringify(detail))
  }
}
