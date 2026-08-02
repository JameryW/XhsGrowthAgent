<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useChartTheme } from '@/composables/useChartTheme'
import { formatNumber } from '@/utils/format'

// Register ECharts modules
use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

const { t, locale } = useI18n()
const { theme } = useChartTheme()

interface DataItem {
  category: string
  value: number
}

interface Props {
  data: DataItem[]
  title?: string
  variant?: 'pink' | 'cyan' | 'purple' | 'peach'
  height?: number
}

const props = withDefaults(defineProps<Props>(), {
  title: '',
  variant: 'pink',
  height: 300,
})

// Neon colors for bars - refined palette
const neonColors = {
  pink: '#F43F5E',
  cyan: '#14B8A6',
  purple: '#8B5CF6',
  peach: '#F59E0B',
}

// ponytail: per-category palette so the 4 engagement types are visually
// distinct, not a single monochrome bar set. Anchored to the metric palette.
const CATEGORY_COLORS = ['#F43F5E', '#8B5CF6', '#14B8A6', '#F59E0B']

// Static variant → border-class map. Interpolated classes like
// `border-${variant}-200/30` are invisible to Tailwind's content scan and get
// purged, so the tint never rendered.
const VARIANT_BORDER_CLASS: Record<NonNullable<Props['variant']>, string> = {
  pink: 'border-rose-200/30',
  cyan: 'border-teal-200/30',
  purple: 'border-violet-200/30',
  peach: 'border-amber-200/30',
}

const totalValue = computed(() => props.data.reduce((sum, d) => sum + d.value, 0))
// All-zero data is as empty as no data: four 0-height bars read as a broken
// chart, so the template and the SR summary both treat it as the empty state.
const hasChartData = computed(() => props.data.length > 0 && totalValue.value > 0)

// Accessibility: compute chart description for screen readers
const chartDescription = computed(() => {
  if (!hasChartData.value) return t('charts.noEngagementData')
  const total = totalValue.value
  const maxCategory = props.data.reduce((max, d) => d.value > max.value ? d : max, props.data[0])
  return t('charts.engagementSummary', {
    total: formatNumber(total, locale.value),
    category: maxCategory.category,
    value: formatNumber(maxCategory.value, locale.value),
  })
})

const chartOption = computed(() => {
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
    data: props.data.map(d => d.category),
    axisLine: {
      lineStyle: { color: th.axisLine },
    },
    axisLabel: {
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
      lineStyle: { color: th.splitLine },
    },
    axisLabel: {
      color: th.axisLabel,
      fontSize: 10,
    },
  },
  tooltip: {
    trigger: 'axis',
    backgroundColor: th.tooltipBg,
    borderColor: neonColors[props.variant],
    borderWidth: 1,
    textStyle: { color: th.tooltipText },
    shadowBlur: 8,
    shadowColor: th.tooltipShadow,
  },
  series: [
    {
      type: 'bar',
      data: props.data.map((d, i) => ({
        value: d.value,
        itemStyle: {
          color: CATEGORY_COLORS[i % CATEGORY_COLORS.length],
          borderRadius: [4, 4, 0, 0],
        },
      })),
      barWidth: '40%',
      emphasis: {
        itemStyle: {
          shadowBlur: 15,
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
    <!-- Title bar (matches TrendChart style) -->
    <div v-if="props.title" class="text-xs text-slate-500 mb-4 flex items-center justify-between gap-2 font-medium uppercase tracking-wide">
      <div class="flex items-center gap-2">
        <div class="w-2 h-2 rounded-full" :style="{ background: neonColors[props.variant] }" aria-hidden="true" />
        {{ props.title }}
      </div>
      <span v-if="totalValue > 0" class="text-slate-400 normal-case tracking-normal font-semibold tabular-nums">{{ formatNumber(totalValue, locale) }}</span>
    </div>

    <div v-if="!hasChartData" class="dark-explicit flex items-center justify-center rounded-lg border border-dashed border-slate-200 text-sm text-slate-400 dark:border-slate-700 dark:text-slate-500" :style="{ height: `${props.height}px` }" role="status">
      {{ t('charts.noEngagementData') }}
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
    <table class="sr-only" :aria-label="t('charts.engagementTable')">
      <caption>{{ t('charts.engagementTable') }}</caption>
      <thead>
        <tr>
          <th scope="col">{{ t('charts.type') }}</th>
          <th scope="col">{{ t('charts.count') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in props.data" :key="item.category">
          <td>{{ item.category }}</td>
          <td>{{ item.value }}</td>
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
