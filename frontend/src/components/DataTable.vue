<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'

const { t } = useI18n()

interface Column {
  key: string
  label: string
  align?: 'left' | 'center' | 'right'
  sortable?: boolean
}

interface Props {
  columns: Column[]
  data: Record<string, any>[]
  rowKey?: string
  highlightRowKey?: string
  highlightKeyValue?: string
}

const props = withDefaults(defineProps<Props>(), {
  rowKey: 'title',
})

const sortKey = ref('')
const sortOrder = ref<'asc' | 'desc'>('desc')

const alignClasses = computed(() => {
  const classes: Record<string, string> = {}
  for (const col of props.columns) {
    classes[col.key] = col.align === 'center' ? 'text-center' : col.align === 'right' ? 'text-right' : 'text-left'
  }
  return classes
})

const getRowKey = (row: Record<string, any>, idx: number) => {
  return props.rowKey && row[props.rowKey] ? row[props.rowKey] : `row-${idx}`
}

const hasData = computed(() => props.data.length > 0)

const sortedData = computed(() => {
  if (!sortKey.value) return props.data
  const key = sortKey.value
  const order = sortOrder.value === 'asc' ? 1 : -1
  return [...props.data].sort((a, b) => {
    const va = a[key]
    const vb = b[key]
    if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * order
    return String(va).localeCompare(String(vb)) * order
  })
})

function toggleSort(key: string) {
  if (sortKey.value === key) {
    sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortOrder.value = 'desc'
  }
}
</script>

<template>
  <div class="rounded-xl overflow-x-auto relative bg-white/98 backdrop-blur-sm border border-slate-200/50" role="table" :aria-label="t('dataTable.title')">
    <!-- Header -->
    <div
      class="grid gap-2 md:gap-4 px-3 md:px-4 py-2 md:py-3 bg-slate-50 border-b border-slate-100 text-[10px] md:text-xs text-slate-500 uppercase tracking-wide font-medium min-w-[500px]"
      :style="{ gridTemplateColumns: `repeat(${props.columns.length}, 1fr)` }"
      role="rowgroup"
    >
      <div
        v-for="col in props.columns"
        :key="col.key"
        :class="[alignClasses[col.key]]"
        role="columnheader"
      >
        <button
          v-if="col.sortable"
          @click="toggleSort(col.key)"
          class="inline-flex items-center gap-1 hover:text-slate-700 transition-colors"
        >
          {{ col.label }}
          <span class="inline-flex flex-col -space-y-1" aria-hidden="true">
            <AppIcon name="ChevronUp" size="xs" :variant="sortKey === col.key && sortOrder === 'asc' ? 'pink' : 'cyan'" />
            <AppIcon name="ChevronDown" size="xs" :variant="sortKey === col.key && sortOrder === 'desc' ? 'pink' : 'cyan'" />
          </span>
        </button>
        <span v-else>{{ col.label }}</span>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!hasData" class="p-10 text-center flex flex-col items-center gap-3" role="status" aria-live="polite" :aria-label="t('dataTable.noData')">
      <div class="w-14 h-14 rounded-xl bg-slate-50 flex items-center justify-center" aria-hidden="true">
        <AppIcon name="Inbox" size="xl" variant="cyan" />
      </div>
      <div class="text-sm text-slate-600 font-medium">{{ t('dataTable.noData') }}</div>
      <div class="text-xs text-slate-400">{{ t('dataTable.noDataDesc') }}</div>
    </div>

    <!-- Data rows -->
    <div
      v-for="(row, idx) in sortedData"
      :key="getRowKey(row, idx)"
      class="grid gap-2 md:gap-4 px-3 md:px-4 py-2 md:py-3 border-b border-slate-50 text-[10px] md:text-xs hover:bg-slate-50/50 transition-colors duration-150 min-w-[500px]"
      :class="{ 'bg-rose-50/50': highlightRowKey && highlightKeyValue && row[highlightRowKey] === highlightKeyValue }"
      :style="{ gridTemplateColumns: `repeat(${props.columns.length}, 1fr)` }"
      role="row"
    >
      <div
        v-for="col in props.columns"
        :key="col.key"
        :class="[alignClasses[col.key], col.key === 'title' ? 'text-rose-500 font-medium truncate' : 'text-slate-600']"
        role="cell"
      >
        {{ row[col.key] }}
      </div>
    </div>

    <!-- Footer -->
    <div v-if="hasData" class="px-3 md:px-4 py-2 md:py-3 border-t border-slate-100 bg-slate-50/50 text-[10px] md:text-xs text-slate-500 text-center font-medium" role="rowgroup">
      {{ t('dataTable.records', { count: props.data.length }) }}
    </div>
  </div>
</template>
