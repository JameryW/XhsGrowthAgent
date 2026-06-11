<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed, watch } from "vue"
import { useRoute } from "vue-router"
import { useI18n } from "vue-i18n"
import ConnectionStatus from "@/components/ConnectionStatus.vue"
import Toast from "@/components/Toast.vue"
import OfflineIndicator from "@/components/OfflineIndicator.vue"
import OfflineRecovery from "@/components/OfflineRecovery.vue"
import KeyboardShortcutsHelp from "@/components/KeyboardShortcutsHelp.vue"
import Navbar from "@/components/Navbar.vue"
import MobileTabBar from "@/components/MobileTabBar.vue"
import ErrorBoundary from "@/components/ErrorBoundary.vue"
import PageTransition from "@/components/PageTransition.vue"
import OnboardingTour from "@/components/OnboardingTour.vue"
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

// Hide Navbar and chrome on login page
const showChrome = computed(() => authStore.isAuthenticated && route.name !== 'login' && route.name !== 'showcase')
const { initOnboarding, skipTour, completeTour, advanceStep } = useOnboarding()
useShortcuts()

// Keyboard shortcuts help
const showShortcutsHelp = ref(false)

// Onboarding state for OnboardingTour component
const onboardingCurrentStep = computed(() => onboardingStore.currentStep)
const isOnboardingActive = computed(() => onboardingStore.isOnboardingActive)

const handleGlobalKeyDown = (e: KeyboardEvent) => {
  // Skip shortcuts when typing in input/textarea/contenteditable
  const target = e.target as HTMLElement
  if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
    return
  }

  // Show shortcuts help with "?" key (Shift+/)
  if (e.key === "?" || (e.shiftKey && e.key === "/")) {
    showShortcutsHelp.value = true
    shortcutsStore.showShortcutsPanel()
  }
  // Ctrl+K to open command palette
  if (e.ctrlKey && e.key === "k") {
    e.preventDefault()
    shortcutsStore.showShortcutsPanel()
    showShortcutsHelp.value = true
  }
}

onMounted(async () => {
  // Auth is already initialized by router guard on first navigation
  // Add global keyboard listener
  window.addEventListener("keydown", handleGlobalKeyDown)
  // Initialize onboarding - check if user needs to see tour
  initOnboarding()
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
  showShortcutsHelp.value = false
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
  <div class="h-screen flex relative overflow-hidden">
    <!-- Liquid glass background mesh -->
    <div class="liquid-mesh-bg">
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
      <OfflineIndicator />
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

      <!-- Offline recovery bar (above navbar) -->
      <OfflineRecovery />

      <!-- 左侧导航 (hidden on mobile) -->
      <Navbar v-if="!isMobile" />

      <!-- 底部 Tab Bar (mobile only) -->
      <MobileTabBar v-if="isMobile" />
    </template>

    <!-- 主内容区 -->
    <main
      id="main-content"
      class="flex-1 overflow-y-auto relative z-10"
      :class="isMobile ? 'p-3 pb-20' : isTablet ? 'p-4' : 'p-6'"
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