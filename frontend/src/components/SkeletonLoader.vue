<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  type: 'text' | 'card' | 'avatar' | 'list'
  lines?: number
  width?: number
  size?: number
}

const props = withDefaults(defineProps<Props>(), {
  lines: 1,
  width: 200,
  size: 40
})

const skeletonStyle = computed(() => {
  if (props.type === 'card') {
    return { width: `${props.width}px`, height: '120px' }
  }
  if (props.type === 'avatar') {
    return { width: `${props.size}px`, height: `${props.size}px` }
  }
  return {}
})
</script>

<template>
  <div class="skeleton-wrapper">
    <!-- Text skeleton -->
    <div v-if="type === 'text'" class="space-y-2">
      <div
        v-for="i in lines"
        :key="i"
        class="skeleton-text-line shimmer-animation h-4 rounded"
        :style="{ width: i === lines ? '75%' : '100%' }"
      />
    </div>

    <!-- Card skeleton -->
    <div
      v-else-if="type === 'card'"
      class="skeleton-card shimmer-animation rounded-lg border border-slate-200"
      :style="skeletonStyle"
    />

    <!-- Avatar skeleton -->
    <div
      v-else-if="type === 'avatar'"
      class="skeleton-avatar shimmer-animation rounded-full"
      :style="skeletonStyle"
    />

    <!-- List skeleton -->
    <div v-else-if="type === 'list'" class="space-y-3">
      <div v-for="i in 3" :key="i" class="flex gap-3">
        <div class="shimmer-animation w-10 h-10 rounded-full" />
        <div class="flex-1 space-y-2">
          <div class="shimmer-animation h-4 w-3/4 rounded" />
          <div class="shimmer-animation h-3 w-full rounded" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.skeleton-wrapper {
  display: inline-block;
}
</style>