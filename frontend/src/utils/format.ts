// INF-04: locale-aware formatting utilities. Centralizes the number / percent /
// date formatting that five pages were each writing inline (toLocaleString,
// toFixed, manual Date slicing). Consumers pass the active locale; the Intl
// constructors handle grouping and calendar differences.
//
// ponytail: thin wrappers over Intl — no custom formatting logic. If a page
// needs compact notation (1.2k) later, add formatCompact here rather than
// re-implementing per page.

function resolveLocale(locale: string | undefined | null): string {
  return locale || undefined as unknown as string
}

/** Grouped integer/decimal number, e.g. 1234 → "1,234". */
export function formatNumber(value: number | null | undefined, locale?: string, maximumFractionDigits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return new Intl.NumberFormat(resolveLocale(locale), {
    maximumFractionDigits,
  }).format(value)
}

/** Percent with one decimal, e.g. 10 → "10.0%". Rate is a plain number, not 0..1. */
export function formatPercent(value: number | null | undefined, locale?: string, fractionDigits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return new Intl.NumberFormat(resolveLocale(locale), {
    style: 'percent',
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(value / 100)
}

/** Short month + day, e.g. ISO → "Jul 17". Returns '—' for null/invalid. */
export function formatShortDate(isoDate: string | null | undefined, locale?: string): string {
  if (!isoDate) return '—'
  const d = new Date(isoDate)
  if (Number.isNaN(d.getTime())) return '—'
  const month = d.toLocaleDateString(resolveLocale(locale), { month: 'short' })
  return `${month} ${d.getDate()}`
}
