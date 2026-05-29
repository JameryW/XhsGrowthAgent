<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed } from "vue"
import { useRoute } from "vue-router"
import ConnectionStatus from "@/components/ConnectionStatus.vue"
import LanguageSwitcher from "@/components/LanguageSwitcher.vue"
import Toast from "@/components/Toast.vue"
import OfflineIndicator from "@/components/OfflineIndicator.vue"
import OfflineRecovery from "@/components/OfflineRecovery.vue"
import KeyboardShortcutsHelp from "@/components/KeyboardShortcutsHelp.vue"
import Navbar from "@/components/Navbar.vue"
import ErrorBoundary from "@/components/ErrorBoundary.vue"
import PageTransition from "@/components/PageTransition.vue"
import OnboardingTour from "@/components/OnboardingTour.vue"
import { useRealtimeStore, useOnboardingStore, useShortcutsStore, useAuthStore } from "@/stores"
import { useOnboarding } from "@/composables/useOnboarding"
import { useShortcuts } from "@/composables/useShortcuts"

const realtimeStore = useRealtimeStore()
const onboardingStore = useOnboardingStore()
const shortcutsStore = useShortcutsStore()
const authStore = useAuthStore()
const route = useRoute()

// Hide Navbar and chrome on login page
const showChrome = computed(() => authStore.isAuthenticated && route.name !== 'login')
const { initOnboarding, isVisible: showOnboarding, skipTour, completeTour, advanceStep } = useOnboarding()
const { handleShortcutAction } = useShortcuts()

// Keyboard shortcuts help
const showShortcutsHelp = ref(false)

// Onboarding state for OnboardingTour component
const onboardingCurrentStep = computed(() => onboardingStore.currentStep)
const isOnboardingActive = computed(() => onboardingStore.isOnboardingActive)

const handleGlobalKeyDown = (e: KeyboardEvent) => {
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
  // Validate token in background — don't block router navigation
  if (authStore.isAuthenticated) {
    authStore.initialize()
    realtimeStore.connect()
  }
  // Add global keyboard listener
  window.addEventListener("keydown", handleGlobalKeyDown)
  // Initialize onboarding - check if user needs to see tour
  initOnboarding()
})

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
  <div class="min-h-screen bg-gradient-to-br from-slate-50 via-white to-slate-100/80 flex relative overflow-hidden">
    <!-- Skip to main content link for keyboard users -->
    <a
      href="#main-content"
      class="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-[100] focus:px-4 focus:py-2 focus:bg-teal-500 focus:text-white focus:rounded-lg focus:shadow-lg focus:outline-none"
    >
      跳转到主内容
    </a>

    <!-- Animated gradient mesh -->
    <div class="absolute inset-0 pointer-events-none overflow-hidden">
      <div class="absolute -top-40 -right-40 w-[500px] h-[500px] rounded-full opacity-70 animate-pulse" style="background: radial-gradient(circle, rgba(244,63,94,0.15) 0%, transparent 50%); animation-duration: 4s;" />
      <div class="absolute -bottom-40 -left-40 w-[400px] h-[400px] rounded-full opacity-60 animate-pulse" style="background: radial-gradient(circle, rgba(20,184,166,0.12) 0%, transparent 50%); animation-duration: 5s; animation-delay: 1s;" />
      <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[300px] h-[300px] rounded-full opacity-40 animate-pulse" style="background: radial-gradient(circle, rgba(139,92,246,0.1) 0%, transparent 50%); animation-duration: 6s; animation-delay: 2s;" />
    </div>

    <!-- Subtle grid -->
    <div class="absolute inset-0 pointer-events-none" style="background-image: linear-gradient(rgba(0,0,0,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,0,0.02) 1px, transparent 1px); background-size: 40px 40px;" />

    <!-- Status indicators (always visible) -->
    <Toast />

    <!-- Authenticated chrome -->
    <template v-if="showChrome">
      <OfflineIndicator />
      <ConnectionStatus />
      <LanguageSwitcher />

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

      <!-- 左侧导航 -->
      <Navbar />
    </template>

    <!-- 主内容区 -->
    <main id="main-content" class="flex-1 p-8 overflow-auto relative z-10" tabindex="-1">
      <ErrorBoundary
        fallback-message="页面加载出现问题"
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