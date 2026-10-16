<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import {
  getLearningRecommendations,
  type LearningTopicRecommendation,
} from '@/api/analytics'

const props = defineProps<{
  accountId: string
}>()

const emit = defineEmits<{
  applyTopic: [topic: string]
}>()

const { t } = useI18n()
const router = useRouter()

const loading = ref(false)
const empty = ref(false)
const emptyReason = ref<string | null>(null)
const items = ref<LearningTopicRecommendation[]>([])
const outcomeDoc = ref('docs/outcome-learning.md')
let requestToken = 0

async function load() {
  const accountId = (props.accountId || '').trim()
  if (!accountId) {
    items.value = []
    empty.value = true
    emptyReason.value = 'no_account'
    return
  }
  const token = ++requestToken
  loading.value = true
  try {
    const data = await getLearningRecommendations(accountId, 5)
    if (token !== requestToken) return
    items.value = data.recommendations || []
    empty.value = Boolean(data.empty) || items.value.length === 0
    emptyReason.value = data.empty_reason
    outcomeDoc.value = data.outcome_learning_doc || 'docs/outcome-learning.md'
  } catch {
    if (token !== requestToken) return
    items.value = []
    empty.value = true
    emptyReason.value = 'load_failed'
  } finally {
    if (token === requestToken) loading.value = false
  }
}

watch(() => props.accountId, () => { void load() }, { immediate: true })

function apply(item: LearningTopicRecommendation) {
  emit('applyTopic', item.topic)
}

function openEvidence(item: LearningTopicRecommendation) {
  const href = item.evidence_href || '/analytics'
  if (href.startsWith('/')) {
    void router.push(href)
    return
  }
  window.open(href, '_blank', 'noopener')
}

function formatRate(rate: number): string {
  if (!Number.isFinite(rate) || rate <= 0) return '—'
  return `${(rate * 100).toFixed(1)}%`
}
</script>

<template>
  <section
    class="rounded-xl border border-teal-100/80 bg-gradient-to-br from-teal-50/80 via-white to-cyan-50/60 p-4 shadow-sm md:rounded-2xl md:p-5 dark:border-teal-500/20 dark:from-slate-900/90 dark:via-slate-900/80 dark:to-cyan-950/40 dark-explicit"
    aria-labelledby="learning-recs-title"
  >
    <div class="mb-3 flex items-start gap-2">
      <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-teal-400 to-cyan-400 shadow-sm">
        <AppIcon name="Sparkles" size="sm" variant="white" aria-hidden="true" />
      </div>
      <div class="min-w-0 flex-1">
        <h2 id="learning-recs-title" class="text-sm font-semibold text-slate-700">
          {{ t('home.learningRecs.title') }}
        </h2>
        <p class="text-[11px] leading-5 text-slate-400">
          {{ t('home.learningRecs.subtitle') }}
        </p>
      </div>
    </div>

    <div v-if="loading" class="py-4 text-center text-xs text-slate-400">
      {{ t('home.learningRecs.loading') }}
    </div>

    <div
      v-else-if="empty"
      role="status"
      class="rounded-lg border border-dashed border-slate-200 bg-white/70 px-3 py-4 text-center dark:border-slate-600/50 dark:bg-slate-900/50 dark-explicit"
    >
      <p class="text-xs font-medium text-slate-600">{{ t('home.learningRecs.emptyTitle') }}</p>
      <p class="mt-1 text-[11px] leading-5 text-slate-400">
        {{ t('home.learningRecs.emptyBody') }}
      </p>
      <p v-if="emptyReason === 'load_failed'" class="mt-1 text-[10px] text-amber-600">
        {{ t('home.learningRecs.loadFailed') }}
      </p>
    </div>

    <ul v-else class="space-y-2" role="list">
      <li
        v-for="item in items"
        :key="item.related_note_id + item.topic"
        class="flex flex-col gap-2 rounded-xl border border-white/80 bg-white/90 p-3 shadow-sm sm:flex-row sm:items-center dark:border-slate-700/50 dark:bg-slate-900/70 dark-explicit"
      >
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-semibold text-slate-700">{{ item.topic }}</p>
          <p class="mt-0.5 truncate text-[11px] text-slate-400">
            {{ item.note_title || item.related_note_id }}
            · {{ t('home.learningRecs.engagement', { rate: formatRate(item.engagement_rate) }) }}
          </p>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <button
            type="button"
            class="min-h-11 inline-flex items-center gap-1 rounded-lg border border-teal-200 bg-teal-50 px-3 text-xs font-semibold text-teal-700 transition hover:bg-teal-100 dark:border-teal-500/30 dark:bg-teal-950/40 dark:text-teal-300 dark-explicit"
            @click="apply(item)"
          >
            <AppIcon name="Check" size="sm" variant="cyan" aria-hidden="true" />
            {{ t('home.learningRecs.apply') }}
          </button>
          <button
            type="button"
            class="min-h-11 inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 px-3 text-xs font-medium text-slate-600 transition hover:bg-white dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300 dark-explicit"
            @click="openEvidence(item)"
          >
            <AppIcon name="ExternalLink" size="sm" variant="cyan" aria-hidden="true" />
            {{ t('home.learningRecs.evidence') }}
          </button>
        </div>
      </li>
    </ul>

    <p class="mt-3 text-[10px] leading-4 text-slate-400">
      {{ t('home.learningRecs.traceHint', { doc: outcomeDoc }) }}
    </p>
  </section>
</template>
