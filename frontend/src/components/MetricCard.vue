<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'

const { t } = useI18n()

interface Props {
  icon: string // lucide icon name
  title: string
  value: string | number
  subtitle?: string
  variant?: 'pink' | 'cyan' | 'purple' | 'peach'
  // AN-07: period-over-period delta label, e.g. "↑ 12% vs 前 7 天". Empty
  // string hides it; "—" signals insufficient prior-period samples.
  delta?: string
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'pink',
  delta: '',
})

const colors = {
  pink: {
    bg: 'from-rose-400 via-rose-500 to-amber-400',
    text: 'text-rose-600',
    border: 'border-rose-100',
    shadow: 'shadow-rose-500/10',
    iconShadow: 'shadow-rose-500/20',
    bgLight: 'bg-rose-50',
  },
  cyan: {
    bg: 'from-teal-400 via-teal-500 to-emerald-400',
    text: 'text-teal-600',
    border: 'border-teal-100',
    shadow: 'shadow-teal-500/10',
    iconShadow: 'shadow-teal-500/20',
    bgLight: 'bg-teal-50',
  },
  purple: {
    bg: 'from-violet-400 via-violet-500 to-indigo-400',
    text: 'text-violet-600',
    border: 'border-violet-100',
    shadow: 'shadow-violet-500/10',
    iconShadow: 'shadow-violet-500/20',
    bgLight: 'bg-violet-50',
  },
  peach: {
    bg: 'from-amber-400 via-amber-500 to-orange-400',
    text: 'text-amber-600',
    border: 'border-amber-100',
    shadow: 'shadow-amber-500/10',
    iconShadow: 'shadow-amber-500/20',
    bgLight: 'bg-amber-50',
  },
}
</script>

<template>
  <div :class="['metric-card-surface rounded-xl md:rounded-2xl p-3 md:p-6 relative overflow-hidden bg-white/80 backdrop-blur-sm border transition-all duration-300 hover:shadow-lg group dark:bg-slate-900/75 dark:border-slate-700/50', colors[props.variant].border, colors[props.variant].shadow]" role="region" :aria-label="t('metricCard.ariaLabel', { title })">
    <!-- Hover glow -->
    <div class="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 -z-10" :style="{ background: `radial-gradient(circle at 50% 0%, ${props.variant === 'pink' ? 'rgba(244,63,94,0.08)' : props.variant === 'cyan' ? 'rgba(20,184,166,0.08)' : props.variant === 'purple' ? 'rgba(139,92,246,0.08)' : 'rgba(245,158,11,0.08)'} 0%, transparent 50%)` }" aria-hidden="true" />

    <div class="flex items-center gap-2 md:gap-3 mb-3 md:mb-5">
      <div :class="['w-8 h-8 md:w-10 md:h-10 rounded-lg md:rounded-xl bg-gradient-to-br flex items-center justify-center shadow-lg transition-all duration-300 group-hover:scale-110 group-hover:-translate-y-0.5', colors[props.variant].bg, colors[props.variant].iconShadow]" aria-hidden="true">
        <AppIcon :name="props.icon" size="sm" variant="white" class="md:hidden" />
        <AppIcon :name="props.icon" size="md" variant="white" class="hidden md:block" />
      </div>
      <div class="text-[10px] md:text-xs text-slate-500 uppercase tracking-wide font-medium">{{ props.title }}</div>
    </div>
    <div :class="['text-xl md:text-3xl font-bold tabular-nums transition-all duration-300 group-hover:translate-x-1', colors[props.variant].text]" aria-live="polite">
      {{ props.value }}
    </div>
    <div v-if="props.delta" class="mt-0.5 text-[11px] md:text-xs font-medium text-slate-500">
      {{ props.delta }}
    </div>
    <div v-if="props.subtitle" class="mt-1.5 md:mt-3 flex items-center gap-1.5 md:gap-2 group/sub">
      <AppIcon name="TrendingUp" size="sm" :variant="props.variant" class="transition-transform duration-200 group-hover/sub:scale-110" aria-hidden="true" />
      <span :class="['text-[10px] md:text-xs font-medium px-1.5 md:px-2 py-0.5 rounded', colors[props.variant].bgLight, colors[props.variant].text]">{{ props.subtitle }}</span>
    </div>
  </div>
</template>