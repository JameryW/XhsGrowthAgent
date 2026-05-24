<script setup lang="ts">
interface Column {
  key: string
  label: string
  align?: 'left' | 'center' | 'right'
}

interface Props {
  columns: Column[]
  data: Record<string, any>[]
}

const props = defineProps<Props>()

const getAlignClass = (align?: string) => {
  return align === 'center' ? 'text-center' : align === 'right' ? 'text-right' : 'text-left'
}
</script>

<template>
  <div class="bg-black/50 rounded-lg overflow-hidden">
    <!-- 表头 -->
    <div class="grid gap-4 p-3 bg-neon-purple/10 border-b border-neon-purple/20 mono text-xs text-white/50" :style="{ gridTemplateColumns: `repeat(${props.columns.length}, 1fr)` }">
      <div
        v-for="col in props.columns"
        :key="col.key"
        :class="getAlignClass(col.align)"
      >
        {{ col.label }}
      </div>
    </div>

    <!-- 数据行 -->
    <div
      v-for="(row, idx) in props.data"
      :key="idx"
      class="grid gap-4 p-3 border-b border-white/10 mono text-xs"
      :style="{ gridTemplateColumns: `repeat(${props.columns.length}, 1fr)` }"
    >
      <div
        v-for="col in props.columns"
        :key="col.key"
        :class="[getAlignClass(col.align), col.key === 'title' ? 'text-neon-pink' : 'text-white/70']"
      >
        {{ row[col.key] }}
      </div>
    </div>
  </div>
</template>