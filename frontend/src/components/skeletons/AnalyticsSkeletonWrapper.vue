<script setup lang="ts">
import SkeletonLoader from '@/components/SkeletonLoader.vue'
</script>

<template>
  <div class="space-y-4">
    <SkeletonLoader type="card" :width="600" />
    <SkeletonLoader type="list" />
  </div>
</template>