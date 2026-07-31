<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import { getSystemHealth, type HealthCheck } from '@/api/system'

const { t } = useI18n()

const health = ref<HealthCheck | null>(null)
const isLoading = ref(false)
const error = ref<string | null>(null)
const isExpanded = ref(false)

async function fetchHealth() {
  isLoading.value = true
  error.value = null
  try {
    health.value = await getSystemHealth()
    // Auto-expand if there are issues
    if (health.value && health.value.status !== 'ok') {
      isExpanded.value = true
    }
  } catch (e: any) {
    error.value = e.message
    isExpanded.value = true
  } finally {
    isLoading.value = false
  }
}

onMounted(fetchHealth)

const statusColor = (status: string) => {
  switch (status) {
    case 'ok': return 'bg-emerald-500'
    case 'warning': return 'bg-amber-500'
    case 'degraded': return 'bg-amber-500'
    case 'disabled': return 'bg-slate-400'
    case 'missing': return 'bg-rose-500'
    case 'error': return 'bg-rose-500'
    default: return 'bg-slate-400'
  }
}

const statusBg = (status: string) => {
  switch (status) {
    case 'ok': return 'bg-emerald-50 border-emerald-100'
    case 'warning': return 'bg-amber-50 border-amber-100'
    case 'degraded': return 'bg-amber-50 border-amber-100'
    case 'disabled': return 'bg-slate-50 border-slate-100 dark:bg-slate-800/70 dark:border-slate-700/50'
    case 'missing': return 'bg-rose-50 border-rose-100'
    case 'error': return 'bg-rose-50 border-rose-100'
    default: return 'bg-slate-50 border-slate-100 dark:bg-slate-800/70 dark:border-slate-700/50'
  }
}

const statusText = (status: string) => {
  switch (status) {
    case 'ok': return t('health.status.ok')
    case 'warning': return t('health.status.warning')
    case 'degraded': return t('health.status.degraded')
    case 'disabled': return t('health.status.disabled')
    case 'missing': return t('health.status.missing')
    case 'error': return t('health.status.error')
    default: return t('health.status.unknown')
  }
}

const hasIssues = computed(() => health.value && health.value.status !== 'ok')
const issueCount = computed(() => {
  if (!health.value) return 0
  let count = 0
  if (health.value.checks.llm_providers.status !== 'ok') count++
  if (health.value.checks.ripple_cas.status !== 'ok' && health.value.checks.ripple_cas.status !== 'disabled') count++
  return count
})
</script>

<template>
  <div class="rounded-xl border border-slate-200/50 bg-white/90 backdrop-blur-sm overflow-hidden dark:bg-slate-900/90 dark:border-slate-700/55">
    <!-- Header - always visible -->
    <button
      class="w-full flex items-center justify-between p-4 hover:bg-slate-50/50 transition-colors dark:hover:bg-slate-800/50"
      @click="isExpanded = !isExpanded"
      :aria-expanded="isExpanded"
      :aria-label="t('health.title')"
    >
      <div class="flex items-center gap-3">
        <div
          v-if="health"
          :class="[statusColor(health.status), 'w-3 h-3 rounded-full animate-pulse']"
        />
        <div v-else class="w-3 h-3 rounded-full bg-slate-300 animate-pulse" />
        <span class="text-sm font-medium text-slate-700">{{ t('home.systemStatus') }}</span>
        <span v-if="health" class="text-xs px-2 py-0.5 rounded-full" :class="[
          health.status === 'ok' ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'
        ]">
          {{ health.status === 'ok' ? t('health.ready') : t('health.needsConfig') }}
        </span>
        <span v-if="hasIssues && issueCount > 0" class="text-xs px-1.5 py-0.5 rounded-full bg-rose-100 text-rose-600 font-medium">
          {{ issueCount }}
        </span>
      </div>
      <div class="flex items-center gap-2">
        <button
          v-if="!isLoading"
          @click.stop="fetchHealth"
          class="p-1 rounded hover:bg-slate-100 transition-colors dark:hover:bg-slate-800"
          :aria-label="t('health.refresh')"
        >
          <AppIcon name="RefreshCw" size="sm" variant="cyan" />
        </button>
        <AppIcon
          :name="isExpanded ? 'ChevronUp' : 'ChevronDown'"
          size="sm"
          variant="cyan"
        />
      </div>
    </button>

    <!-- Expanded details -->
    <div v-if="isExpanded" class="border-t border-slate-100">
      <div v-if="isLoading" class="p-4 space-y-3">
        <div v-for="i in 4" :key="i" class="h-8 rounded bg-slate-100 animate-pulse dark:bg-slate-800" />
      </div>

      <div v-else-if="error" class="p-4">
        <div class="rounded-lg p-3 bg-rose-50 border border-rose-100">
          <div class="flex items-center gap-2 mb-1">
            <AppIcon name="WifiOff" size="sm" variant="pink" />
            <span class="text-sm font-medium text-rose-700">{{ t('health.apiUnreachable') }}</span>
          </div>
          <p class="text-xs text-rose-600">{{ error }}</p>
          <p class="text-xs text-rose-500 mt-1">{{ t('health.guide.apiUnreachable') }}</p>
          <NeonButton variant="ghost" size="sm" class="mt-2" @click="fetchHealth">
            <AppIcon name="RefreshCw" size="sm" variant="pink" />
            <span class="ml-1">{{ t('common.retry') }}</span>
          </NeonButton>
        </div>
      </div>

      <div v-else-if="health" class="p-4 space-y-3">
        <!-- LLM Providers (Required) -->
        <div class="rounded-lg p-3 border" :class="statusBg(health.checks.llm_providers.status)">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <AppIcon name="Cpu" size="sm" variant="purple" />
              <span class="text-sm font-medium text-slate-700">LLM Provider</span>
              <span class="text-xs px-1.5 py-0.5 rounded bg-rose-50 text-rose-500 font-medium">{{ t('health.required') }}</span>
            </div>
            <div class="flex items-center gap-2">
              <span :class="[statusColor(health.checks.llm_providers.status), 'w-2 h-2 rounded-full']" />
              <span class="text-xs font-medium" :class="health.checks.llm_providers.status === 'ok' ? 'text-emerald-600' : 'text-amber-600'">
                {{ statusText(health.checks.llm_providers.status) }}
              </span>
            </div>
          </div>
          <!-- Provider details -->
          <div v-if="health.checks.llm_providers.status !== 'ok'" class="mt-2 space-y-1">
            <div v-for="(info, name) in health.checks.llm_providers.providers" :key="name"
              class="flex items-center justify-between text-xs">
              <span class="text-slate-500">{{ name }}</span>
              <span :class="info.configured ? 'text-emerald-600' : 'text-slate-400'">
                {{ info.configured ? info.preview : t('health.notConfigured') }}
              </span>
            </div>
            <p class="text-xs text-amber-600 mt-1">{{ t('health.guide.llmMissing') }}</p>
          </div>
        </div>

        <!-- Ripple CAS (Optional) -->
        <div class="rounded-lg p-3 border" :class="statusBg(health.checks.ripple_cas.status)">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <AppIcon name="Zap" size="sm" variant="cyan" />
              <span class="text-sm font-medium text-slate-700">Ripple CAS</span>
              <span class="text-xs px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 font-medium dark:bg-slate-800 dark:text-slate-400">{{ t('health.optional') }}</span>
            </div>
            <div class="flex items-center gap-2">
              <span :class="[statusColor(health.checks.ripple_cas.status), 'w-2 h-2 rounded-full']" />
              <span class="text-xs font-medium" :class="{
                'text-emerald-600': health.checks.ripple_cas.status === 'ok',
                'text-slate-400': health.checks.ripple_cas.status === 'disabled',
                'text-amber-600': health.checks.ripple_cas.status === 'warning',
              }">
                {{ statusText(health.checks.ripple_cas.status) }}
              </span>
            </div>
          </div>
          <p v-if="health.checks.ripple_cas.status === 'warning'" class="text-xs text-amber-600 mt-1">
            {{ t('health.guide.rippleMissing') }}
          </p>
          <p v-else-if="health.checks.ripple_cas.status === 'disabled'" class="text-xs text-slate-400 mt-1">
            {{ t('health.guide.rippleDisabled') }}
          </p>
        </div>

        <!-- Database -->
        <div class="rounded-lg p-3 border" :class="statusBg(health.checks.database.status)">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <AppIcon name="Database" size="sm" variant="peach" />
              <span class="text-sm font-medium text-slate-700">{{ t('health.storage') }}</span>
            </div>
            <div class="flex items-center gap-2">
              <span :class="[statusColor(health.checks.database.status), 'w-2 h-2 rounded-full']" />
              <span class="text-xs text-slate-500">{{ health.checks.database.mode }}</span>
            </div>
          </div>
        </div>

        <!-- Memory Store -->
        <div class="rounded-lg p-3 border" :class="statusBg(health.checks.memory_store.status)">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <AppIcon name="Brain" size="sm" variant="cyan" />
              <span class="text-sm font-medium text-slate-700">{{ t('health.memory') }}</span>
            </div>
            <div class="flex items-center gap-2">
              <span :class="[statusColor(health.checks.memory_store.status), 'w-2 h-2 rounded-full']" />
              <span class="text-xs font-medium" :class="{
                'text-emerald-600': health.checks.memory_store.status === 'ok',
                'text-amber-600': health.checks.memory_store.status === 'degraded' || health.checks.memory_store.status === 'warning',
                'text-rose-600': health.checks.memory_store.status === 'error',
              }">
                {{ health.checks.memory_store.backend }}
              </span>
            </div>
          </div>
          <div class="mt-2 flex gap-4 text-xs text-slate-500">
            <span :class="health.checks.memory_store.semantic_index ? 'text-emerald-600' : 'text-amber-500'">
              Semantic: {{ health.checks.memory_store.semantic_index ? t('health.enabled') : t('health.disabled') }}
            </span>
            <span v-if="health.checks.memory_store.semantic_index && health.checks.memory_store.embed_model">
              {{ health.checks.memory_store.embed_model }}
            </span>
            <span v-if="health.checks.memory_store.total_items != null">
              {{ health.checks.memory_store.total_items }} items
            </span>
          </div>
        </div>

        <!-- Creator stats scheduler -->
        <div
          v-if="health.checks.creator_stats_scheduler"
          class="rounded-lg p-3 border"
          :class="statusBg(health.checks.creator_stats_scheduler.status)"
        >
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <AppIcon name="Clock" size="sm" variant="peach" />
              <span class="text-sm font-medium text-slate-700">{{ t('health.scheduler') }}</span>
            </div>
            <div class="flex items-center gap-2">
              <span :class="[statusColor(health.checks.creator_stats_scheduler.status), 'w-2 h-2 rounded-full']" />
              <span class="text-xs text-slate-500">{{ health.checks.creator_stats_scheduler.message }}</span>
            </div>
          </div>
          <div class="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
            <span v-if="health.checks.creator_stats_scheduler.interval_hours != null">
              every {{ health.checks.creator_stats_scheduler.interval_hours }}h
            </span>
            <span v-if="health.checks.creator_stats_scheduler.run_count != null">
              runs {{ health.checks.creator_stats_scheduler.run_count }}
            </span>
            <span v-if="health.checks.creator_stats_scheduler.next_run_at" class="truncate max-w-[14rem]">
              next {{ health.checks.creator_stats_scheduler.next_run_at }}
            </span>
          </div>
        </div>

        <!-- Risk control / CDP -->
        <div
          v-if="health.checks.risk_control"
          class="rounded-lg p-3 border"
          :class="statusBg(health.checks.risk_control.status)"
        >
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <AppIcon name="Lock" size="sm" variant="cyan" />
              <span class="text-sm font-medium text-slate-700">{{ t('health.riskControl') }}</span>
            </div>
            <div class="flex items-center gap-2">
              <span :class="[statusColor(health.checks.risk_control.status), 'w-2 h-2 rounded-full']" />
              <span class="text-xs text-slate-500">{{ health.checks.risk_control.message }}</span>
            </div>
          </div>
          <div class="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
            <span>
              CDP {{ (health.checks.risk_control.cdp_sessions || []).length }}
            </span>
            <span>
              cool-downs {{ health.checks.risk_control.active_browser_cooldowns ?? 0 }}
            </span>
            <span>
              auth blocks {{ health.checks.risk_control.active_sync_auth_blocks ?? 0 }}
            </span>
            <span :class="health.checks.risk_control.durable ? 'text-emerald-600' : 'text-amber-500'">
              {{ health.checks.risk_control.durable ? t('health.durableOn') : t('health.durableOff') }}
            </span>
          </div>
          <div
            v-if="(health.checks.risk_control.cdp_sessions || []).length"
            class="mt-2 space-y-1 text-xs text-slate-500"
          >
            <div
              v-for="row in health.checks.risk_control.cdp_sessions"
              :key="row.key"
              class="flex justify-between gap-2 font-mono"
            >
              <span class="truncate">{{ row.holder }} · {{ row.key }}</span>
              <span v-if="row.held_for_seconds != null">{{ row.held_for_seconds }}s</span>
            </div>
          </div>
        </div>

        <!-- Version & refresh -->
        <div class="flex items-center justify-between text-xs text-slate-400 pt-1">
          <span>v{{ health.version }}</span>
          <button @click.stop="fetchHealth" class="flex items-center gap-1 hover:text-slate-600 transition-colors">
            <AppIcon name="RefreshCw" size="sm" variant="cyan" />
            {{ t('health.refresh') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
