/** Format an Analytics API rate after honoring its declared raw unit. */
export function formatAnalyticsRate(value: number | undefined, unit?: string): string {
  const rate = Number(value) || 0;
  const percent = unit === "fraction" ? rate * 100 : unit === "percent" ? rate : rate <= 1 ? rate * 100 : rate;
  return `${percent.toFixed(2)}%`;
}
