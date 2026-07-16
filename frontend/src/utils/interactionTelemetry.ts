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
  | 'showcase_cases_loaded'
  | 'showcase_first_case_visible'
  | 'showcase_cases_error'
  | 'showcase_filters_clear'
  | 'showcase_case_open'
  | 'showcase_filter_change'
  | 'showcase_workflow_open'
  | 'showcase_detail_retry'
  | 'showcase_primary_cta_click'
  | 'replay_view'
  | 'replay_first_result_visible'
  | 'replay_select_to_render'
  | 'replay_step_select'
  | 'replay_view_mode_change'
  | 'replay_step_link_copy'
  | 'replay_case_link_copy'
  | 'replay_share_error'
  | 'replay_checkpoint_select'
  | 'replay_phase_select'
  | 'replay_checkpoint_link_copy'
  | 'replay_back'
  | 'replay_primary_cta_click'
  | 'replay_load_error'
  | 'replay_load_more_error'

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
  'count',
  'cached',
  'view',
  'has_steps',
  'has_result',
  'authenticated',
  'has_public_id',
  'has_step',
  'duration_ms',
  'event_version',
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
    event_version: 1,
    viewport: viewportCategory(),
    ...safeProperties(properties),
  }
  window.dispatchEvent(new CustomEvent('xhs:interaction', { detail }))

  // Same-origin collection is the production default. An explicitly empty
  // value disables collection for local/offline builds.
  const configuredEndpoint = import.meta.env.VITE_TELEMETRY_ENDPOINT
  const endpoint = import.meta.env.MODE === 'test'
    ? ''
    : configuredEndpoint === undefined
      ? '/api/public/telemetry'
      : configuredEndpoint
  if (endpoint && navigator.sendBeacon) {
    const body = new Blob([JSON.stringify(detail)], { type: 'application/json' })
    navigator.sendBeacon(endpoint, body)
  }
}
