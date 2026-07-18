// INF-03 / AN-02: shared ECharts theme. Charts read axis/splitLine/tooltip
// text colors from here so dark mode is readable and theme switches re-render
// without a page reload (chartOption is a computed that depends on isDark).
//
// ponytail: returns plain option fragments, no ECharts registerTheme — keeps
// each chart's option composable. If a 5th chart needs the palette, add it
// to the consumer rather than growing a registry here.
import { computed } from 'vue'
import { useThemeStore } from '@/stores/theme'

export interface ChartTheme {
  axisLabel: string
  axisLine: string
  splitLine: string
  tooltipBg: string
  tooltipText: string
  tooltipShadow: string
}

export function useChartTheme() {
  const themeStore = useThemeStore()
  const isDark = computed(() => themeStore.isDark)

  const theme = computed<ChartTheme>(() =>
    isDark.value
      ? {
          axisLabel: '#94A3B8', // slate-400
          axisLine: 'rgba(148,163,184,0.25)',
          splitLine: 'rgba(148,163,184,0.15)',
          tooltipBg: '#1E293B', // slate-800
          tooltipText: '#E2E8F0', // slate-200
          tooltipShadow: 'rgba(0,0,0,0.4)',
        }
      : {
          axisLabel: '#64748B', // slate-500
          axisLine: 'rgba(0,0,0,0.1)',
          splitLine: 'rgba(0,0,0,0.05)',
          tooltipBg: '#FFFFFF',
          tooltipText: '#1E293B', // slate-800
          tooltipShadow: 'rgba(0,0,0,0.1)',
        },
  )

  return { theme, isDark }
}
