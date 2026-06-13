<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import type { CheckpointSnapshot } from '@/types/workflow'

const { t } = useI18n()
defineProps<{
  cp: CheckpointSnapshot
  shootingPlan: Record<string, any> | null
  hideDraft?: boolean
  showPublish?: boolean
}>()

const has = (v: unknown) => !!v && typeof v === 'object' && Object.keys(v as Record<string, unknown>).length > 0
</script>

<template>
  <!-- Brief content summary -->
  <div v-if="cp.brief_content && has(cp.brief_content)" class="p-3 rounded-lg bg-pink-50 border border-pink-100">
    <div class="text-xs text-pink-600 font-medium mb-2">{{ t('brief.contentTitle') }}</div>
    <div class="space-y-1.5">
      <div v-if="cp.brief_content.brand_name" class="flex items-start gap-2">
        <span class="text-[10px] text-slate-400 min-w-[60px]">{{ t('brief.brand') }}</span>
        <span class="text-xs text-slate-700 font-medium">{{ cp.brief_content.brand_name }}</span>
      </div>
      <div v-if="cp.brief_content.product_name" class="flex items-start gap-2">
        <span class="text-[10px] text-slate-400 min-w-[60px]">{{ t('brief.product') }}</span>
        <span class="text-xs text-slate-700 font-medium">{{ cp.brief_content.product_name }}</span>
      </div>
      <div v-if="cp.brief_content.content_direction" class="flex items-start gap-2">
        <span class="text-[10px] text-slate-400 min-w-[60px]">{{ t('brief.direction') }}</span>
        <span class="text-xs text-slate-700">{{ cp.brief_content.content_direction }}</span>
      </div>
      <div v-if="cp.brief_content.selling_points?.length" class="flex items-start gap-2">
        <span class="text-[10px] text-slate-400 min-w-[60px]">{{ t('brief.sellingPoints') }}</span>
        <div class="flex flex-wrap gap-1">
          <span v-for="sp in cp.brief_content.selling_points" :key="sp" class="text-[10px] px-1.5 py-0.5 rounded bg-pink-100 text-pink-600">{{ sp }}</span>
        </div>
      </div>
      <div v-if="cp.brief_content.required_hashtags?.length" class="flex items-start gap-2">
        <span class="text-[10px] text-slate-400 min-w-[60px]">{{ t('brief.hashtags') }}</span>
        <div class="flex flex-wrap gap-1">
          <span v-for="tag in cp.brief_content.required_hashtags" :key="tag" class="text-[10px] px-1.5 py-0.5 rounded bg-teal-50 text-teal-600">#{{ tag }}</span>
        </div>
      </div>
      <span v-if="cp.brief_content.confidence != null" class="text-[10px] px-1.5 py-0.5 rounded-full" :class="(cp.brief_content.confidence ?? 0) >= 0.6 ? 'bg-teal-50 text-teal-600' : 'bg-amber-50 text-amber-600'">
        {{ Math.round((cp.brief_content.confidence ?? 0) * 100) }}%
      </span>
    </div>
  </div>

  <!-- Shooting plan -->
  <div v-if="shootingPlan && Object.keys(shootingPlan).length > 0" class="p-3 rounded-lg bg-violet-50 border border-violet-100">
    <div class="text-xs text-violet-600 font-medium mb-2">{{ t('shootingPlan.title') }}</div>
    <div class="grid grid-cols-2 gap-2 mb-2">
      <div v-if="shootingPlan.creator_nickname" class="p-2 rounded liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('shootingPlan.creator') }}</div>
        <div class="text-xs text-slate-700">{{ shootingPlan.creator_nickname }}</div>
      </div>
      <div v-if="shootingPlan.content_type_label" class="p-2 rounded liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('shootingPlan.type') }}</div>
        <div class="text-xs text-slate-700">{{ shootingPlan.content_type_label }}</div>
      </div>
      <div v-if="shootingPlan.content_direction" class="p-2 rounded liquid-glass-inset">
        <div class="text-[10px] text-slate-400">{{ t('shootingPlan.direction') }}</div>
        <div class="text-xs text-slate-700">{{ shootingPlan.content_direction }}</div>
      </div>
      <div v-if="shootingPlan.product_specification" class="p-2 rounded bg-rose-50 border border-rose-100">
        <div class="text-[10px] text-rose-500">{{ t('shootingPlan.product') }}</div>
        <div class="text-xs text-rose-700">{{ shootingPlan.product_specification }}</div>
      </div>
    </div>
    <div v-if="shootingPlan.title_candidates?.length" class="mb-2">
      <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('shootingPlan.titleCandidates') }}</div>
      <div class="space-y-0.5">
        <div v-for="(title, i) in shootingPlan.title_candidates" :key="i" class="text-xs text-slate-600">
          <span class="text-violet-400 font-medium">{{ i + 1 }}.</span> {{ title }}
        </div>
      </div>
    </div>
    <div v-if="shootingPlan.body_copy" class="p-2.5 rounded-lg liquid-glass-inset mb-2">
      <p class="text-xs text-slate-600 whitespace-pre-line line-clamp-6">{{ shootingPlan.body_copy }}</p>
    </div>
    <div v-if="shootingPlan.required_hashtags?.length || shootingPlan.optional_hashtags?.length" class="flex flex-wrap gap-1.5 mb-2">
      <span v-for="tag in (shootingPlan.required_hashtags || [])" :key="'r-'+tag" class="text-[10px] px-1.5 py-0.5 rounded-full bg-rose-50 text-rose-600 border border-rose-200 font-medium">#{{ tag }}</span>
      <span v-for="tag in (shootingPlan.optional_hashtags || [])" :key="'o-'+tag" class="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-50 text-slate-500 border border-slate-200">#{{ tag }}</span>
    </div>
    <div v-if="shootingPlan.outfits && Object.keys(shootingPlan.outfits).length > 0" class="mb-2">
      <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('shootingPlan.outfits') }}</div>
      <div class="grid grid-cols-2 gap-1.5">
        <div v-for="(items, scene) in shootingPlan.outfits" :key="scene" class="p-1.5 rounded bg-violet-50 border border-violet-100">
          <span class="text-[10px] text-violet-500 font-medium">{{ scene }}</span>
          <p class="text-[10px] text-violet-700">{{ (items as string[]).join(', ') }}</p>
        </div>
      </div>
    </div>
    <div v-if="shootingPlan.shooting_angles?.length" class="space-y-1.5">
      <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('shootingPlan.shootingAngles') }}</div>
      <div v-for="(angle, i) in shootingPlan.shooting_angles" :key="i" class="p-2 rounded liquid-glass-inset">
        <div class="flex items-center gap-1.5 mb-0.5">
          <AppIcon name="Camera" size="xs" variant="cyan" />
          <span class="text-xs font-medium text-slate-700">{{ angle.angle }}</span>
        </div>
        <p class="text-[10px] text-slate-500">{{ angle.description }}</p>
        <p v-if="angle.tips" class="text-[10px] text-teal-500 mt-0.5">{{ t('shootingPlan.tip') }}: {{ angle.tips }}</p>
      </div>
    </div>
  </div>

  <!-- Publish result (placed below shooting plan) -->
  <div v-if="showPublish && cp.publish_result && has(cp.publish_result)" class="p-3 rounded-lg bg-emerald-50 border border-emerald-100">
    <div class="text-xs text-emerald-600 font-medium mb-2">{{ t('replay.publishResult') }}</div>
    <div class="space-y-1.5">
      <div v-if="(cp.publish_result as any).post_url" class="flex items-start gap-2">
        <span class="text-[10px] text-slate-400 min-w-[60px]">URL</span>
        <a :href="(cp.publish_result as any).post_url" target="_blank" rel="noopener" class="text-xs text-emerald-600 hover:text-emerald-700 font-medium underline underline-offset-2">{{ (cp.publish_result as any).post_url }}</a>
      </div>
      <div v-if="(cp.publish_result as any).status" class="flex items-start gap-2">
        <span class="text-[10px] text-slate-400 min-w-[60px]">{{ t('replay.status') }}</span>
        <span class="text-xs text-slate-700">{{ (cp.publish_result as any).status }}</span>
      </div>
    </div>
  </div>

  <!-- Copy content -->
  <template v-if="cp.copy_content && Object.keys(cp.copy_content).length > 0">
    <div v-if="cp.draft_content?.text" class="text-[10px] text-slate-400 font-medium uppercase tracking-wide mb-1">{{ t('replay.finalCopy') }}</div>
    <div v-if="cp.copy_content.selected_title" class="text-sm font-semibold text-rose-600 leading-snug">{{ cp.copy_content.selected_title }}</div>
    <div v-if="cp.copy_content.title_candidates?.length && cp.copy_content.title_candidates.length > 1">
      <div class="text-xs text-slate-400 font-medium mb-1">{{ t('replay.titleCandidates') }}</div>
      <div class="space-y-0.5">
        <div v-for="(title, i) in cp.copy_content.title_candidates" :key="i" class="text-xs" :class="title === cp.copy_content.selected_title ? 'text-violet-600 font-semibold' : 'text-slate-500'">
          {{ i + 1 }}. {{ title }}
        </div>
      </div>
    </div>
    <div v-if="cp.copy_content.body_text" class="p-3 rounded-lg liquid-glass-inset">
      <p class="text-xs text-slate-600 whitespace-pre-line">{{ cp.copy_content.body_text }}</p>
    </div>
    <div v-if="cp.copy_content.hashtags?.length" class="flex flex-wrap gap-1.5">
      <span v-for="tag in cp.copy_content.hashtags" :key="tag" class="text-[11px] px-2 py-0.5 rounded-md bg-teal-50 text-teal-600 border border-teal-100">#{{ tag }}</span>
    </div>
    <div class="grid grid-cols-2 md:grid-cols-3 gap-2">
      <div v-if="cp.copy_content.cta" class="p-2 rounded-lg bg-rose-50 border border-rose-100">
        <div class="text-[10px] text-rose-500 font-medium">CTA</div>
        <div class="text-xs text-rose-700">{{ cp.copy_content.cta }}</div>
      </div>
      <div v-if="cp.copy_content.tone" class="p-2 rounded-lg bg-violet-50 border border-violet-100">
        <div class="text-[10px] text-violet-500 font-medium">{{ t('replay.tone') }}</div>
        <div class="text-xs text-violet-700">{{ cp.copy_content.tone }}</div>
      </div>
      <div v-if="cp.copy_content.emoji_usage?.length" class="p-2 rounded-lg bg-amber-50 border border-amber-100">
        <div class="text-[10px] text-amber-500 font-medium">{{ t('replay.emoji') }}</div>
        <div class="text-xs text-amber-700">{{ cp.copy_content.emoji_usage.join(' ') }}</div>
      </div>
    </div>

  </template>

  <!-- Draft content (independent of copy_content) -->
  <div v-if="!hideDraft && cp.draft_content?.text" class="p-3 rounded-lg bg-blue-50 border border-blue-100">
    <div class="text-[10px] text-blue-500 font-medium mb-1">{{ t('replay.draftContent') }}</div>
    <div v-if="cp.draft_content.title" class="text-xs font-semibold text-blue-700 mb-0.5">{{ cp.draft_content.title }}</div>
    <div v-if="cp.draft_content.text" class="text-xs text-blue-600 whitespace-pre-line line-clamp-6">{{ cp.draft_content.text }}</div>
    <div v-if="cp.draft_content.hashtags?.length" class="flex flex-wrap gap-1 mt-1">
      <span v-for="tag in cp.draft_content.hashtags" :key="tag" class="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-600">#{{ tag }}</span>
    </div>
  </div>

  <!-- Optimization analysis (independent of copy_content) -->
  <div v-if="cp.optimization_analysis && (cp.optimization_analysis.gaps?.length || cp.optimization_analysis.suggestions?.length || cp.optimization_analysis.viral_patterns?.length)" class="p-3 rounded-lg bg-violet-50 border border-violet-100">
    <div class="text-[10px] text-violet-500 font-medium mb-1.5">{{ t('replay.optimizationAnalysis') }}</div>
    <div v-if="cp.optimization_analysis.gaps?.length" class="mb-2">
      <div class="text-[10px] text-violet-400 mb-0.5">{{ t('replay.gapAnalysis') }}</div>
      <div class="space-y-1">
        <div v-for="(gap, i) in cp.optimization_analysis.gaps" :key="i" class="text-xs flex gap-1.5">
          <span class="shrink-0 px-1 rounded text-[10px] font-medium" :class="gap.severity === 'high' ? 'bg-red-100 text-red-600' : gap.severity === 'medium' ? 'bg-amber-100 text-amber-600' : 'bg-green-100 text-green-600'">{{ gap.severity }}</span>
          <div>
            <div class="text-slate-700 font-medium">{{ gap.dimension }}</div>
            <div class="text-slate-500">{{ gap.description }}</div>
          </div>
        </div>
      </div>
    </div>
    <div v-if="cp.optimization_analysis.suggestions?.length" class="mb-2">
      <div class="text-[10px] text-violet-400 mb-0.5">{{ t('replay.suggestions') }}</div>
      <div class="space-y-1">
        <div v-for="(sug, i) in cp.optimization_analysis.suggestions" :key="i" class="text-xs flex gap-1.5">
          <span class="shrink-0 text-violet-400">P{{ sug.priority }}</span>
          <div>
            <div class="text-slate-700">{{ sug.action }}</div>
            <div class="text-slate-500 text-[11px]">{{ sug.reasoning }}</div>
          </div>
        </div>
      </div>
    </div>
    <div v-if="cp.optimization_analysis.viral_patterns?.length">
      <div class="text-[10px] text-violet-400 mb-0.5">{{ t('replay.viralPatterns') }}</div>
      <div class="flex flex-wrap gap-1">
        <span v-for="p in cp.optimization_analysis.viral_patterns" :key="p" class="text-[11px] px-1.5 py-0.5 rounded-md bg-violet-100 text-violet-600">{{ p }}</span>
      </div>
    </div>
  </div>

  <!-- Content versions (independent of copy_content) -->
  <div v-if="cp.content_versions?.length">
    <div class="text-xs text-slate-400 font-medium mb-1.5 uppercase tracking-wide">{{ t('replay.contentVersions') }} ({{ cp.content_versions.length }})</div>
    <div class="space-y-2">
      <div v-for="(ver, i) in cp.content_versions" :key="ver.version_id || i" class="p-2.5 rounded-lg border" :class="ver.version_type === 'A' ? 'bg-rose-50 border-rose-100' : ver.version_type === 'B' ? 'bg-blue-50 border-blue-100' : 'bg-emerald-50 border-emerald-100'">
        <div class="flex items-center justify-between mb-1">
          <div class="flex items-center gap-1.5">
            <span class="text-[10px] font-bold px-1.5 py-0.5 rounded" :class="ver.version_type === 'A' ? 'bg-rose-200 text-rose-700' : ver.version_type === 'B' ? 'bg-blue-200 text-blue-700' : 'bg-emerald-200 text-emerald-700'">{{ t('review.versionLabel', { n: ver.version_type || (i + 1) }) }}</span>
            <span class="text-xs font-semibold" :class="ver.version_type === 'A' ? 'text-rose-700' : ver.version_type === 'B' ? 'text-blue-700' : 'text-emerald-700'">{{ ver.title }}</span>
          </div>
          <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-500">{{ ver.predicted_score }}{{ t('versionCompare.scoreUnit') }}</span>
        </div>
        <div v-if="ver.body" class="text-xs text-slate-600 whitespace-pre-line line-clamp-4 mb-1">{{ ver.body }}</div>
        <div v-if="ver.changes_summary" class="text-[11px] text-slate-400 mb-1">&#8635; {{ ver.changes_summary }}</div>
        <div class="flex flex-wrap gap-1">
          <span v-for="tag in ver.hashtags" :key="tag" class="text-[10px] px-1 py-0.5 rounded bg-teal-50 text-teal-600">#{{ tag }}</span>
          <span v-if="ver.style_suggestion" class="text-[10px] px-1 py-0.5 rounded bg-violet-50 text-violet-600">{{ ver.style_suggestion }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
