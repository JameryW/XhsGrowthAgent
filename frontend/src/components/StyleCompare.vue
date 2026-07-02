<script setup lang="ts">
// StyleCompare — first choice_gate layer: pick a writing style variant.
// Differs from VersionCompare: no predicted_score / A-B-C badges; surfaces
// style_name + tone + visual_style + style_suggestion instead.
// Emits the same VersionChoice shape so OptimizationPanel/selectVersion is reused.
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import type { ContentVersion, VersionChoice } from '@/types/optimization'

interface Props {
  versions: ContentVersion[]
  isLoading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  isLoading: false,
})

const emit = defineEmits<{
  (e: 'select', choice: VersionChoice): void
}>()

const { t } = useI18n()

const selectedVersionId = ref<string | null>(null)

const selectedVersion = computed(() =>
  props.versions.find(v => v.version_id === selectedVersionId.value),
)

// ponytail: keep input order (style_a/b/c) — no score to sort by
const orderedVersions = computed(() => [...props.versions])

// Variant accent color by style index — mirrors VersionCompare's style_a/b/c palette
function getStyleColor(version: ContentVersion): string {
  switch (version.version_id) {
    case 'style_a': return 'border-violet-200 bg-violet-50 text-violet-600'
    case 'style_b': return 'border-amber-200 bg-amber-50 text-amber-600'
    case 'style_c': return 'border-emerald-200 bg-emerald-50 text-emerald-600'
    default: return 'border-slate-200 bg-slate-50 text-slate-600'
  }
}

function getCardClass(version: ContentVersion): string[] {
  const isSelected = selectedVersionId.value === version.version_id
  const classes = ['relative rounded-lg p-4 border-2 cursor-pointer transition-all duration-300']
  if (isSelected) {
    classes.push('border-teal-400 bg-teal-50/80 scale-[1.02]', 'shadow-lg shadow-teal-500/20', 'ring-2 ring-teal-400/30')
  } else {
    classes.push('border-slate-100 hover:border-slate-200 hover:bg-slate-50/50', 'hover:scale-[1.01]')
  }
  return classes
}

function selectVersion(versionId: string) {
  selectedVersionId.value = versionId
}

function handleConfirm() {
  if (!selectedVersionId.value) return
  const version = props.versions.find(v => v.version_id === selectedVersionId.value)
  if (!version) return
  // selected_version carries version_type (style_a/b/c) — same field the backend
  // VersionChoice expects; choice_gate_node keys off style_selected, not this value.
  emit('select', {
    selected_version: version.version_type || version.version_id,
    version_id: selectedVersionId.value,
  })
}
</script>

<template>
  <div class="rounded-xl p-5 bg-white/98 backdrop-blur-sm border border-violet-200/50">
    <div class="flex items-center gap-3 mb-4">
      <div class="w-11 h-11 rounded-xl bg-gradient-to-br from-violet-400 to-violet-500 flex items-center justify-center shadow-sm">
        <AppIcon name="Palette" size="md" variant="white" :aria-label="t('styleCompare.chooseStyle')" />
      </div>
      <div class="flex-1">
        <div class="text-slate-800 font-semibold text-sm">{{ t('styleCompare.styleComparison') }}</div>
        <div class="text-xs text-slate-400 uppercase tracking-wide">{{ t('styleCompare.chooseStyle') }}</div>
      </div>
    </div>

    <!-- Style Cards -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div
        v-for="version in orderedVersions"
        :key="version.version_id"
        :class="getCardClass(version)"
        tabindex="0"
        role="button"
        :aria-label="version.style_name || version.title"
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

        <!-- Style name badge -->
        <div class="flex items-center gap-2 mb-3">
          <span :class="['px-2 py-1 rounded-lg text-xs font-semibold border', getStyleColor(version)]">
            {{ version.style_name || t('styleCompare.style') }}
          </span>
        </div>

        <!-- Tone -->
        <div v-if="version.tone" class="mb-2">
          <span class="text-xs text-slate-400">{{ t('styleCompare.tone') }}</span>
          <p class="text-xs text-slate-600 font-medium">{{ version.tone }}</p>
        </div>

        <!-- Visual style -->
        <div v-if="version.visual_style" class="mb-2">
          <span class="text-xs text-slate-400">{{ t('styleCompare.visualStyle') }}</span>
          <p class="text-xs text-slate-600 font-medium">{{ version.visual_style }}</p>
        </div>

        <!-- Color palette swatches -->
        <div v-if="version.color_palette" class="flex gap-1.5 mb-2">
          <span
            v-for="(hex, name) in version.color_palette"
            :key="name"
            class="w-5 h-5 rounded-full border border-white shadow-sm"
            :style="{ backgroundColor: hex }"
            :title="`${name}: ${hex}`"
            aria-hidden="true"
          />
        </div>

        <!-- Title preview -->
        <div class="mt-2">
          <h4 class="text-sm font-medium text-slate-700 line-clamp-2">{{ version.title }}</h4>
        </div>

        <!-- Body preview -->
        <div class="mt-2">
          <p class="text-xs text-slate-500 line-clamp-3">{{ version.body.slice(0, 120) }}...</p>
        </div>

        <!-- Style suggestion -->
        <div v-if="version.style_suggestion" class="mt-3 pt-3 border-t border-slate-100">
          <p class="text-xs text-teal-600">💡 {{ version.style_suggestion }}</p>
        </div>
      </div>
    </div>

    <!-- Selection indicator -->
    <Transition name="fade">
      <div v-if="selectedVersion" class="mt-4 p-3 rounded-lg bg-teal-50 border border-teal-200">
        <div class="flex items-center gap-2">
          <AppIcon name="CheckCircle" size="sm" variant="cyan" />
          <span class="text-xs text-teal-600 font-medium">
            {{ t('styleCompare.selected', { style: selectedVersion.style_name || selectedVersion.title, title: selectedVersion.title }) }}
          </span>
        </div>
      </div>
    </Transition>

    <!-- Actions -->
    <div class="flex gap-3 mt-5 pt-4 border-t border-slate-100">
      <NeonButton
        variant="cyan"
        :disabled="!selectedVersionId || props.isLoading"
        :loading="props.isLoading"
        @click="handleConfirm"
      >
        <AppIcon name="Check" size="sm" variant="white" />
        <span>{{ t('styleCompare.confirmSelection') }}</span>
      </NeonButton>
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
