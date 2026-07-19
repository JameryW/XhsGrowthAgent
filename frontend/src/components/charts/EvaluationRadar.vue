<script setup lang="ts">
import { computed } from 'vue'
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

function tooltipFormatter(params: unknown): string {
  const point = (Array.isArray(params) ? params[0] : params) as { value?: number[]; name?: string } | undefined
  if (!point) return ''
  const index = indicators.value.findIndex((indicator) => indicator.name === point.name)
  if (index < 0 && Array.isArray(point.value)) {
    return radarDimensions.value.map((dimension, dimensionIndex) => {
      const label = indicators.value[dimensionIndex]?.name || dimension.dimension
      const rationale = dimension.rationale ? `<br/>${t('evaluation.radarRationale')}: ${dimension.rationale}` : ''
      return `${label}: ${point.value?.[dimensionIndex] ?? dimension.score}${rationale}`
    }).join('<br/>')
  }
  const dimension = index >= 0 ? radarDimensions.value[index] : undefined
  const score = point.value?.[index] ?? dimension?.score
  return `${point.name || ''}<br/>${t('evaluation.radarScore')}: ${score ?? '—'}${dimension?.rationale ? `<br/>${t('evaluation.radarRationale')}: ${dimension.rationale}` : ''}`
}

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
    radius: '65%',
    axisName: { color: th.axisLabel, fontSize: 12 },
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
  <VChart
    v-if="dimensions.length"
    class="evaluation-radar"
    :option="chartOption"
    :style="{ height: `${height}px` }"
    autoresize
  />
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
</style>
