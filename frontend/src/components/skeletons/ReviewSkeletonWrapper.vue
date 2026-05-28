<script setup lang="ts">
import SkeletonLoader from '@/components/SkeletonLoader.vue'
</script>

<template>
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
    <SkeletonLoader type="card" :width="300" />
    <SkeletonLoader type="card" :width="300" />
  </div>
</template>