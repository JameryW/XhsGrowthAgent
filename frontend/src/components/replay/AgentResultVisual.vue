<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { CheckpointSnapshot } from '@/types/workflow'

const { t } = useI18n()
defineProps<{ cp: CheckpointSnapshot }>()
</script>

<template>
  <div v-if="cp.visual_plan" class="replay-section">
    <div class="text-[10px] text-slate-400 font-medium mb-2 uppercase tracking-wide">{{ t('showcase.detail.visual') }}</div>

    <!-- Core attributes -->
    <div class="grid grid-cols-2 md:grid-cols-3 gap-2">
      <div class="p-2 rounded-lg liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.layout') }}</div>
        <div class="text-xs font-semibold text-slate-700">{{ cp.visual_plan.layout_style }}</div>
      </div>
      <div class="p-2 rounded-lg liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.imageCount') }}</div>
        <div class="text-xs font-semibold text-slate-700">{{ cp.visual_plan.image_count }}</div>
      </div>
      <div v-if="cp.visual_plan.font_suggestion" class="p-2 rounded-lg liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('replay.font') }}</div>
        <div class="text-xs font-semibold text-slate-700">{{ cp.visual_plan.font_suggestion }}</div>
      </div>
    </div>

    <!-- Color palette -->
    <div v-if="cp.visual_plan.color_palette?.length" class="mt-3">
      <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('replay.colorPalette') }}</div>
      <div class="flex gap-1.5">
        <div v-for="color in cp.visual_plan.color_palette" :key="color" class="w-6 h-6 rounded-full border-2 border-white shadow-sm" :style="{ backgroundColor: color }" :title="color" />
      </div>
    </div>

    <!-- Collapsible: cover prompt -->
    <details v-if="cp.visual_plan.cover_prompt" class="mt-3">
      <summary class="text-[10px] text-slate-400 font-medium cursor-pointer hover:text-slate-600">{{ t('replay.coverPrompt') }}</summary>
      <div class="mt-1.5 p-2.5 rounded-lg liquid-glass-inset text-xs text-slate-600">{{ cp.visual_plan.cover_prompt }}</div>
    </details>

    <!-- Collapsible: image prompts -->
    <details v-if="cp.visual_plan.image_prompts?.length" class="mt-2">
      <summary class="text-[10px] text-slate-400 font-medium cursor-pointer hover:text-slate-600">{{ t('replay.imagePrompts') }}</summary>
      <div class="space-y-1 mt-1.5">
        <div v-for="(prompt, i) in cp.visual_plan.image_prompts" :key="i" class="text-xs text-slate-500 flex gap-1">
          <span class="text-slate-300 shrink-0">{{ i + 1 }}.</span>
          <span class="line-clamp-2">{{ prompt }}</span>
        </div>
      </div>
    </details>

    <!-- Brand elements -->
    <div v-if="cp.visual_plan.brand_elements?.length" class="flex flex-wrap gap-1.5 mt-3">
      <span v-for="el in cp.visual_plan.brand_elements" :key="el" class="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">{{ el }}</span>
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
