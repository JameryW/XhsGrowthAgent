<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

// Register ECharts modules
use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

interface DataItem {
  category: string
  value: number
}

interface Props {
  data: DataItem[]
  variant?: 'pink' | 'cyan' | 'purple' | 'peach'
  height?: number
}

const props = withDefaults(defineProps<Props>(), {
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

const chartOption = computed(() => ({
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
    borderColor: neonColors[props.variant],
    borderWidth: 1,
    textStyle: { color: '#1E293B' },
    shadowBlur: 8,
    shadowColor: 'rgba(0,0,0,0.1)',
  },
  series: [
    {
      type: 'bar',
      data: props.data.map(d => d.value),
      barWidth: '40%',
      itemStyle: {
        color: neonColors[props.variant],
        borderRadius: [4, 4, 0, 0],
      },
      emphasis: {
        itemStyle: {
          shadowBlur: 15,
          shadowColor: neonColors[props.variant] + '40',
        },
      },
    },
  ],
}))
</script>

<template>
  <div class="rounded-xl p-5 transition-all duration-200 hover:shadow-lg bg-white/98 backdrop-blur-sm border border-slate-200/50" :class="`border-${props.variant === 'pink' ? 'rose' : props.variant === 'cyan' ? 'teal' : props.variant === 'purple' ? 'violet' : 'amber'}-200/30`">
    <VChart
      :option="chartOption"
      :style="{ height: `${props.height}px` }"
      autoresize
    />
  </div>
</template>