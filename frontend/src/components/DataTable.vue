<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

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
  <div class="rounded-xl overflow-hidden relative bg-white/98 backdrop-blur-sm border border-slate-200/50" role="table" aria-label="数据表格">
    <!-- 表头 -->
    <div
      class="grid gap-4 p-3 bg-slate-50 border-b border-slate-100 text-xs text-slate-500 uppercase tracking-wide font-medium"
      :style="{ gridTemplateColumns: `repeat(${props.columns.length}, 1fr)` }"
      role="rowgroup"
    >
      <div
        v-for="col in props.columns"
        :key="col.key"
        :class="[alignClasses[col.key]]"
        role="columnheader"
      >
        {{ col.label }}
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!hasData" class="p-10 text-center flex flex-col items-center gap-3" role="status" aria-live="polite" aria-label="表格为空">
      <div class="w-14 h-14 rounded-xl bg-slate-50 flex items-center justify-center" aria-hidden="true">
        <AppIcon name="Inbox" size="xl" variant="cyan" />
      </div>
      <div class="text-sm text-slate-600 font-medium">暂无数据</div>
      <div class="text-xs text-slate-400">等待数据加载或操作生成</div>
    </div>

    <!-- 数据行 -->
    <div
      v-for="(row, idx) in props.data"
      :key="getRowKey(row, idx)"
      class="grid gap-4 p-3 border-b border-slate-50 text-xs hover:bg-slate-50/50 transition-colors duration-150"
      :style="{ gridTemplateColumns: `repeat(${props.columns.length}, 1fr)` }"
      role="row"
    >
      <div
        v-for="col in props.columns"
        :key="col.key"
        :class="[alignClasses[col.key], col.key === 'title' ? 'text-rose-500 font-medium' : 'text-slate-600']"
        role="cell"
      >
        {{ row[col.key] }}
      </div>
    </div>

    <!-- Footer -->
    <div v-if="hasData" class="p-3 border-t border-slate-100 bg-slate-50/50 text-xs text-slate-500 text-center font-medium" role="rowgroup">
      共 {{ props.data.length }} 条记录
    </div>
  </div>
</template>