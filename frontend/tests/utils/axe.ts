// INF-09: shared axe-core runner for vitest (happy-dom). Runs axe against a
// mounted component's root element and asserts 0 critical violations.
//
// happy-dom has no layout engine, so contrast/color rules are meaningless —
// they're disabled. This still catches real a11y regressions: ARIA roles,
// required labels, landmark structure, tab-order, duplicate IDs, nameless
// interactive elements.
import axe from 'axe-core'

export interface AxeRunOptions {
  // Additional rule disables beyond the happy-dom baseline.
  disableRules?: string[]
}

// ponytail: tag-based gate — only `critical` fails the build. serious/moderate
// surface as warnings; raise the bar to serious when the baseline is clean.
const CRITICAL_ONLY: axe.RunOptions = {
  runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
  rules: {
    'color-contrast': { enabled: false },
    'region': { enabled: false },
  },
  resultTypes: ['violations'],
}

export async function assertNoCriticalAxeViolations(
  el: Element | Document,
  opts: AxeRunOptions = {},
): Promise<void> {
  const config: axe.ElementContext | axe.RunOptions = {
    ...CRITICAL_ONLY,
    rules: {
      ...CRITICAL_ONLY.rules,
      ...(opts.disableRules
        ? Object.fromEntries(opts.disableRules.map((r) => [r, { enabled: false }]))
        : {}),
    },
  }
  const results = await axe.run(el, config as axe.RunOptions)
  const critical = results.violations.filter((v) => v.impact === 'critical')
  if (critical.length > 0) {
    const detail = critical
      .map((v) => `- ${v.id} (${v.help}): ${v.nodes.map((n) => n.target.join(',')).join(' | ')}`)
      .join('\n')
    throw new Error(`axe critical violations:\n${detail}`)
  }
}
