<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'

const { t } = useI18n()
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
  [...props.versions].sort((a, b) => (b.predicted_score ?? 0) - (a.predicted_score ?? 0))
)

const bestVersion = computed(() => {
  if (!props.versions.length) return undefined
  const scored = props.versions.filter(v => v.predicted_score != null)
  if (!scored.length) return undefined
  return scored.reduce((best, v) => (v.predicted_score ?? 0) > (best.predicted_score ?? 0) ? v : best)
})

const gapSeverityClass = (severity: string): string => {
  switch (severity) {
    case 'high': return 'text-rose-500 border-rose-300 dark:text-rose-300 dark:border-rose-500/30 dark:bg-rose-950/40'
    case 'medium': return 'text-amber-500 border-amber-300 dark:text-amber-300 dark:border-amber-500/30 dark:bg-amber-950/40'
    case 'low': return 'text-slate-400 border-slate-200 dark:text-slate-400 dark:border-slate-600/50 dark:bg-slate-800/50'
    default: return 'text-slate-400 border-slate-200 dark:text-slate-400 dark:border-slate-600/50 dark:bg-slate-800/50'
  }
}

const suggestionPriorityClass = (priority: number): string => {
  if (priority >= 8) return 'bg-rose-50 border-rose-300 dark:bg-rose-950/40 dark:border-rose-500/30'
  if (priority >= 5) return 'bg-amber-50 border-amber-200 dark:bg-amber-950/40 dark:border-amber-500/30'
  return 'bg-slate-50 border-slate-200 dark:bg-slate-800/70 dark:border-slate-600/50'
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
    selected_version: version.version_type || 'A',
    version_id: selectedVersionId.value,
  })
}

function getVersionTypeColor(type: string): string {
  switch (type) {
    case 'A': return 'border-teal-200 bg-teal-50 text-teal-600 dark:border-teal-500/30 dark:bg-teal-950/40 dark:text-teal-300'
    case 'B': return 'border-cyan-200 bg-cyan-50 text-cyan-600 dark:border-cyan-500/30 dark:bg-cyan-950/40 dark:text-cyan-300'
    case 'C': return 'border-rose-200 bg-rose-50 text-rose-600 dark:border-rose-500/30 dark:bg-rose-950/40 dark:text-rose-300'
    case 'style_a': return 'border-violet-200 bg-violet-50 text-violet-600 dark:border-violet-500/30 dark:bg-violet-950/40 dark:text-violet-300'
    case 'style_b': return 'border-amber-200 bg-amber-50 text-amber-600 dark:border-amber-500/30 dark:bg-amber-950/40 dark:text-amber-300'
    case 'style_c': return 'border-emerald-200 bg-emerald-50 text-emerald-600 dark:border-emerald-500/30 dark:bg-emerald-950/40 dark:text-emerald-300'
    default: return 'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-600/50 dark:bg-slate-800/70 dark:text-slate-300'
  }
}

function getCardClass(version: ContentVersion): string[] {
  const isSelected = selectedVersionId.value === version.version_id
  const isBest = version.version_id === bestVersion.value?.version_id

  const classes = [
    'relative rounded-lg p-4 border-2 cursor-pointer transition-all duration-300',
    'focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/30 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-offset-slate-900',
  ]

  if (isSelected) {
    classes.push('border-teal-400 bg-teal-50/80 scale-[1.02] dark:border-teal-500/60 dark:bg-teal-950/40', 'shadow-lg shadow-teal-500/20', 'ring-2 ring-teal-400/30')
  } else if (isBest) {
    classes.push('border-amber-300 bg-amber-50/50 hover:border-amber-400 hover:bg-amber-50/80 dark:border-amber-500/40 dark:bg-amber-950/30 dark:hover:border-amber-500/60 dark:hover:bg-amber-950/50', 'hover:scale-[1.01]', 'ring-1 ring-amber-300/20')
  } else {
    classes.push('border-slate-100 hover:border-slate-200 hover:bg-slate-50/50 dark:border-slate-700 dark:hover:border-slate-600 dark:hover:bg-slate-800/50', 'hover:scale-[1.01]')
  }

  return classes
}
</script>

<template>
  <div class="space-y-6">
    <!-- Optimization Analysis Summary -->
    <div v-if="props.analysis" class="rounded-xl p-5 bg-white/90 backdrop-blur-sm border border-violet-200/50 dark:bg-slate-900/90 dark:border-violet-500/25">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-11 h-11 rounded-xl bg-gradient-to-br from-violet-400 to-violet-500 flex items-center justify-center shadow-sm">
          <AppIcon name="Scan" size="md" variant="white" :aria-label="t('versionCompare.analysisReport')" />
        </div>
        <div class="flex-1">
          <div class="text-slate-800 font-semibold text-sm">{{ t('versionCompare.analysisReport') }}</div>
          <div class="text-xs text-slate-400 uppercase tracking-wide">{{ t('versionCompare.gapAnalysis') }}</div>
        </div>
      </div>

      <!-- Gaps -->
      <div v-if="props.analysis.gaps.length > 0" class="mb-4">
        <h4 class="text-xs text-slate-500 font-medium mb-2">{{ t('versionCompare.gapsFound') }}</h4>
        <div class="space-y-2">
          <div
            v-for="gap in props.analysis.gaps"
            :key="gap.dimension"
            :class="['px-3 py-2 rounded-lg border-l-2', gapSeverityClass(gap.severity)]"
          >
            <div class="flex items-center justify-between">
              <span class="text-xs font-medium text-slate-700">{{ gap.dimension }}</span>
              <span :class="['text-xs px-2 py-0.5 rounded-full', gapSeverityClass(gap.severity)]">
                {{ t(`versionCompare.severity.${gap.severity}`) }}
              </span>
            </div>
            <p class="text-xs text-slate-500 mt-1">{{ gap.description }}</p>
          </div>
        </div>
      </div>

      <!-- Suggestions -->
      <div v-if="props.analysis.suggestions.length > 0">
        <h4 class="text-xs text-slate-500 font-medium mb-2">{{ t('versionCompare.suggestions') }}</h4>
        <div class="space-y-2">
          <div
            v-for="suggestion in props.analysis.suggestions"
            :key="suggestion.dimension"
            :class="['px-3 py-2.5 rounded-lg border', suggestionPriorityClass(suggestion.priority)]"
          >
            <div class="flex items-center justify-between mb-1">
              <span class="text-xs font-medium text-slate-700">{{ suggestion.dimension }}</span>
              <span class="text-xs text-slate-400">{{ t('versionCompare.priority') }} {{ suggestion.priority }}</span>
            </div>
            <p class="text-xs text-slate-600 font-medium">{{ suggestion.action }}</p>
            <p class="text-xs text-slate-400 mt-0.5">{{ suggestion.reasoning }}</p>
          </div>
        </div>
      </div>

      <!-- Viral Patterns -->
      <div v-if="props.analysis.viral_patterns.length > 0" class="mt-4 pt-4 border-t border-slate-100 dark:border-slate-700/60">
        <h4 class="text-xs text-slate-500 font-medium mb-2">{{ t('versionCompare.viralPatterns') }}</h4>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="pattern in props.analysis.viral_patterns"
            :key="pattern"
            class="px-3 py-1 rounded-full bg-violet-50 text-violet-600 text-xs"
          >
            {{ pattern }}
          </span>
        </div>
      </div>
    </div>

    <!-- Version Comparison -->
    <div class="rounded-xl p-5 bg-white/90 backdrop-blur-sm border border-teal-200/50 dark:bg-slate-900/90 dark:border-teal-500/25">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-11 h-11 rounded-xl bg-gradient-to-br from-teal-400 to-teal-500 flex items-center justify-center shadow-sm">
          <AppIcon name="GitBranch" size="md" variant="white" :aria-label="t('versionCompare.versionComparison')" />
        </div>
        <div class="flex-1">
          <div class="text-slate-800 font-semibold text-sm">{{ t('versionCompare.versionComparison') }}</div>
          <div class="text-xs text-slate-400 uppercase tracking-wide">{{ t('versionCompare.chooseVersion') }}</div>
        </div>
        <!-- Best recommendation badge -->
        <div v-if="bestVersion" class="px-3 py-1.5 rounded-lg bg-amber-50 border border-amber-200 text-amber-600 text-xs font-medium flex items-center gap-1.5 dark:bg-amber-950/40 dark:border-amber-500/30 dark:text-amber-300">
          <AppIcon name="Star" size="sm" variant="peach" aria-hidden="true" />
          {{ t('versionCompare.bestRecommendation') }}: {{ bestVersion.version_type }}
        </div>
      </div>

      <!-- Version Cards -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div
          v-for="version in sortedVersions"
          :key="version.version_id"
          :class="getCardClass(version)"
          tabindex="0"
          role="button"
          :aria-label="`${version.version_type} - ${(version.predicted_score ?? 0).toFixed(1)}`"
          :aria-pressed="selectedVersionId === version.version_id"
          @click="selectVersion(version.version_id)"
          @keydown.enter="selectVersion(version.version_id)"
          @keydown.space.prevent="selectVersion(version.version_id)"
        >
          <!-- Selection checkmark -->
          <div
            v-if="selectedVersionId === version.version_id"
            class="absolute top-2 right-2 w-6 h-6 rounded-full bg-teal-500 flex items-center justify-center shadow-sm"
            aria-hidden="true"
          >
            <AppIcon name="Check" size="sm" variant="white" />
          </div>

          <!-- Best badge -->
          <div
            v-if="version.version_id === bestVersion?.version_id && selectedVersionId !== version.version_id"
            class="absolute top-2 right-2 w-6 h-6 rounded-full bg-amber-400 flex items-center justify-center shadow-sm"
            aria-hidden="true"
          >
            <AppIcon name="Star" size="sm" variant="white" />
          </div>

          <!-- Version Header -->
          <div class="flex items-center justify-between mb-3">
            <span :class="['px-2 py-1 rounded-lg text-xs font-semibold border', getVersionTypeColor(version.version_type || 'A')]">
              {{ version.version_type || 'A' }}
            </span>
            <span :class="['text-xs', version.version_id === bestVersion?.version_id ? 'text-amber-500 font-medium' : 'text-slate-400']">
              {{ (version.predicted_score ?? 0).toFixed(1) }} {{ t('versionCompare.scoreUnit') }}
            </span>
          </div>

          <!-- Predicted Score -->
          <MiniProgress
            :value="version.predicted_score ?? 0"
            :max="100"
            :label="t('versionCompare.predictedScore')"
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
              class="px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-500 text-xs dark:bg-slate-800 dark:text-slate-400"
            >
              #{{ tag }}
            </span>
          </div>

          <!-- Changes Summary -->
          <div class="mt-3 pt-3 border-t border-slate-100 dark:border-slate-700/60">
            <p class="text-xs text-slate-400">{{ version.changes_summary }}</p>
          </div>

          <!-- Style Suggestion -->
          <div v-if="version.style_suggestion" class="mt-2">
            <p class="text-xs text-teal-600">💡 {{ version.style_suggestion }}</p>
          </div>
        </div>
      </div>

      <!-- Selection Indicator -->
      <Transition name="fade">
        <div v-if="selectedVersion" class="mt-4 p-3 rounded-lg bg-teal-50 border border-teal-200 dark:bg-teal-950/40 dark:border-teal-500/30">
          <div class="flex items-center gap-2">
            <AppIcon name="CheckCircle" size="sm" variant="cyan" />
            <span class="text-xs text-teal-600 font-medium dark:text-teal-300">
              {{ t('versionCompare.selected', { type: selectedVersion.version_type, title: selectedVersion.title }) }}
            </span>
          </div>
        </div>
      </Transition>

      <!-- Actions -->
      <div class="flex gap-3 mt-5 pt-4 border-t border-slate-100 dark:border-slate-700/60">
        <NeonButton
          variant="cyan"
          :disabled="!selectedVersionId || props.isLoading"
          :loading="props.isLoading"
          @click="handleConfirm"
        >
          <AppIcon name="Check" size="sm" variant="white" />
          <span>{{ t('versionCompare.confirmSelection') }}</span>
        </NeonButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fade-enter-active {
  transition: all 0.3s ease-out;
}

.fade-leave-active {
  transition: all 0.2s ease-in;
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(-5px);
}

.fade-leave-to {
  opacity: 0;
  transform: translateY(5px);
}
</style>
