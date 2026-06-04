<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import type { WorkflowPhase } from '@/types/workflow'

const { t } = useI18n()

export type WorkflowMode = 'trend' | 'brief'

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
}>()

const workflowMode = ref<WorkflowMode>('trend')
const accountId = ref('default')
const phase = ref<WorkflowPhase>('scouting')
const dryRun = ref(true)
const autoPublish = ref(false)
const topic = ref(props.initialTopic || '')
const niche = ref('母婴')
const briefText = ref('')

// When switching to brief mode, auto-set phase to scouting (brief starts from orchestrator)
// When switching to trend mode, keep current phase
watch(workflowMode, (mode) => {
  if (mode === 'brief') {
    phase.value = 'scouting'
  }
})

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

const phases: { value: WorkflowPhase; key: string; icon: string }[] = [
  { value: 'scouting', key: 'scouting', icon: 'Compass' },
  { value: 'planning', key: 'planning', icon: 'Lightbulb' },
  { value: 'creating', key: 'creating', icon: 'Pencil' },
  { value: 'reviewing', key: 'reviewing', icon: 'ClipboardList' },
]

function getConfig(): WorkflowConfig {
  return {
    accountId: accountId.value.trim(),
    phase: phase.value,
    dryRun: dryRun.value,
    autoPublish: autoPublish.value,
    topic: topic.value.trim() || undefined,
    niche: niche.value,
    workflowMode: workflowMode.value,
    briefText: workflowMode.value === 'brief' ? briefText.value.trim() || undefined : undefined,
  }
}

defineExpose({ getConfig })
</script>

<template>
  <div class="space-y-6">
    <!-- Workflow Mode Selector -->
    <div>
      <label class="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">
        <AppIcon name="Workflow" size="sm" variant="pink" />
        {{ t('home.form.workflowMode') }}
      </label>
      <div class="grid grid-cols-2 gap-2">
        <button
          @click="workflowMode = 'trend'"
          :class="[
            'relative flex flex-col items-center gap-1.5 p-3.5 rounded-xl border-2 text-center',
            'transition-all duration-300 ease-out cursor-pointer select-none',
            workflowMode === 'trend'
              ? 'border-neon-pink/50 bg-gradient-to-br from-neon-pink/10 to-neon-peach/5 shadow-neon-pink-sm'
              : 'border-slate-100 bg-white hover:border-slate-200 hover:bg-slate-50 hover:shadow-sm'
          ]"
        >
          <AppIcon name="Compass" size="md" :variant="workflowMode === 'trend' ? 'pink' : 'cyan'" />
          <span :class="['text-sm font-semibold', workflowMode === 'trend' ? 'text-neon-pinkDark' : 'text-slate-500']">
            {{ t('home.trendMode') }}
          </span>
        </button>
        <button
          @click="workflowMode = 'brief'"
          :class="[
            'relative flex flex-col items-center gap-1.5 p-3.5 rounded-xl border-2 text-center',
            'transition-all duration-300 ease-out cursor-pointer select-none',
            workflowMode === 'brief'
              ? 'border-neon-pink/50 bg-gradient-to-br from-neon-pink/10 to-neon-peach/5 shadow-neon-pink-sm'
              : 'border-slate-100 bg-white hover:border-slate-200 hover:bg-slate-50 hover:shadow-sm'
          ]"
        >
          <AppIcon name="FileText" size="md" :variant="workflowMode === 'brief' ? 'pink' : 'cyan'" />
          <span :class="['text-sm font-semibold', workflowMode === 'brief' ? 'text-neon-pinkDark' : 'text-slate-500']">
            {{ t('home.briefMode') }}
          </span>
        </button>
      </div>
    </div>

    <!-- Account ID -->
    <div class="group">
      <label class="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400 mb-2">
        <AppIcon name="Lock" size="sm" variant="cyan" />
        {{ t('home.form.accountId') }}
      </label>
      <div class="relative">
        <input
          v-model="accountId"
          type="text"
          class="w-full pl-4 pr-4 py-3 rounded-xl border-2 border-slate-100 bg-slate-50/50 text-sm text-slate-700 font-medium
                 transition-all duration-300 ease-out
                 focus:outline-none focus:border-neon-pink/40 focus:bg-white focus:shadow-neon-pink-sm
                 placeholder:text-slate-300 placeholder:font-normal"
          :placeholder="t('home.form.accountIdPlaceholder')"
        />
        <div class="absolute inset-0 rounded-xl bg-gradient-to-r from-neon-pink/5 to-neon-cyan/5 opacity-0 group-focus-within:opacity-100 transition-opacity duration-300 pointer-events-none" />
      </div>
      <p class="text-xs text-slate-400 mt-1.5 pl-1">{{ t('home.form.accountIdHelp') }}</p>
    </div>

    <!-- Topic (optional, trend mode only) -->
    <div v-if="workflowMode === 'trend'" class="group">
      <label class="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400 mb-2">
        <AppIcon name="Sparkles" size="sm" variant="purple" />
        {{ t('home.form.topic') }}
        <span class="text-[10px] font-normal tracking-normal normal-case text-slate-300 bg-slate-100 px-1.5 py-0.5 rounded-full">{{ t('common.optional') }}</span>
      </label>
      <div class="relative">
        <input
          v-model="topic"
          type="text"
          class="w-full pl-4 pr-4 py-3 rounded-xl border-2 border-slate-100 bg-slate-50/50 text-sm text-slate-700 font-medium
                 transition-all duration-300 ease-out
                 focus:outline-none focus:border-neon-purple/40 focus:bg-white focus:shadow-neon-purple-sm
                 placeholder:text-slate-300 placeholder:font-normal"
          :placeholder="t('home.form.topicPlaceholder')"
        />
      </div>
      <p class="text-xs text-slate-400 mt-1.5 pl-1">{{ t('home.form.topicHelp') }}</p>
    </div>

    <!-- Brief text (brief mode only) -->
    <div v-if="workflowMode === 'brief'" class="group">
      <label class="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400 mb-2">
        <AppIcon name="FileText" size="sm" variant="pink" />
        {{ t('home.form.briefText') }}
      </label>
      <div class="relative">
        <textarea
          v-model="briefText"
          rows="6"
          class="w-full pl-4 pr-4 py-3 rounded-xl border-2 border-slate-100 bg-slate-50/50 text-sm text-slate-700 font-medium
                 transition-all duration-300 ease-out resize-y
                 focus:outline-none focus:border-neon-pink/40 focus:bg-white focus:shadow-neon-pink-sm
                 placeholder:text-slate-300 placeholder:font-normal"
          :placeholder="t('home.form.briefTextPlaceholder')"
        />
      </div>
      <p class="text-xs text-slate-400 mt-1.5 pl-1">{{ t('home.form.briefTextHelp') }}</p>
    </div>

    <!-- Divider -->
    <div class="flex items-center gap-3 py-1">
      <div class="flex-1 h-px bg-gradient-to-r from-transparent via-slate-200 to-transparent" />
    </div>

    <!-- Niche / Track -->
    <div>
      <label class="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">
        <AppIcon name="Compass" size="sm" variant="pink" />
        {{ t('home.form.niche') }}
      </label>
      <div class="flex flex-wrap gap-2">
        <button
          v-for="n in niches"
          :key="n.value"
          @click="niche = n.value"
          :class="[
            'group/chip relative flex items-center gap-2 px-3.5 py-2 rounded-full border-2 text-sm font-medium',
            'transition-all duration-300 ease-out cursor-pointer select-none',
            niche === n.value
              ? 'border-neon-pink/50 bg-gradient-to-r from-neon-pink/10 to-neon-peach/10 text-neon-pinkDark shadow-neon-pink-sm scale-[1.02]'
              : 'border-slate-100 bg-white text-slate-500 hover:border-slate-200 hover:bg-slate-50 hover:text-slate-700 hover:shadow-sm hover:-translate-y-0.5'
          ]"
        >
          <AppIcon
            :name="n.icon"
            size="sm"
            :variant="niche === n.value ? 'pink' : 'cyan'"
          />
          <span class="text-xs font-semibold whitespace-nowrap">{{ t(`home.form.niches.${n.key}`) }}</span>
          <div
            v-if="niche === n.value"
            class="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-neon-pink animate-pulse-glow"
          />
        </button>
      </div>
      <p class="text-xs text-slate-400 mt-2 pl-1">{{ t('home.form.nicheHelp') }}</p>
    </div>

    <!-- Divider -->
    <div class="flex items-center gap-3 py-1">
      <div class="flex-1 h-px bg-gradient-to-r from-transparent via-slate-200 to-transparent" />
    </div>

    <!-- Starting Phase (trend mode only) -->
    <div v-if="workflowMode === 'trend'">
      <label class="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">
        <AppIcon name="GitBranch" size="sm" variant="purple" />
        {{ t('home.form.startPhase') }}
      </label>
      <div class="relative">
        <!-- Timeline connector line -->
        <div class="absolute left-[23px] top-4 bottom-4 w-px bg-gradient-to-b from-neon-pink/30 via-neon-purple/20 to-slate-200" />

        <div class="space-y-1.5">
          <button
            v-for="(p, idx) in phases"
            :key="p.value"
            @click="phase = p.value"
            :class="[
              'relative w-full flex items-center gap-3.5 p-3 pl-3 rounded-xl border-2 text-left',
              'transition-all duration-300 ease-out cursor-pointer select-none',
              phase === p.value
                ? 'border-neon-pink/30 bg-gradient-to-r from-neon-pink/[0.04] to-transparent shadow-sm'
                : 'border-transparent bg-transparent hover:bg-slate-50 hover:border-slate-100'
            ]"
          >
            <!-- Step indicator -->
            <div :class="[
              'relative z-10 flex items-center justify-center w-[22px] h-[22px] rounded-full border-2 shrink-0',
              'transition-all duration-300',
              phase === p.value
                ? 'border-neon-pink bg-neon-pink shadow-neon-pink-sm'
                : 'border-slate-200 bg-white'
            ]">
              <AppIcon
                v-if="phase === p.value"
                :name="p.icon"
                size="sm"
                variant="white"
              />
              <span
                v-else
                class="text-[10px] font-bold text-slate-400"
              >{{ idx + 1 }}</span>
            </div>

            <!-- Text -->
            <div class="flex-1 min-w-0">
              <span :class="[
                'text-sm font-semibold block',
                phase === p.value ? 'text-neon-pinkDark' : 'text-slate-600'
              ]">
                {{ t(`home.form.phases.${p.key}.label`) }}
              </span>
              <span :class="[
                'text-xs block mt-0.5',
                phase === p.value ? 'text-slate-500' : 'text-slate-400'
              ]">
                {{ t(`home.form.phases.${p.key}.desc`) }}
              </span>
            </div>

            <!-- Selected checkmark -->
            <div
              v-if="phase === p.value"
              class="flex items-center justify-center w-5 h-5 rounded-full bg-neon-pink/10 shrink-0"
            >
              <AppIcon name="Check" size="sm" variant="pink" />
            </div>
          </button>
        </div>
      </div>
    </div>

    <!-- Divider -->
    <div class="flex items-center gap-3 py-1">
      <div class="flex-1 h-px bg-gradient-to-r from-transparent via-slate-200 to-transparent" />
    </div>

    <!-- Options -->
    <div class="space-y-2.5">
      <label class="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400 mb-2">
        <AppIcon name="Settings" size="sm" variant="cyan" />
        {{ t('home.form.options') }}
      </label>

      <!-- Dry Run toggle -->
      <div class="flex items-center justify-between p-3.5 rounded-xl border-2 border-slate-100 bg-white
                    hover:border-slate-200 hover:shadow-sm transition-all duration-300 group/opt">
        <div class="flex items-center gap-3">
          <div class="flex items-center justify-center w-8 h-8 rounded-lg bg-teal-50 group-hover/opt:bg-teal-100 transition-colors">
            <AppIcon name="FlaskConical" size="sm" variant="cyan" />
          </div>
          <div>
            <span class="text-sm font-semibold text-slate-700 block">{{ t('home.form.dryRun') }}</span>
            <p class="text-xs text-slate-400 mt-0.5">{{ t('home.form.dryRunHelp') }}</p>
          </div>
        </div>
        <button
          @click="dryRun = !dryRun"
          :class="[
            'relative w-12 h-7 rounded-full transition-all duration-300 ease-out cursor-pointer shrink-0',
            dryRun
              ? 'bg-gradient-to-r from-teal-400 to-teal-500 shadow-neon-cyan-sm'
              : 'bg-slate-200'
          ]"
          role="switch"
          :aria-checked="dryRun"
        >
          <span
            :class="[
              'absolute top-1 left-1 w-5 h-5 rounded-full bg-white shadow-md transition-all duration-300 ease-out',
              dryRun ? 'translate-x-5' : 'translate-x-0'
            ]"
          />
        </button>
      </div>

      <!-- Auto Publish toggle -->
      <div class="flex items-center justify-between p-3.5 rounded-xl border-2 border-slate-100 bg-white
                    hover:border-slate-200 hover:shadow-sm transition-all duration-300 group/opt">
        <div class="flex items-center gap-3">
          <div class="flex items-center justify-center w-8 h-8 rounded-lg bg-rose-50 group-hover/opt:bg-rose-100 transition-colors">
            <AppIcon name="Upload" size="sm" variant="pink" />
          </div>
          <div>
            <span class="text-sm font-semibold text-slate-700 block">{{ t('home.form.autoPublish') }}</span>
            <p class="text-xs text-slate-400 mt-0.5">{{ t('home.form.autoPublishHelp') }}</p>
          </div>
        </div>
        <button
          @click="autoPublish = !autoPublish"
          :class="[
            'relative w-12 h-7 rounded-full transition-all duration-300 ease-out cursor-pointer shrink-0',
            autoPublish
              ? 'bg-gradient-to-r from-neon-pink to-neon-peach shadow-neon-pink-sm'
              : 'bg-slate-200'
          ]"
          role="switch"
          :aria-checked="autoPublish"
        >
          <span
            :class="[
              'absolute top-1 left-1 w-5 h-5 rounded-full bg-white shadow-md transition-all duration-300 ease-out',
              autoPublish ? 'translate-x-5' : 'translate-x-0'
            ]"
          />
        </button>
      </div>
    </div>
  </div>
</template>
