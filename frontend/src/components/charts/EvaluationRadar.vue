<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { RadarChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { DimensionScore } from '@/types/evaluation'

use([RadarChart, TooltipComponent, LegendComponent, CanvasRenderer])

const { t } = useI18n()

interface Props {
  dimensions: DimensionScore[]
  height?: number
}

const props = withDefaults(defineProps<Props>(), {
  height: 320,
})

// ponytail: dimension label i18n keys; fallback to raw dimension name
const DIMENSION_LABEL_KEYS: Record<string, string> = {
  copywriting: 'evaluation.dim.copywriting',
  visual: 'evaluation.dim.visual',
  compliance: 'evaluation.dim.compliance',
  reach: 'evaluation.dim.reach',
  audience: 'evaluation.dim.audience',
  ai_taste: 'evaluation.dim.ai_taste',
  image_quality: 'evaluation.dim.image_quality',
  commercial_tone: 'evaluation.dim.commercial_tone',
  altruism: 'evaluation.dim.altruism',
  bias_check: 'evaluation.dim.bias_check',
}

const indicators = computed(() =>
  props.dimensions.map((d) => ({
    name: t(DIMENSION_LABEL_KEYS[d.dimension] ?? 'evaluation.dim.unknown', { dim: d.dimension }),
    max: 100,
  })),
)

const values = computed(() => props.dimensions.map((d) => d.score))

const chartOption = computed(() => ({
  tooltip: {},
  radar: {
    indicator: indicators.value,
    radius: '65%',
    axisName: { color: '#94a3b8', fontSize: 12 },
    splitArea: {
      areaStyle: {
        color: ['rgba(244,63,94,0.04)', 'rgba(244,63,94,0.08)'],
      },
    },
    splitLine: { lineStyle: { color: 'rgba(148,163,184,0.2)' } },
    axisLine: { lineStyle: { color: 'rgba(148,163,184,0.3)' } },
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
}))
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
