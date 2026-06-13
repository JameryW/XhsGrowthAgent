<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { CheckpointSnapshot } from '@/types/workflow'

const { t } = useI18n()
defineProps<{ cp: CheckpointSnapshot }>()
</script>

<template>
  <div v-if="cp.visual_plan">
    <div class="text-xs text-slate-400 font-medium mb-1.5 uppercase tracking-wide">{{ t('showcase.detail.visual') }}</div>
    <div class="grid grid-cols-2 md:grid-cols-3 gap-2">
      <div class="p-2 rounded-lg liquid-glass-inset">
        <div class="text-[10px] text-slate-400 font-medium">{{ t('replay.layout') }}</div>
        <div class="text-xs text-slate-700">{{ cp.visual_plan.layout_style }}</div>
      </div>
      <div class="p-2 rounded-lg liquid-glass-inset">
        <div class="text-[10px] text-slate-400 font-medium">{{ t('replay.imageCount') }}</div>
        <div class="text-xs text-slate-700">{{ cp.visual_plan.image_count }}</div>
      </div>
      <div v-if="cp.visual_plan.font_suggestion" class="p-2 rounded-lg liquid-glass-inset">
        <div class="text-[10px] text-slate-400 font-medium">{{ t('replay.font') }}</div>
        <div class="text-xs text-slate-700">{{ cp.visual_plan.font_suggestion }}</div>
      </div>
    </div>
    <div v-if="cp.visual_plan.color_palette?.length" class="mt-2">
      <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('replay.colorPalette') }}</div>
      <div class="flex gap-1.5">
        <div v-for="color in cp.visual_plan.color_palette" :key="color" class="w-6 h-6 rounded-full border-2 border-white shadow-sm" :style="{ backgroundColor: color }" :title="color" />
      </div>
    </div>
    <div v-if="cp.visual_plan.cover_prompt" class="mt-2 p-2.5 rounded-lg liquid-glass-inset">
      <div class="text-[10px] text-slate-400 font-medium mb-0.5">{{ t('replay.coverPrompt') }}</div>
      <div class="text-xs text-slate-600">{{ cp.visual_plan.cover_prompt }}</div>
    </div>
    <div v-if="cp.visual_plan.image_prompts?.length" class="mt-2">
      <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('replay.imagePrompts') }}</div>
      <div class="space-y-1">
        <div v-for="(prompt, i) in cp.visual_plan.image_prompts" :key="i" class="text-xs text-slate-500 flex gap-1">
          <span class="text-slate-300 shrink-0">{{ i + 1 }}.</span>
          <span class="line-clamp-2">{{ prompt }}</span>
        </div>
      </div>
    </div>
    <div v-if="cp.visual_plan.brand_elements?.length" class="mt-2 flex flex-wrap gap-1.5">
      <span v-for="el in cp.visual_plan.brand_elements" :key="el" class="text-[11px] px-2 py-0.5 rounded-md bg-amber-50 text-amber-600 border border-amber-100">{{ el }}</span>
    </div>
  </div>
</template>
