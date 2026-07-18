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
  props.dimensions.filter((d) => !RADAR_EXCLUDED_DIMENSIONS.includes(d.dimension)),
)

// ponytail: dimension label i18n keys; fallback to raw dimension name
const indicators = computed(() =>
  radarDimensions.value.map((d) => ({
    name: t(DIMENSION_LABEL_KEYS[d.dimension] ?? 'evaluation.dim.unknown', { dim: d.dimension }),
    max: 100,
  })),
)

const values = computed(() => radarDimensions.value.map((d) => d.score))

const chartOption = computed(() => {
  const th = theme.value
  return ({
  tooltip: {
    backgroundColor: th.tooltipBg,
    borderColor: '#F43F5E',
    textStyle: { color: th.tooltipText },
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
</style>
