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

async function fetchHealth() {
  isLoading.value = true
  error.value = null
  try {
    health.value = await getSystemHealth()
  } catch (e: any) {
    error.value = e.message
  } finally {
    isLoading.value = false
  }
}

onMounted(fetchHealth)

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

  // XHS Platform (Optional but affects publishing mode)
  const xhsStatus = health.value.checks.xhs_platform
  items.push({
    id: 'xhs',
    label: t('checklist.xhs.label'),
    description: t('checklist.xhs.description'),
    status: xhsStatus.status as ChecklistItem['status'],
    required: false,
    impact: xhsStatus.status === 'ok'
      ? t('checklist.xhs.impactReal')
      : t('checklist.xhs.impactDryRun'),
    fixGuide: xhsStatus.status !== 'ok' ? t('checklist.xhs.fixGuide') : undefined,
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
  const xhsOk = items.find(i => i.id === 'xhs')?.status === 'ok'

  return {
    status: requiredOk ? (xhsOk ? 'full' : 'dry-run') : 'blocked',
    canStart: requiredOk,
    canPublish: xhsOk,
  }
})

// Auto-set dry-run based on XHS status
const suggestedDryRun = computed(() => !readiness.value.canPublish)

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
    case 'disabled': return 'bg-slate-50 border-slate-100'
    default: return 'bg-slate-50 border-slate-100'
  }
}

// Expose readiness for parent
defineExpose({ readiness, suggestedDryRun })
</script>

<template>
  <div class="rounded-xl border border-slate-200/50 bg-white/90 backdrop-blur-sm overflow-hidden">
    <!-- Header -->
    <div class="p-4 border-b border-slate-100">
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
            v-else-if="readiness.status === 'dry-run'"
            class="px-2.5 py-1 rounded-full bg-amber-50 text-amber-600 text-xs font-medium border border-amber-100"
          >
            {{ t('checklist.readyDryRun') }}
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
      <div v-for="i in 4" :key="i" class="h-12 rounded-lg bg-slate-100 animate-pulse" />
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="p-4">
      <div class="rounded-lg p-3 bg-rose-50 border border-rose-100">
        <div class="flex items-center gap-2 mb-1">
          <AppIcon name="WifiOff" size="sm" variant="pink" />
          <span class="text-sm font-medium text-rose-700">{{ t('checklist.apiError') }}</span>
        </div>
        <p class="text-xs text-rose-600">{{ error }}</p>
        <NeonButton variant="ghost" size="sm" class="mt-2" @click="fetchHealth">
          <AppIcon name="RefreshCw" size="sm" variant="pink" />
          <span class="ml-1">{{ t('common.retry') }}</span>
        </NeonButton>
      </div>
    </div>

    <!-- Checklist items -->
    <div v-else class="divide-y divide-slate-100">
      <div
        v-for="item in checklistItems"
        :key="item.id"
        class="p-4 hover:bg-slate-50/50 transition-colors"
      >
        <div class="flex items-start gap-3">
          <!-- Status icon -->
          <div class="mt-0.5">
            <AppIcon
              :name="statusIcon(item.status)"
              size="md"
              :class="statusColor(item.status)"
            />
          </div>

          <!-- Content -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1">
              <span class="text-sm font-medium text-slate-700">{{ item.label }}</span>
              <span
                v-if="item.required"
                class="px-1.5 py-0.5 rounded text-xs font-medium bg-rose-50 text-rose-500"
              >
                {{ t('checklist.required') }}
              </span>
              <span
                v-else
                class="px-1.5 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-500"
              >
                {{ t('checklist.optional') }}
              </span>
            </div>

            <p class="text-xs text-slate-500 mb-1.5">{{ item.description }}</p>

            <!-- Impact -->
            <div class="flex items-center gap-1.5 text-xs">
              <AppIcon name="Info" size="sm" variant="cyan" />
              <span class="text-slate-500">{{ item.impact }}</span>
            </div>

            <!-- Fix guide -->
            <div
              v-if="item.fixGuide && item.status !== 'ok'"
              class="mt-2 p-2 rounded text-xs border"
              :class="statusBg(item.status)"
            >
              <div class="flex items-start gap-1.5">
                <AppIcon name="Lightbulb" size="sm" variant="peach" class="mt-0.5" />
                <span class="text-slate-600">{{ item.fixGuide }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Summary & Actions -->
    <div v-if="!isLoading && !error" class="p-4 bg-slate-50/50 border-t border-slate-100">
      <!-- Dry-run suggestion -->
      <div
        v-if="suggestedDryRun && readiness.canStart"
        class="mb-3 p-2.5 rounded-lg bg-amber-50 border border-amber-100"
      >
        <div class="flex items-start gap-2">
          <AppIcon name="FlaskConical" size="sm" variant="peach" class="mt-0.5" />
          <div>
            <p class="text-xs font-medium text-amber-700">{{ t('checklist.suggestDryRun') }}</p>
            <p class="text-xs text-amber-600 mt-0.5">{{ t('checklist.suggestDryRunReason') }}</p>
          </div>
        </div>
      </div>

      <!-- Action buttons -->
      <div class="flex items-center justify-between">
        <button
          @click="fetchHealth"
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
