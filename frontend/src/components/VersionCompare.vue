<script setup lang="ts">
import { ref, computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import MiniProgress from '@/components/MiniProgress.vue'
import type { ContentVersion, OptimizationAnalysis, VersionChoice } from '@/types/optimization'

interface Props {
  versions: ContentVersion[]
  analysis?: OptimizationAnalysis | null
  isLoading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  isLoading: false,
})

const emit = defineEmits<{
  (e: 'select', choice: VersionChoice): void
}>()

// State
const selectedVersionId = ref<string | null>(null)

// Computed
const selectedVersion = computed(() =>
  props.versions.find(v => v.version_id === selectedVersionId.value)
)

const sortedVersions = computed(() =>
  [...props.versions].sort((a, b) => b.predicted_score - a.predicted_score)
)

const bestVersion = computed(() => sortedVersions.value[0])

const gapSeverityClass = (severity: string): string => {
  switch (severity) {
    case 'high': return 'text-neon-pink border-neon-pink/30'
    case 'medium': return 'text-neon-peach border-neon-peach/30'
    case 'low': return 'text-slate-400 border-slate-200'
    default: return 'text-slate-400 border-slate-200'
  }
}

const suggestionPriorityClass = (priority: number): string => {
  if (priority >= 8) return 'bg-neon-pink/10 border-neon-pink'
  if (priority >= 5) return 'bg-neon-peach/10 border-neon-peach'
  return 'bg-slate-50 border-slate-200'
}

// Actions
function selectVersion(versionId: string) {
  selectedVersionId.value = versionId
}

function handleConfirm() {
  if (!selectedVersionId.value) return

  const version = props.versions.find(v => v.version_id === selectedVersionId.value)
  if (!version) return

  emit('select', {
    selected_version: version.version_type,
    version_id: selectedVersionId.value,
  })
}

function getVersionTypeLabel(type: string): string {
  switch (type) {
    case 'A': return '保守优化'
    case 'B': return '平衡优化'
    case 'C': return '激进优化'
    default: return type
  }
}

function getVersionTypeColor(type: string): string {
  switch (type) {
    case 'A': return 'border-teal-200 bg-teal-50 text-teal-600'
    case 'B': return 'border-neon-cyan bg-neon-cyan/10 text-neon-cyan'
    case 'C': return 'border-neon-pink bg-neon-pink/10 text-neon-pink'
    default: return 'border-slate-200 bg-slate-50 text-slate-600'
  }
}
</script>

<template>
  <div class="space-y-6">
    <!-- Optimization Analysis Summary -->
    <div v-if="props.analysis" class="rounded-xl p-5 bg-white/98 backdrop-blur-sm border border-neon-purple/10">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-11 h-11 rounded-xl bg-gradient-to-br from-neon-purple via-neon-purpleLight to-neon-blue flex items-center justify-center shadow-sm">
          <AppIcon name="Scan" size="md" variant="white" aria-label="Analysis" />
        </div>
        <div class="flex-1">
          <div class="text-slate-800 font-semibold text-sm">优化分析报告</div>
          <div class="text-xs text-slate-400 uppercase tracking-wide">Gap Analysis</div>
        </div>
      </div>

      <!-- Gaps -->
      <div v-if="props.analysis.gaps.length > 0" class="mb-4">
        <h4 class="text-xs text-slate-500 font-medium mb-2">发现差距</h4>
        <div class="space-y-2">
          <div
            v-for="gap in props.analysis.gaps"
            :key="gap.dimension"
            :class="['px-3 py-2 rounded-lg border-l-2', gapSeverityClass(gap.severity)]"
          >
            <div class="flex items-center justify-between">
              <span class="text-xs font-medium text-slate-700">{{ gap.dimension }}</span>
              <span :class="['text-xs px-2 py-0.5 rounded-full', gapSeverityClass(gap.severity)]">
                {{ gap.severity }}
              </span>
            </div>
            <p class="text-xs text-slate-500 mt-1">{{ gap.description }}</p>
          </div>
        </div>
      </div>

      <!-- Suggestions -->
      <div v-if="props.analysis.suggestions.length > 0">
        <h4 class="text-xs text-slate-500 font-medium mb-2">优化建议</h4>
        <div class="space-y-2">
          <div
            v-for="suggestion in props.analysis.suggestions"
            :key="suggestion.dimension"
            :class="['px-3 py-2.5 rounded-lg border', suggestionPriorityClass(suggestion.priority)]"
          >
            <div class="flex items-center justify-between mb-1">
              <span class="text-xs font-medium text-slate-700">{{ suggestion.dimension }}</span>
              <span class="text-xs text-slate-400">优先级 {{ suggestion.priority }}</span>
            </div>
            <p class="text-xs text-slate-600 font-medium">{{ suggestion.action }}</p>
            <p class="text-xs text-slate-400 mt-0.5">{{ suggestion.reasoning }}</p>
          </div>
        </div>
      </div>

      <!-- Viral Patterns -->
      <div v-if="props.analysis.viral_patterns.length > 0" class="mt-4 pt-4 border-t border-slate-100">
        <h4 class="text-xs text-slate-500 font-medium mb-2">爆款模式</h4>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="pattern in props.analysis.viral_patterns"
            :key="pattern"
            class="px-3 py-1 rounded-full bg-neon-purple/10 text-neon-purple text-xs"
          >
            {{ pattern }}
          </span>
        </div>
      </div>
    </div>

    <!-- Version Comparison -->
    <div class="rounded-xl p-5 bg-white/98 backdrop-blur-sm border border-neon-cyan/10">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-11 h-11 rounded-xl bg-gradient-to-br from-neon-cyan via-neon-cyanLight to-neon-green flex items-center justify-center shadow-sm">
          <AppIcon name="GitBranch" size="md" variant="white" aria-label="Versions" />
        </div>
        <div class="flex-1">
          <div class="text-slate-800 font-semibold text-sm">版本对比</div>
          <div class="text-xs text-slate-400 uppercase tracking-wide">Choose Your Version</div>
        </div>
      </div>

      <!-- Version Cards -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div
          v-for="version in sortedVersions"
          :key="version.version_id"
          :class="[
            'rounded-lg p-4 border-2 cursor-pointer transition-all hover:shadow-md',
            selectedVersionId === version.version_id
              ? 'border-neon-cyan bg-neon-cyan/5 shadow-neon-cyan-sm'
              : 'border-slate-100 hover:border-slate-200'
          ]"
          @click="selectVersion(version.version_id)"
        >
          <!-- Version Header -->
          <div class="flex items-center justify-between mb-3">
            <span :class="['px-2 py-1 rounded-lg text-xs font-semibold border', getVersionTypeColor(version.version_type)]">
              {{ version.version_type }} 版
            </span>
            <span :class="['text-xs', version.version_id === bestVersion?.version_id ? 'text-teal-500 font-medium' : 'text-slate-400']">
              {{ version.version_id === bestVersion?.version_id ? '最佳推荐' : `评分 ${version.predicted_score.toFixed(1)}` }}
            </span>
          </div>

          <!-- Predicted Score -->
          <MiniProgress
            :value="version.predicted_score"
            :max="100"
            :label="'预测得分'"
            :color="version.version_type === 'C' ? 'pink' : version.version_type === 'B' ? 'cyan' : 'teal'"
          />

          <!-- Title Preview -->
          <div class="mt-3">
            <h4 class="text-sm font-medium text-slate-700 line-clamp-2">{{ version.title }}</h4>
          </div>

          <!-- Body Preview -->
          <div class="mt-2">
            <p class="text-xs text-slate-500 line-clamp-3">{{ version.body.slice(0, 150) }}...</p>
          </div>

          <!-- Hashtags -->
          <div v-if="version.hashtags.length > 0" class="flex flex-wrap gap-1 mt-3">
            <span
              v-for="tag in version.hashtags.slice(0, 4)"
              :key="tag"
              class="px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-500 text-xs"
            >
              #{{ tag }}
            </span>
          </div>

          <!-- Changes Summary -->
          <div class="mt-3 pt-3 border-t border-slate-100">
            <p class="text-xs text-slate-400">{{ version.changes_summary }}</p>
          </div>

          <!-- Style Suggestion -->
          <div v-if="version.style_suggestion" class="mt-2">
            <p class="text-xs text-neon-cyan">💡 {{ version.style_suggestion }}</p>
          </div>
        </div>
      </div>

      <!-- Selection Indicator -->
      <div v-if="selectedVersion" class="mt-4 p-3 rounded-lg bg-teal-50 border border-teal-100">
        <div class="flex items-center gap-2">
          <AppIcon name="CheckCircle" size="sm" variant="cyan" />
          <span class="text-xs text-teal-600 font-medium">
            已选择 {{ selectedVersion.version_type }} 版 - {{ selectedVersion.title }}
          </span>
        </div>
      </div>

      <!-- Actions -->
      <div class="flex gap-3 mt-5 pt-4 border-t border-slate-100">
        <NeonButton
          variant="cyan"
          :disabled="!selectedVersionId || props.isLoading"
          :loading="props.isLoading"
          @click="handleConfirm"
        >
          <AppIcon name="Check" size="sm" variant="white" />
          <span>确认选择</span>
        </NeonButton>
      </div>
    </div>
  </div>
</template>