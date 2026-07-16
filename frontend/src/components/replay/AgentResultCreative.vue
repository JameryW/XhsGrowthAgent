<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import type { CheckpointSnapshot } from '@/types/workflow'

const { t, locale } = useI18n()
defineProps<{
  cp: CheckpointSnapshot
  shootingPlan: Record<string, any> | null
  hideDraft?: boolean
  showPublish?: boolean
}>()

const has = (v: unknown) => !!v && typeof v === 'object' && Object.keys(v as Record<string, unknown>).length > 0
</script>

<template>
  <!-- ============ Brief & Shooting (默认展开) ============ -->
  <details v-if="(cp.brief_content && has(cp.brief_content)) || (shootingPlan && Object.keys(shootingPlan).length > 0)" open class="replay-section">
    <summary class="replay-section-header">
      <AppIcon name="ClipboardList" size="sm" variant="cyan" />
      <span class="text-sm font-semibold text-slate-700">{{ t('brief.contentTitle') }}</span>
    </summary>

    <div class="space-y-3 mt-3">
      <!-- Brief content -->
      <div v-if="cp.brief_content && has(cp.brief_content)" class="space-y-1.5">
        <div v-if="cp.brief_content.brand_name" class="flex items-start gap-2">
          <span class="text-[10px] text-slate-400 min-w-[60px]">{{ t('brief.brand') }}</span>
          <span class="text-sm font-semibold text-slate-800">{{ cp.brief_content.brand_name }}</span>
        </div>
        <div v-if="cp.brief_content.product_name" class="flex items-start gap-2">
          <span class="text-[10px] text-slate-400 min-w-[60px]">{{ t('brief.product') }}</span>
          <span class="text-sm font-semibold text-slate-700">{{ cp.brief_content.product_name }}</span>
        </div>
        <div v-if="cp.brief_content.content_direction" class="flex items-start gap-2">
          <span class="text-[10px] text-slate-400 min-w-[60px]">{{ t('brief.direction') }}</span>
          <span class="text-xs text-slate-600">{{ cp.brief_content.content_direction }}</span>
        </div>
        <div v-if="cp.brief_content.selling_points?.length" class="flex items-start gap-2">
          <span class="text-[10px] text-slate-400 min-w-[60px]">{{ t('brief.sellingPoints') }}</span>
          <div class="flex flex-wrap gap-1">
            <span v-for="sp in cp.brief_content.selling_points.slice(0, 3)" :key="sp" class="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">{{ sp }}</span>
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

      <!-- Shooting plan -->
      <div v-if="shootingPlan && Object.keys(shootingPlan).length > 0" class="space-y-2">
        <div class="grid grid-cols-2 gap-2">
          <div v-if="shootingPlan.creator_nickname" class="p-2 rounded-lg liquid-glass-inset">
            <div class="text-[10px] text-slate-400">{{ t('shootingPlan.creator') }}</div>
            <div class="text-xs font-medium text-slate-700">{{ shootingPlan.creator_nickname }}</div>
          </div>
          <div v-if="shootingPlan.content_type_label" class="p-2 rounded-lg liquid-glass-inset">
            <div class="text-[10px] text-slate-400">{{ t('shootingPlan.type') }}</div>
            <div class="text-xs font-medium text-slate-700">{{ shootingPlan.content_type_label }}</div>
          </div>
          <div v-if="shootingPlan.content_direction" class="p-2 rounded-lg liquid-glass-inset">
            <div class="text-[10px] text-slate-400">{{ t('shootingPlan.direction') }}</div>
            <div class="text-xs text-slate-700">{{ shootingPlan.content_direction }}</div>
          </div>
          <div v-if="shootingPlan.product_specification" class="p-2 rounded-lg liquid-glass-inset">
            <div class="text-[10px] text-slate-400">{{ t('shootingPlan.product') }}</div>
            <div class="text-xs font-medium text-slate-700">{{ shootingPlan.product_specification }}</div>
          </div>
        </div>
        <div v-if="shootingPlan.title_candidates?.length" class="space-y-0.5">
          <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('shootingPlan.titleCandidates') }}</div>
          <div v-for="(title, i) in shootingPlan.title_candidates" :key="i" class="text-xs text-slate-600">
            <span class="text-slate-400 font-medium">{{ i + 1 }}.</span> {{ title }}
          </div>
        </div>
        <div v-if="shootingPlan.body_copy" class="p-2.5 rounded-lg liquid-glass-inset">
          <p class="text-xs text-slate-600 whitespace-pre-line line-clamp-6">{{ shootingPlan.body_copy }}</p>
        </div>
        <div v-if="shootingPlan.required_hashtags?.length || shootingPlan.optional_hashtags?.length" class="flex flex-wrap gap-1.5">
          <span v-for="tag in (shootingPlan.required_hashtags || [])" :key="'r-'+tag" class="text-[10px] px-1.5 py-0.5 rounded-full bg-teal-50 text-teal-600">#{{ tag }}</span>
          <span v-for="tag in (shootingPlan.optional_hashtags || [])" :key="'o-'+tag" class="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-50 text-slate-500">#{{ tag }}</span>
        </div>
        <details v-if="shootingPlan.outfits && Object.keys(shootingPlan.outfits).length > 0" class="text-xs">
          <summary class="text-[10px] text-slate-400 font-medium cursor-pointer hover:text-slate-600">{{ t('shootingPlan.outfits') }}</summary>
          <div class="grid grid-cols-2 gap-1.5 mt-1.5">
            <div v-for="(items, scene) in shootingPlan.outfits" :key="scene" class="p-1.5 rounded-lg liquid-glass-inset">
              <span class="text-[10px] text-slate-500 font-medium">{{ scene }}</span>
              <p class="text-[10px] text-slate-600">{{ (items as string[]).join(', ') }}</p>
            </div>
          </div>
        </details>
        <details v-if="shootingPlan.shooting_angles?.length" class="text-xs">
          <summary class="text-[10px] text-slate-400 font-medium cursor-pointer hover:text-slate-600">{{ t('shootingPlan.shootingAngles') }}</summary>
          <div class="space-y-1.5 mt-1.5">
            <div v-for="(angle, i) in shootingPlan.shooting_angles" :key="i" class="p-2 rounded-lg liquid-glass-inset">
              <div class="flex items-center gap-1.5 mb-0.5">
                <AppIcon name="Camera" size="xs" variant="cyan" />
                <span class="text-xs font-medium text-slate-700">{{ angle.angle }}</span>
              </div>
              <p class="text-[10px] text-slate-500">{{ angle.description }}</p>
              <p v-if="angle.tips" class="text-[10px] text-teal-500 mt-0.5">{{ t('shootingPlan.tip') }}: {{ angle.tips }}</p>
            </div>
          </div>
        </details>
      </div>
    </div>
  </details>

  <!-- ============ Copy Content (默认展开) ============ -->
  <details v-if="cp.copy_content && Object.keys(cp.copy_content).length > 0" open class="replay-section">
    <summary class="replay-section-header">
      <AppIcon name="Pencil" size="sm" variant="pink" />
      <span class="text-sm font-semibold text-slate-700">{{ t('replay.finalCopy') }}</span>
    </summary>

    <div class="space-y-3 mt-3">
      <!-- Selected title — L1 -->
      <div v-if="cp.copy_content.selected_title" class="text-base font-bold text-slate-800 leading-snug">{{ cp.copy_content.selected_title }}</div>

      <!-- Title candidates — L3 -->
      <details v-if="cp.copy_content.title_candidates?.length && cp.copy_content.title_candidates.length > 1" class="text-xs">
        <summary class="text-[10px] text-slate-400 font-medium cursor-pointer hover:text-slate-600">{{ t('replay.titleCandidates') }}</summary>
        <div class="space-y-0.5 mt-1">
          <div v-for="(title, i) in cp.copy_content.title_candidates" :key="i" class="text-xs" :class="title === cp.copy_content.selected_title ? 'text-slate-800 font-semibold' : 'text-slate-500'">
            {{ i + 1 }}. {{ title }}
          </div>
        </div>
      </details>

      <!-- Body text -->
      <div v-if="cp.copy_content.body_text" class="p-3 rounded-lg liquid-glass-inset">
        <p class="text-xs text-slate-600 whitespace-pre-line">{{ cp.copy_content.body_text }}</p>
      </div>

      <!-- Hashtags -->
      <div v-if="cp.copy_content.hashtags?.length" class="flex flex-wrap gap-1.5">
        <span v-for="tag in cp.copy_content.hashtags" :key="tag" class="text-[10px] px-1.5 py-0.5 rounded bg-teal-50 text-teal-600">#{{ tag }}</span>
      </div>

      <!-- CTA / Tone / Emoji — compact row -->
      <div class="grid grid-cols-3 gap-2">
        <div v-if="cp.copy_content.cta" class="p-2 rounded-lg liquid-glass-inset">
          <div class="text-[10px] text-slate-400">CTA</div>
          <div class="text-xs font-medium text-slate-700">{{ cp.copy_content.cta }}</div>
        </div>
        <div v-if="cp.copy_content.tone" class="p-2 rounded-lg liquid-glass-inset">
          <div class="text-[10px] text-slate-400">{{ t('replay.tone') }}</div>
          <div class="text-xs font-medium text-slate-700">{{ cp.copy_content.tone }}</div>
        </div>
        <div v-if="cp.copy_content.emoji_usage?.length" class="p-2 rounded-lg liquid-glass-inset">
          <div class="text-[10px] text-slate-400">{{ t('replay.emoji') }}</div>
          <div class="text-xs text-slate-700">{{ cp.copy_content.emoji_usage.join(' ') }}</div>
        </div>
      </div>
    </div>
  </details>

  <!-- ============ Draft Content (默认折叠) ============ -->
  <details v-if="!hideDraft && cp.draft_content?.text" class="replay-section">
    <summary class="replay-section-header">
      <AppIcon name="FileText" size="sm" variant="cyan" />
      <span class="text-sm font-semibold text-slate-700">{{ t('replay.draftContent') }}</span>
    </summary>

    <div class="space-y-2 mt-3">
      <div v-if="cp.draft_content.title" class="text-sm font-semibold text-slate-800">{{ cp.draft_content.title }}</div>
      <div v-if="cp.draft_content.text" class="p-3 rounded-lg liquid-glass-inset">
        <p class="text-xs text-slate-600 whitespace-pre-line line-clamp-6">{{ cp.draft_content.text }}</p>
      </div>
      <div v-if="cp.draft_content.hashtags?.length" class="flex flex-wrap gap-1">
        <span v-for="tag in cp.draft_content.hashtags" :key="tag" class="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">#{{ tag }}</span>
      </div>
    </div>
  </details>

  <!-- ============ Optimization (默认折叠) ============ -->
  <details v-if="cp.optimization_analysis && (cp.optimization_analysis.gaps?.length || cp.optimization_analysis.suggestions?.length || cp.optimization_analysis.viral_patterns?.length)" class="replay-section">
    <summary class="replay-section-header">
      <AppIcon name="TrendingUp" size="sm" variant="purple" />
      <span class="text-sm font-semibold text-slate-700">{{ t('replay.optimizationAnalysis') }}</span>
    </summary>

    <div class="space-y-3 mt-3">
      <!-- Gaps -->
      <div v-if="cp.optimization_analysis.gaps?.length">
        <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('replay.gapAnalysis') }}</div>
        <div class="space-y-1">
          <div v-for="(gap, i) in cp.optimization_analysis.gaps" :key="i" class="flex items-start gap-2 p-2 rounded-lg liquid-glass-inset">
            <span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium" :class="gap.severity === 'high' ? 'bg-red-50 text-red-600' : gap.severity === 'medium' ? 'bg-amber-50 text-amber-600' : 'bg-emerald-50 text-emerald-600'">{{ gap.severity }}</span>
            <div class="min-w-0">
              <div class="text-xs font-medium text-slate-700">{{ gap.dimension }}</div>
              <div class="text-[11px] text-slate-500">{{ gap.description }}</div>
            </div>
          </div>
        </div>
      </div>
      <!-- Suggestions -->
      <div v-if="cp.optimization_analysis.suggestions?.length">
        <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('replay.suggestions') }}</div>
        <div class="space-y-1">
          <div v-for="(sug, i) in cp.optimization_analysis.suggestions" :key="i" class="flex items-start gap-2 p-2 rounded-lg liquid-glass-inset">
            <span class="shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 font-medium">P{{ sug.priority }}</span>
            <div class="min-w-0">
              <div class="text-xs text-slate-700">{{ sug.action }}</div>
              <div class="text-[11px] text-slate-500">{{ sug.reasoning }}</div>
            </div>
          </div>
        </div>
      </div>
      <!-- Viral patterns -->
      <div v-if="cp.optimization_analysis.viral_patterns?.length">
        <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('replay.viralPatterns') }}</div>
        <div class="flex flex-wrap gap-1">
          <span v-for="p in cp.optimization_analysis.viral_patterns" :key="p" class="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">{{ p }}</span>
        </div>
      </div>
    </div>
  </details>

  <!-- ============ Content Versions (默认折叠) ============ -->
  <details v-if="cp.content_versions?.length" class="replay-section">
    <summary class="replay-section-header">
      <AppIcon name="GitBranch" size="sm" variant="cyan" />
      <span class="text-sm font-semibold text-slate-700">{{ t('replay.contentVersions') }} ({{ cp.content_versions.length }})</span>
    </summary>

    <div class="space-y-2 mt-3">
      <div v-for="(ver, i) in cp.content_versions" :key="ver.version_id || i" class="p-2.5 rounded-lg liquid-glass-inset">
        <div class="flex items-center justify-between mb-1">
          <div class="flex items-center gap-1.5">
            <span class="text-[10px] font-bold px-1.5 py-0.5 rounded" :class="ver.version_type === 'A' ? 'bg-rose-50 text-rose-600' : ver.version_type === 'B' ? 'bg-blue-50 text-blue-600' : 'bg-slate-100 text-slate-600'">{{ t('review.versionLabel', { n: ver.version_type || (i + 1) }) }}</span>
            <span class="text-xs font-semibold text-slate-800">{{ ver.title }}</span>
          </div>
          <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-500">{{ ver.predicted_score }}{{ t('versionCompare.scoreUnit') }}</span>
        </div>
        <div v-if="ver.body" class="text-xs text-slate-600 whitespace-pre-line line-clamp-3 mb-1">{{ ver.body }}</div>
        <div v-if="ver.changes_summary" class="text-[10px] text-slate-400 mb-1">&#8635; {{ ver.changes_summary }}</div>
        <div class="flex flex-wrap gap-1">
          <span v-for="tag in ver.hashtags" :key="tag" class="text-[10px] px-1 py-0.5 rounded bg-teal-50 text-teal-600">#{{ tag }}</span>
          <span v-if="ver.style_suggestion" class="text-[10px] px-1 py-0.5 rounded bg-slate-100 text-slate-500">{{ ver.style_suggestion }}</span>
        </div>
      </div>
    </div>
  </details>

  <!-- ============ Publish Result (默认折叠) ============ -->
  <details v-if="showPublish && cp.publish_result && has(cp.publish_result)" class="replay-section">
    <summary class="replay-section-header">
      <AppIcon name="Upload" size="sm" variant="pink" />
      <span class="text-sm font-semibold text-slate-700">{{ t('replay.publishResult') }}</span>
    </summary>

    <div class="space-y-2 mt-3">
      <div class="grid grid-cols-2 gap-2">
        <div v-if="(cp.publish_result as any).post_id" class="p-2 rounded-lg liquid-glass-inset">
          <div class="text-[10px] text-slate-400">{{ t('replay.postId') }}</div>
          <div class="text-xs font-mono text-slate-700">{{ (cp.publish_result as any).post_id }}</div>
        </div>
        <div v-if="(cp.publish_result as any).status" class="p-2 rounded-lg liquid-glass-inset">
          <div class="text-[10px] text-slate-400">{{ t('replay.status') }}</div>
          <div class="text-xs font-medium" :class="(cp.publish_result as any).status === 'published' ? 'text-emerald-600' : 'text-amber-600'">{{ (cp.publish_result as any).status }}</div>
        </div>
        <div v-if="(cp.publish_result as any).published_at" class="p-2 rounded-lg liquid-glass-inset">
          <div class="text-[10px] text-slate-400">{{ t('replay.publishedAt') }}</div>
          <div class="text-xs text-slate-600">{{ new Date((cp.publish_result as any).published_at).toLocaleString(locale || undefined) }}</div>
        </div>
      </div>
      <div v-if="(cp.publish_result as any).post_url">
        <a :href="(cp.publish_result as any).post_url" target="_blank" rel="noopener" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg liquid-glass-inset text-xs text-emerald-600 font-medium hover:bg-emerald-50 transition-colors">
          <AppIcon name="ExternalLink" size="sm" />
          {{ t('replay.viewPost') }}
        </a>
      </div>
    </div>
  </details>
</template>

<style scoped>
.replay-section {
  border-radius: 0.75rem;
  background: rgba(248, 250, 252, 0.66);
  border: 1px solid rgba(226, 232, 240, 0.72);
  padding: 0.75rem 1rem;
  box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.04);
}

.replay-section-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  user-select: none;
  list-style: none;
}

.replay-section-header::-webkit-details-marker {
  display: none;
}

.replay-section-header::before {
  content: '▸';
  font-size: 10px;
  color: #94a3b8;
  transition: transform 0.15s;
  width: 14px;
  text-align: center;
  flex-shrink: 0;
}

.replay-section[open] > .replay-section-header::before {
  transform: rotate(90deg);
}

.replay-section + .replay-section {
  margin-top: 0.5rem;
}
</style>
