<script setup lang="ts">
import { computed } from 'vue'

interface Column {
  key: string
  label: string
  align?: 'left' | 'center' | 'right'
}

interface Props {
  columns: Column[]
  data: Record<string, any>[]
  rowKey?: string
}

const props = withDefaults(defineProps<Props>(), {
  rowKey: 'title',
})

// Memoize align classes to avoid repeated function calls
const alignClasses = computed(() => {
  const classes: Record<string, string> = {}
  for (const col of props.columns) {
    classes[col.key] = col.align === 'center' ? 'text-center' : col.align === 'right' ? 'text-right' : 'text-left'
  }
  return classes
})

// Get unique row key
const getRowKey = (row: Record<string, any>, idx: number) => {
  return props.rowKey && row[props.rowKey] ? row[props.rowKey] : `row-${idx}`
}

const hasData = computed(() => props.data.length > 0)
</script>

<template>
  <div class="bg-black/50 rounded-lg overflow-hidden">
    <!-- 表头 -->
    <div
      class="grid gap-4 p-3 bg-neon-purple/10 border-b border-neon-purple/20 mono text-xs text-white/50"
      :style="{ gridTemplateColumns: `repeat(${props.columns.length}, 1fr)` }"
    >
      <div
        v-for="col in props.columns"
        :key="col.key"
        :class="alignClasses[col.key]"
      >
        {{ col.label }}
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!hasData" class="p-8 text-center text-white/40 mono text-sm">
      <span class="text-2xl mb-2">📭</span>
      <div>暂无数据</div>
    </div>

    <!-- 数据行 -->
    <div
      v-for="(row, idx) in props.data"
      :key="getRowKey(row, idx)"
      class="grid gap-4 p-3 border-b border-white/10 mono text-xs hover:bg-white/5 transition-colors"
      :style="{ gridTemplateColumns: `repeat(${props.columns.length}, 1fr)` }"
    >
      <div
        v-for="col in props.columns"
        :key="col.key"
        :class="[alignClasses[col.key], col.key === 'title' ? 'text-neon-pink' : 'text-white/70']"
      >
        {{ row[col.key] }}
      </div>
    </div>
  </div>
</template>