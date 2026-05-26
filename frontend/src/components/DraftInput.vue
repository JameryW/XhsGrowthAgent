<script setup lang="ts">
import { ref, computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import type { DraftContent } from '@/types/optimization'

interface Props {
  isLoading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  isLoading: false,
})

const emit = defineEmits<{
  (e: 'submit', draft: DraftContent, viralLinks: string[]): void
}>()

// Form state
const draftText = ref('')
const draftTitle = ref('')
const draftHashtags = ref('')
const viralLinks = ref('')
const showViralLinks = ref(false)

// Computed
const isValidDraft = computed(() => draftText.value.trim().length >= 50)

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
  <div class="rounded-xl p-6 bg-white/98 backdrop-blur-sm border border-neon-cyan/10">
    <!-- Header -->
    <div class="flex items-center gap-3 mb-5">
      <div class="w-11 h-11 rounded-xl bg-gradient-to-br from-neon-cyan via-neon-cyanLight to-neon-green flex items-center justify-center shadow-sm">
        <AppIcon name="FileText" size="md" variant="white" aria-label="Draft Input" />
      </div>
      <div class="flex-1">
        <div class="text-slate-800 font-semibold text-sm">提交草稿内容</div>
        <div class="text-xs text-slate-400 uppercase tracking-wide">Pre-Publish Optimization</div>
      </div>
    </div>

    <!-- Draft Input -->
    <div class="space-y-4">
      <!-- Main text input -->
      <div>
        <label class="text-xs text-slate-500 font-medium mb-1.5 block">
          草稿正文 <span class="text-neon-pink">*</span>
        </label>
        <textarea
          v-model="draftText"
          :disabled="props.isLoading"
          placeholder="输入您的笔记正文内容（至少50字）..."
          rows="6"
          class="w-full px-4 py-3 rounded-lg border border-slate-200 focus:border-neon-cyan focus:ring-1 focus:ring-neon-cyan/30 text-slate-700 placeholder:text-slate-300 resize-none transition-all"
        />
        <div class="flex justify-between mt-1.5">
          <span :class="['text-xs', isValidDraft ? 'text-teal-500' : 'text-slate-400']">
            {{ draftText.length }} 字 {{ isValidDraft ? '✓' : '(需≥50字)' }}
          </span>
        </div>
      </div>

      <!-- Title input -->
      <div>
        <label class="text-xs text-slate-500 font-medium mb-1.5 block">标题（可选）</label>
        <input
          v-model="draftTitle"
          :disabled="props.isLoading"
          type="text"
          placeholder="笔记标题..."
          class="w-full px-4 py-2.5 rounded-lg border border-slate-200 focus:border-neon-cyan focus:ring-1 focus:ring-neon-cyan/30 text-slate-700 placeholder:text-slate-300 transition-all"
        />
      </div>

      <!-- Hashtags input -->
      <div>
        <label class="text-xs text-slate-500 font-medium mb-1.5 block">话题标签（可选）</label>
        <input
          v-model="draftHashtags"
          :disabled="props.isLoading"
          type="text"
          placeholder="#美食 #探店 或 逗号分隔..."
          class="w-full px-4 py-2.5 rounded-lg border border-slate-200 focus:border-neon-cyan focus:ring-1 focus:ring-neon-cyan/30 text-slate-700 placeholder:text-slate-300 transition-all"
        />
        <div v-if="parsedHashtags.length > 0" class="flex gap-2 mt-2">
          <span
            v-for="tag in parsedHashtags"
            :key="tag"
            class="px-2 py-0.5 rounded-full bg-neon-cyan/10 text-neon-cyan text-xs"
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
          class="flex items-center gap-2 text-xs text-slate-500 hover:text-neon-cyan transition-colors"
        >
          <AppIcon :name="showViralLinks ? 'ChevronDown' : 'ChevronRight'" size="sm" variant="cyan" />
          <span>提供爆款参考链接（可选）</span>
        </button>

        <!-- Viral links input (collapsible) -->
        <div v-if="showViralLinks" class="mt-3">
          <textarea
            v-model="viralLinks"
            :disabled="props.isLoading"
            placeholder="粘贴小红书笔记链接，每行一个..."
            rows="3"
            class="w-full px-4 py-3 rounded-lg border border-slate-200 focus:border-neon-purple focus:ring-1 focus:ring-neon-purple/30 text-slate-700 placeholder:text-slate-300 resize-none transition-all"
          />
          <div class="flex justify-between mt-1.5">
            <span class="text-xs text-slate-400">
              {{ parsedViralLinks.length }} 个链接
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
        <span>开始优化分析</span>
      </NeonButton>
      <NeonButton
        variant="peach"
        :disabled="props.isLoading"
        @click="handleSkip"
      >
        <span>跳过优化</span>
      </NeonButton>
    </div>
  </div>
</template>