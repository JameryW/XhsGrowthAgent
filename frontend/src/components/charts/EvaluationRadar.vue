<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { RadarChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { DimensionScore } from '@/types/evaluation'
import { RADAR_EXCLUDED_DIMENSIONS, DIMENSION_LABEL_KEYS } from '@/constants/evaluation'
import { useChartTheme } from '@/composables/useChartTheme'

use([RadarChart, TooltipComponent, LegendComponent, CanvasRenderer])

const { t } = useI18n()
const { theme } = useChartTheme()

interface Props {
  dimensions: DimensionScore[]
  height?: number
}

const props = withDefaults(defineProps<Props>(), {
  height: 320,
})

// EV-06 / D7: bias_check (and any RADAR_EXCLUDED_DIMENSIONS) is not on the
// weighted radar — its bias_severity is inverse to score, so a shared scale
// misleads. It renders in a separate bias alert card instead.
const radarDimensions = computed(() =>
  props.dimensions
    .filter((d) => !RADAR_EXCLUDED_DIMENSIONS.includes(d.dimension))
    .sort((a, b) => {
      const ai = Object.keys(DIMENSION_LABEL_KEYS).indexOf(a.dimension)
      const bi = Object.keys(DIMENSION_LABEL_KEYS).indexOf(b.dimension)
      return (ai < 0 ? Number.MAX_SAFE_INTEGER : ai) - (bi < 0 ? Number.MAX_SAFE_INTEGER : bi)
    }),
)

// ponytail: dimension label i18n keys; fallback to raw dimension name
const indicators = computed(() =>
  radarDimensions.value.map((d) => ({
    name: t(DIMENSION_LABEL_KEYS[d.dimension] ?? 'evaluation.dim.unknown', { dim: d.dimension }),
    max: 100,
  })),
)

const values = computed(() => radarDimensions.value.map((d) => d.score))

// Tooltip content is injected as HTML — escape every interpolated string so a
// rationale or label can never smuggle markup into the tooltip.
function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function tooltipFormatter(params: unknown): string {
  const point = (Array.isArray(params) ? params[0] : params) as { value?: number[]; name?: string } | undefined
  if (!point) return ''
  // trigger:'item' on a radar series always carries the series name plus the
  // full value vector — never a single dimension — so the tooltip lists the
  // name plus every dimension's score. Rationales stay in the dims list below
  // the chart instead of being dumped into the tooltip.
  const lines = radarDimensions.value.map((dimension, dimensionIndex) => {
    const label = indicators.value[dimensionIndex]?.name || dimension.dimension
    const score = Array.isArray(point.value) ? point.value[dimensionIndex] ?? dimension.score : dimension.score
    return `${escapeHtml(label)}: ${escapeHtml(score ?? '—')}`
  })
  return [escapeHtml(point.name || ''), ...lines].join('<br/>')
}

// Narrow viewports shrink the radar canvas (see the <style> media query); a
// smaller radius and font keep the indicator labels inside it.
const isNarrowViewport = ref(false)
let narrowMql: MediaQueryList | null = null
const onNarrowMqlChange = (e: MediaQueryListEvent) => { isNarrowViewport.value = e.matches }
onMounted(() => {
  if (typeof window === 'undefined' || !window.matchMedia) return
  narrowMql = window.matchMedia('(max-width: 380px)')
  isNarrowViewport.value = narrowMql.matches
  if (narrowMql.addEventListener) narrowMql.addEventListener('change', onNarrowMqlChange)
  else if ((narrowMql as any).addListener) (narrowMql as any).addListener(onNarrowMqlChange)
})
onBeforeUnmount(() => {
  if (!narrowMql) return
  if (narrowMql.removeEventListener) narrowMql.removeEventListener('change', onNarrowMqlChange)
  else if ((narrowMql as any).removeListener) (narrowMql as any).removeListener(onNarrowMqlChange)
  narrowMql = null
})

// Accessibility: text summary of the same scores the radar plots.
const chartDescription = computed(() => {
  const scores = radarDimensions.value.map(d => d.score).filter((s): s is number => s != null)
  if (!scores.length) return t('charts.noData')
  const min = Math.min(...scores)
  const max = Math.max(...scores)
  const avg = Math.round(scores.reduce((a, b) => a + b, 0) / scores.length)
  return t('evaluation.radarSummary', {
    title: t('evaluation.radarTitleDynamic', { count: radarDimensions.value.length }),
    avg,
    min,
    max,
  })
})

const chartOption = computed(() => {
  const th = theme.value
  return ({
  tooltip: {
    backgroundColor: th.tooltipBg,
    borderColor: '#F43F5E',
    textStyle: { color: th.tooltipText },
    formatter: tooltipFormatter,
  },
  radar: {
    indicator: indicators.value,
    radius: isNarrowViewport.value ? '55%' : '65%',
    axisName: { color: th.axisLabel, fontSize: isNarrowViewport.value ? 10 : 12 },
    splitArea: {
      areaStyle: {
        color: ['rgba(244,63,94,0.04)', 'rgba(244,63,94,0.08)'],
      },
    },
    splitLine: { lineStyle: { color: th.splitLine } },
    axisLine: { lineStyle: { color: th.axisLine } },
  },
  series: [
    {
      type: 'radar',
      data: [
        {
          value: values.value,
          name: t('evaluation.radarSeries'),
          areaStyle: { color: 'rgba(244,63,94,0.25)' },
          lineStyle: { color: '#F43F5E', width: 2 },
          itemStyle: { color: '#F43F5E' },
        },
      ],
    },
  ],
  })
})
</script>

<template>
  <div
    v-if="dimensions.length"
    role="figure"
    :aria-label="chartDescription"
  >
    <VChart
      class="evaluation-radar"
      :option="chartOption"
      :style="{ height: `${height}px` }"
      autoresize
      aria-hidden="true"
    />
    <!-- Screen-reader list of the same dimension scores the radar plots. -->
    <ul class="sr-only">
      <li v-for="(dimension, index) in radarDimensions" :key="dimension.dimension">
        {{ indicators[index]?.name || dimension.dimension }}: {{ dimension.score ?? '—' }}
      </li>
    </ul>
  </div>
</template>

<style scoped>
.evaluation-radar {
  width: 100%;
}

@media (max-width: 380px) {
  .evaluation-radar {
    height: 260px !important;
  }
}

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
