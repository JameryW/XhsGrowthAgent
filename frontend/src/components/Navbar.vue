<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useWorkflowStore, useOnboardingStore, useAuthStore, useRealtimeStore } from '@/stores'
import AppIcon from '@/components/AppIcon.vue'
import HelpCenter from '@/components/HelpCenter.vue'
import LanguageSwitcher from '@/components/LanguageSwitcher.vue'

const { t } = useI18n()

const route = useRoute()
const router = useRouter()
const workflowStore = useWorkflowStore()
const onboardingStore = useOnboardingStore()
const authStore = useAuthStore()
const realtimeStore = useRealtimeStore()

const navItems = computed(() => [
  { path: '/dashboard', icon: 'Home', label: t('nav.dashboard'), color: 'pink' },
  { path: '/review', icon: 'CheckCircle', label: t('nav.review'), color: 'cyan' },
  { path: '/analytics', icon: 'BarChart3', label: t('nav.analytics'), color: 'purple' },
  { path: '/history', icon: 'History', label: t('nav.history'), color: 'peach' },
])

const currentPath = computed(() => route.path)

const navigateTo = (path: string) => {
  router.push(path)
}

const currentPhase = computed(() => workflowStore.currentPhase)

const phaseLabel = computed(() => {
  const phase = currentPhase.value
  const key = `dashboard.timeline.${phase}`
  // Only use translation if the key exists, otherwise show raw phase
  const translated = t(key)
  return translated !== key ? translated : phase
})

// HelpCenter handlers
const handleOpenFaq = () => {
  // Navigate to FAQ page or show modal
  router.push('/faq')
}

const handleOpenShortcuts = () => {
  // Emit event to show shortcuts panel or toggle
  onboardingStore.startTour() // Could trigger shortcuts panel instead
}

const handleSendFeedback = () => {
  // Open feedback modal or navigate to feedback page
  window.open('mailto:feedback@example.com', '_blank')
}

// Logout handler
const handleLogout = async () => {
  await authStore.logout()
  router.push('/login')
}
</script>

<template>
  <nav class="w-64 bg-white/80 backdrop-blur-xl p-6 flex flex-col border-r border-slate-200/60 relative overflow-hidden" role="navigation" :aria-label="t('nav.home')">
    <!-- Animated glow border -->
    <div class="absolute inset-y-0 right-0 w-px bg-gradient-to-b from-transparent via-rose-300/30 to-transparent animate-pulse" style="animation-duration: 3s;" aria-hidden="true" />

    <!-- Logo -->
    <div class="mb-8 relative group">
      <div class="flex items-center gap-4">
        <div class="w-12 h-12 rounded-xl bg-gradient-to-br from-rose-400 via-rose-500 to-amber-400 flex items-center justify-center shadow-lg shadow-rose-500/20 transition-all duration-300 group-hover:shadow-rose-500/40 group-hover:scale-105" aria-hidden="true">
          <AppIcon name="BookOpen" size="lg" variant="white" />
        </div>
        <div>
          <div class="text-slate-800 font-semibold text-lg tracking-tight">{{ t('nav.appName') }}</div>
          <div class="text-xs text-slate-400 mt-0.5">XHS Growth Agent</div>
        </div>
      </div>
      <div class="mt-4 bg-gradient-to-r from-slate-50 to-white rounded-lg px-3 py-2 flex items-center gap-2 border border-slate-100 transition-all duration-200 hover:border-slate-200 hover:shadow-sm" role="status" aria-live="polite" :aria-label="t('nav.phase')">
        <div class="w-2 h-2 rounded-full animate-pulse" :class="currentPhase === 'idle' ? 'bg-amber-400' : 'bg-teal-500'" aria-hidden="true" />
        <div class="text-xs text-slate-500">
          {{ t('nav.phase') }}: <span class="text-teal-600 font-medium">{{ phaseLabel }}</span>
        </div>
      </div>
    </div>

    <!-- 启动新工作流按钮 -->
    <button
      @click="router.push('/')"
      class="mb-4 w-full p-3 rounded-xl bg-gradient-to-r from-rose-500 to-amber-500 text-white font-medium text-sm flex items-center justify-center gap-2 shadow-lg shadow-rose-500/25 hover:shadow-rose-500/40 hover:scale-[1.02] active:scale-[0.98] transition-all duration-200"
      :aria-label="t('nav.startWorkflow')"
    >
      <AppIcon name="Rocket" size="sm" variant="white" />
      <span>{{ t('nav.startWorkflow') }}</span>
    </button>

    <!-- 导航项 -->
    <div class="space-y-1.5 relative" role="list" :aria-label="t('nav.home')">
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
    <div class="mt-auto pt-6 border-t border-slate-100" :aria-label="t('nav.systemInfo')">
      <!-- Logout button -->
      <button
        v-if="authStore.isAuthenticated"
        @click="handleLogout"
        class="mb-3 w-full p-2.5 rounded-lg border border-slate-200 bg-slate-50 text-slate-600 hover:bg-rose-50 hover:border-rose-200 hover:text-rose-500 transition-all duration-200 flex items-center justify-center gap-2 text-sm font-medium"
        :aria-label="t('nav.logout')"
      >
        <AppIcon name="LogOut" size="sm" variant="pink" />
        <span>{{ t('nav.logout') }}</span>
      </button>

      <!-- HelpCenter -->
      <div class="mb-3 flex justify-center">
        <HelpCenter
          @open-faq="handleOpenFaq"
          @open-shortcuts="handleOpenShortcuts"
          @send-feedback="handleSendFeedback"
        />
      </div>

      <!-- WebSocket Connection Status -->
      <div class="mb-3 flex items-center justify-between px-3 py-2 rounded-lg border border-slate-100 bg-slate-50/50">
        <div class="flex items-center gap-2">
          <span
            class="w-2 h-2 rounded-full"
            :class="{
              'bg-emerald-500': realtimeStore.connectionStatus === 'connected',
              'bg-amber-500 animate-pulse': realtimeStore.connectionStatus === 'connecting' || realtimeStore.connectionStatus === 'reconnecting',
              'bg-rose-500': realtimeStore.connectionStatus === 'disconnected',
            }"
          />
          <span class="text-xs text-slate-500">
            {{ realtimeStore.connectionStatus === 'connected' ? t('nav.ws.connected') : realtimeStore.connectionStatus === 'reconnecting' ? t('nav.ws.reconnecting') : realtimeStore.connectionStatus === 'connecting' ? t('nav.ws.connecting') : t('nav.ws.disconnected') }}
          </span>
        </div>
        <button
          v-if="realtimeStore.connectionStatus === 'disconnected'"
          @click="realtimeStore.connect()"
          class="text-xs text-rose-500 hover:text-rose-600 font-medium transition-colors"
        >
          {{ t('nav.ws.reconnect') }}
        </button>
      </div>

      <!-- Language Switcher -->
      <div class="mb-3 flex items-center justify-between px-3 py-2 rounded-lg border border-slate-100 bg-slate-50/50">
        <div class="flex items-center gap-2">
          <AppIcon name="Globe" size="sm" variant="cyan" />
          <span class="text-xs text-slate-500">{{ t('nav.language') }}</span>
        </div>
        <LanguageSwitcher />
      </div>

      <div class="bg-gradient-to-r from-slate-50 to-white rounded-lg p-3 text-xs border border-slate-100 hover:border-slate-200 transition-all duration-200">
        <div class="flex items-center justify-between mb-2">
          <span class="text-slate-400">{{ t('nav.account') }}</span>
          <span class="text-teal-600 font-medium bg-teal-50 px-2 py-0.5 rounded">{{ authStore.user?.username || 'default' }}</span>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-slate-400">{{ t('nav.version') }}</span>
          <span class="text-violet-600 font-medium bg-violet-50 px-2 py-0.5 rounded">v0.2.0</span>
        </div>
      </div>
    </div>
  </nav>
</template>