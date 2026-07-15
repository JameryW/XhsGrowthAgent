<script setup lang="ts">
import { computed, useSlots } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

type HeaderTone = 'pink' | 'cyan' | 'purple' | 'peach' | 'slate'

interface Props {
  title: string
  description?: string
  eyebrow?: string
  icon?: string
  tone?: HeaderTone
  titleId?: string
}

const props = withDefaults(defineProps<Props>(), {
  description: '',
  eyebrow: '',
  icon: 'Sparkles',
  tone: 'pink',
  titleId: 'page-title',
})

const slots = useSlots()

const toneClasses: Record<HeaderTone, { shell: string; icon: string; glow: string }> = {
  pink: {
    shell: 'from-rose-50/90 via-white to-amber-50/70 border-rose-100/70',
    icon: 'from-rose-500 to-amber-400 shadow-rose-500/20',
    glow: 'bg-rose-300/20',
  },
  cyan: {
    shell: 'from-cyan-50/90 via-white to-emerald-50/70 border-cyan-100/70',
    icon: 'from-cyan-500 to-emerald-400 shadow-cyan-500/20',
    glow: 'bg-cyan-300/20',
  },
  purple: {
    shell: 'from-violet-50/90 via-white to-fuchsia-50/70 border-violet-100/70',
    icon: 'from-violet-500 to-fuchsia-500 shadow-violet-500/20',
    glow: 'bg-violet-300/20',
  },
  peach: {
    shell: 'from-amber-50/90 via-white to-rose-50/70 border-amber-100/70',
    icon: 'from-amber-500 to-rose-400 shadow-amber-500/20',
    glow: 'bg-amber-300/20',
  },
  slate: {
    shell: 'from-slate-100/90 via-white to-cyan-50/60 border-slate-200/70',
    icon: 'from-slate-700 to-slate-500 shadow-slate-500/20',
    glow: 'bg-slate-300/25',
  },
}

const tone = computed(() => toneClasses[props.tone])
</script>

<template>
  <header
    class="page-header-shell relative isolate overflow-hidden rounded-2xl border bg-gradient-to-br p-4 shadow-sm md:rounded-3xl md:p-6"
    :class="tone.shell"
    :aria-labelledby="titleId"
  >
    <div class="pointer-events-none absolute -right-14 -top-16 h-44 w-44 rounded-full blur-3xl" :class="tone.glow" aria-hidden="true" />
    <div class="relative flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
      <div class="flex min-w-0 items-start gap-3 md:gap-4">
        <div class="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br shadow-lg md:h-14 md:w-14" :class="tone.icon" aria-hidden="true">
          <AppIcon :name="icon" size="lg" variant="white" />
        </div>
        <div class="min-w-0">
          <p v-if="eyebrow" class="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">{{ eyebrow }}</p>
          <h1 :id="titleId" class="mt-0.5 text-xl font-bold tracking-tight text-slate-800 md:text-2xl">{{ title }}</h1>
          <p v-if="description" class="mt-1 max-w-2xl text-xs leading-5 text-slate-500 md:text-sm">{{ description }}</p>
          <div v-if="slots.meta" class="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-slate-400 md:text-xs">
            <slot name="meta" />
          </div>
        </div>
      </div>
      <div v-if="slots.actions" class="flex w-full flex-wrap items-center gap-2 lg:w-auto lg:shrink-0 lg:justify-end">
        <slot name="actions" />
      </div>
    </div>
  </header>
</template>
