<script setup lang="ts">
import { ref, watch, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  KNOWN_NICHES,
  resolveAccountNiche,
  type Account,
  type NicheResolution,
} from '@/api/accounts'
import {
  syncCreatorStats,
  getCreatorStats,
  getCreatorSuggestions,
  type CreatorAccountStats,
  type CreatorNoteStats,
  type CreatorAggregatePoint,
  type CreatorAudienceAnalysis,
  type CreatorSuggestion,
  type CreatorStatsSyncResult,
} from '@/api/analytics'
import { useAccountsStore } from '@/stores/accounts'
import { useToastStore } from '@/stores/toast'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'

const props = defineProps<{
  accountId: string
  /** Optional display name; falls back to id */
  accountName?: string
  /** Compact layout for Analytics page */
  compact?: boolean
}>()

const emit = defineEmits<{
  updated: []
}>()

const { t } = useI18n()
const accountsStore = useAccountsStore()
const toast = useToastStore()

const isSyncing = ref(false)
const isResolvingNiche = ref(false)
const isLoadingStats = ref(false)

const period = ref('30d')
const analyze = ref(true)
const syncError = ref('')

const manualNiche = ref('')
const lastSync = ref<CreatorStatsSyncResult | null>(null)
const accountStats = ref<CreatorAccountStats | null>(null)
const notes = ref<CreatorNoteStats[]>([])
const notesTotal = ref(0)
const suggestions = ref<CreatorSuggestion[]>([])
const audience = ref<CreatorAudienceAnalysis | null>(null)
const suggestionMode = ref<'trend' | 'brief' | 'free'>('trend')
const nicheResult = ref<NicheResolution | null>(null)

const account = computed<Account | undefined>(() =>
  accountsStore.accounts.find(a => a.id === props.accountId)
    ?? (accountsStore.activeAccount?.id === props.accountId
      ? accountsStore.activeAccount
      : undefined)
)

const boundNiche = computed(() => {
  if (nicheResult.value?.niche) return nicheResult.value.niche
  return account.value?.niche || ''
})

const boundSource = computed(() => {
  if (nicheResult.value?.source) return nicheResult.value.source
  return account.value?.niche_source || ''
})

const sourceLabel = computed(() => {
  const s = boundSource.value
  if (!s) return t('creatorStats.sourceNone')
  const key = `creatorStats.source.${s}` as const
  const translated = t(key)
  return translated === key ? s : translated
})

const hasCreatorProfile = computed(() => {
  const profile = accountStats.value
  return Boolean(
    profile && (
      profile.creator_user_id
      || profile.creator_name
      || profile.red_id
      || profile.avatar_url
      || profile.bio
      || profile.creator_role
      || profile.zone
    )
  )
})

const profileDisplayName = computed(() =>
  accountStats.value?.creator_name || props.accountName || props.accountId
)

const profileInitial = computed(() => profileDisplayName.value.trim().slice(0, 1) || '?')

/**
 * Creator Center profile data is authoritative for the display name after a
 * real import. Keep the shared account store in sync immediately, including
 * when the page was opened before the import completed and still holds an
 * older account name.
 */
function syncImportedDisplayName(profile: CreatorAccountStats | null) {
  const importedName = profile?.creator_name?.trim()
  if (!importedName || !props.accountId) return
  accountsStore.syncImportedAccountName(props.accountId, importedName)
}

// Keep manual niche field in sync when account store loads/refreshes
watch(
  () => [props.accountId, account.value?.niche, account.value?.niche_source] as const,
  ([id, niche]) => {
    if (!id) return
    if (!nicheResult.value && niche) {
      manualNiche.value = niche
    }
  },
  { immediate: true }
)

watch(
  () => props.accountId,
  async (id, prev) => {
    if (!id) return
    if (id !== prev) {
      lastSync.value = null
      syncError.value = ''
      nicheResult.value = null
      notesTotal.value = 0
      audience.value = null
      manualNiche.value = account.value?.niche || ''
    }
    await loadImported()
  },
  { immediate: true }
)

onMounted(async () => {
  if (!accountsStore.accounts.length) {
    try {
      await accountsStore.fetchAccounts()
    } catch {
      /* ignore — panel still works with bare accountId */
    }
  }
})

async function loadImported() {
  if (!props.accountId) return
  isLoadingStats.value = true
  try {
    const [stats, tips] = await Promise.all([
      getCreatorStats(props.accountId, 100),
      getCreatorSuggestions(props.accountId, suggestionMode.value),
    ])
    accountStats.value = stats.account
    syncImportedDisplayName(accountStats.value)
    notes.value = stats.notes || []
    notesTotal.value = stats.total ?? notes.value.length
    audience.value = stats.audience_analysis || null
    suggestions.value = tips.suggestions || []
  } catch {
    // No imported data yet is fine
    accountStats.value = null
    notes.value = []
    notesTotal.value = 0
    audience.value = null
    suggestions.value = []
  } finally {
    isLoadingStats.value = false
  }
}

function applySuggestionsFromSync(result: CreatorStatsSyncResult) {
  const modeMap = result.suggestions
  if (!modeMap || typeof modeMap !== 'object') return
  const items = modeMap[suggestionMode.value]
  if (Array.isArray(items) && items.length) {
    suggestions.value = items
  }
}

async function runSync() {
  if (!props.accountId) return
  isSyncing.value = true
  syncError.value = ''
  try {
    const result = await syncCreatorStats({
      account_id: props.accountId,
      period: period.value,
      analyze: analyze.value,
    })
    lastSync.value = result
    if (result.ok === false || (result.error && !result.import_ok && !result.account_synced)) {
      syncError.value = result.error || t('creatorStats.syncFailed')
      toast.error(syncError.value)
    } else {
      toast.success(
        t('creatorStats.syncSuccess', {
          imported: result.notes_imported ?? 0,
          updated: result.notes_updated ?? 0,
          total: (result.notes_imported ?? 0) + (result.notes_updated ?? 0),
        })
      )
      if (result.niche_resolution?.niche) {
        nicheResult.value = result.niche_resolution
        manualNiche.value = result.niche_resolution.niche
      }
      applySuggestionsFromSync(result)
      // Partial analysis failure still means import worked
      if (result.error && String(result.error).startsWith('import succeeded')) {
        toast.warning(result.error)
      }
    }
    await loadImported()
    await accountsStore.fetchAccounts()
    emit('updated')
  } catch (e: any) {
    syncError.value = e?.message || t('creatorStats.syncFailed')
    toast.error(syncError.value)
  } finally {
    isSyncing.value = false
  }
}

async function autoBindNiche() {
  if (!props.accountId) return
  isResolvingNiche.value = true
  try {
    const res = await resolveAccountNiche(props.accountId, {
      manual_niche: '',
      persist: true,
    })
    nicheResult.value = res
    if (res.cold_start || !res.niche) {
      toast.warning(t('creatorStats.nicheColdStart'))
    } else {
      manualNiche.value = res.niche
      toast.success(
        t('creatorStats.nicheBound', {
          niche: res.niche,
          source: res.source,
        })
      )
    }
    await accountsStore.fetchAccounts()
    emit('updated')
  } catch (e: any) {
    toast.error(e?.message || t('creatorStats.nicheFailed'))
  } finally {
    isResolvingNiche.value = false
  }
}

async function applyManualNiche() {
  if (!props.accountId) return
  const niche = manualNiche.value.trim()
  if (!niche) {
    toast.error(t('creatorStats.nicheRequired'))
    return
  }
  isResolvingNiche.value = true
  try {
    const res = await resolveAccountNiche(props.accountId, {
      manual_niche: niche,
      persist: true,
    })
    nicheResult.value = res
    toast.success(
      t('creatorStats.nicheBound', {
        niche: res.niche,
        source: res.source,
      })
    )
    await accountsStore.fetchAccounts()
    emit('updated')
  } catch (e: any) {
    toast.error(e?.message || t('creatorStats.nicheFailed'))
  } finally {
    isResolvingNiche.value = false
  }
}

async function changeSuggestionMode(mode: 'trend' | 'brief' | 'free') {
  suggestionMode.value = mode
  try {
    const tips = await getCreatorSuggestions(props.accountId, mode)
    suggestions.value = tips.suggestions || []
  } catch {
    suggestions.value = []
  }
}

function formatRate(rate: number | undefined): string {
  if (rate == null || Number.isNaN(rate)) return '—'
  // Backend may store 0–1 or already percent-ish; treat >1 as already %
  const pct = rate > 1 ? rate : rate * 100
  return `${pct.toFixed(1)}%`
}

function formatNum(n: number | undefined): string {
  if (n == null) return '0'
  return n.toLocaleString()
}

function pointLabel(point: CreatorAggregatePoint): string {
  return String(point.title || point.name || point.label || point.text || point.start_point || '未命名')
}

function pointValue(point: CreatorAggregatePoint): string {
  const value = point.value ?? point.count
  if (value == null) return '—'
  const numeric = Number(value)
  return Number.isFinite(numeric) ? formatNum(numeric) : String(value)
}
</script>

<template>
  <div
    class="rounded-xl border border-slate-200/50 bg-white/90 backdrop-blur-sm p-4 space-y-4"
    :class="compact ? 'space-y-3' : ''"
  >
    <!-- Header -->
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <div class="flex items-center gap-2">
          <div class="w-7 h-7 rounded-lg bg-gradient-to-br from-violet-400 to-fuchsia-400 flex items-center justify-center shrink-0">
            <AppIcon name="Database" size="xs" variant="white" />
          </div>
          <h3 class="text-sm font-semibold text-slate-800">
            {{ t('creatorStats.title') }}
          </h3>
        </div>
        <p class="text-[11px] text-slate-400 mt-1 leading-relaxed">
          {{ t('creatorStats.subtitle') }}
          <span v-if="accountName || accountId" class="text-slate-500">
            · {{ accountName || accountId }}
          </span>
        </p>
      </div>
      <button
        type="button"
        class="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
        :title="t('creatorStats.refresh')"
        :disabled="isLoadingStats"
        @click="loadImported"
      >
        <AppIcon name="RefreshCw" size="xs" variant="cyan" :animate="isLoadingStats" />
      </button>
    </div>

    <!-- Niche bind -->
    <div class="rounded-lg border border-slate-100 bg-slate-50/60 p-3 space-y-2.5">
      <div class="flex items-center justify-between gap-2">
        <div class="text-xs font-semibold text-slate-500 uppercase tracking-wider">
          {{ t('creatorStats.nicheSection') }}
        </div>
        <div v-if="boundNiche" class="flex items-center gap-1.5">
          <span class="text-[11px] px-2 py-0.5 rounded-full bg-violet-100 text-violet-700 font-medium">
            {{ boundNiche }}
          </span>
          <span class="text-[10px] text-slate-400">{{ sourceLabel }}</span>
        </div>
        <span v-else class="text-[11px] text-amber-600">{{ t('creatorStats.nicheUnbound') }}</span>
      </div>
      <p class="text-[11px] text-slate-400 leading-relaxed">
        {{ t('creatorStats.nicheHint') }}
      </p>
      <div class="flex flex-wrap items-center gap-2">
        <select
          v-model="manualNiche"
          class="px-2.5 py-1.5 text-sm rounded-lg border border-slate-200 bg-white focus:border-violet-400 focus:ring-2 focus:ring-violet-400/20 outline-none min-w-[7rem]"
        >
          <option value="">{{ t('creatorStats.nichePlaceholder') }}</option>
          <option v-for="n in KNOWN_NICHES" :key="n" :value="n">{{ n }}</option>
        </select>
        <input
          v-model="manualNiche"
          type="text"
          :placeholder="t('creatorStats.nicheCustomPlaceholder')"
          class="px-2.5 py-1.5 text-sm rounded-lg border border-slate-200 bg-white focus:border-violet-400 focus:ring-2 focus:ring-violet-400/20 outline-none flex-1 min-w-[6rem]"
        />
        <NeonButton
          variant="purple"
          size="sm"
          :loading="isResolvingNiche"
          :disabled="isResolvingNiche"
          @click="applyManualNiche"
        >
          <AppIcon name="Check" size="xs" variant="white" />
          <span class="ml-1">{{ t('creatorStats.bindManual') }}</span>
        </NeonButton>
        <NeonButton
          variant="ghost"
          size="sm"
          :loading="isResolvingNiche"
          :disabled="isResolvingNiche"
          @click="autoBindNiche"
        >
          <AppIcon name="Sparkles" size="xs" variant="purple" />
          <span class="ml-1">{{ t('creatorStats.bindAuto') }}</span>
        </NeonButton>
      </div>
    </div>

    <!-- Import / sync -->
    <div class="rounded-lg border border-slate-100 bg-slate-50/60 p-3 space-y-2.5">
      <div class="text-xs font-semibold text-slate-500 uppercase tracking-wider">
        {{ t('creatorStats.importSection') }}
      </div>
      <p class="text-[11px] text-slate-400 leading-relaxed">
        {{ t('creatorStats.importHint') }}
      </p>
      <p class="text-[11px] text-violet-600 leading-relaxed">
        {{ t('creatorStats.browserPrerequisite') }}
      </p>

      <div class="flex flex-wrap items-center gap-3">
        <label class="flex items-center gap-2 text-sm text-slate-600 cursor-pointer select-none">
          <input
            v-model="analyze"
            type="checkbox"
            class="rounded border-slate-300 text-violet-500 focus:ring-violet-400"
          />
          <span>{{ t('creatorStats.analyze') }}</span>
        </label>
        <select
          v-model="period"
          class="px-2 py-1 text-xs rounded-lg border border-slate-200 bg-white outline-none"
        >
          <option value="7d">{{ t('creatorStats.period.last7Days') }}</option>
          <option value="30d">{{ t('creatorStats.period.last30Days') }}</option>
          <option value="90d">{{ t('creatorStats.period.last90Days') }}</option>
        </select>
      </div>

      <div class="flex items-center gap-2">
        <NeonButton
          variant="pink"
          size="sm"
          :loading="isSyncing"
          :disabled="isSyncing"
          @click="runSync"
        >
          <AppIcon name="Upload" size="xs" variant="white" />
          <span class="ml-1">{{ t('creatorStats.syncBrowser') }}</span>
        </NeonButton>
        <span v-if="lastSync && !syncError" class="text-[11px] text-slate-400">
          {{ t('creatorStats.lastSync', {
            source: lastSync.source,
            imported: lastSync.notes_imported ?? 0,
            updated: lastSync.notes_updated ?? 0,
          }) }}
        </span>
      </div>
      <p v-if="syncError || lastSync?.error" class="text-[11px] text-rose-500">
        {{ syncError || lastSync?.error }}
      </p>
    </div>

    <!-- Imported overview -->
    <div v-if="accountStats || notes.length" class="space-y-2">
      <div class="text-xs font-semibold text-slate-500 uppercase tracking-wider">
        {{ t('creatorStats.importedSection') }}
      </div>
      <div
        v-if="accountStats && hasCreatorProfile"
        class="rounded-lg border border-slate-100 bg-slate-50/70 p-3"
      >
        <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
          {{ t('creatorStats.profile.title') }}
        </div>
        <div class="flex items-start gap-3">
          <img
            v-if="accountStats.avatar_url"
            :src="accountStats.avatar_url"
            :alt="t('creatorStats.profile.avatarAlt', { name: profileDisplayName })"
            class="h-11 w-11 shrink-0 rounded-full object-cover border border-slate-200 bg-white"
          />
          <div
            v-else
            class="h-11 w-11 shrink-0 rounded-full bg-violet-100 text-violet-700 flex items-center justify-center text-sm font-semibold"
          >
            {{ profileInitial }}
          </div>
          <div class="min-w-0 flex-1">
            <div class="text-sm font-semibold text-slate-700 truncate">{{ profileDisplayName }}</div>
            <div class="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
              <span v-if="accountStats.red_id">
                {{ t('creatorStats.profile.redId') }}: {{ accountStats.red_id }}
              </span>
              <span v-if="accountStats.creator_user_id">
                {{ t('creatorStats.profile.userId') }}: {{ accountStats.creator_user_id }}
              </span>
            </div>
            <p v-if="accountStats.bio" class="mt-1 text-[11px] text-slate-500 leading-relaxed line-clamp-2">
              {{ accountStats.bio }}
            </p>
          </div>
        </div>
        <div
          v-if="accountStats.creator_role || accountStats.zone"
          class="mt-2 flex flex-wrap gap-1.5 text-[10px]"
        >
          <span
            v-if="accountStats.creator_role"
            class="rounded-full bg-violet-100 px-2 py-0.5 text-violet-700"
          >
            {{ t('creatorStats.profile.role') }}: {{ accountStats.creator_role }}
          </span>
          <span
            v-if="accountStats.zone"
            class="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600"
          >
            {{ t('creatorStats.profile.zone') }}: {{ accountStats.zone }}
          </span>
        </div>
      </div>
      <div v-if="accountStats" class="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <div class="rounded-lg bg-slate-50 border border-slate-100 p-2 text-center">
          <div class="text-[10px] text-slate-400">{{ t('creatorStats.metrics.notes') }}</div>
          <div class="text-sm font-semibold text-slate-700">
            {{ formatNum(notesTotal || accountStats.note_count || notes.length) }}
          </div>
        </div>
        <div class="rounded-lg bg-slate-50 border border-slate-100 p-2 text-center">
          <div class="text-[10px] text-slate-400">{{ t('creatorStats.metrics.views') }}</div>
          <div class="text-sm font-semibold text-slate-700">{{ formatNum(accountStats.views) }}</div>
        </div>
        <div class="rounded-lg bg-slate-50 border border-slate-100 p-2 text-center">
          <div class="text-[10px] text-slate-400">{{ t('creatorStats.metrics.likes') }}</div>
          <div class="text-sm font-semibold text-slate-700">{{ formatNum(accountStats.likes) }}</div>
        </div>
        <div class="rounded-lg bg-slate-50 border border-slate-100 p-2 text-center">
          <div class="text-[10px] text-slate-400">{{ t('creatorStats.metrics.fans') }}</div>
          <div class="text-sm font-semibold text-slate-700">{{ formatNum(accountStats.fans) }}</div>
        </div>
      </div>

      <!-- Audience enrichment is aggregate Creator Center data; an empty
           dimension means the signed endpoint was unavailable, not zero. -->
      <div v-if="audience" class="grid gap-2 lg:grid-cols-3">
        <div class="rounded-lg border border-slate-100 bg-white p-3">
          <div class="flex items-center justify-between gap-2">
            <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
              {{ t('creatorStats.audience.sources') }}
            </div>
            <span v-if="!audience.coverage.sources" class="text-[10px] text-slate-400">
              {{ t('creatorStats.audience.unavailable') }}
            </span>
          </div>
          <div v-if="audience.source_distribution.length" class="mt-2 space-y-1.5">
            <div v-for="item in audience.source_distribution.slice(0, 5)" :key="pointLabel(item)" class="flex items-center justify-between gap-2 text-[11px]">
              <span class="truncate text-slate-600">{{ pointLabel(item) }}</span>
              <span class="shrink-0 font-medium text-violet-700">{{ pointValue(item) }}</span>
            </div>
          </div>
        </div>
        <div class="rounded-lg border border-slate-100 bg-white p-3">
          <div class="flex items-center justify-between gap-2">
            <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
              {{ t('creatorStats.audience.periods') }}
            </div>
            <span v-if="!audience.coverage.periods" class="text-[10px] text-slate-400">
              {{ t('creatorStats.audience.unavailable') }}
            </span>
          </div>
          <div v-if="audience.peak_view_periods.length" class="mt-2 space-y-1.5">
            <div v-for="item in audience.peak_view_periods.slice(0, 5)" :key="`${item.start_point}-${item.end_point}`" class="flex items-center justify-between gap-2 text-[11px]">
              <span class="truncate text-slate-600">{{ item.start_point || item.end_point || pointLabel(item) }}</span>
              <span class="shrink-0 font-medium text-cyan-700">{{ pointValue(item) }}</span>
            </div>
          </div>
        </div>
        <div class="rounded-lg border border-slate-100 bg-white p-3">
          <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
            {{ t('creatorStats.audience.profile') }}
          </div>
          <div v-if="audience.audience_profile.length" class="mt-2 flex flex-wrap gap-1.5">
            <span v-for="item in audience.audience_profile.slice(0, 8)" :key="pointLabel(item)" class="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] text-amber-700">
              {{ pointLabel(item) }}<span v-if="item.value != null || item.count != null"> · {{ pointValue(item) }}</span>
            </span>
          </div>
          <p v-else class="mt-2 text-[11px] leading-relaxed text-slate-400">
            {{ t('creatorStats.audience.profileHint') }}
          </p>
        </div>
      </div>

      <div v-if="audience?.insights?.length" class="rounded-lg bg-violet-50/70 border border-violet-100 px-3 py-2">
        <div class="text-[10px] font-semibold text-violet-700 uppercase tracking-wider">{{ t('creatorStats.audience.analysis') }}</div>
        <ul class="mt-1 space-y-0.5 text-[11px] text-violet-800">
          <li v-for="line in audience.insights.slice(0, 3)" :key="line">{{ line }}</li>
        </ul>
      </div>

      <div v-if="notes.length" class="overflow-x-auto rounded-lg border border-slate-100">
        <table class="w-full text-xs">
          <thead class="bg-slate-50 text-slate-500">
            <tr>
              <th class="text-left px-2 py-1.5 font-medium">{{ t('creatorStats.table.title') }}</th>
              <th class="text-right px-2 py-1.5 font-medium">{{ t('creatorStats.table.views') }}</th>
              <th class="text-right px-2 py-1.5 font-medium">{{ t('creatorStats.table.likes') }}</th>
              <th class="text-right px-2 py-1.5 font-medium">{{ t('creatorStats.table.comments') }}</th>
              <th class="text-right px-2 py-1.5 font-medium">{{ t('creatorStats.table.sources') }}</th>
              <th class="text-right px-2 py-1.5 font-medium">{{ t('creatorStats.table.rate') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="n in notes.slice(0, compact ? 8 : 20)"
              :key="n.note_id"
              class="border-t border-slate-50 hover:bg-slate-50/80"
            >
              <td class="px-2 py-1.5 text-slate-700 max-w-[14rem] truncate" :title="n.title">
                {{ n.title || n.note_id }}
              </td>
              <td class="px-2 py-1.5 text-right text-slate-600">{{ formatNum(n.views) }}</td>
              <td class="px-2 py-1.5 text-right text-slate-600">{{ formatNum(n.likes) }}</td>
              <td class="px-2 py-1.5 text-right text-slate-600">{{ formatNum(n.comments) }}</td>
              <td class="px-2 py-1.5 text-right text-slate-600">{{ n.view_sources?.length || '—' }}</td>
              <td class="px-2 py-1.5 text-right text-slate-600">{{ formatRate(n.engagement_rate) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-else-if="!isLoadingStats" class="text-center py-4 text-xs text-slate-400">
      {{ t('creatorStats.noImported') }}
    </div>

    <!-- Suggestions -->
    <div v-if="suggestions.length" class="space-y-2">
      <div class="flex items-center justify-between gap-2">
        <div class="text-xs font-semibold text-slate-500 uppercase tracking-wider">
          {{ t('creatorStats.suggestionsSection') }}
        </div>
        <div class="flex items-center gap-1">
          <button
            v-for="m in (['trend', 'brief', 'free'] as const)"
            :key="m"
            type="button"
            class="text-[10px] px-2 py-0.5 rounded-full transition-colors"
            :class="suggestionMode === m
              ? 'bg-violet-100 text-violet-700 font-medium'
              : 'text-slate-400 hover:bg-slate-100'"
            @click="changeSuggestionMode(m)"
          >
            {{ t(`creatorStats.mode.${m}`) }}
          </button>
        </div>
      </div>
      <ul class="space-y-1.5">
        <li
          v-for="(s, i) in suggestions.slice(0, compact ? 3 : 6)"
          :key="`${s.category}-${i}`"
          class="rounded-lg border border-slate-100 bg-white px-3 py-2"
        >
          <div class="flex items-center gap-1.5">
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">{{ s.category }}</span>
            <span class="text-xs font-medium text-slate-700 truncate">{{ s.title }}</span>
          </div>
          <p class="text-[11px] text-slate-500 mt-1 leading-relaxed">{{ s.advice }}</p>
        </li>
      </ul>
    </div>
  </div>
</template>
