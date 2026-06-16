<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import type { CheckpointSnapshot } from '@/types/workflow'

const { t } = useI18n()
defineProps<{ cp: CheckpointSnapshot }>()
</script>

<template>
  <div v-if="cp.publish_result" class="replay-section">
    <div class="text-[10px] text-slate-400 font-medium mb-2 uppercase tracking-wide">{{ t('replay.publishResult') }}</div>

    <div class="grid grid-cols-2 gap-2">
      <div v-if="(cp.publish_result as any).post_id" class="p-2 rounded-lg liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.postId') }}</div>
        <div class="text-xs font-semibold font-mono text-slate-700">{{ (cp.publish_result as any).post_id }}</div>
      </div>
      <div v-if="(cp.publish_result as any).status" class="p-2 rounded-lg liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.status') }}</div>
        <div class="text-xs font-semibold" :class="(cp.publish_result as any).status === 'published' ? 'text-emerald-600' : 'text-amber-600'">{{ (cp.publish_result as any).status }}</div>
      </div>
      <div v-if="(cp.publish_result as any).published_at" class="p-2 rounded-lg liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.publishedAt') }}</div>
        <div class="text-xs text-slate-700">{{ new Date((cp.publish_result as any).published_at).toLocaleString() }}</div>
      </div>
    </div>
    <div v-if="(cp.publish_result as any).post_url" class="mt-2">
      <a :href="(cp.publish_result as any).post_url" target="_blank" rel="noopener" class="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg liquid-glass-inset text-xs text-emerald-600 font-medium hover:bg-emerald-50 transition-colors">
        <AppIcon name="ExternalLink" size="sm" />
        {{ t('replay.viewPost') }}
      </a>
    </div>
  </div>
</template>

<style scoped>
.replay-section {
  border-radius: 0.75rem;
  background: rgba(248, 250, 252, 0.66);
  border: 1px solid rgba(226, 232, 240, 0.72);
  padding: 0.75rem 1rem;
  box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.04);
}
</style>
