<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import { useThemeStore } from '@/stores/theme'

const { t } = useI18n()
const themeStore = useThemeStore()

// Tri-state cycle light → dark → system: label/icon reflect the current mode.
const modeIcons = { light: 'Sun', dark: 'Moon', system: 'Monitor' } as const

const label = computed(() => t(`theme.${themeStore.mode}`))
const iconName = computed(() => modeIcons[themeStore.mode])

onMounted(() => themeStore.init())
</script>

<template>
  <button
    type="button"
    class="theme-toggle inline-flex min-h-11 min-w-11 items-center justify-center rounded-xl border border-slate-200/70 bg-white/70 px-3 text-slate-600 shadow-sm transition-colors hover:bg-white hover:text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/70 dark:border-slate-700/70 dark:bg-slate-900/65 dark:text-slate-200 dark:hover:bg-slate-800 dark:hover:text-white"
    :aria-label="label"
    :title="label"
    @click="themeStore.toggle"
  >
    <AppIcon :name="iconName" size="sm" variant="cyan" aria-hidden="true" />
    <span class="sr-only">{{ label }}</span>
  </button>
</template>
