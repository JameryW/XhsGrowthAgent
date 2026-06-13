<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import type { CheckpointSnapshot } from '@/types/workflow'

const { t } = useI18n()
defineProps<{ cp: CheckpointSnapshot }>()
</script>

<template>
  <div v-if="cp.publish_result">
    <div class="grid grid-cols-2 gap-2">
      <div v-if="(cp.publish_result as any).post_id" class="p-2 rounded-lg bg-emerald-50 border border-emerald-100">
        <div class="text-[10px] text-emerald-500 font-medium">{{ t('replay.postId') }}</div>
        <div class="text-xs text-emerald-700 font-mono">{{ (cp.publish_result as any).post_id }}</div>
      </div>
      <div v-if="(cp.publish_result as any).status" class="p-2 rounded-lg liquid-glass-inset">
        <div class="text-[10px] text-slate-400 font-medium">{{ t('replay.status') }}</div>
        <div class="text-xs font-medium" :class="(cp.publish_result as any).status === 'published' ? 'text-emerald-600' : 'text-amber-600'">{{ (cp.publish_result as any).status }}</div>
      </div>
      <div v-if="(cp.publish_result as any).published_at" class="p-2 rounded-lg liquid-glass-inset">
        <div class="text-[10px] text-slate-400 font-medium">{{ t('replay.publishedAt') }}</div>
        <div class="text-xs text-slate-600">{{ new Date((cp.publish_result as any).published_at).toLocaleString() }}</div>
      </div>
    </div>
    <div v-if="(cp.publish_result as any).post_url" class="mt-1">
      <a :href="(cp.publish_result as any).post_url" target="_blank" rel="noopener" class="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-50 text-emerald-600 text-xs font-medium hover:bg-emerald-100 transition-colors border border-emerald-100">
        <AppIcon name="ExternalLink" size="sm" />
        {{ t('replay.viewPost') }}
      </a>
    </div>
  </div>
</template>
