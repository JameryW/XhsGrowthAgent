<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkflowStore } from '@/stores'

const route = useRoute()
const router = useRouter()
const workflowStore = useWorkflowStore()

const navItems = [
  { path: '/dashboard', icon: '🏠', label: '工作流仪表盘' },
  { path: '/review', icon: '✅', label: '内容审核' },
  { path: '/analytics', icon: '📊', label: '数据分析' },
]

const currentPath = computed(() => route.path)

const navigateTo = (path: string) => {
  router.push(path)
}

const currentPhase = computed(() => workflowStore.currentPhase)
</script>

<template>
  <nav class="w-56 bg-dark-panel p-4 flex flex-col border-r border-dark-border">
    <!-- Logo -->
    <div class="mb-6">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-neon-pink to-neon-peach flex items-center justify-center shadow-neon-pink">
          📚
        </div>
        <div class="text-white font-bold">增长引擎</div>
      </div>
      <div class="mt-2 text-xs mono text-neon-cyan">
        Phase: {{ currentPhase }}
      </div>
    </div>

    <!-- 导航项 -->
    <div class="space-y-2">
      <button
        v-for="item in navItems"
        :key="item.path"
        @click="navigateTo(item.path)"
        :class="[
          'p-3 rounded-lg cursor-pointer transition-all duration-200 w-full text-left',
          currentPath === item.path
            ? 'bg-neon-pink/20 border border-neon-pink/50 shadow-neon-pink'
            : 'hover:bg-dark-card border border-transparent'
        ]"
      >
        <div class="flex items-center gap-3">
          <span class="text-lg">{{ item.icon }}</span>
          <span :class="[
            'text-sm',
            currentPath === item.path ? 'text-neon-pink font-bold' : 'text-white/70'
          ]">
            {{ item.label }}
          </span>
        </div>
      </button>
    </div>

    <!-- 底部信息 -->
    <div class="mt-auto pt-4 border-t border-dark-border">
      <div class="text-xs mono text-white/40">
        <div>Account: default</div>
        <div>Version: v0.1.0</div>
      </div>
    </div>
  </nav>
</template>