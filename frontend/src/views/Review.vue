<script setup lang="ts">
import { onMounted, ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import CelebrationEffect from '@/components/CelebrationEffect.vue'
import { ReviewSkeleton } from '@/components/skeletons'
import { useWorkflowStore, useReviewStore, useToastStore } from '@/stores'
import type { ContentStatus, CopyContent, VisualPlan } from '@/types'

const router = useRouter()
const workflowStore = useWorkflowStore()
const reviewStore = useReviewStore()
const toastStore = useToastStore()

const comments = ref('')
const selectedDecision = ref<ContentStatus | null>(null)
const isSubmitting = ref(false)
const error = ref<string | null>(null)

// Celebration effect state
const showCelebration = ref(false)

// Watch for workflow completion
watch(
  () => workflowStore.currentPhase,
  (newPhase) => {
    if (newPhase === 'completed') {
      showCelebration.value = true
    }
  }
)

// Loading state
const isLoading = computed(() => reviewStore.isLoading && !reviewStore.pendingReview)

// Confirmation modal state
const showConfirmModal = ref(false)
const pendingDecision = ref<ContentStatus | null>(null)
const confirmModalTitle = ref('')
const confirmModalMessage = ref('')
const confirmModalAction = ref('')
const confirmModalVariant = ref<'danger' | 'warning' | 'info'>('warning')

onMounted(() => {
  if (workflowStore.currentThreadId) {
    reviewStore.fetchPendingReview(workflowStore.currentThreadId)
  }
})

const copyContent = computed<Partial<CopyContent>>(() => reviewStore.copyContent || {})
const visualPlan = computed<Partial<VisualPlan>>(() => reviewStore.visualPlan || {})

// Request confirmation before action
const requestDecision = (decision: ContentStatus) => {
  pendingDecision.value = decision

  if (decision === 'rejected') {
    confirmModalTitle.value = '确认拒绝内容'
    confirmModalMessage.value = '拒绝后内容将被放弃，此操作不可撤销。确定要拒绝这篇内容吗？'
    confirmModalAction.value = '内容将被标记为"已拒绝"，工作流将结束。'
    confirmModalVariant.value = 'danger'
    showConfirmModal.value = true
  } else if (decision === 'approved') {
    confirmModalTitle.value = '确认批准内容'
    confirmModalMessage.value = '批准后内容将进入发布流程。确定内容已准备好发布吗？'
    confirmModalAction.value = '内容将被标记为"已批准"，进入发布阶段。'
    confirmModalVariant.value = 'info'
    showConfirmModal.value = true
  } else {
    // needs_revision - no confirmation needed
    executeDecision(decision)
  }
}

// Execute decision after confirmation
const executeDecision = async (decision: ContentStatus) => {
  selectedDecision.value = decision
  error.value = null
  isSubmitting.value = true
  showConfirmModal.value = false

  try {
    await reviewStore.submitDecision(decision, comments.value)
    toastStore.success('审核完成', `决定: ${decision}`)
    router.push('/dashboard')
  } catch (e: any) {
    error.value = e.message || '提交失败，请重试'
    toastStore.error('提交失败', e.message)
  } finally {
    isSubmitting.value = false
    pendingDecision.value = null
  }
}

const handleConfirm = () => {
  if (pendingDecision.value) {
    executeDecision(pendingDecision.value)
  }
}

const handleCancelConfirm = () => {
  showConfirmModal.value = false
  pendingDecision.value = null
  toastStore.info('操作已取消', '您可以继续审核内容')
}
</script>

<template>
  <ReviewSkeleton v-if="isLoading" />
  <div v-else class="relative space-y-5">
    <!-- 审核状态栏 -->
    <div class="rounded-2xl p-5 relative overflow-hidden bg-white/98 backdrop-blur-sm border border-slate-200/50 shadow-sm">
      <div class="flex items-center gap-5">
        <div class="w-14 h-14 rounded-xl bg-gradient-to-br from-amber-400 to-rose-400 flex items-center justify-center shadow-sm">
          <AppIcon name="Clock" size="xl" variant="white" aria-label="Review" />
        </div>
        <div class="flex-1">
          <div class="flex items-center gap-2 mb-1">
            <span class="px-2 py-1 rounded bg-amber-50 text-amber-600 text-xs uppercase tracking-wide font-medium">PENDING_APPROVAL</span>
          </div>
          <div class="text-xl font-semibold text-slate-800">内容审核 · 等待您的决定</div>
          <div class="text-xs text-slate-400 mt-1">
            Thread: {{ workflowStore.currentThreadId || '—' }}
          </div>
        </div>
      </div>
    </div>

    <!-- 内容预览 -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <!-- 文案预览 -->
      <div class="rounded-xl p-5 border border-slate-200/50 bg-white/98 backdrop-blur-sm transition-all duration-200 hover:shadow-lg hover:-translate-y-0.5">
        <div class="flex items-center gap-3 mb-4">
          <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-400 to-violet-500 flex items-center justify-center shadow-sm">
            <AppIcon name="Pencil" size="md" variant="white" aria-label="Copy content" />
          </div>
          <div class="flex-1">
            <div class="text-slate-800 font-semibold text-sm">文案内容</div>
            <div class="text-xs text-slate-400 uppercase tracking-wide">Copy Content</div>
          </div>
        </div>

        <div class="bg-slate-50 rounded-lg p-4 border-l-2 border-rose-400">
          <div v-if="copyContent.selected_title" class="text-rose-500 font-bold text-lg mb-2">
            {{ copyContent.selected_title }}
          </div>
          <div v-if="copyContent.body_text" class="text-slate-600 text-sm mb-3 leading-relaxed">
            {{ copyContent.body_text }}
          </div>
          <div v-if="copyContent.hashtags?.length" class="flex gap-2 flex-wrap">
            <span v-for="tag in copyContent.hashtags" :key="tag" class="px-2 py-1 rounded bg-rose-50 border border-rose-100 text-rose-500 text-xs font-medium">
              {{ tag }}
            </span>
          </div>
          <div v-if="!copyContent.selected_title && !copyContent.body_text" class="space-y-2">
            <div class="h-4 w-3/4 rounded bg-slate-200 animate-pulse" />
            <div class="h-3 w-full rounded bg-slate-200 animate-pulse" />
          </div>
        </div>
      </div>

      <!-- 视觉方案预览 -->
      <div class="rounded-xl p-5 border border-slate-200/50 bg-white/98 backdrop-blur-sm transition-all duration-200 hover:shadow-lg hover:-translate-y-0.5">
        <div class="flex items-center gap-3 mb-4">
          <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-teal-400 to-teal-500 flex items-center justify-center shadow-sm">
            <AppIcon name="Palette" size="md" variant="white" aria-label="Visual plan" />
          </div>
          <div class="flex-1">
            <div class="text-slate-800 font-semibold text-sm">视觉方案</div>
            <div class="text-xs text-slate-400 uppercase tracking-wide">Visual Plan</div>
          </div>
        </div>

        <div class="bg-slate-50 rounded-lg p-4 border-l-2 border-teal-400">
          <div v-if="visualPlan.layout_style" class="text-teal-500 font-bold mb-2">
            {{ visualPlan.layout_style }}
          </div>
          <div v-if="visualPlan.cover_prompt" class="text-slate-600 text-sm mb-3 leading-relaxed">
            {{ visualPlan.cover_prompt }}
          </div>
          <div v-if="visualPlan.color_palette?.length" class="flex gap-2 mt-2">
            <div v-for="color in visualPlan.color_palette" :key="color" class="w-6 h-6 rounded-lg border border-slate-200 hover:scale-110 transition-transform cursor-pointer" :style="{ background: color }" :title="color" />
          </div>
          <div v-if="!visualPlan.layout_style && !visualPlan.cover_prompt" class="space-y-2">
            <div class="h-4 w-1/2 rounded bg-slate-200 animate-pulse" />
            <div class="h-3 w-full rounded bg-slate-200 animate-pulse" />
          </div>
        </div>
      </div>
    </div>

    <!-- 操作按钮区 -->
    <div class="rounded-2xl p-5 border border-slate-200/50 bg-white/98 backdrop-blur-sm shadow-sm">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-rose-400 to-amber-400 flex items-center justify-center shadow-sm">
          <AppIcon name="GitBranch" size="md" variant="white" aria-label="Actions" />
        </div>
        <div>
          <div class="text-rose-500 font-semibold text-sm">审核操作</div>
          <div class="text-xs text-slate-400">SELECT_ACTION</div>
        </div>
      </div>

      <!-- Error display -->
      <div v-if="error" class="mb-4 p-3 rounded-lg bg-rose-50 border border-rose-100 text-rose-500 text-sm flex items-center gap-2">
        <div class="w-6 h-6 rounded bg-rose-100 flex items-center justify-center">
          <AppIcon name="AlertTriangle" size="md" variant="pink" animate />
        </div>
        <span>{{ error }}</span>
      </div>

      <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
        <NeonButton variant="cyan" size="lg" class="w-full" @click="requestDecision('approved')" :loading="isSubmitting" :disabled="isSubmitting">
          <span class="flex flex-col items-center gap-1">
            <AppIcon name="CheckCircle" size="lg" variant="white" />
            <span class="font-semibold">APPROVE</span>
            <span class="text-xs opacity-70">直接发布</span>
          </span>
        </NeonButton>

        <NeonButton variant="purple" size="lg" class="w-full" @click="requestDecision('needs_revision')" :loading="isSubmitting" :disabled="isSubmitting">
          <span class="flex flex-col items-center gap-1">
            <AppIcon name="Edit3" size="lg" variant="white" />
            <span class="font-semibold">REVISE</span>
            <span class="text-xs opacity-70">要求修改</span>
          </span>
        </NeonButton>

        <NeonButton variant="ghost" size="lg" class="w-full border border-rose-200 text-rose-500 hover:bg-rose-50" @click="requestDecision('rejected')" :disabled="isSubmitting">
          <span class="flex flex-col items-center gap-1">
            <AppIcon name="XCircle" size="lg" variant="pink" />
            <span class="font-semibold">REJECT</span>
            <span class="text-xs opacity-70">放弃内容</span>
          </span>
        </NeonButton>
      </div>

      <!-- 反馈输入 -->
      <div class="bg-slate-50 rounded-lg p-4 border border-slate-100">
        <div class="flex items-center gap-2 mb-2">
          <AppIcon name="MessageSquare" size="sm" variant="purple" />
          <span class="text-xs text-violet-600 uppercase tracking-wide font-medium">FEEDBACK_INPUT</span>
        </div>
        <textarea
          v-model="comments"
          aria-label="审核意见输入框"
          class="w-full bg-white rounded-lg p-3 border border-slate-200 text-slate-700 text-sm resize-none focus:outline-none focus:border-violet-300 focus:ring-1 focus:ring-violet-200 placeholder:text-slate-400 transition-all duration-200"
          rows="3"
          placeholder="请输入审核意见或修改建议..."
        />
      </div>
    </div>

    <!-- Confirmation Modal -->
    <ConfirmModal
      :is-open="showConfirmModal"
      :title="confirmModalTitle"
      :message="confirmModalMessage"
      :confirm-action="confirmModalAction"
      :variant="confirmModalVariant"
      @confirm="handleConfirm"
      @cancel="handleCancelConfirm"
    />

    <!-- Celebration Effect for workflow completion -->
    <div class="relative">
      <CelebrationEffect
        :is-active="showCelebration"
        type="confetti"
        :duration="3000"
      />
    </div>
  </div>
</template>