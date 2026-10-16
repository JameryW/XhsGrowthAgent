<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import {
  getAcceptanceSignoff,
  type AcceptanceSignoffBoard,
  type AcceptanceSignoffGate,
} from '@/api/system'

const { t } = useI18n()

const loading = ref(true)
const board = ref<AcceptanceSignoffBoard | null>(null)
const loadError = ref(false)

onMounted(async () => {
  loading.value = true
  loadError.value = false
  try {
    board.value = await getAcceptanceSignoff()
  } catch {
    loadError.value = true
    board.value = null
  } finally {
    loading.value = false
  }
})

function isWaivedStatus(status: string): boolean {
  return status === 'waived_risk_accepted' || status === 'waived'
}

function isWaivedGate(gate: AcceptanceSignoffGate): boolean {
  // Prefer server-derived flag; waived is never pass.
  if (typeof gate.is_waived === 'boolean') return gate.is_waived
  return isWaivedStatus(gate.status)
}

function isPassedGate(gate: AcceptanceSignoffGate): boolean {
  // Waived must never render as success / passed (even if status string is odd).
  if (isWaivedGate(gate)) return false
  if (typeof gate.is_passed === 'boolean') return gate.is_passed
  return gate.status === 'passed' || gate.status === 'approved'
}

function statusLabel(status: string): string {
  const key = `settings.acceptance.status.${status}`
  const translated = t(key)
  return translated === key ? status : translated
}

function statusClass(gate: AcceptanceSignoffGate): string {
  if (isPassedGate(gate)) {
    return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-400/15 dark:text-emerald-200'
  }
  if (gate.status === 'rejected' || gate.status === 'failed') {
    return 'bg-rose-100 text-rose-800 dark:bg-rose-400/15 dark:text-rose-200'
  }
  if (isWaivedGate(gate)) {
    // Distinct from pass: slate warning, not emerald success.
    return 'bg-slate-200/90 text-slate-700 dark:bg-slate-700/50 dark:text-slate-200'
  }
  return 'bg-amber-100 text-amber-800 dark:bg-amber-400/15 dark:text-amber-200'
}

function gateConclusion(gate: AcceptanceSignoffGate): string {
  return gate.conclusion?.trim() || t('settings.acceptance.conclusionPlaceholder')
}

const waiverSummary = computed(() => {
  const w = board.value?.waiver
  if (!w || typeof w !== 'object') return ''
  return typeof w.summary === 'string' ? w.summary : ''
})

const nextGlobalReview = computed(() => {
  const w = board.value?.waiver
  if (!w || typeof w !== 'object') return ''
  return typeof w.next_global_review_at === 'string' ? w.next_global_review_at : ''
})
</script>

<template>
  <section class="space-y-4" aria-labelledby="acceptance-board-title">
    <div class="rounded-xl border border-slate-200/70 bg-white/90 p-4 shadow-sm md:p-5 dark:border-slate-700/55 dark:bg-slate-900/80 dark-explicit">
      <div class="mb-3 flex items-start gap-3">
        <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 dark:bg-slate-800 dark-explicit">
          <AppIcon name="ClipboardCheck" size="sm" variant="pink" aria-hidden="true" />
        </div>
        <div class="min-w-0 flex-1">
          <h2 id="acceptance-board-title" class="text-sm font-semibold text-slate-800">
            {{ t('settings.acceptance.title') }}
          </h2>
          <p class="mt-1 text-xs leading-5 text-slate-500">
            {{ t('settings.acceptance.subtitle') }}
          </p>
        </div>
      </div>

      <div
        role="note"
        class="mb-4 rounded-lg border border-amber-200/80 bg-amber-50/90 px-3 py-2 text-xs leading-5 text-amber-800 dark:border-amber-500/30 dark:bg-amber-950/40 dark:text-amber-200 dark-explicit"
      >
        {{ board?.disclaimer || t('settings.acceptance.disclaimer') }}
      </div>

      <div
        v-if="waiverSummary || nextGlobalReview"
        class="mb-4 rounded-lg border border-slate-200 bg-slate-50/90 px-3 py-2 text-xs leading-5 text-slate-600 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-300 dark-explicit"
      >
        <p v-if="waiverSummary" class="font-medium text-slate-700 dark:text-slate-200">
          {{ t('settings.acceptance.waiverLabel') }}: {{ waiverSummary }}
        </p>
        <p v-if="nextGlobalReview" class="mt-1">
          {{ t('settings.acceptance.nextGlobalReview', { date: nextGlobalReview }) }}
        </p>
        <p class="mt-1 text-[10px] text-slate-500">
          {{ t('settings.acceptance.waiverNotPass') }}
        </p>
      </div>

      <div v-if="loading" class="py-8 text-center text-xs text-slate-400">
        {{ t('settings.acceptance.loading') }}
      </div>
      <div v-else-if="loadError" class="py-8 text-center text-xs text-rose-600">
        {{ t('settings.acceptance.loadFailed') }}
      </div>
      <div v-else class="overflow-x-auto">
        <table class="min-w-full text-left text-xs">
          <thead>
            <tr class="border-b border-slate-200 text-[10px] uppercase tracking-wider text-slate-400 dark:border-slate-700 dark-explicit">
              <th class="px-2 py-2 font-semibold">{{ t('settings.acceptance.cols.gate') }}</th>
              <th class="px-2 py-2 font-semibold">{{ t('settings.acceptance.cols.status') }}</th>
              <th class="px-2 py-2 font-semibold">{{ t('settings.acceptance.cols.owner') }}</th>
              <th class="px-2 py-2 font-semibold">{{ t('settings.acceptance.cols.nextReview') }}</th>
              <th class="px-2 py-2 font-semibold">{{ t('settings.acceptance.cols.conclusion') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="gate in board?.gates || []"
              :key="gate.id"
              class="border-b border-slate-100 last:border-0 dark:border-slate-800 dark-explicit"
            >
              <td class="px-2 py-3 align-top">
                <div class="font-semibold text-slate-700">{{ gate.id }}</div>
                <div class="mt-0.5 text-slate-500">{{ gate.title }}</div>
                <div v-if="gate.chase_action" class="mt-1 text-[10px] leading-4 text-slate-400">
                  {{ gate.chase_action }}
                </div>
              </td>
              <td class="px-2 py-3 align-top">
                <span
                  class="inline-flex rounded-md px-2 py-0.5 text-[10px] font-bold dark-explicit"
                  :class="statusClass(gate)"
                  :data-status="gate.status"
                  :data-passed="isPassedGate(gate) ? 'true' : 'false'"
                  :data-waived="isWaivedGate(gate) ? 'true' : 'false'"
                >
                  {{ statusLabel(gate.status) }}
                </span>
              </td>
              <td class="px-2 py-3 align-top text-slate-600">{{ gate.owner_role }}</td>
              <td class="px-2 py-3 align-top text-slate-600">
                {{ gate.next_review_at || t('settings.acceptance.nextReviewPlaceholder') }}
              </td>
              <td class="px-2 py-3 align-top text-slate-500">{{ gateConclusion(gate) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="board?.source_doc" class="mt-3 text-[10px] text-slate-400">
          {{ t('settings.acceptance.source', { doc: board.source_doc }) }}
        </p>
      </div>
    </div>
  </section>
</template>
