<script setup lang="ts">
/**
 * Shared banners for multi-account local view:
 * - auto: soft-jumped from an empty preferred account
 * - viewOnly: browsing a non-workspace account
 */
withDefaults(
  defineProps<{
    variant: 'auto' | 'viewOnly'
    message: string
  }>(),
  {},
)
</script>

<template>
  <div
    class="flex flex-col gap-2 rounded-xl border p-3 sm:flex-row sm:items-center sm:justify-between"
    :class="variant === 'auto'
      ? 'border-cyan-100 bg-cyan-50/80 dark:border-cyan-500/25 dark:bg-cyan-950/25'
      : 'border-amber-100 bg-amber-50/80 dark:border-amber-500/25 dark:bg-amber-950/25'"
    role="status"
    :data-testid="variant === 'auto' ? 'account-view-notice-auto' : 'account-view-notice-view-only'"
  >
    <p
      class="text-xs sm:text-sm"
      :class="variant === 'auto'
        ? 'text-cyan-900 dark:text-cyan-100'
        : 'text-amber-800 dark:text-amber-100'"
    >
      {{ message }}
    </p>
    <div class="flex flex-wrap gap-2 shrink-0">
      <slot name="actions" />
    </div>
  </div>
</template>
