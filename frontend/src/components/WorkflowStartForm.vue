<script setup lang="ts">
import { ref, watch, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import BriefFileUpload from '@/components/BriefFileUpload.vue'
import { useWorkflowStore } from '@/stores/workflow'
import { useAccountsStore } from '@/stores/accounts'
import type { WorkflowPhase } from '@/types/workflow'

const { t } = useI18n()
const workflowStore = useWorkflowStore()
const accountsStore = useAccountsStore()

export type WorkflowMode = 'trend' | 'brief' | 'free'

export interface WorkflowConfig {
  accountId: string
  phase: WorkflowPhase
  dryRun: boolean
  autoPublish: boolean
  topic?: string
  niche: string
  workflowMode: WorkflowMode
  briefText?: string
}

const props = defineProps<{
  initialTopic?: string
  /** Explicit route-level niche (for example, from an Analytics recommendation). */
  initialNiche?: string
  isLoading?: boolean
}>()

const emit = defineEmits<{
  submit: []
  accountChange: [accountId: string]
}>()

const workflowMode = ref<WorkflowMode>('trend')
const accountId = ref('')
const phase = ref<WorkflowPhase>('scouting')
const dryRun = ref(false)
const autoPublish = ref(false)
const showAdvancedOptions = ref(false)
const topic = ref(props.initialTopic || '')
const niche = ref('母婴')
const hasManualNiche = ref(false)
const briefText = ref('')
const briefPdfText = ref<string | null>(null)
const hasPdfUpload = computed(() => !!briefPdfText.value)

const pendingPdfFile = ref<File | null>(null)
const pendingPdfName = computed(() => pendingPdfFile.value?.name ?? null)

const selectedAccount = computed(() =>
  accountsStore.accounts.find((account) => account.id === accountId.value)
)
const boundNiche = computed(() => selectedAccount.value?.niche?.trim() || '')
const explicitNiche = computed(() => props.initialNiche?.trim() || '')
const isUsingBoundNiche = computed(() =>
  !hasManualNiche.value
  && !explicitNiche.value
  && Boolean(boundNiche.value)
  && niche.value === boundNiche.value
)

function applyNicheDefault() {
  // A manual click is always intentional. Route-level recommendations are the
  // next priority; otherwise use the selected account's durable niche.
  if (hasManualNiche.value) return
  niche.value = explicitNiche.value || boundNiche.value || '母婴'
}

function selectNiche(value: string) {
  niche.value = value
  hasManualNiche.value = true
}

// Load accounts and auto-select the active one
onMounted(async () => {
  try {
    await accountsStore.fetchAccounts()
    // Auto-select active account
    if (accountsStore.activeAccountId) {
      accountId.value = accountsStore.activeAccountId
    } else if (accountsStore.accountOptions.length > 0) {
      accountId.value = accountsStore.accountOptions[0].id
    }
    applyNicheDefault()
  } catch {
    // Accounts API unavailable — fallback to 'default'
    accountId.value = 'default'
    applyNicheDefault()
  }
})

// Follow the global active account when it changes while this form is alive.
watch(() => accountsStore.activeAccountId, (nextId, prevId) => {
  if (!nextId || !prevId || nextId === prevId) return
  accountId.value = nextId
  applyNicheDefault()
})

async function onBriefPdfUpload(file: File) {
  // Extract text immediately for preview — no thread ID needed
  await workflowStore.extractBriefPdf(file)
  // Also queue the file for upload to the workflow after it starts
  pendingPdfFile.value = file
}

async function uploadPendingPdf(threadId: string) {
  const file = pendingPdfFile.value
  if (!file) return
  pendingPdfFile.value = null
  await workflowStore.uploadBriefPdf(threadId, file)
}

function onBriefPdfConfirm(text: string) {
  briefPdfText.value = text
  briefText.value = '' // Clear text input when PDF confirmed
}

function onBriefPdfClear() {
  briefPdfText.value = null
  pendingPdfFile.value = null
  workflowStore.clearBriefUpload()
}

// When switching to brief mode, auto-set phase to scouting (brief starts from orchestrator)
// When switching to trend mode, keep current phase
watch(workflowMode, (mode) => {
  if (mode === 'brief') {
    phase.value = 'scouting'
  }
})

watch(accountId, (nextAccountId) => {
  applyNicheDefault()
  emit('accountChange', nextAccountId)
})

watch(boundNiche, () => {
  applyNicheDefault()
})

watch(explicitNiche, (next, previous) => {
  // A new route recommendation starts a fresh default-selection context. A
  // manual choice made afterwards still takes precedence while the user stays
  // on this page.
  if (next && next !== previous) hasManualNiche.value = false
  applyNicheDefault()
}, { immediate: true })

const niches = [
  { value: '母婴', key: 'baby', icon: 'Baby', color: 'rose' },
  { value: '美妆', key: 'beauty', icon: 'Sparkles', color: 'pink' },
  { value: '穿搭', key: 'fashion', icon: 'Shirt', color: 'violet' },
  { value: '美食', key: 'food', icon: 'UtensilsCrossed', color: 'amber' },
  { value: '家居', key: 'homeDecor', icon: 'Home', color: 'teal' },
  { value: '健身', key: 'fitness', icon: 'Dumbbell', color: 'cyan' },
  { value: '旅行', key: 'travel', icon: 'Plane', color: 'sky' },
  { value: '数码', key: 'tech', icon: 'Smartphone', color: 'indigo' },
  { value: '宠物', key: 'pets', icon: 'PawPrint', color: 'orange' },
  { value: '知识', key: 'knowledge', icon: 'BookOpen', color: 'emerald' },
]

const availableNiches = computed(() => {
  if (!niche.value || niches.some((item) => item.value === niche.value)) return niches
  // A manually bound niche may be outside the built-in taxonomy. Keep it
  // visible and selected instead of silently replacing it with a preset.
  return [...niches, { value: niche.value, key: 'custom', icon: 'Compass', color: 'violet' }]
})

const phases: { value: WorkflowPhase; key: string; icon: string }[] = [
  { value: 'scouting', key: 'scouting', icon: 'Compass' },
  { value: 'planning', key: 'planning', icon: 'Lightbulb' },
  { value: 'creating', key: 'creating', icon: 'Pencil' },
  { value: 'reviewing', key: 'reviewing', icon: 'ClipboardList' },
]

// Array-driven mode selector (extensible for future modes)
const modes: { value: WorkflowMode; icon: string; labelKey: string }[] = [
  { value: 'trend', icon: 'Compass', labelKey: 'home.trendMode' },
  { value: 'brief', icon: 'FileText', labelKey: 'home.briefMode' },
  { value: 'free', icon: 'Terminal', labelKey: 'home.freeMode' },
]

const modeDescriptionKeys: Record<WorkflowMode, string> = {
  trend: 'home.modeDescriptions.trend',
  brief: 'home.modeDescriptions.brief',
  free: 'home.modeDescriptions.free',
}

const selectedModeLabel = computed(() => {
  const mode = modes.find((item) => item.value === workflowMode.value)
  return mode ? t(mode.labelKey) : ''
})

// Submit button label: free mode → enterFree, else startWorkflow
const submitLabel = computed(() =>
  workflowMode.value === 'free'
    ? t('home.form.enterFree')
    : t('home.startWorkflow')
)

function getConfig(): WorkflowConfig {
  // When PDF is uploaded, don't pass preview text as briefText — it's truncated.
  // The workflow starts without brief_text (triggers "waiting for upload" path),
  // then the full PDF is uploaded via /brief/upload which writes the complete text.
  const effectiveBriefText = hasPdfUpload.value
    ? undefined
    : (briefText.value.trim() || undefined)
  return {
    accountId: accountId.value.trim(),
    phase: phase.value,
    dryRun: dryRun.value,
    autoPublish: autoPublish.value,
    topic: topic.value.trim() || undefined,
    niche: niche.value,
    workflowMode: workflowMode.value,
    briefText: workflowMode.value === 'brief' ? effectiveBriefText : undefined,
  }
}

defineExpose({ getConfig, uploadPendingPdf, pendingPdfFile })
</script>

<template>
  <div class="space-y-6">
    <!-- A compact progress cue keeps the form oriented on both desktop and mobile. -->
    <div class="flex items-center gap-2 rounded-xl border border-slate-200/80 bg-slate-50/70 px-3 py-2.5 dark:border-slate-700/60 dark:bg-slate-900/70" role="list" :aria-label="t('home.formIntro')">
      <div v-for="(step, index) in [t('home.stepConfigure'), t('home.stepReview'), t('home.stepCreate')]" :key="step" class="flex min-w-0 flex-1 items-center gap-2" role="listitem">
        <span :class="[
          'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold',
          index === 0 ? 'bg-neon-pink text-white shadow-neon-pink-sm' : 'bg-white text-slate-400 ring-1 ring-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:ring-slate-600'
        ]">{{ index + 1 }}</span>
        <span :class="['truncate text-[11px] font-semibold', index === 0 ? 'text-slate-700' : 'text-slate-400']">{{ step }}</span>
        <span v-if="index < 2" class="h-px min-w-2 flex-1 bg-slate-200" aria-hidden="true" />
      </div>
    </div>

    <!-- Workflow Mode Selector -->
    <div>
      <label class="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">
        <AppIcon name="Workflow" size="sm" variant="pink" />
        {{ t('home.form.workflowMode') }}
      </label>
      <div class="grid grid-cols-3 gap-2" role="group" :aria-label="t('home.form.workflowMode')">
        <button
          v-for="m in modes"
          :key="m.value"
          type="button"
          @click="workflowMode = m.value"
          :aria-pressed="workflowMode === m.value"
          :aria-label="`${t(m.labelKey)}: ${t(modeDescriptionKeys[m.value])}`"
          :class="[
            'relative flex min-h-[112px] flex-col items-center gap-1.5 rounded-xl border-2 p-3 text-center',
            'transition-all duration-300 ease-out cursor-pointer select-none',
            workflowMode === m.value
              ? 'border-neon-pink/50 bg-gradient-to-br from-neon-pink/10 to-neon-peach/5 shadow-neon-pink-sm'
              : 'border-slate-100 bg-white hover:border-slate-200 hover:bg-slate-50 hover:shadow-sm dark:border-slate-700/55 dark:bg-slate-900/80 dark:hover:border-slate-600 dark:hover:bg-slate-800/80'
          ]"
        >
          <span v-if="m.value === 'trend'" class="absolute right-2 top-2 rounded-full bg-rose-50 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-neon-pinkDark">
            {{ t('home.modeRecommended') }}
          </span>
          <AppIcon
            :name="m.icon"
            size="md"
            :variant="workflowMode === m.value ? 'pink' : 'cyan'"
          />
          <span :class="['text-sm font-semibold', workflowMode === m.value ? 'text-neon-pinkDark' : 'text-slate-500']">
            {{ t(m.labelKey) }}
          </span>
          <span class="line-clamp-2 text-[10px] leading-4 text-slate-400">{{ t(modeDescriptionKeys[m.value]) }}</span>
          <span v-if="workflowMode === m.value" class="mt-auto inline-flex items-center gap-1 text-[10px] font-semibold text-neon-pinkDark">
            <AppIcon name="Check" size="xs" variant="pink" aria-hidden="true" />
            {{ t('home.selectedMode', { mode: selectedModeLabel }) }}
          </span>
        </button>
      </div>
    </div>

    <!-- Free mode help text (only in free mode) -->
    <p v-if="workflowMode === 'free'" class="text-xs text-slate-400 pl-1 leading-5">
      {{ t('home.form.freeModeHelp') }}
    </p>

    <!-- Account ID -->
    <div class="group">
      <label class="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400 mb-2">
        <AppIcon name="Lock" size="sm" variant="cyan" />
        {{ t('home.form.accountId') }}
      </label>
      <div class="relative">
        <select
          v-model="accountId"
          class="w-full pl-4 pr-10 py-3 rounded-xl border-2 border-slate-100 bg-slate-50/50 text-sm text-slate-700 font-medium
                 transition-all duration-300 ease-out appearance-none dark:border-slate-700/55 dark:bg-slate-900/70 dark:text-slate-200
                 focus:outline-none focus:border-neon-pink/40 focus:bg-white focus:shadow-neon-pink-sm dark:focus:bg-slate-900"
        >
          <option value="" disabled>{{ t('home.form.accountIdPlaceholder') }}</option>
          <option v-for="acc in accountsStore.accountOptions" :key="acc.id" :value="acc.id">
            {{ acc.name }}{{ acc.isActive ? ` (${t('settings.active')})` : '' }}
          </option>
        </select>
        <div class="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none">
          <AppIcon name="ChevronDown" size="sm" variant="cyan" />
        </div>
        <div class="absolute inset-0 rounded-xl bg-gradient-to-r from-neon-pink/5 to-neon-cyan/5 opacity-0 group-focus-within:opacity-100 transition-opacity duration-300 pointer-events-none" />
      </div>
      <p class="text-xs text-slate-400 mt-1.5 pl-1">{{ t('home.form.accountIdHelp') }}</p>
    </div>

    <!-- Topic (optional, trend mode only) -->
    <div v-if="workflowMode === 'trend'" class="group">
      <label class="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400 mb-2">
        <AppIcon name="Sparkles" size="sm" variant="purple" />
        {{ t('home.form.topic') }}
        <span class="text-[10px] font-normal tracking-normal normal-case text-slate-300 bg-slate-100 px-1.5 py-0.5 rounded-full dark:bg-slate-800 dark:text-slate-400">{{ t('common.optional') }}</span>
      </label>
      <div class="relative">
        <input
          v-model="topic"
          type="text"
          class="w-full pl-4 pr-4 py-3 rounded-xl border-2 border-slate-100 bg-slate-50/50 text-sm text-slate-700 font-medium
                 transition-all duration-300 ease-out dark:border-slate-700/55 dark:bg-slate-900/70 dark:text-slate-200
                 focus:outline-none focus:border-neon-purple/40 focus:bg-white focus:shadow-neon-purple-sm dark:focus:bg-slate-900
                 placeholder:text-slate-300 placeholder:font-normal dark:placeholder:text-slate-500"
          :placeholder="t('home.form.topicPlaceholder')"
        />
      </div>
      <p class="text-xs text-slate-400 mt-1.5 pl-1">{{ t('home.form.topicHelp') }}</p>
    </div>

    <!-- Brief input (brief mode only) -->
    <div v-if="workflowMode === 'brief'" class="space-y-4">
      <!-- PDF upload -->
      <BriefFileUpload
        :is-uploading="workflowStore.isBriefUploading"
        :uploaded-text="workflowStore.briefUploadedText"
        :source-type="workflowStore.briefSourceType"
        :thread-id="workflowStore.currentThreadId || ''"
        :pending-file-name="pendingPdfName"
        @upload="onBriefPdfUpload"
        @confirm="onBriefPdfConfirm"
        @clear="onBriefPdfClear"
      />

      <!-- Divider between upload and text input -->
      <div class="flex items-center gap-3 py-1">
        <div class="flex-1 h-px bg-gradient-to-r from-transparent via-slate-200 to-transparent" />
        <span class="text-xs text-slate-400 font-medium">{{ t('brief.orText') }}</span>
        <div class="flex-1 h-px bg-gradient-to-r from-transparent via-slate-200 to-transparent" />
      </div>

      <!-- Text input (disabled when PDF is uploaded) -->
      <div class="group">
        <label class="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400 mb-2">
          <AppIcon name="FileText" size="sm" variant="pink" />
          {{ t('home.form.briefText') }}
        </label>
        <div class="relative">
          <textarea
            v-model="briefText"
            rows="6"
            :disabled="hasPdfUpload"
            :class="[
              'w-full pl-4 pr-4 py-3 rounded-xl border-2 text-sm text-slate-700 font-medium',
              'transition-all duration-300 ease-out resize-y',
              hasPdfUpload
                ? 'border-slate-100 bg-slate-100/50 text-slate-400 cursor-not-allowed dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-500'
                : 'bg-slate-50/50 border-slate-100 focus:outline-none focus:border-neon-pink/40 focus:bg-white focus:shadow-neon-pink-sm placeholder:text-slate-300 placeholder:font-normal dark:bg-slate-900/70 dark:border-slate-700/55 dark:focus:bg-slate-900 dark:placeholder:text-slate-500'
            ]"
            :placeholder="hasPdfUpload ? t('brief.textDisabledByPdf') : t('home.form.briefTextPlaceholder')"
          />
        </div>
        <p class="text-xs text-slate-400 mt-1.5 pl-1">{{ t('home.form.briefTextHelp') }}</p>
      </div>
    </div>

    <!-- Divider (hidden in free mode) -->
    <div v-if="workflowMode !== 'free'" class="flex items-center gap-3 py-1">
      <div class="flex-1 h-px bg-gradient-to-r from-transparent via-slate-200 to-transparent" />
    </div>

    <!-- Niche / Track (hidden in free mode) -->
    <div v-if="workflowMode !== 'free'">
      <label class="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">
        <AppIcon name="Compass" size="sm" variant="pink" />
        {{ t('home.form.niche') }}
      </label>
      <div class="flex flex-wrap gap-2">
        <button
          v-for="n in availableNiches"
          :key="n.value"
          @click="selectNiche(n.value)"
          :class="[
            'group/chip relative flex items-center gap-2 px-3.5 py-2 rounded-full border-2 text-sm font-medium',
            'transition-all duration-300 ease-out cursor-pointer select-none',
            niche === n.value
              ? 'border-neon-pink/50 bg-gradient-to-r from-neon-pink/10 to-neon-peach/10 text-neon-pinkDark shadow-neon-pink-sm scale-[1.02]'
              : 'border-slate-100 bg-white text-slate-500 hover:border-slate-200 hover:bg-slate-50 hover:text-slate-700 hover:shadow-sm hover:-translate-y-0.5 dark:border-slate-700/55 dark:bg-slate-900/80 dark:text-slate-400 dark:hover:border-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-200'
          ]"
        >
          <AppIcon
            :name="n.icon"
            size="sm"
            :variant="niche === n.value ? 'pink' : 'cyan'"
          />
          <span class="text-xs font-semibold whitespace-nowrap">
            {{ n.key === 'custom' ? n.value : t(`home.form.niches.${n.key}`) }}
          </span>
          <div
            v-if="niche === n.value"
            class="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-neon-pink animate-pulse-glow"
          />
        </button>
      </div>
      <p v-if="isUsingBoundNiche" class="text-xs text-violet-500 mt-2 pl-1">
        {{ t('home.form.nicheBound', { niche }) }}
      </p>
      <p v-else class="text-xs text-slate-400 mt-2 pl-1">{{ t('home.form.nicheHelp') }}</p>
    </div>

    <!-- Advanced settings stay collapsed until the user needs them. -->
    <button
      v-if="workflowMode !== 'free'"
      type="button"
      class="flex min-h-11 w-full items-center justify-between rounded-xl border border-slate-200/70 bg-slate-50/60 px-4 text-left text-sm font-medium text-slate-600 transition hover:border-slate-300 hover:bg-white dark:border-slate-700/55 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:bg-slate-800"
      :aria-expanded="showAdvancedOptions"
      @click="showAdvancedOptions = !showAdvancedOptions"
    >
      <span class="inline-flex items-center gap-2">
        <AppIcon name="Settings2" size="sm" variant="cyan" />
        {{ showAdvancedOptions ? t('home.form.advancedOptionsHide') : t('home.form.advancedOptions') }}
      </span>
      <AppIcon :name="showAdvancedOptions ? 'ChevronUp' : 'ChevronDown'" size="sm" variant="cyan" />
    </button>

    <!-- Divider (hidden in free mode; follows phase block) -->
    <div v-if="workflowMode !== 'free' && showAdvancedOptions" class="flex items-center gap-3 py-1">
      <div class="flex-1 h-px bg-gradient-to-r from-transparent via-slate-200 to-transparent" />
    </div>

    <!-- Starting Phase (trend mode only) -->
    <div v-if="workflowMode === 'trend' && showAdvancedOptions">
      <label class="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">
        <AppIcon name="GitBranch" size="sm" variant="purple" />
        {{ t('home.form.startPhase') }}
      </label>
      <div class="grid grid-cols-4 gap-2">
        <button
          v-for="(p, idx) in phases"
          :key="p.value"
          @click="phase = p.value"
          :class="[
            'relative flex flex-col items-center gap-1.5 p-2.5 rounded-xl border-2 text-center',
            'transition-all duration-300 ease-out cursor-pointer select-none',
            phase === p.value
              ? 'border-neon-pink/50 bg-gradient-to-br from-neon-pink/10 to-neon-peach/5 shadow-neon-pink-sm'
              : 'border-slate-100 bg-white hover:border-slate-200 hover:bg-slate-50 hover:shadow-sm dark:border-slate-700/55 dark:bg-slate-900/80 dark:hover:border-slate-600 dark:hover:bg-slate-800/80'
          ]"
        >
          <div :class="[
            'flex items-center justify-center w-6 h-6 rounded-full border-2 shrink-0',
            'transition-all duration-300',
            phase === p.value
              ? 'border-neon-pink bg-neon-pink'
              : 'border-slate-200 bg-white dark:border-slate-600 dark:bg-slate-800'
          ]">
            <AppIcon
              v-if="phase === p.value"
              :name="p.icon"
              size="sm"
              variant="white"
            />
            <span
              v-else
              class="text-[9px] font-bold text-slate-400"
            >{{ idx + 1 }}</span>
          </div>
          <span :class="[
            'text-[11px] font-semibold leading-tight',
            phase === p.value ? 'text-neon-pinkDark' : 'text-slate-500'
          ]">
            {{ t(`home.form.phases.${p.key}.label`) }}
          </span>
        </button>
      </div>
    </div>

    <!-- Divider (hidden in free mode) -->
    <div v-if="workflowMode !== 'free' && showAdvancedOptions" class="flex items-center gap-3 py-1">
      <div class="flex-1 h-px bg-gradient-to-r from-transparent via-slate-200 to-transparent" />
    </div>

    <!-- Options (hidden in free mode) -->
    <div v-if="workflowMode !== 'free' && showAdvancedOptions">
      <label class="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400 mb-2">
        <AppIcon name="Settings" size="sm" variant="cyan" />
        {{ t('home.form.options') }}
      </label>

      <div class="grid grid-cols-2 gap-2.5">
        <!-- Dry Run toggle -->
        <div class="flex items-center justify-between p-3 rounded-xl border-2 border-slate-100 bg-white
                      hover:border-slate-200 hover:shadow-sm transition-all duration-300 group/opt dark:border-slate-700/55 dark:bg-slate-900/80 dark:hover:border-slate-600">
          <div class="flex items-center gap-2 min-w-0">
            <div class="flex items-center justify-center w-7 h-7 rounded-lg bg-teal-50 group-hover/opt:bg-teal-100 transition-colors shrink-0 dark:bg-teal-950/50 dark:group-hover/opt:bg-teal-900/50">
              <AppIcon name="FlaskConical" size="sm" variant="cyan" />
            </div>
            <span class="text-xs font-semibold text-slate-700 truncate">{{ t('home.form.dryRun') }}</span>
          </div>
          <button
            @click="dryRun = !dryRun"
            :class="[
              'relative w-10 h-6 rounded-full transition-all duration-300 ease-out cursor-pointer shrink-0',
              dryRun
                ? 'bg-gradient-to-r from-teal-400 to-teal-500 shadow-neon-cyan-sm'
                : 'bg-slate-200'
            ]"
            role="switch"
            :aria-checked="dryRun"
          >
            <span
              :class="[
                'absolute top-1 left-1 w-4 h-4 rounded-full bg-white shadow-md transition-all duration-300 ease-out',
                dryRun ? 'translate-x-4' : 'translate-x-0'
              ]"
            />
          </button>
        </div>

        <!-- Auto Publish toggle -->
        <div class="flex items-center justify-between p-3 rounded-xl border-2 border-slate-100 bg-white
                      hover:border-slate-200 hover:shadow-sm transition-all duration-300 group/opt dark:border-slate-700/55 dark:bg-slate-900/80 dark:hover:border-slate-600">
          <div class="flex items-center gap-2 min-w-0">
            <div class="flex items-center justify-center w-7 h-7 rounded-lg bg-rose-50 group-hover/opt:bg-rose-100 transition-colors shrink-0 dark:bg-rose-950/50 dark:group-hover/opt:bg-rose-900/50">
              <AppIcon name="Upload" size="sm" variant="pink" />
            </div>
            <span class="text-xs font-semibold text-slate-700 truncate">{{ t('home.form.autoPublish') }}</span>
          </div>
          <button
            @click="autoPublish = !autoPublish"
            :class="[
              'relative w-10 h-6 rounded-full transition-all duration-300 ease-out cursor-pointer shrink-0',
              autoPublish
                ? 'bg-gradient-to-r from-neon-pink to-neon-peach shadow-neon-pink-sm'
                : 'bg-slate-200'
            ]"
            role="switch"
            :aria-checked="autoPublish"
          >
            <span
              :class="[
                'absolute top-1 left-1 w-4 h-4 rounded-full bg-white shadow-md transition-all duration-300 ease-out',
                autoPublish ? 'translate-x-4' : 'translate-x-0'
              ]"
            />
          </button>
        </div>
      </div>
    </div>

    <!-- Submit button (moved from Home into form) -->
    <div class="pt-1">
      <NeonButton
        variant="pink"
        size="md"
        class="w-full max-w-xs mx-auto group/btn"
        :loading="props.isLoading"
        :aria-label="submitLabel"
        @click="emit('submit')"
      >
        <span class="inline-flex items-center gap-2 transition-transform duration-200 group-hover/btn:translate-x-1">
          <AppIcon name="Rocket" size="sm" variant="white" aria-hidden="true" />
          <span class="font-semibold">{{ submitLabel }}</span>
        </span>
      </NeonButton>
    </div>
  </div>
</template>
