<script setup lang="ts">
import { computed, ref } from 'vue'
import WorkflowNode from '@/components/WorkflowNode.vue'
import AppIcon from '@/components/AppIcon.vue'
import { useWorkflowStore } from '@/stores'

const workflowStore = useWorkflowStore()

// Keyboard navigation state
const focusedIndex = ref(-1)

// Memoized phase order for performance
const phaseOrder = ['scouting', 'planning', 'creating', 'reviewing', 'publishing', 'completed'] as const

// Progress calculation based on current phase
const workflowProgress = computed(() => {
  const currentPhase = workflowStore.currentPhase
  const currentIndex = phaseOrder.indexOf(currentPhase as any)
  if (currentIndex === -1) return 0
  return Math.round((currentIndex / (phaseOrder.length - 1)) * 100)
})

// Workflow nodes configuration
const workflowNodes = computed(() => [
  { icon: 'Search', label: '趋势发现', phase: 'scouting', description: '发现热门趋势和话题' },
  { icon: 'ClipboardList', label: '策略规划', phase: 'planning', description: '制定内容发布策略' },
  { icon: 'Pencil', label: '文案创作', phase: 'creating', description: 'AI生成文案内容' },
  { icon: 'Palette', label: '视觉设计', phase: 'creating', description: '设计封面和图片方案' },
  { icon: 'Clock', label: '审核', phase: 'reviewing', description: '人工审核确认发布' },
  { icon: 'Upload', label: '发布', phase: 'publishing', description: '发布到小红书平台' },
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

// Keyboard navigation handlers
const handleKeyDown = (e: KeyboardEvent) => {
  const nodeCount = workflowNodes.value.length
  switch (e.key) {
    case 'ArrowRight':
      e.preventDefault()
      focusedIndex.value = Math.min(nodeCount - 1, focusedIndex.value + 1)
      break
    case 'ArrowLeft':
      e.preventDefault()
      focusedIndex.value = Math.max(0, focusedIndex.value - 1)
      break
    case 'Home':
      e.preventDefault()
      focusedIndex.value = 0
      break
    case 'End':
      e.preventDefault()
      focusedIndex.value = nodeCount - 1
      break
  }
}

const isFocused = (index: number) => focusedIndex.value === index
</script>

<template>
  <div
    class="bg-white/98 backdrop-blur-sm rounded-2xl p-6 border border-slate-200/50 shadow-sm"
    role="region"
    aria-label="工作流进度"
    @keydown="handleKeyDown"
  >
    <div class="flex items-center gap-2 mb-5">
      <AppIcon name="GitBranch" size="md" variant="cyan" aria-hidden="true" />
      <span class="text-xs text-slate-500 uppercase tracking-wide font-medium">Workflow Pipeline</span>
      <span class="text-xs text-slate-400 ml-auto">使用方向键导航</span>
    </div>

    <!-- Progress line with ARIA -->
    <div class="relative py-4" role="progressbar" :aria-valuenow="workflowProgress" aria-valuemin="0" aria-valuemax="100" :aria-label="`工作流进度 ${workflowProgress}%`">
      <div class="absolute top-1/2 left-0 right-0 h-1 bg-slate-100 rounded-full" aria-hidden="true" />
      <div
        class="absolute top-1/2 left-0 h-1 bg-gradient-to-r from-rose-400 to-teal-400 rounded-full transition-all duration-500"
        :style="{ width: `${workflowProgress}%` }"
        aria-hidden="true"
      />
    </div>

    <!-- Nodes with keyboard navigation -->
    <div class="flex justify-between items-center relative px-4" role="list" aria-label="工作流阶段">
      <WorkflowNode
        v-for="(node, index) in workflowNodes"
        :key="node.phase"
        :icon="node.icon"
        :label="node.label"
        :status="getNodeStatus(node.phase)"
        :focused="isFocused(index)"
        role="listitem"
        :tabindex="isFocused(index) ? 0 : -1"
        :aria-label="`${node.label} - ${getNodeStatus(node.phase) === 'completed' ? '已完成' : getNodeStatus(node.phase) === 'running' ? '正在执行' : '待处理'}`"
        :aria-describedby="`node-desc-${index}`"
      />

      <!-- Hidden descriptions for screen readers -->
      <div id="node-desc-0" class="sr-only">发现热门趋势和话题</div>
      <div id="node-desc-1" class="sr-only">制定内容发布策略</div>
      <div id="node-desc-2" class="sr-only">AI生成文案内容</div>
      <div id="node-desc-3" class="sr-only">设计封面和图片方案</div>
      <div id="node-desc-4" class="sr-only">人工审核确认发布</div>
      <div id="node-desc-5" class="sr-only">发布到小红书平台</div>
    </div>
  </div>
</template>

<style scoped>
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>