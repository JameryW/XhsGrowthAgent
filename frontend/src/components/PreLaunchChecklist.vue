<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import { getSystemHealth, type HealthCheck } from '@/api/system'

const { t } = useI18n()

interface ChecklistItem {
  id: string
  label: string
  description: string
  status: 'ok' | 'warning' | 'error' | 'disabled'
  required: boolean
  impact: string
  fixGuide?: string
}

const health = ref<HealthCheck | null>(null)
const isLoading = ref(false)
const error = ref<string | null>(null)

async function fetchHealth(options?: { fresh?: boolean }) {
  isLoading.value = true
  error.value = null
  try {
    health.value = await getSystemHealth(options)
  } catch (e: any) {
    error.value = e.message
  } finally {
    isLoading.value = false
  }
}

// Defer health probe so the start form paints first; still uses client+server caches.
onMounted(() => {
  const run = () => { void fetchHealth() }
  if (typeof window !== 'undefined' && 'requestIdleCallback' in window) {
    const idle = window.requestIdleCallback as (cb: () => void, opts?: { timeout: number }) => number
    idle(run, { timeout: 400 })
  } else {
    window.setTimeout(run, 0)
  }
})

// Build checklist items from health data
const checklistItems = computed<ChecklistItem[]>(() => {
  if (!health.value) return []

  const items: ChecklistItem[] = []

  // LLM Providers (Required)
  const llmStatus = health.value.checks.llm_providers
  items.push({
    id: 'llm',
    label: t('checklist.llm.label'),
    description: t('checklist.llm.description'),
    status: llmStatus.status as ChecklistItem['status'],
    required: true,
    impact: t('checklist.llm.impact'),
    fixGuide: llmStatus.status !== 'ok' ? t('checklist.llm.fixGuide') : undefined,
  })

  // Ripple CAS (Optional)
  const rippleStatus = health.value.checks.ripple_cas
  if (rippleStatus.status !== 'disabled') {
    items.push({
      id: 'ripple',
      label: t('checklist.ripple.label'),
      description: t('checklist.ripple.description'),
      status: rippleStatus.status as ChecklistItem['status'],
      required: false,
      impact: t('checklist.ripple.impact'),
      fixGuide: rippleStatus.status !== 'ok' ? t('checklist.ripple.fixGuide') : undefined,
    })
  }

  // Database (Optional - shows storage mode)
  const dbStatus = health.value.checks.database
  items.push({
    id: 'database',
    label: t('checklist.database.label'),
    description: t('checklist.database.description'),
    status: dbStatus.status as ChecklistItem['status'],
    required: false,
    impact: dbStatus.mode === 'memory'
      ? t('checklist.database.impactMemory')
      : t('checklist.database.impactPersistent'),
  })

  return items
})

// Overall readiness
const readiness = computed(() => {
  const items = checklistItems.value
  if (items.length === 0) return { status: 'loading', canStart: false, canPublish: false }

  const requiredOk = items.filter(i => i.required).every(i => i.status === 'ok')

  return {
    status: requiredOk ? 'full' : 'blocked',
    canStart: requiredOk,
    canPublish: requiredOk,
  }
})

// Status styling
const statusIcon = (status: string) => {
  switch (status) {
    case 'ok': return 'CheckCircle'
    case 'warning': return 'AlertTriangle'
    case 'error': return 'XCircle'
    case 'disabled': return 'Minus'
    default: return 'Circle'
  }
}

const statusColor = (status: string) => {
  switch (status) {
    case 'ok': return 'text-emerald-500'
    case 'warning': return 'text-amber-500'
    case 'error': return 'text-rose-500'
    case 'disabled': return 'text-slate-400'
    default: return 'text-slate-400'
  }
}

const statusBg = (status: string) => {
  switch (status) {
    case 'ok': return 'bg-emerald-50 border-emerald-100'
    case 'warning': return 'bg-amber-50 border-amber-100'
    case 'error': return 'bg-rose-50 border-rose-100'
    case 'disabled': return 'bg-slate-50 border-slate-100 dark:bg-slate-800/70 dark:border-slate-700/50'
    default: return 'bg-slate-50 border-slate-100 dark:bg-slate-800/70 dark:border-slate-700/50'
  }
}

// Expose readiness for parent
defineExpose({ readiness })
</script>

<template>
  <div class="rounded-xl liquid-glass overflow-hidden">
    <!-- Header -->
    <div class="px-3 py-2.5 md:px-4 md:py-3 border-b border-slate-100">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-400 to-teal-400 flex items-center justify-center">
            <AppIcon name="ClipboardCheck" size="sm" variant="white" />
          </div>
          <div>
            <h3 class="text-sm font-semibold text-slate-700">{{ t('checklist.title') }}</h3>
            <p class="text-xs text-slate-400">{{ t('checklist.subtitle') }}</p>
          </div>
        </div>

        <!-- Readiness badge -->
        <div v-if="!isLoading" class="flex items-center gap-2">
          <span
            v-if="readiness.status === 'full'"
            class="px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-600 text-xs font-medium border border-emerald-100"
          >
            {{ t('checklist.readyFull') }}
          </span>
          <span
            v-else-if="readiness.status === 'blocked'"
            class="px-2.5 py-1 rounded-full bg-rose-50 text-rose-600 text-xs font-medium border border-rose-100"
          >
            {{ t('checklist.blocked') }}
          </span>
        </div>
      </div>
    </div>

    <!-- Loading state -->
    <div v-if="isLoading" class="p-4 space-y-3">
      <div v-for="i in 4" :key="i" class="h-12 rounded-lg bg-slate-100 animate-pulse dark:bg-slate-800" />
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="p-4">
      <div class="rounded-lg p-3 liquid-glass-rose liquid-glass-hover">
        <div class="flex items-center gap-2 mb-1">
          <AppIcon name="WifiOff" size="sm" variant="pink" />
          <span class="text-sm font-medium text-rose-700">{{ t('checklist.apiError') }}</span>
        </div>
        <p class="text-xs text-rose-600">{{ error }}</p>
        <NeonButton variant="ghost" size="sm" class="mt-2" @click="fetchHealth({ fresh: true })">
          <AppIcon name="RefreshCw" size="sm" variant="pink" />
          <span class="ml-1">{{ t('common.retry') }}</span>
        </NeonButton>
      </div>
    </div>

    <!-- Checklist items -->
    <div v-else class="grid grid-cols-2 gap-0">
      <div
        v-for="(item, idx) in checklistItems"
        :key="item.id"
        class="px-3 py-2 md:px-4 md:py-2.5 hover:bg-slate-50/50 transition-colors dark:bg-slate-800/70 dark:border-slate-700/50"
        :class="{
          'border-r border-slate-100': idx % 2 === 0,
          'border-b border-slate-100': idx < checklistItems.length - 2
        }"
      >
        <div class="flex items-start gap-2">
          <!-- Status icon -->
          <div class="mt-0.5 shrink-0">
            <AppIcon
              :name="statusIcon(item.status)"
              size="sm"
              :class="statusColor(item.status)"
            />
          </div>

          <!-- Content -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-1.5 mb-0.5">
              <span class="text-xs font-medium text-slate-700 truncate">{{ item.label }}</span>
              <span
                v-if="item.required"
                class="px-1 py-0.5 rounded text-[10px] font-medium bg-rose-50 text-rose-500 shrink-0"
              >
                {{ t('checklist.required') }}
              </span>
              <span
                v-else
                class="px-1 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-500 shrink-0 dark:bg-slate-800 dark:text-slate-400"
              >
                {{ t('checklist.optional') }}
              </span>
            </div>

            <p class="text-[10px] text-slate-400 leading-tight">{{ item.impact }}</p>

            <!-- Fix guide -->
            <div
              v-if="item.fixGuide && item.status !== 'ok'"
              class="mt-1.5 p-1.5 rounded text-[10px] border"
              :class="statusBg(item.status)"
            >
              <div class="flex items-start gap-1">
                <AppIcon name="Lightbulb" size="sm" variant="peach" class="mt-0.5 shrink-0" />
                <span class="text-slate-600 leading-tight">{{ item.fixGuide }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Summary & Actions -->
    <div v-if="!isLoading && !error" class="px-3 py-2.5 md:px-4 md:py-3 liquid-glass-inset border-t border-white/10">
      <!-- Action buttons -->
      <div class="flex items-center justify-between">
        <button
          type="button"
          @click="fetchHealth({ fresh: true })"
          class="text-xs text-slate-400 hover:text-slate-600 transition-colors flex items-center gap-1"
        >
          <AppIcon name="RefreshCw" size="sm" variant="cyan" />
          {{ t('checklist.refresh') }}
        </button>

        <div class="flex items-center gap-2 text-xs text-slate-400">
          <span>{{ checklistItems.filter(i => i.status === 'ok').length }}/{{ checklistItems.length }}</span>
          <span>{{ t('checklist.ready') }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
