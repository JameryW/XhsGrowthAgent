<script setup lang="ts">
/**
 * Multi-account local view switcher shared by History and Review.
 * Selects a *view* account only — does not flip the workspace active account.
 */
import { nextTick, ref, watch } from 'vue'
import { useReducedMotion } from '@/composables/useReducedMotion'

export type AccountScopeChip = {
  id: string
  name: string
  total?: number
  isViewing: boolean
  isWorkspace: boolean
}

const props = withDefaults(
  defineProps<{
    chips: AccountScopeChip[]
    /** Accessible group label, e.g. "查看账号" */
    label: string
    tone?: 'violet' | 'amber'
    disabled?: boolean
    idPrefix?: string
    workspaceBadgeLabel: string
    /** Full title strings already interpolated with the chip name, or templates with {name}. */
    titleForWorkspace?: string
    titleForBrowse?: string
    /** Spoken when the viewing account changes (screen readers). */
    announceTemplate?: string
  }>(),
  {
    tone: 'violet',
    disabled: false,
    idPrefix: 'account-chip',
    titleForWorkspace: '',
    titleForBrowse: '',
    announceTemplate: '',
  },
)

const emit = defineEmits<{
  select: [accountId: string]
  prefetch: [accountId: string]
}>()

const liveMessage = ref('')
const { prefersReduced } = useReducedMotion()

const activeClasses = {
  violet:
    'border-violet-300 bg-violet-50 text-violet-700 dark:border-violet-500/40 dark:bg-violet-950/40 dark:text-violet-200 focus-visible:ring-violet-400/60',
  amber:
    'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-500/40 dark:bg-amber-950/40 dark:text-amber-100 focus-visible:ring-amber-400/60',
} as const

const idleClasses =
  'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 focus-visible:ring-slate-400/50'

const totalActiveClasses = {
  violet: 'bg-violet-200/80 text-violet-800 dark:bg-violet-800/60 dark:text-violet-100',
  amber: 'bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-100',
} as const

function chipTitle(chip: AccountScopeChip): string {
  const tpl = chip.isWorkspace ? props.titleForWorkspace : props.titleForBrowse
  if (tpl) return tpl.replace(/\{name\}/g, chip.name)
  return chip.name
}

function onKeydown(event: KeyboardEvent, index: number) {
  const chips = props.chips
  if (!chips.length) return
  let next = index
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
    next = (index + 1) % chips.length
  } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
    next = (index - 1 + chips.length) % chips.length
  } else if (event.key === 'Home') {
    next = 0
  } else if (event.key === 'End') {
    next = chips.length - 1
  } else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    emit('select', chips[index].id)
    return
  } else {
    return
  }
  event.preventDefault()
  document.getElementById(`${props.idPrefix}-${chips[next].id}`)?.focus()
}

watch(
  () => props.chips.find(c => c.isViewing)?.id,
  async (id, prev) => {
    const chip = props.chips.find(c => c.id === id)
    if (chip?.name && id !== prev && props.announceTemplate) {
      liveMessage.value = props.announceTemplate.replace(/\{name\}/g, chip.name)
    }
    // Keep the active chip visible inside the horizontal scroller on mobile.
    if (!id || id === prev) return
    await nextTick()
    document.getElementById(`${props.idPrefix}-${id}`)?.scrollIntoView({
      behavior: prefersReduced.value ? 'auto' : 'smooth',
      block: 'nearest',
      inline: 'center',
    })
  },
)
</script>

<template>
  <div v-if="chips.length > 1" class="space-y-1">
    <div
      class="flex flex-col gap-2 sm:flex-row sm:items-center"
      role="group"
      :aria-label="label"
    >
      <span class="shrink-0 text-[10px] md:text-xs font-semibold uppercase tracking-wider text-slate-400">
        {{ label }}
      </span>
      <!--
        Mobile: single-row horizontal scroll so many accounts stay tappable.
        Desktop: wrap as before.
      -->
      <div
        class="flex min-w-0 flex-1 gap-2 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] sm:flex-wrap sm:overflow-visible sm:pb-0 [&::-webkit-scrollbar]:hidden"
      >
        <button
          v-for="(acc, index) in chips"
          :id="`${idPrefix}-${acc.id}`"
          :key="acc.id"
          type="button"
          class="inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2"
          :class="acc.isViewing ? activeClasses[tone] : idleClasses"
          :disabled="disabled"
          :aria-pressed="acc.isViewing"
          :aria-current="acc.isViewing ? 'true' : undefined"
          tabindex="0"
          :title="chipTitle(acc)"
          @click="emit('select', acc.id)"
          @mouseenter="emit('prefetch', acc.id)"
          @focus="emit('prefetch', acc.id)"
          @keydown="onKeydown($event, index)"
        >
          <span class="max-w-[10rem] truncate">{{ acc.name }}</span>
          <span
            v-if="typeof acc.total === 'number'"
            class="rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums"
            :class="acc.isViewing
              ? totalActiveClasses[tone]
              : acc.total > 0
                ? 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-200'
                : 'bg-slate-50 text-slate-400 dark:bg-slate-800/60 dark:text-slate-500'"
          >
            {{ acc.total }}
          </span>
          <span
            v-if="acc.isWorkspace"
            class="rounded-full bg-teal-50 px-1.5 py-0.5 text-[10px] font-semibold text-teal-700 dark:bg-teal-950/50 dark:text-teal-300"
          >
            {{ workspaceBadgeLabel }}
          </span>
        </button>
      </div>
    </div>
    <p class="sr-only" aria-live="polite" aria-atomic="true">{{ liveMessage }}</p>
  </div>
</template>
