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
  <main class="flex min-h-[80vh] items-center justify-center px-4 py-8 md:py-12" aria-labelledby="login-title">
    <div class="grid w-full max-w-5xl overflow-hidden rounded-3xl border border-white/80 bg-white/75 shadow-xl shadow-slate-200/60 backdrop-blur-xl lg:grid-cols-[0.9fr_1.1fr]">
      <aside class="relative hidden overflow-hidden bg-gradient-to-br from-rose-500 via-fuchsia-500 to-violet-600 p-8 text-white lg:flex lg:flex-col lg:justify-between xl:p-10">
        <div class="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full bg-white/20 blur-3xl" aria-hidden="true" />
        <div class="relative">
          <div class="mb-8 flex h-14 w-14 items-center justify-center rounded-2xl bg-white/20 shadow-lg ring-1 ring-white/30">
            <AppIcon name="Rocket" size="lg" variant="white" aria-hidden="true" />
          </div>
          <p class="text-[10px] font-bold uppercase tracking-[0.2em] text-white/70">{{ t('nav.brandEyebrow') }}</p>
          <h2 class="mt-3 text-3xl font-bold tracking-tight">{{ t('nav.appName') }}</h2>
          <p class="mt-3 max-w-xs text-sm leading-6 text-white/80">{{ t('nav.appSubtitle') }}</p>
        </div>
        <div class="relative rounded-2xl border border-white/20 bg-white/10 p-4 text-sm text-white/85">
          <p class="font-semibold text-white">{{ t('login.subtitle') }}</p>
          <p class="mt-1 text-xs leading-5">{{ t('login.version') }}</p>
        </div>
      </aside>

      <section class="p-6 md:p-10">
        <div class="mb-8 text-center lg:text-left">
          <div class="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-rose-400 via-rose-500 to-amber-400 shadow-lg shadow-rose-500/20 lg:mx-0">
            <AppIcon name="Lock" size="lg" variant="white" :aria-label="t('login.title')" />
          </div>
          <p class="text-[10px] font-bold uppercase tracking-[0.18em] text-rose-400">{{ t('nav.brandEyebrow') }}</p>
          <h1 id="login-title" class="mt-1 text-2xl font-bold text-slate-800">{{ t('login.title') }}</h1>
          <p class="mt-2 text-sm text-slate-500">{{ t('login.subtitle') }}</p>
        </div>

      <form @submit.prevent="handleLogin" class="space-y-5" :aria-label="t('login.title')">
        <!-- Username -->
        <div>
          <label for="username" class="block text-sm font-medium text-slate-700 mb-2">{{ t('login.username') }}</label>
          <input
            id="username"
            ref="usernameInput"
            v-model="username"
            type="text"
            autocomplete="username"
            class="min-h-11 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-slate-800 outline-none transition-all duration-200 placeholder:text-slate-400 focus:border-rose-400 focus:ring-2 focus:ring-rose-400/20"
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
            class="min-h-11 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-slate-800 outline-none transition-all duration-200 placeholder:text-slate-400 focus:border-rose-400 focus:ring-2 focus:ring-rose-400/20"
            :placeholder="t('login.passwordPlaceholder')"
          />
        </div>

        <!-- Error display -->
        <div v-if="localError" id="login-error" role="alert" class="flex items-center gap-3 rounded-xl p-3 text-sm text-rose-500 liquid-glass-rose">
          <div class="w-6 h-6 rounded bg-rose-100 flex items-center justify-center">
            <AppIcon name="AlertCircle" size="sm" variant="pink" />
          </div>
          <span class="flex-1">{{ localError }}</span>
          <button
            type="button"
            @click="handleDismissError"
            class="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg transition-colors hover:bg-rose-100"
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
          class="min-h-12 w-full"
          :loading="authStore.isLoading"
        >
          <span class="inline-flex items-center gap-2">
            <AppIcon name="LogIn" size="sm" variant="white" />
            <span>{{ t('login.submit') }}</span>
          </span>
        </NeonButton>
      </form>

      <div class="mt-6 text-center text-xs text-slate-400">
        <p>{{ t('login.version') }}</p>
      </div>
      </section>
    </div>
  </main>
</template>
