<script setup lang="ts">
import { onMounted, onUnmounted, computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import NeonButton from '@/components/NeonButton.vue'
import WorkflowNode from '@/components/WorkflowNode.vue'
import ContentCard from '@/components/ContentCard.vue'
import AppIcon from '@/components/AppIcon.vue'
import CircularProgress from '@/components/CircularProgress.vue'
import MiniProgress from '@/components/MiniProgress.vue'
import DraftInput from '@/components/DraftInput.vue'
import VersionCompare from '@/components/VersionCompare.vue'
import { useWorkflowStore, useReviewStore, useOptimizationStore } from '@/stores'
import type { DraftContent, VersionChoice } from '@/types/optimization'

const router = useRouter()
const workflowStore = useWorkflowStore()
const reviewStore = useReviewStore()
const optimizationStore = useOptimizationStore()

// Optimization flow state
const showDraftInput = ref(false)

// Memoized phase order for performance
const phaseOrder = ['scouting', 'planning', 'creating', 'reviewing', 'publishing', 'completed'] as const

// Progress calculation based on current phase
const workflowProgress = computed(() => {
  const currentPhase = workflowStore.currentPhase
  const currentIndex = phaseOrder.indexOf(currentPhase as any)
  if (currentIndex === -1) return 0
  return Math.round((currentIndex / (phaseOrder.length - 1)) * 100)
})

// 生命周期
onMounted(() => {
  // Only refresh status if thread exists - don't auto-start
  if (workflowStore.currentThreadId) {
    workflowStore.refreshStatus()
    workflowStore.startPolling(5000)
  }
})

onUnmounted(() => {
  workflowStore.stopPolling()
})

// 计算属性
const workflowNodes = computed(() => [
  { icon: 'Search', label: '趋势发现', phase: 'scouting' },
  { icon: 'ClipboardList', label: '策略规划', phase: 'planning' },
  { icon: 'Pencil', label: '文案创作', phase: 'creating' },
  { icon: 'Palette', label: '视觉设计', phase: 'creating' },
  { icon: 'Clock', label: '审核', phase: 'reviewing' },
  { icon: 'Upload', label: '发布', phase: 'publishing' },
])

// Use memoized phaseOrder for consistent lookup
const getNodeStatus = (phase: string) => {
  const currentPhase = workflowStore.currentPhase
  const currentIndex = phaseOrder.indexOf(currentPhase as any)
  const nodeIndex = phaseOrder.indexOf(phase as any)

  if (nodeIndex < currentIndex) return 'completed'
  if (nodeIndex === currentIndex) return 'running'
  return 'pending'
}

// Optimization flow computed
const isOptimizationPending = computed(() =>
  workflowStore.currentPhase === 'creating' &&
  optimizationStore.contentVersions.length > 0 &&
  !optimizationStore.selectedVersion
)

const isDraftInputPending = computed(() =>
  workflowStore.currentPhase === 'creating' &&
  !optimizationStore.draftContent &&
  !isOptimizationPending.value
)

// 操作
const pauseWorkflow = () => {
  workflowStore.pauseWorkflow()
}

const goToReview = () => {
  if (workflowStore.currentThreadId) {
    reviewStore.fetchPendingReview(workflowStore.currentThreadId)
    router.push('/review')
  }
}

const startOptimization = () => {
  showDraftInput.value = true
}

const handleDraftSubmit = (draft: DraftContent, viralLinks: string[]) => {
  optimizationStore.submitDraft(draft, viralLinks)
  showDraftInput.value = false
}

const handleVersionSelect = (choice: VersionChoice) => {
  optimizationStore.selectVersion(choice)
}
</script>

<template>
  <div class="relative space-y-6">
    <!-- 顶部状态栏 -->
    <div class="rounded-2xl p-6 relative overflow-hidden bg-white/98 backdrop-blur-sm border border-slate-200/50 shadow-sm">
      <div class="flex items-center gap-5">
        <!-- Progress & Logo -->
        <div class="flex items-center gap-4">
          <CircularProgress :value="workflowProgress" variant="cyan" size="lg" show-value />
          <div class="w-16 h-16 rounded-xl bg-gradient-to-br from-rose-400 via-rose-500 to-amber-400 flex items-center justify-center shadow-sm">
            <AppIcon name="Rocket" size="xl" variant="white" aria-label="Workflow" />
          </div>
        </div>

        <!-- Info -->
        <div class="flex-1 space-y-2">
          <div class="flex items-center gap-3">
            <span class="px-2 py-1 rounded bg-teal-50 text-teal-600 text-xs uppercase tracking-wide font-medium">WORKFLOW</span>
            <span class="text-xs text-slate-400">{{ workflowStore.currentThreadId || '—' }}</span>
          </div>
          <div class="text-xl font-semibold text-slate-800">
            {{ workflowStore.currentPhase === 'idle' ? '等待启动' : `${workflowStore.currentPhase} 阶段` }}
          </div>
          <MiniProgress :value="workflowProgress" variant="cyan" class="max-w-xs" />
        </div>

        <!-- Status Badge -->
        <div :class="[
          'px-4 py-2.5 rounded-lg border font-medium flex items-center gap-2 transition-all duration-200',
          workflowStore.isRunning
            ? 'bg-gradient-to-r from-teal-500 to-teal-400 border-teal-200 text-white shadow-sm'
            : 'bg-slate-50 border-slate-200 text-slate-500'
        ]">
          <AppIcon :name="workflowStore.isRunning ? 'Circle' : 'Minus'" size="sm" :variant="workflowStore.isRunning ? 'white' : 'cyan'" :animate="workflowStore.isRunning" />
          <span>{{ workflowStore.isRunning ? 'RUNNING' : 'IDLE' }}</span>
        </div>
      </div>
    </div>

    <!-- 流程节点时间轴 -->
    <div class="bg-white/98 backdrop-blur-sm rounded-2xl p-6 border border-slate-200/50 shadow-sm">
      <div class="flex items-center gap-2 mb-5">
        <AppIcon name="GitBranch" size="md" variant="cyan" />
        <span class="text-xs text-slate-500 uppercase tracking-wide font-medium">Workflow Pipeline</span>
      </div>

      <!-- Progress line -->
      <div class="relative py-4">
        <div class="absolute top-1/2 left-0 right-0 h-1 bg-slate-100 rounded-full" />
        <div
          class="absolute top-1/2 left-0 h-1 bg-gradient-to-r from-rose-400 to-teal-400 rounded-full transition-all duration-500"
          :style="{ width: `${workflowProgress}%` }"
        />
      </div>

      <!-- Nodes -->
      <div class="flex justify-between items-center relative px-4">
        <WorkflowNode
          v-for="node in workflowNodes"
          :key="node.phase"
          :icon="node.icon"
          :label="node.label"
          :status="getNodeStatus(node.phase)"
        />
      </div>
    </div>

    <!-- 输出卡片 -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <ContentCard
        v-if="Object.keys(workflowStore.trendData).length > 0"
        title="趋势发现"
        icon="Search"
        :content="workflowStore.trendData"
        variant="pink"
        :completed="getNodeStatus('scouting') === 'completed'"
      />
      <ContentCard
        v-if="Object.keys(workflowStore.contentPlan).length > 0"
        title="策略规划"
        icon="ClipboardList"
        :content="workflowStore.contentPlan"
        variant="cyan"
        :completed="getNodeStatus('planning') === 'completed'"
      />
      <ContentCard
        v-if="Object.keys(workflowStore.copyContent).length > 0"
        title="文案创作"
        icon="Pencil"
        :content="workflowStore.copyContent"
        variant="purple"
        :completed="true"
      />
    </div>

    <!-- 发布前优化流程 -->
    <div v-if="workflowStore.currentPhase === 'creating'" class="space-y-4">
      <!-- Optimization prompt when draft input is pending -->
      <div v-if="isDraftInputPending && !showDraftInput" class="rounded-xl p-5 bg-gradient-to-r from-neon-cyan/5 to-neon-purple/5 border border-neon-cyan/20">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3">
            <AppIcon name="Sparkles" size="md" variant="cyan" />
            <div>
              <span class="text-sm font-medium text-slate-700">发布前优化</span>
              <span class="text-xs text-slate-400 ml-2">对比爆款笔记，一键优化</span>
            </div>
          </div>
          <NeonButton variant="cyan" @click="startOptimization">
            <AppIcon name="Wand2" size="sm" variant="white" />
            <span>提交草稿优化</span>
          </NeonButton>
        </div>
      </div>

      <!-- Draft Input Component -->
      <DraftInput
        v-if="showDraftInput"
        :is-loading="optimizationStore.isLoading"
        @submit="handleDraftSubmit"
      />

      <!-- Version Compare Component (when versions are available) -->
      <VersionCompare
        v-if="isOptimizationPending"
        :versions="optimizationStore.contentVersions"
        :analysis="optimizationStore.optimizationAnalysis"
        :is-loading="optimizationStore.isLoading"
        @select="handleVersionSelect"
      />
    </div>

    <!-- 操作按钮 -->
    <div class="flex flex-wrap gap-3">
      <NeonButton variant="pink" @click="pauseWorkflow" :loading="workflowStore.isLoading">
        <span class="inline-flex items-center gap-2">
          <AppIcon name="Pause" size="sm" variant="white" />
          <span>暂停工作流</span>
        </span>
      </NeonButton>
      <NeonButton variant="cyan" @click="workflowStore.refreshStatus()">
        <span class="inline-flex items-center gap-2">
          <AppIcon name="RefreshCw" size="sm" variant="white" />
          <span>刷新状态</span>
        </span>
      </NeonButton>
      <NeonButton variant="purple" @click="goToReview">
        <span class="inline-flex items-center gap-2">
          <AppIcon name="CheckCircle" size="sm" variant="white" />
          <span>进入审核</span>
        </span>
      </NeonButton>
    </div>
  </div>
</template>
