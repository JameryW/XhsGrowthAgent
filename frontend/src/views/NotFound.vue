<script setup lang="ts">
import NeonButton from '@/components/NeonButton.vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const goHome = () => {
  router.push('/')
}
</script>

<template>
  <div class="min-h-[80vh] flex flex-col items-center justify-center">
    <div class="glass rounded-2xl p-8 max-w-md w-full text-center">
      <div class="w-20 h-20 rounded-2xl bg-gradient-to-br from-neon-pink to-neon-peach flex items-center justify-center mx-auto mb-4 shadow-neon-pink text-4xl">
        🔍
      </div>
      <h1 class="text-2xl font-bold text-neon-pink mb-2">404</h1>
      <p class="mono text-sm text-white/60 mb-6">PAGE_NOT_FOUND // 页面不存在</p>
      <NeonButton variant="cyan" size="lg" @click="goHome">
        🏠 返回首页
      </NeonButton>
    </div>
  </div>
</template>