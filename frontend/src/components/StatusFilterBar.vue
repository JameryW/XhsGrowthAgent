<script setup lang="ts">
/**
 * Horizontal status filter chips (History list, etc.).
 * Mobile: single-row scroll; desktop: wrap.
 */
export type StatusFilterOption = {
  value: string
  label: string
  count: number
}

defineProps<{
  label: string
  options: StatusFilterOption[]
  modelValue: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()
</script>

<template>
  <div
    class="flex flex-col gap-2 sm:flex-row sm:items-center"
    role="group"
    :aria-label="label"
  >
    <span class="shrink-0 text-[10px] md:text-xs font-semibold uppercase tracking-wider text-slate-400">
      {{ label }}
    </span>
    <div
      class="flex min-w-0 flex-1 gap-2 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] sm:flex-wrap sm:overflow-visible sm:pb-0 [&::-webkit-scrollbar]:hidden"
    >
      <button
        v-for="opt in options"
        :key="String(opt.value)"
        type="button"
        class="min-h-9 shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors"
        :class="modelValue === opt.value
          ? 'border-slate-400 bg-slate-100 text-slate-800 dark:border-slate-500 dark:bg-slate-800 dark:text-slate-100'
          : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400'"
        :aria-pressed="modelValue === opt.value"
        @click="emit('update:modelValue', opt.value)"
      >
        {{ opt.label }}
        <span class="ml-1 tabular-nums opacity-70">{{ opt.count }}</span>
      </button>
    </div>
  </div>
</template>
