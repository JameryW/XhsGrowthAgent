<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

// Register ECharts modules
use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

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

const chartOption = computed(() => {
  const colors = neonColors[props.variant]

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
        lineStyle: { color: 'rgba(0,0,0,0.1)' },
      },
      axisLabel: {
        color: '#64748B',
        fontSize: 10,
      },
    },
    yAxis: {
      type: 'value',
      axisLine: {
        show: false,
      },
      splitLine: {
        lineStyle: { color: 'rgba(0,0,0,0.05)' },
      },
      axisLabel: {
        color: '#64748B',
        fontSize: 10,
      },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#FFFFFF',
      borderColor: colors.main,
      borderWidth: 1,
      textStyle: { color: '#1E293B' },
      shadowBlur: 8,
      shadowColor: 'rgba(0,0,0,0.1)',
    },
    series: [
      {
        type: 'line',
        data: props.data.map(d => d.value),
        smooth: true,
        symbol: 'none',
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
  <div class="rounded-xl p-5 transition-all duration-200 hover:shadow-lg bg-white/98 backdrop-blur-sm border border-slate-200/50" :class="`border-${props.variant === 'pink' ? 'rose' : props.variant === 'cyan' ? 'teal' : 'violet'}-200/30`">
    <div v-if="props.title" class="text-xs text-slate-500 mb-4 flex items-center gap-2 font-medium uppercase tracking-wide">
      <div class="w-2 h-2 rounded-full" :style="{ background: neonColors[props.variant].main }" />
      {{ props.title }}
    </div>
    <VChart
      :option="chartOption"
      :style="{ height: `${props.height}px` }"
      autoresize
    />
  </div>
</template>