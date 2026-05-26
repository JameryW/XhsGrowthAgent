<script setup lang="ts">
interface Props {
  rows?: number
  columns?: number
}

const props = withDefaults(defineProps<Props>(), {
  rows: 5,
  columns: 6,
})
</script>

<template>
  <div class="bg-black/50 rounded-lg overflow-hidden">
    <!-- Header skeleton -->
    <div
      class="grid gap-4 p-3 bg-neon-purple/10 border-b border-neon-purple/20"
      :style="{ gridTemplateColumns: `repeat(${props.columns}, 1fr)` }"
    >
      <div
        v-for="i in props.columns"
        :key="`header-${i}`"
        class="h-3 w-16 rounded bg-gradient-to-r from-neon-purple/20 via-neon-purple/10 to-neon-purple/20 animate-pulse"
      />
    </div>
    <!-- Row skeletons -->
    <div
      v-for="row in props.rows"
      :key="`row-${row}`"
      class="grid gap-4 p-3 border-b border-white/5"
      :style="{ gridTemplateColumns: `repeat(${props.columns}, 1fr)` }"
    >
      <div
        v-for="col in props.columns"
        :key="`cell-${row}-${col}`"
        class="h-3 rounded bg-gradient-to-r from-white/10 via-white/5 to-white/10 animate-pulse"
        :class="col === 1 ? 'w-32' : 'w-12'"
      />
    </div>
  </div>
</template>