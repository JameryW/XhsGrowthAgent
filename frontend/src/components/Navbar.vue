<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useWorkflowStore, useOnboardingStore, useAuthStore, useRealtimeStore } from '@/stores'
import { useBreakpoints } from '@/composables/useBreakpoints'
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
const { isTablet } = useBreakpoints()

const navItems = computed(() => [
  { path: '/dashboard', icon: 'Home', label: t('nav.dashboard'), color: 'pink' },
  { path: '/review', icon: 'CheckCircle', label: t('nav.review'), color: 'cyan' },
  { path: '/analytics', icon: 'BarChart3', label: t('nav.analytics'), color: 'purple' },
  { path: '/evaluation', icon: 'ClipboardCheck', label: t('nav.evaluation'), color: 'rose' },
  { path: '/history', icon: 'History', label: t('nav.history'), color: 'peach' },
  { path: '/tui', icon: 'Terminal', label: t('nav.tui'), color: 'emerald' },
])

const currentPath = computed(() => route.path)

const navigateTo = (path: string) => {
  router.push(path)
}

const currentPhase = computed(() => workflowStore.currentPhase)

const phaseLabel = computed(() => {
  if (workflowStore.isAwaitingDraft) return t('dashboard.phase.awaitingDraft')
  if (workflowStore.isAwaitingChoice) return t('dashboard.phase.awaitingChoice')
  if (workflowStore.isAwaitingReview) return t('dashboard.phase.awaitingReview')
  if (workflowStore.isAwaitingBrief) return t('dashboard.phase.awaitingBrief')
  if (workflowStore.isAwaitingRippleDecision) return t('showcase.status.awaitingRipple')
  if (workflowStore.isAwaitingBloggerSelection) return t('dashboard.phase.awaitingBlogger')

  const phase = currentPhase.value
  const key = `dashboard.phase.${phase}`
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
  <nav
    class="liquid-glass-nav flex flex-col border-r border-white/15 relative overflow-hidden transition-all duration-300"
    :class="isTablet ? 'w-[68px] p-3' : 'w-64 p-6'"
    role="navigation"
    :aria-label="t('nav.home')"
  >
    <!-- Animated glow border -->
    <div class="absolute inset-y-0 right-0 w-px bg-gradient-to-b from-transparent via-rose-300/30 to-transparent animate-pulse" style="animation-duration: 3s;" aria-hidden="true" />

    <!-- Logo -->
    <div class="mb-8 relative group">
      <div class="flex items-center" :class="isTablet ? 'justify-center' : 'gap-4'">
        <div class="w-12 h-12 rounded-xl bg-gradient-to-br from-rose-400 via-rose-500 to-amber-400 flex items-center justify-center shadow-lg shadow-rose-500/20 transition-all duration-300 group-hover:shadow-rose-500/40 group-hover:scale-105 flex-shrink-0" aria-hidden="true">
          <AppIcon name="BookOpen" size="lg" variant="white" />
        </div>
        <div v-if="!isTablet">
          <div class="text-slate-800 font-semibold text-lg tracking-tight">{{ t('nav.appName') }}</div>
          <div class="text-xs text-slate-400 mt-0.5">XHS Growth Agent</div>
        </div>
      </div>
      <div v-if="!isTablet" class="mt-4 liquid-glass-inset rounded-lg px-3 py-2 flex items-center gap-2 transition-all duration-200" role="status" aria-live="polite" :aria-label="t('nav.phase')">
        <div class="w-2 h-2 rounded-full animate-pulse" :class="currentPhase === 'idle' ? 'bg-amber-400' : 'bg-teal-500'" aria-hidden="true" />
        <div class="text-xs text-slate-500">
          {{ t('nav.phase') }}: <span class="text-teal-600 font-medium">{{ phaseLabel }}</span>
        </div>
      </div>
      <!-- Tablet: phase indicator dot only -->
      <div v-else class="flex justify-center mt-2" role="status" :aria-label="t('nav.phase')">
        <div class="w-2 h-2 rounded-full animate-pulse" :class="currentPhase === 'idle' ? 'bg-amber-400' : 'bg-teal-500'" />
      </div>
    </div>

    <!-- 启动新工作流按钮 -->
    <button
      @click="router.push('/start')"
      class="mb-4 w-full p-3 rounded-xl bg-gradient-to-r from-rose-500 to-amber-500 text-white font-medium text-sm flex items-center justify-center gap-2 shadow-lg shadow-rose-500/25 hover:shadow-rose-500/40 hover:scale-[1.02] active:scale-[0.98] transition-all duration-200"
      :aria-label="t('nav.startWorkflow')"
    >
      <AppIcon name="Rocket" size="sm" variant="white" />
      <span v-if="!isTablet">{{ t('nav.startWorkflow') }}</span>
    </button>

    <!-- 导航项 -->
    <div class="space-y-1.5 relative" role="list" :aria-label="t('nav.home')">
      <button
        v-for="item in navItems"
        :key="item.path"
        @click="navigateTo(item.path)"
        :class="[
          'rounded-lg cursor-pointer transition-all duration-200 w-full text-left group relative overflow-hidden',
          isTablet ? 'p-2 flex justify-center' : 'p-3',
          currentPath === item.path
            ? 'bg-gradient-to-r from-slate-100/80 to-white border border-slate-200 shadow-sm'
            : 'hover:bg-slate-50/50 border border-transparent'
        ]"
        :aria-current="currentPath === item.path ? 'page' : undefined"
        :aria-label="item.label"
        :title="isTablet ? item.label : undefined"
      >
        <!-- Active indicator -->
        <div v-if="currentPath === item.path && !isTablet" class="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-8 rounded-full bg-gradient-to-b from-rose-400 to-teal-400" aria-hidden="true" />
        <!-- Active indicator (tablet: top) -->
        <div v-if="currentPath === item.path && isTablet" class="absolute top-0 left-1/2 -translate-x-1/2 w-6 h-0.5 rounded-full bg-gradient-to-r from-rose-400 to-teal-400" aria-hidden="true" />

        <div :class="isTablet ? '' : 'flex items-center gap-3'">
          <div :class="[
            'w-9 h-9 rounded-lg flex items-center justify-center transition-all duration-200',
            currentPath === item.path
              ? 'bg-gradient-to-br from-slate-700 to-slate-600 shadow-md'
              : 'bg-slate-100 group-hover:bg-slate-200'
          ]" aria-hidden="true">
            <AppIcon :name="item.icon" size="md" :variant="currentPath === item.path ? 'white' : 'cyan'" />
          </div>
          <span v-if="!isTablet" :class="[
            'text-sm font-medium transition-colors duration-200',
            currentPath === item.path ? 'text-slate-800' : 'text-slate-500 group-hover:text-slate-600'
          ]">
            {{ item.label }}
          </span>
        </div>
      </button>
    </div>

    <!-- 底部信息 -->
    <div class="mt-auto pt-4 border-t border-slate-100" :aria-label="t('nav.systemInfo')">
      <!-- Desktop: compact bottom section -->
      <template v-if="!isTablet">
        <!-- Account & version -->
        <div class="flex items-center justify-between px-1 mb-2">
          <span class="text-xs text-slate-400">{{ authStore.user?.username || 'default' }}</span>
          <span class="text-[10px] text-slate-300">v0.2.0</span>
        </div>

        <!-- Utilities row: WS status + language -->
        <div class="flex items-center justify-between px-1 mb-2">
          <div class="flex items-center gap-1.5">
            <span
              class="w-1.5 h-1.5 rounded-full"
              :class="{
                'bg-emerald-500': realtimeStore.connectionStatus === 'connected',
                'bg-amber-500 animate-pulse': realtimeStore.connectionStatus === 'connecting' || realtimeStore.connectionStatus === 'reconnecting',
                'bg-rose-500': realtimeStore.connectionStatus === 'disconnected',
              }"
            />
            <span class="text-[10px] text-slate-400">
              {{ realtimeStore.connectionStatus === 'connected' ? t('nav.ws.connected') : realtimeStore.connectionStatus === 'reconnecting' ? t('nav.ws.reconnecting') : realtimeStore.connectionStatus === 'connecting' ? t('nav.ws.connecting') : t('nav.ws.disconnected') }}
            </span>
            <button
              v-if="realtimeStore.connectionStatus === 'disconnected'"
              @click="realtimeStore.connect()"
              class="text-[10px] text-rose-400 hover:text-rose-500 transition-colors"
            >
              {{ t('nav.ws.reconnect') }}
            </button>
          </div>
          <LanguageSwitcher />
        </div>

        <!-- Actions: Help + Settings + Logout -->
        <div class="flex items-center gap-2">
          <HelpCenter
            @open-faq="handleOpenFaq"
            @open-shortcuts="handleOpenShortcuts"
            @send-feedback="handleSendFeedback"
          />
          <button
            @click="router.push('/settings')"
            class="text-xs text-slate-400 hover:text-teal-500 transition-colors flex items-center gap-1"
            :aria-label="t('nav.settings')"
            :title="t('nav.settings')"
          >
            <AppIcon name="Settings" size="xs" variant="cyan" />
          </button>
          <button
            v-if="authStore.isAuthenticated"
            @click="handleLogout"
            class="ml-auto text-xs text-slate-400 hover:text-rose-500 transition-colors flex items-center gap-1"
            :aria-label="t('nav.logout')"
          >
            <AppIcon name="LogOut" size="xs" variant="pink" />
            <span>{{ t('nav.logout') }}</span>
          </button>
        </div>
      </template>

      <!-- Tablet: compact bottom section -->
      <template v-else>
        <div class="flex flex-col items-center gap-2">
          <!-- WS status dot -->
          <div
            class="w-2 h-2 rounded-full"
            :class="{
              'bg-emerald-500': realtimeStore.connectionStatus === 'connected',
              'bg-amber-500 animate-pulse': realtimeStore.connectionStatus === 'connecting' || realtimeStore.connectionStatus === 'reconnecting',
              'bg-rose-500': realtimeStore.connectionStatus === 'disconnected',
            }"
            :title="realtimeStore.connectionStatus"
          />
          <!-- Settings -->
          <button
            @click="router.push('/settings')"
            class="p-2 rounded-lg text-slate-400 hover:text-teal-500 hover:bg-teal-50 transition-all"
            :aria-label="t('nav.settings')"
            :title="t('nav.settings')"
          >
            <AppIcon name="Settings" size="sm" variant="cyan" />
          </button>
          <!-- Logout -->
          <button
            v-if="authStore.isAuthenticated"
            @click="handleLogout"
            class="p-2 rounded-lg text-slate-400 hover:text-rose-500 hover:bg-rose-50 transition-all"
            :aria-label="t('nav.logout')"
            :title="t('nav.logout')"
          >
            <AppIcon name="LogOut" size="sm" variant="pink" />
          </button>
        </div>
      </template>
    </div>
  </nav>
</template>
