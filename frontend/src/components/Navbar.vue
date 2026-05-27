<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkflowStore } from '@/stores'
import AppIcon from '@/components/AppIcon.vue'

const route = useRoute()
const router = useRouter()
const workflowStore = useWorkflowStore()

const navItems = [
  { path: '/dashboard', icon: 'Home', label: '工作流仪表盘', color: 'pink' },
  { path: '/review', icon: 'CheckCircle', label: '内容审核', color: 'cyan' },
  { path: '/analytics', icon: 'BarChart3', label: '数据分析', color: 'purple' },
]

const currentPath = computed(() => route.path)

const navigateTo = (path: string) => {
  router.push(path)
}

const currentPhase = computed(() => workflowStore.currentPhase)
</script>

<template>
  <nav class="w-64 bg-white/80 backdrop-blur-xl p-6 flex flex-col border-r border-slate-200/60 relative overflow-hidden" role="navigation" aria-label="主导航">
    <!-- Animated glow border -->
    <div class="absolute inset-y-0 right-0 w-px bg-gradient-to-b from-transparent via-rose-300/30 to-transparent animate-pulse" style="animation-duration: 3s;" aria-hidden="true" />

    <!-- Logo -->
    <div class="mb-8 relative group">
      <div class="flex items-center gap-4">
        <div class="w-12 h-12 rounded-xl bg-gradient-to-br from-rose-400 via-rose-500 to-amber-400 flex items-center justify-center shadow-lg shadow-rose-500/20 transition-all duration-300 group-hover:shadow-rose-500/40 group-hover:scale-105" aria-hidden="true">
          <AppIcon name="BookOpen" size="lg" variant="white" />
        </div>
        <div>
          <div class="text-slate-800 font-semibold text-lg tracking-tight">增长引擎</div>
          <div class="text-xs text-slate-400 mt-0.5">XHS Growth Agent</div>
        </div>
      </div>
      <div class="mt-4 bg-gradient-to-r from-slate-50 to-white rounded-lg px-3 py-2 flex items-center gap-2 border border-slate-100 transition-all duration-200 hover:border-slate-200 hover:shadow-sm" role="status" aria-live="polite" aria-label="当前工作流阶段">
        <div class="w-2 h-2 rounded-full animate-pulse" :class="currentPhase === 'idle' ? 'bg-amber-400' : 'bg-teal-500'" aria-hidden="true" />
        <div class="text-xs text-slate-500">
          Phase: <span class="text-teal-600 font-medium">{{ currentPhase }}</span>
        </div>
      </div>
    </div>

    <!-- 导航项 -->
    <div class="space-y-1.5 relative" role="list" aria-label="导航链接">
      <button
        v-for="item in navItems"
        :key="item.path"
        @click="navigateTo(item.path)"
        :class="[
          'p-3 rounded-lg cursor-pointer transition-all duration-200 w-full text-left group relative overflow-hidden',
          currentPath === item.path
            ? 'bg-gradient-to-r from-slate-100/80 to-white border border-slate-200 shadow-sm'
            : 'hover:bg-slate-50/50 border border-transparent'
        ]"
        :aria-current="currentPath === item.path ? 'page' : undefined"
        :aria-label="item.label"
      >
        <!-- Active indicator -->
        <div v-if="currentPath === item.path" class="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-8 rounded-full bg-gradient-to-b from-rose-400 to-teal-400" aria-hidden="true" />

        <div class="flex items-center gap-3">
          <div :class="[
            'w-9 h-9 rounded-lg flex items-center justify-center transition-all duration-200',
            currentPath === item.path
              ? 'bg-gradient-to-br from-slate-700 to-slate-600 shadow-md'
              : 'bg-slate-100 group-hover:bg-slate-200'
          ]" aria-hidden="true">
            <AppIcon :name="item.icon" size="md" :variant="currentPath === item.path ? 'white' : 'cyan'" />
          </div>
          <span :class="[
            'text-sm font-medium transition-colors duration-200',
            currentPath === item.path ? 'text-slate-800' : 'text-slate-500 group-hover:text-slate-600'
          ]">
            {{ item.label }}
          </span>
        </div>
      </button>
    </div>

    <!-- 底部信息 -->
    <div class="mt-auto pt-6 border-t border-slate-100" aria-label="系统信息">
      <div class="bg-gradient-to-r from-slate-50 to-white rounded-lg p-3 text-xs border border-slate-100 hover:border-slate-200 transition-all duration-200">
        <div class="flex items-center justify-between mb-2">
          <span class="text-slate-400">Account</span>
          <span class="text-teal-600 font-medium bg-teal-50 px-2 py-0.5 rounded">default</span>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-slate-400">Version</span>
          <span class="text-violet-600 font-medium bg-violet-50 px-2 py-0.5 rounded">v0.2.0</span>
        </div>
      </div>
    </div>
  </nav>
</template>