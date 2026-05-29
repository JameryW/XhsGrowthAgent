<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import { useAuthStore } from '@/stores'

const { t } = useI18n()

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const username = ref('')
const password = ref('')
const localError = ref<string | null>(null)
const usernameInput = ref<HTMLInputElement | null>(null)

onMounted(() => {
  // Auto-focus username field
  usernameInput.value?.focus()
})

const handleLogin = async () => {
  localError.value = null

  if (!username.value.trim()) {
    localError.value = t('login.error.usernameRequired')
    return
  }
  if (!password.value.trim()) {
    localError.value = t('login.error.passwordRequired')
    return
  }

  try {
    await authStore.login(username.value.trim(), password.value.trim())
    // Redirect to intended destination or dashboard
    const redirect = route.query.redirect as string || '/dashboard'
    router.push(redirect)
  } catch (e: any) {
    localError.value = e.message || t('login.error.loginFailed')
    // Clear password on failed login
    password.value = ''
  }
}

const handleDismissError = () => {
  localError.value = null
}
</script>

<template>
  <div class="min-h-[80vh] flex flex-col items-center justify-center px-4">
    <div class="rounded-2xl p-10 max-w-md w-full bg-white/85 backdrop-blur-xl border border-slate-200/50 shadow-2xl">
      <!-- Header -->
      <div class="text-center mb-8">
        <div class="w-16 h-16 rounded-2xl bg-gradient-to-br from-rose-400 via-rose-500 to-amber-400 flex items-center justify-center mb-4 shadow-lg shadow-rose-500/20">
          <AppIcon name="Lock" size="lg" variant="white" :aria-label="t('login.title')" />
        </div>
        <h1 class="text-2xl font-bold text-slate-800">{{ t('login.title') }}</h1>
        <p class="text-slate-500 mt-2">{{ t('login.subtitle') }}</p>
      </div>

      <!-- Form -->
      <form @submit.prevent="handleLogin" class="space-y-5">
        <!-- Username -->
        <div>
          <label for="username" class="block text-sm font-medium text-slate-700 mb-2">{{ t('login.username') }}</label>
          <input
            id="username"
            ref="usernameInput"
            v-model="username"
            type="text"
            autocomplete="username"
            class="w-full px-4 py-3 rounded-lg border border-slate-200 bg-white text-slate-800 placeholder:text-slate-400 focus:border-rose-400 focus:ring-2 focus:ring-rose-400/20 outline-none transition-all duration-200"
            :placeholder="t('login.usernamePlaceholder')"
          />
        </div>

        <!-- Password -->
        <div>
          <label for="password" class="block text-sm font-medium text-slate-700 mb-2">{{ t('login.password') }}</label>
          <input
            id="password"
            v-model="password"
            type="password"
            autocomplete="current-password"
            class="w-full px-4 py-3 rounded-lg border border-slate-200 bg-white text-slate-800 placeholder:text-slate-400 focus:border-rose-400 focus:ring-2 focus:ring-rose-400/20 outline-none transition-all duration-200"
            :placeholder="t('login.passwordPlaceholder')"
          />
        </div>

        <!-- Error display -->
        <div v-if="localError" class="p-3 rounded-lg bg-rose-50 border border-rose-100 text-rose-500 text-sm flex items-center gap-3">
          <div class="w-6 h-6 rounded bg-rose-100 flex items-center justify-center">
            <AppIcon name="AlertCircle" size="sm" variant="pink" />
          </div>
          <span class="flex-1">{{ localError }}</span>
          <button
            type="button"
            @click="handleDismissError"
            class="w-6 h-6 rounded hover:bg-rose-100 flex items-center justify-center transition-colors"
            :aria-label="t('login.dismissError')"
          >
            <AppIcon name="X" size="sm" variant="pink" />
          </button>
        </div>

        <!-- Submit button -->
        <NeonButton
          type="submit"
          variant="pink"
          size="lg"
          class="w-full"
          :loading="authStore.isLoading"
        >
          <span class="inline-flex items-center gap-2">
            <AppIcon name="LogIn" size="sm" variant="white" />
            <span>{{ t('login.submit') }}</span>
          </span>
        </NeonButton>
      </form>

      <!-- Footer -->
      <div class="mt-6 text-center text-xs text-slate-400">
        <p>{{ t('login.version') }}</p>
      </div>
    </div>
  </div>
</template>