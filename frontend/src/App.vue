<script setup lang="ts">
import { onMounted, onUnmounted, computed, watch, nextTick, ref, defineAsyncComponent } from "vue"
import { useRoute } from "vue-router"
import { useI18n } from "vue-i18n"
import Toast from "@/components/Toast.vue"
import ErrorBoundary from "@/components/ErrorBoundary.vue"
import PageTransition from "@/components/PageTransition.vue"
// ponytail: 以下组件仅在 showChrome（已登录、非 showcase 页）块内渲染，首屏（Showcase/Login）不渲染。
// 用 defineAsyncComponent 懒加载，把整条依赖链从 entry chunk 剥离成独立 chunk，首屏不下载。
const ConnectionStatus = defineAsyncComponent(() => import("@/components/ConnectionStatus.vue"))
const OfflineRecovery = defineAsyncComponent(() => import("@/components/OfflineRecovery.vue"))
const KeyboardShortcutsHelp = defineAsyncComponent(() => import("@/components/KeyboardShortcutsHelp.vue"))
const Navbar = defineAsyncComponent(() => import("@/components/Navbar.vue"))
const MobileTabBar = defineAsyncComponent(() => import("@/components/MobileTabBar.vue"))
const OnboardingTour = defineAsyncComponent(() => import("@/components/OnboardingTour.vue"))
import { useRealtimeStore, useOnboardingStore, useShortcutsStore, useAuthStore } from "@/stores"
import { useOnboarding } from "@/composables/useOnboarding"
import { useShortcuts } from "@/composables/useShortcuts"
import { useBreakpoints } from "@/composables/useBreakpoints"

const { t } = useI18n()
const realtimeStore = useRealtimeStore()
const onboardingStore = useOnboardingStore()
const shortcutsStore = useShortcutsStore()
const authStore = useAuthStore()
const route = useRoute()
const { isMobile, isTablet } = useBreakpoints()

// Public immersive pages own their full-bleed layout and navigation chrome.
const isImmersivePage = computed(() => route.name === 'showcase' || route.name === 'replay')
const showChrome = computed(() => authStore.isAuthenticated && route.name !== 'login' && !isImmersivePage.value)
// Immersive pages manage their own full-bleed layout — remove App-level mesh background.
const { initOnboarding, skipTour, completeTour, advanceStep } = useOnboarding()
useShortcuts()

// Keyboard shortcuts help
const showShortcutsHelp = computed(() => shortcutsStore.showPanel)

// ponytail: OfflineRecovery 用浏览器 navigator.onLine 误报频繁（容器 recreate / VPN / 远程访问触发 offline 后不复位）。
// 改受控模式：黄条反映真实后端 WS 连通，非网卡状态。未登录或连接中/重连中不亮，仅已认证且 disconnected 才亮。
const isBackendOnline = computed(
  () => !authStore.isAuthenticated || realtimeStore.connectionStatus !== "disconnected"
)

// Onboarding state for OnboardingTour component
const onboardingCurrentStep = computed(() => onboardingStore.currentStep)
const isOnboardingActive = computed(() => onboardingStore.isOnboardingActive)
const onboardingInitialized = ref(false)

async function initializeContextualOnboarding(routeName = route.name) {
  // The tour targets dashboard controls. Starting it on settings, history or
  // the TUI produced a centered tooltip with no actionable target.
  if (onboardingInitialized.value || !authStore.isAuthenticated || routeName !== 'dashboard') return
  await nextTick()
  initOnboarding()
  onboardingInitialized.value = true
}

const handleGlobalKeyDown = (e: KeyboardEvent) => {
  // Skip shortcuts when typing in input/textarea/contenteditable
  const target = e.target as HTMLElement
  if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
    return
  }

  // Show shortcuts help with "?" key (Shift+/)
  if (e.key === "?" || (e.shiftKey && e.key === "/")) {
    shortcutsStore.showShortcutsPanel()
  }
  // Ctrl+K to open command palette
  if (e.ctrlKey && e.key === "k") {
    e.preventDefault()
    shortcutsStore.showShortcutsPanel()
  }
}

onMounted(async () => {
  // Auth is already initialized by router guard on first navigation
  // Add global keyboard listener
  window.addEventListener("keydown", handleGlobalKeyDown)
  await initializeContextualOnboarding()
})

watch(() => route.name, (name) => {
  void initializeContextualOnboarding(name)
})

// Return keyboard focus to the page shell after navigation.  This keeps route
// changes usable for keyboard and screen-reader users without moving scroll
// position or stealing focus while they are typing in a control.
watch(() => route.path, async () => {
  await nextTick()
  const active = document.activeElement as HTMLElement | null
  if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable)) return
  document.getElementById('main-content')?.focus({ preventScroll: true })
})

// Connect/disconnect WebSocket when auth state changes
watch(
  () => authStore.isAuthenticated,
  (authenticated) => {
    if (authenticated) {
      realtimeStore.connect()
    } else {
      realtimeStore.disconnect()
    }
  },
  { immediate: true }
)

onUnmounted(() => {
  // 应用卸载时断开WebSocket
  realtimeStore.disconnect()
  // Remove keyboard listener
  window.removeEventListener("keydown", handleGlobalKeyDown)
})

const handleCloseShortcutsHelp = () => {
  shortcutsStore.hideShortcutsPanel()
}

// Onboarding tour handlers
const handleOnboardingNext = () => {
  advanceStep()
}

const handleOnboardingSkip = () => {
  skipTour()
}

const handleOnboardingComplete = () => {
  completeTour()
}

// ErrorBoundary handler
const handleErrorBoundaryError = (error: Error) => {
  console.error('ErrorBoundary captured:', error)
}

const handleErrorBoundaryRefresh = () => {
  // Force a page refresh to reset state
  window.location.reload()
}
</script>

<template>
  <div class="app-shell h-screen min-w-0 flex relative overflow-hidden">
    <!-- Liquid glass background mesh (hidden on showcase — it has its own) -->
    <div v-if="!isImmersivePage" class="liquid-mesh-bg">
      <div class="absolute w-[55vw] h-[55vw] top-[30%] left-[30%] rounded-full" style="background: radial-gradient(circle, rgba(139,92,246,0.20) 0%, transparent 60%); animation: mesh-drift-3 22s ease-in-out infinite;" />
    </div>

    <!-- Skip to main content link for keyboard users -->
    <a
      href="#main-content"
      class="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-[100] focus:px-4 focus:py-2 focus:bg-teal-500 focus:text-white focus:rounded-lg focus:shadow-lg focus:outline-none"
    >
      {{ t('common.skipToContent') }}
    </a>

    <!-- Status indicators (always visible) -->
    <Toast />

    <!-- Authenticated chrome -->
    <template v-if="showChrome">
      <ConnectionStatus />

      <!-- Keyboard shortcuts help -->
      <KeyboardShortcutsHelp :is-open="showShortcutsHelp" @close="handleCloseShortcutsHelp" />

      <!-- Onboarding tour -->
      <OnboardingTour
        :is-active="isOnboardingActive"
        :current-step="onboardingCurrentStep"
        @next="handleOnboardingNext"
        @skip="handleOnboardingSkip"
        @complete="handleOnboardingComplete"
      />

      <!-- Offline recovery bar (above navbar) — WS 连通驱动，非 navigator.onLine -->
      <OfflineRecovery :is-online="isBackendOnline" />

      <!-- 左侧导航 (hidden on mobile) -->
      <Navbar v-if="!isMobile" />

      <!-- 底部 Tab Bar (mobile only) -->
      <MobileTabBar v-if="isMobile" />
    </template>

    <!-- 主内容区 -->
    <main
      id="main-content"
      class="app-main min-w-0 w-full flex-1 overflow-y-auto relative z-10"
      :class="isImmersivePage ? 'app-main-immersive' : (isMobile ? 'p-3 pb-20' : isTablet ? 'p-4' : 'p-6')"
      tabindex="-1"
    >
      <ErrorBoundary
        :fallback-message="t('common.pageLoadError')"
        @error="handleErrorBoundaryError"
        @refresh="handleErrorBoundaryRefresh"
      >
        <PageTransition />
      </ErrorBoundary>
    </main>
  </div>
</template>

<style scoped>
/* Fade slide transition styles (legacy, kept for reference) */
.page-transition-enter-active {
  transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}
.page-transition-leave-active {
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
.page-transition-enter-from {
  opacity: 0;
  transform: translateY(12px);
}
.page-transition-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

.slide-fade-enter-active {
  transition: all 0.4s ease-out;
}

.slide-fade-leave-active {
  transition: all 0.3s ease-in;
}

.slide-fade-enter-from {
  transform: translateY(20px);
  opacity: 0;
}

.slide-fade-leave-to {
  transform: translateY(-10px);
  opacity: 0;
}
</style>
