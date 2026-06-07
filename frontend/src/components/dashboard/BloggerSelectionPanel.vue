<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import { useWorkflowStore } from '@/stores'
import { selectBlogger } from '@/api/workflow'
import type { BloggerProfile } from '@/types/workflow'

const { t } = useI18n()
const workflowStore = useWorkflowStore()

const isLoading = ref(false)
const error = ref('')

const candidates = computed<BloggerProfile[]>(() =>
  workflowStore.bloggerCandidates
)

const activeThreadId = computed(() =>
  workflowStore.activeThreadId
)

function formatNumber(n: number | undefined): string {
  if (!n) return '0'
  if (n >= 10000) return `${(n / 10000).toFixed(1)}${t('blogger.wan')}`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}${t('blogger.qian')}`
  return n.toString()
}

async function handleSelect(candidate: BloggerProfile) {
  if (!activeThreadId.value) return
  isLoading.value = true
  error.value = ''
  try {
    await selectBlogger(activeThreadId.value, {
      user_id: candidate.user_id,
      nickname: candidate.nickname,
    })
  } catch (e: any) {
    error.value = e?.message || t('blogger.selectError')
  } finally {
    isLoading.value = false
  }
}

async function handleSkip() {
  if (!activeThreadId.value) return
  isLoading.value = true
  error.value = ''
  try {
    await selectBlogger(activeThreadId.value, { skip: true })
  } catch (e: any) {
    error.value = e?.message || t('blogger.selectError')
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="blogger-selection-panel space-y-3">
    <div class="flex items-center gap-2 mb-2">
      <AppIcon name="Users" class="w-5 h-5 text-violet-500" />
      <h3 class="text-sm font-semibold text-slate-700">{{ t('blogger.selectTitle') }}</h3>
    </div>

    <div v-if="error" class="p-2 rounded-lg bg-red-50 border border-red-200 text-red-600 text-xs">
      {{ error }}
    </div>

    <div v-if="candidates.length === 0" class="p-3 rounded-lg bg-slate-50 text-slate-400 text-sm text-center">
      {{ t('blogger.noCandidates') }}
    </div>

    <div v-else class="space-y-2">
      <div
        v-for="candidate in candidates"
        :key="candidate.user_id"
        class="p-3 rounded-lg bg-white border border-slate-200 hover:border-violet-300 hover:shadow-sm transition-all"
      >
        <div class="flex items-start gap-3">
          <!-- Avatar -->
          <div class="w-10 h-10 rounded-full bg-slate-100 flex-shrink-0 overflow-hidden">
            <img
              v-if="candidate.avatar_url"
              :src="candidate.avatar_url"
              :alt="candidate.nickname"
              class="w-full h-full object-cover"
            />
            <div v-else class="w-full h-full flex items-center justify-center text-slate-400 text-xs font-bold">
              {{ candidate.nickname?.charAt(0) || '?' }}
            </div>
          </div>

          <!-- Info -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span class="text-sm font-medium text-slate-800 truncate">{{ candidate.nickname }}</span>
            </div>
            <div class="flex items-center gap-3 mt-1 text-xs text-slate-500">
              <span v-if="candidate.follower_count">{{ t('blogger.followers') }}: {{ formatNumber(candidate.follower_count) }}</span>
              <span v-if="candidate.note_count">{{ t('blogger.notes') }}: {{ candidate.note_count }}</span>
            </div>
            <div class="flex items-center gap-2 mt-1">
              <span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-violet-50 text-violet-600">
                <AppIcon name="Flame" class="w-3 h-3" />
                {{ formatNumber(candidate.total_engagement) }}
              </span>
              <span v-if="candidate.top_note_title" class="text-xs text-slate-400 truncate">
                {{ t('blogger.topNote') }}: {{ candidate.top_note_title }}
              </span>
            </div>
          </div>

          <!-- Select button -->
          <NeonButton
            size="sm"
            variant="cyan"
            :loading="isLoading"
            @click="handleSelect(candidate)"
          >
            {{ t('blogger.select') }}
          </NeonButton>
        </div>
      </div>
    </div>

    <!-- Skip button -->
    <div class="flex justify-center pt-1">
      <button
        class="text-xs text-slate-400 hover:text-slate-600 transition-colors"
        :disabled="isLoading"
        @click="handleSkip"
      >
        {{ t('blogger.skip') }}
      </button>
    </div>
  </div>
</template>
