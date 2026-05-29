<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import type { WorkflowPhase } from '@/types/workflow'

const { t } = useI18n()

export interface WorkflowConfig {
  accountId: string
  phase: WorkflowPhase
  dryRun: boolean
  autoPublish: boolean
  topic?: string
}

const props = defineProps<{
  initialTopic?: string
}>()

const accountId = ref('default')
const phase = ref<WorkflowPhase>('scouting')
const dryRun = ref(true)
const autoPublish = ref(false)
const topic = ref(props.initialTopic || '')

const phases: { value: WorkflowPhase; label: string; desc: string }[] = [
  { value: 'scouting', label: '趋势发现', desc: '从发现热门趋势开始' },
  { value: 'planning', label: '策略规划', desc: '跳过趋势发现，直接制定策略' },
  { value: 'creating', label: '内容创作', desc: '跳过策略，直接开始创作' },
  { value: 'reviewing', label: '内容审核', desc: '跳到审核阶段' },
]

// Expose config for parent to read
function getConfig(): WorkflowConfig {
  return {
    accountId: accountId.value.trim(),
    phase: phase.value,
    dryRun: dryRun.value,
    autoPublish: autoPublish.value,
    topic: topic.value.trim() || undefined,
  }
}

defineExpose({ getConfig })
</script>

<template>
  <div class="space-y-5">
    <!-- Account ID -->
    <div>
      <label class="block text-sm font-medium text-slate-700 mb-1.5">
        {{ t('home.form.accountId') }}
      </label>
      <input
        v-model="accountId"
        type="text"
        class="w-full px-3 py-2.5 rounded-lg border border-slate-200 bg-white text-sm text-slate-700 focus:outline-none focus:border-rose-300 focus:ring-1 focus:ring-rose-200 transition-all"
        :placeholder="t('home.form.accountIdPlaceholder')"
      />
      <p class="text-xs text-slate-400 mt-1">{{ t('home.form.accountIdHelp') }}</p>
    </div>

    <!-- Topic (optional) -->
    <div>
      <label class="block text-sm font-medium text-slate-700 mb-1.5">
        {{ t('home.form.topic') || '话题主题' }}
      </label>
      <input
        v-model="topic"
        type="text"
        class="w-full px-3 py-2.5 rounded-lg border border-slate-200 bg-white text-sm text-slate-700 focus:outline-none focus:border-rose-300 focus:ring-1 focus:ring-rose-200 transition-all"
        :placeholder="t('home.form.topicPlaceholder') || '可选：输入内容主题或关键词'"
      />
      <p class="text-xs text-slate-400 mt-1">{{ t('home.form.topicHelp') || '指定主题可引导内容策略方向' }}</p>
    </div>

    <!-- Starting Phase -->
    <div>
      <label class="block text-sm font-medium text-slate-700 mb-1.5">
        {{ t('home.form.startPhase') }}
      </label>
      <div class="grid grid-cols-2 gap-2">
        <button
          v-for="p in phases"
          :key="p.value"
          @click="phase = p.value"
          :class="[
            'flex flex-col items-start p-3 rounded-lg border text-left transition-all duration-200',
            phase === p.value
              ? 'border-rose-300 bg-rose-50 shadow-sm'
              : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
          ]"
        >
          <span :class="['text-sm font-medium', phase === p.value ? 'text-rose-600' : 'text-slate-700']">
            {{ p.label }}
          </span>
          <span class="text-xs text-slate-400 mt-0.5">{{ p.desc }}</span>
        </button>
      </div>
    </div>

    <!-- Options -->
    <div class="space-y-3">
      <label class="block text-sm font-medium text-slate-700">
        {{ t('home.form.options') }}
      </label>

      <!-- Dry Run toggle -->
      <div class="flex items-center justify-between py-2 px-3 rounded-lg bg-slate-50 border border-slate-100">
        <div class="flex items-center gap-2">
          <AppIcon name="FlaskConical" size="sm" variant="cyan" />
          <div>
            <span class="text-sm text-slate-700">{{ t('home.form.dryRun') }}</span>
            <p class="text-xs text-slate-400">{{ t('home.form.dryRunHelp') }}</p>
          </div>
        </div>
        <button
          @click="dryRun = !dryRun"
          :class="[
            'relative w-11 h-6 rounded-full transition-colors duration-200',
            dryRun ? 'bg-teal-500' : 'bg-slate-300'
          ]"
          role="switch"
          :aria-checked="dryRun"
        >
          <span
            :class="[
              'absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform duration-200',
              dryRun ? 'translate-x-5' : 'translate-x-0'
            ]"
          />
        </button>
      </div>

      <!-- Auto Publish toggle -->
      <div class="flex items-center justify-between py-2 px-3 rounded-lg bg-slate-50 border border-slate-100">
        <div class="flex items-center gap-2">
          <AppIcon name="Upload" size="sm" variant="pink" />
          <div>
            <span class="text-sm text-slate-700">{{ t('home.form.autoPublish') }}</span>
            <p class="text-xs text-slate-400">{{ t('home.form.autoPublishHelp') }}</p>
          </div>
        </div>
        <button
          @click="autoPublish = !autoPublish"
          :class="[
            'relative w-11 h-6 rounded-full transition-colors duration-200',
            autoPublish ? 'bg-rose-500' : 'bg-slate-300'
          ]"
          role="switch"
          :aria-checked="autoPublish"
        >
          <span
            :class="[
              'absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform duration-200',
              autoPublish ? 'translate-x-5' : 'translate-x-0'
            ]"
          />
        </button>
      </div>
    </div>
  </div>
</template>
