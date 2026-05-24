<script setup lang="ts">
import { onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import NeonButton from '@/components/NeonButton.vue'
import WorkflowNode from '@/components/WorkflowNode.vue'
import ContentCard from '@/components/ContentCard.vue'
import { useWorkflowStore, useReviewStore } from '@/stores'

const router = useRouter()
const workflowStore = useWorkflowStore()
const reviewStore = useReviewStore()

// 生命周期
onMounted(() => {
  if (!workflowStore.currentThreadId) {
    workflowStore.startWorkflow('default', 'scouting')
  } else {
    workflowStore.refreshStatus()
  }
  workflowStore.startPolling(5000)
})

onUnmounted(() => {
  workflowStore.stopPolling()
})

// 计算属性
const workflowNodes = computed(() => [
  { icon: '🔍', label: '趋势发现', phase: 'scouting' },
  { icon: '📋', label: '策略规划', phase: 'planning' },
  { icon: '✍️', label: '文案创作', phase: 'creating' },
  { icon: '🎨', label: '视觉设计', phase: 'creating' },
  { icon: '⏳', label: '审核', phase: 'reviewing' },
  { icon: '📤', label: '发布', phase: 'publishing' },
])

const getNodeStatus = (phase: string) => {
  const currentPhase = workflowStore.currentPhase
  const phaseOrder = ['scouting', 'planning', 'creating', 'reviewing', 'publishing', 'completed']
  const currentIndex = phaseOrder.indexOf(currentPhase)
  const nodeIndex = phaseOrder.indexOf(phase)

  if (nodeIndex < currentIndex) return 'completed'
  if (nodeIndex === currentIndex) return 'running'
  return 'pending'
}

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
</script>

<template>
  <div class="relative overflow-hidden">
    <!-- 扫描线效果 -->
    <div class="absolute top-0 left-0 right-0 h-2 bg-gradient-to-r from-transparent via-neon-pink/30 to-transparent animate-scan pointer-events-none" />

    <!-- 顶部状态栏 -->
    <div class="glass rounded-xl p-4 mb-6 border border-neon-pink/30">
      <div class="flex items-center gap-4">
        <div class="w-14 h-14 rounded-xl bg-gradient-to-br from-neon-pink to-neon-peach flex items-center justify-center shadow-neon-pink text-3xl">
          🚀
        </div>
        <div class="flex-1">
          <div class="mono text-xs text-neon-cyan">WORKFLOW_ID: {{ workflowStore.currentThreadId }}</div>
          <div class="text-lg font-bold text-white mt-1">
            <span class="text-neon-pink">●</span>
            {{ workflowStore.currentPhase === 'idle' ? '等待启动' : `${workflowStore.currentPhase} 阶段` }}
          </div>
          <div class="flex gap-4 mt-2 mono text-xs">
            <span class="text-neon-peach">⚡ 运行中</span>
            <span class="text-neon-cyan">📊 进度 {{ workflowStore.isRunning ? '60%' : '100%' }}</span>
          </div>
        </div>
        <div class="bg-gradient-to-br from-neon-cyan to-emerald-600 rounded-lg px-6 py-3 border border-neon-cyan shadow-neon-cyan mono font-bold">
          <span class="animate-blink">●</span> RUNNING
        </div>
      </div>
    </div>

    <!-- 流程节点时间轴 -->
    <div class="relative py-8 mb-8">
      <!-- 进度线 -->
      <div class="absolute top-1/2 left-0 right-0 h-1 bg-gradient-to-r from-neon-pink via-neon-pink/50 to-transparent rounded-full shadow-neon-pink" />

      <!-- 节点 -->
      <div class="flex justify-around relative">
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
    <div class="grid grid-cols-3 gap-4 mb-6">
      <ContentCard
        v-if="Object.keys(workflowStore.trendData).length > 0"
        title="🔍 趋势发现"
        :content="workflowStore.trendData"
        variant="pink"
        :completed="getNodeStatus('scouting') === 'completed'"
      />
      <ContentCard
        v-if="Object.keys(workflowStore.contentPlan).length > 0"
        title="📋 策略规划"
        :content="workflowStore.contentPlan"
        variant="cyan"
        :completed="getNodeStatus('planning') === 'completed'"
      />
      <ContentCard
        v-if="Object.keys(workflowStore.copyContent).length > 0"
        title="✍️ 文案创作"
        :content="workflowStore.copyContent"
        variant="purple"
        :completed="true"
      />
    </div>

    <!-- 操作按钮 -->
    <div class="flex gap-4">
      <NeonButton variant="pink" @click="pauseWorkflow" :loading="workflowStore.isLoading">
        ⏸️ 暂停工作流
      </NeonButton>
      <NeonButton variant="cyan" @click="workflowStore.refreshStatus()">
        🔄 刷新状态
      </NeonButton>
      <NeonButton variant="purple" @click="goToReview">
        ✅ 进入审核
      </NeonButton>
    </div>
  </div>
</template>