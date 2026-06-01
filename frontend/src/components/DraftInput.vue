<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import type { DraftContent } from '@/types/optimization'

const { t } = useI18n()

interface Props {
  isLoading?: boolean
  initialDraft?: DraftContent | null
}

const props = withDefaults(defineProps<Props>(), {
  isLoading: false,
  initialDraft: null,
})

const emit = defineEmits<{
  (e: 'submit', draft: DraftContent, viralLinks: string[]): void
}>()

// Form state
const draftText = ref(props.initialDraft?.text || '')
const draftTitle = ref(props.initialDraft?.title || '')
const draftHashtags = ref(props.initialDraft?.hashtags?.join(' ') || '')
const viralLinks = ref('')
const showViralLinks = ref(false)

// Validation states
const textFocused = ref(false)

// Computed
const characterProgress = computed(() => {
  const minChars = 50
  const current = draftText.value.length
  return Math.min(100, Math.round((current / minChars) * 100))
})

const isValidDraft = computed(() => draftText.value.trim().length >= 50)
const isNearMinimum = computed(() => draftText.value.trim().length >= 30 && draftText.value.trim().length < 50)
const isEmpty = computed(() => draftText.value.trim().length === 0)

const validationState = computed(() => {
  if (isEmpty.value) return 'empty'
  if (isValidDraft.value) return 'valid'
  if (isNearMinimum.value) return 'near'
  return 'invalid'
})

const validationMessage = computed(() => {
  if (isValidDraft.value) return t('draft.validContent')
  if (isNearMinimum.value) return t('draft.needMoreChars', { count: 50 - draftText.value.trim().length })
  if (isEmpty.value) return t('draft.enterContent')
  return t('draft.contentTooShort')
})

const parsedHashtags = computed(() => {
  if (!draftHashtags.value.trim()) return []
  return draftHashtags.value
    .split(/[,#\s]+/)
    .filter(tag => tag.trim().length > 0)
    .map(tag => tag.trim())
})

const parsedViralLinks = computed(() => {
  if (!viralLinks.value.trim()) return []
  return viralLinks.value
    .split(/[\n,]+/)
    .filter(link => link.trim().length > 0)
    .map(link => link.trim())
})

// Actions
function handleSubmit() {
  if (!isValidDraft.value) return

  const draft: DraftContent = {
    text: draftText.value.trim(),
    title: draftTitle.value.trim() || undefined,
    hashtags: parsedHashtags.value.length > 0 ? parsedHashtags.value : undefined,
    provided_at: new Date().toISOString(),
  }

  emit('submit', draft, parsedViralLinks.value)
}

function handleSkip() {
  const draft: DraftContent = {
    text: draftText.value.trim() || '',
    provided_at: new Date().toISOString(),
  }
  emit('submit', draft, [])
}

function toggleViralLinks() {
  showViralLinks.value = !showViralLinks.value
}
</script>

<template>
  <div class="rounded-xl p-6 bg-white/98 backdrop-blur-sm border border-slate-200/50">
    <!-- Header -->
    <div class="flex items-center gap-3 mb-5">
      <div class="w-11 h-11 rounded-xl bg-gradient-to-br from-teal-400 to-teal-500 flex items-center justify-center shadow-sm">
        <AppIcon name="FileText" size="md" variant="white" :aria-label="t('draft.title')" />
      </div>
      <div class="flex-1">
        <div class="text-slate-800 font-semibold text-sm">{{ t('draft.title') }}</div>
        <div class="text-xs text-slate-400 uppercase tracking-wide">{{ t('draft.subtitle') }}</div>
      </div>
    </div>

    <!-- Draft Input -->
    <div class="space-y-4">
      <!-- Main text input -->
      <div>
        <label class="text-xs text-slate-500 font-medium mb-1.5 block">
          {{ t('draft.draftBody') }} <span class="text-rose-500">{{ t('draft.required') }}</span>
        </label>
        <textarea
          v-model="draftText"
          :disabled="props.isLoading"
          @focus="textFocused = true"
          @blur="textFocused = false"
          :placeholder="t('draft.placeholder')"
          rows="6"
          :aria-invalid="!isValidDraft && draftText.length > 0"
          :aria-errormessage="!isValidDraft && draftText.length > 0 ? 'draft-text-error' : undefined"
          :class="[
            'w-full px-4 py-3 rounded-lg border text-slate-700 placeholder:text-slate-300 resize-none transition-all',
            validationState === 'valid' ? 'border-teal-300 focus:border-teal-400 focus:ring-1 focus:ring-teal-200' :
            validationState === 'invalid' && textFocused ? 'border-rose-300 focus:border-rose-400 focus:ring-1 focus:ring-rose-200' :
            'border-slate-200 focus:border-teal-300 focus:ring-1 focus:ring-teal-200'
          ]"
        />

        <!-- Error message for accessibility -->
        <div id="draft-text-error" class="sr-only" role="alert">
          {{ t('draft.minLength') }}
        </div>

        <!-- Validation feedback -->
        <div class="flex items-center justify-between mt-2">
          <!-- Progress bar -->
          <div class="flex items-center gap-2 flex-1">
            <div class="w-24 h-2 rounded-full bg-slate-100 overflow-hidden">
              <div
                :class="[
                  'h-full rounded-full transition-all duration-300',
                  validationState === 'valid' ? 'bg-teal-500' :
                  validationState === 'near' ? 'bg-amber-400' :
                  validationState === 'empty' ? 'bg-slate-200' :
                  'bg-rose-400'
                ]"
                :style="{ width: `${characterProgress}%` }"
              />
            </div>
            <span :class="['text-xs flex items-center gap-1',
              validationState === 'valid' ? 'text-teal-500' :
              validationState === 'near' ? 'text-amber-500' :
              validationState === 'empty' ? 'text-slate-400' :
              'text-rose-500'
            ]">
              <AppIcon
                v-if="validationState === 'valid'"
                name="CheckCircle"
                size="sm"
                variant="cyan"
                aria-hidden="true"
              />
              <AppIcon
                v-else-if="validationState === 'invalid'"
                name="AlertCircle"
                size="sm"
                variant="pink"
                aria-hidden="true"
              />
              {{ validationMessage }}
            </span>
          </div>

          <span class="text-xs text-slate-400">
            {{ t('draft.charCount', { count: draftText.length }) }}
          </span>
        </div>
      </div>

      <!-- Title input -->
      <div>
        <label class="text-xs text-slate-500 font-medium mb-1.5 block">{{ t('draft.titleLabel') }}</label>
        <input
          v-model="draftTitle"
          :disabled="props.isLoading"
          type="text"
          :placeholder="t('draft.titlePlaceholder')"
          class="w-full px-4 py-2.5 rounded-lg border border-slate-200 focus:border-teal-300 focus:ring-1 focus:ring-teal-200 text-slate-700 placeholder:text-slate-300 transition-all"
        />
      </div>

      <!-- Hashtags input -->
      <div>
        <label class="text-xs text-slate-500 font-medium mb-1.5 block">{{ t('draft.tagsLabel') }}</label>
        <input
          v-model="draftHashtags"
          :disabled="props.isLoading"
          type="text"
          :placeholder="t('draft.tagsPlaceholder')"
          class="w-full px-4 py-2.5 rounded-lg border border-slate-200 focus:border-teal-300 focus:ring-1 focus:ring-teal-200 text-slate-700 placeholder:text-slate-300 transition-all"
        />
        <div v-if="parsedHashtags.length > 0" class="flex gap-2 mt-2">
          <span
            v-for="tag in parsedHashtags"
            :key="tag"
            class="px-2 py-0.5 rounded-full bg-teal-50 text-teal-600 text-xs"
          >
            #{{ tag }}
          </span>
        </div>
      </div>

      <!-- Viral links toggle -->
      <div>
        <button
          @click="toggleViralLinks"
          :disabled="props.isLoading"
          :aria-expanded="showViralLinks"
          aria-controls="viral-links-section"
          class="flex items-center gap-2 text-xs text-slate-500 hover:text-teal-500 transition-colors"
        >
          <AppIcon :name="showViralLinks ? 'ChevronDown' : 'ChevronRight'" size="sm" variant="cyan" />
          <span>{{ t('draft.viralLinksLabel') }}</span>
        </button>

        <!-- Viral links input (collapsible) -->
        <div v-if="showViralLinks" id="viral-links-section" class="mt-3">
          <textarea
            v-model="viralLinks"
            :disabled="props.isLoading"
            :placeholder="t('draft.viralLinksPlaceholder')"
            rows="3"
            class="w-full px-4 py-3 rounded-lg border border-slate-200 focus:border-violet-300 focus:ring-1 focus:ring-violet-200 text-slate-700 placeholder:text-slate-300 resize-none transition-all"
          />
          <div class="flex justify-between mt-1.5">
            <span class="text-xs text-slate-400">
              {{ t('draft.linksCount', { count: parsedViralLinks.length }) }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Actions -->
    <div class="flex gap-3 mt-6 pt-5 border-t border-slate-100">
      <NeonButton
        variant="cyan"
        :disabled="!isValidDraft || props.isLoading"
        :loading="props.isLoading"
        @click="handleSubmit"
      >
        <AppIcon name="Sparkles" size="sm" variant="white" />
        <span>{{ t('draft.startOptimization') }}</span>
      </NeonButton>
      <NeonButton
        variant="ghost"
        :disabled="props.isLoading"
        @click="handleSkip"
      >
        <span>{{ t('draft.skipOptimization') }}</span>
      </NeonButton>
    </div>
  </div>
</template>
