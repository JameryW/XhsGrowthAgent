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

// Accessibility: compute chart description for screen readers
const chartDescription = computed(() => {
  if (props.data.length === 0) return '无数据'
  const total = props.data.reduce((sum, d) => sum + d.value, 0)
  const maxCategory = props.data.reduce((max, d) => d.value > max.value ? d : max, props.data[0])
  return `互动分布图: 总计 ${total} 次, 最高 ${maxCategory.category} ${maxCategory.value} 次`
})

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
  <div
    class="rounded-xl p-5 transition-all duration-200 hover:shadow-lg bg-white/98 backdrop-blur-sm border border-slate-200/50"
    :class="`border-${props.variant === 'pink' ? 'rose' : props.variant === 'cyan' ? 'teal' : props.variant === 'purple' ? 'violet' : 'amber'}-200/30`"
    role="figure"
    :aria-label="chartDescription"
  >
    <!-- Chart for visual users -->
    <VChart
      :option="chartOption"
      :style="{ height: `${props.height}px` }"
      autoresize
      aria-hidden="true"
    />

    <!-- Hidden data table for screen readers -->
    <table class="sr-only" aria-label="互动数据表">
      <caption>互动类型分布</caption>
      <thead>
        <tr>
          <th scope="col">类型</th>
          <th scope="col">次数</th>
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