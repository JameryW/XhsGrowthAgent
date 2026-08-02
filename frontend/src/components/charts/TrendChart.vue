<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useChartTheme } from '@/composables/useChartTheme'

// Register ECharts modules
use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const { t } = useI18n()
const { theme } = useChartTheme()

interface DataPoint {
  date: string
  value: number
}

interface Props {
  data: DataPoint[]
  title?: string
  variant?: 'pink' | 'cyan' | 'purple'
  height?: number
}

const props = withDefaults(defineProps<Props>(), {
  title: '',
  variant: 'cyan',
  height: 300,
})

// Neon colors for chart - refined palette
const neonColors = {
  pink: { main: '#F43F5E', gradient: ['rgba(244,63,94,0.2)', 'rgba(244,63,94,0)'] },
  cyan: { main: '#14B8A6', gradient: ['rgba(20,184,166,0.2)', 'rgba(20,184,166,0)'] },
  purple: { main: '#8B5CF6', gradient: ['rgba(139,92,246,0.2)', 'rgba(139,92,246,0)'] },
}

// Static variant → border-class map. Interpolated classes like
// `border-${variant}-200/30` are invisible to Tailwind's content scan and get
// purged, so the tint never rendered.
const VARIANT_BORDER_CLASS: Record<NonNullable<Props['variant']>, string> = {
  pink: 'border-rose-200/30',
  cyan: 'border-teal-200/30',
  purple: 'border-violet-200/30',
}

// Accessibility: compute chart description for screen readers
const chartDescription = computed(() => {
  if (props.data.length === 0) return t('charts.noData')
  const values = props.data.map(d => d.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const avg = Math.round(values.reduce((a, b) => a + b, 0) / values.length)
  const trend = values[values.length - 1] > values[0] ? t('charts.trend.rising') : values[values.length - 1] < values[0] ? t('charts.trend.falling') : t('charts.trend.stable')
  return t('charts.trendSummary', { title: props.title || t('charts.trendChart'), min, max, avg, trend })
})

// Compact mode (mini charts under 140px, e.g. EvaluationOverview's 110px
// trend): axis labels and split lines are crowded noise at that size.
const isCompact = computed(() => props.height < 140)

const chartOption = computed(() => {
  const colors = neonColors[props.variant]
  const th = theme.value

  return {
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      top: '10%',
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: props.data.map(d => d.date),
      axisLine: {
        lineStyle: { color: th.axisLine },
      },
      axisLabel: {
        show: !isCompact.value,
        color: th.axisLabel,
        fontSize: 10,
      },
    },
    yAxis: {
      type: 'value',
      axisLine: {
        show: false,
      },
      splitLine: {
        show: !isCompact.value,
        lineStyle: { color: th.splitLine },
      },
      axisLabel: {
        show: !isCompact.value,
        color: th.axisLabel,
        fontSize: 10,
      },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: th.tooltipBg,
      borderColor: colors.main,
      borderWidth: 1,
      textStyle: { color: th.tooltipText },
      shadowBlur: 8,
      shadowColor: th.tooltipShadow,
    },
    series: [
      {
        type: 'line',
        data: props.data.map(d => d.value),
        smooth: true,
        showSymbol: true,
        symbol: 'circle',
        symbolSize: 6,
        connectNulls: false,
        lineStyle: {
          color: colors.main,
          width: 2,
        },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: colors.gradient[0] },
              { offset: 1, color: colors.gradient[1] },
            ],
          },
        },
      },
    ],
  }
})
</script>

<template>
  <div
    class="dark-explicit rounded-xl md:rounded-2xl p-3 md:p-6 transition-all duration-200 hover:shadow-lg bg-white/90 backdrop-blur-sm border border-slate-200/50 dark:bg-slate-900/90 dark:border-slate-700/55"
    :class="VARIANT_BORDER_CLASS[props.variant]"
    role="figure"
    :aria-label="chartDescription"
  >
    <div v-if="props.title" class="text-xs text-slate-500 mb-4 flex items-center gap-2 font-medium uppercase tracking-wide">
      <div class="w-2 h-2 rounded-full" :style="{ background: neonColors[props.variant].main }" aria-hidden="true" />
      {{ props.title }}
    </div>

    <!-- Empty state: without it, a no-data series rendered as a blank axes
         box (EngagementChart already shows a placeholder). Height follows the
         chart's own height prop so the swap doesn't jump. -->
    <div v-if="props.data.length === 0" class="dark-explicit flex items-center justify-center rounded-lg border border-dashed border-slate-200 text-sm text-slate-400 dark:border-slate-700 dark:text-slate-500" :style="{ height: `${props.height}px` }" role="status">
      {{ t('charts.noData') }}
    </div>

    <!-- Chart for visual users -->
    <VChart
      v-else
      :option="chartOption"
      :style="{ height: `${props.height}px` }"
      autoresize
      aria-hidden="true"
    />

    <!-- Hidden data table for screen readers -->
    <table class="sr-only" :aria-label="t('charts.trendTable')">
      <caption>{{ props.title || t('charts.trendData') }}</caption>
      <thead>
        <tr>
          <th scope="col">{{ t('charts.date') }}</th>
          <th scope="col">{{ t('charts.value') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="point in props.data" :key="point.date">
          <td>{{ point.date }}</td>
          <td>{{ point.value }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>
