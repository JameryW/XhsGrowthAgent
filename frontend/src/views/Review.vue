<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import NeonButton from '@/components/NeonButton.vue'
import { useWorkflowStore, useReviewStore } from '@/stores'
import type { ContentStatus } from '@/types'

const router = useRouter()
const workflowStore = useWorkflowStore()
const reviewStore = useReviewStore()

const comments = ref('')
const selectedDecision = ref<ContentStatus | null>(null)
const isSubmitting = ref(false)
const error = ref<string | null>(null)

onMounted(() => {
  if (workflowStore.currentThreadId) {
    reviewStore.fetchPendingReview(workflowStore.currentThreadId)
  }
})

const copyContent = computed(() => reviewStore.copyContent)
const visualPlan = computed(() => reviewStore.visualPlan)

const handleDecision = async (decision: ContentStatus) => {
  selectedDecision.value = decision
  error.value = null
  isSubmitting.value = true
  try {
    await reviewStore.submitDecision(decision, comments.value)
    router.push('/dashboard')
  } catch (e: any) {
    error.value = e.message || '提交失败，请重试'
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <div class="relative overflow-hidden">
    <!-- 扫描线 -->
    <div class="absolute top-0 left-0 right-0 h-2 bg-gradient-to-r from-transparent via-neon-pink/30 to-transparent animate-scan pointer-events-none" />

    <!-- 审核状态栏 -->
    <div class="glass rounded-xl p-4 mb-6 border border-neon-peach/30">
      <div class="flex items-center gap-4">
        <div class="w-14 h-14 rounded-xl bg-gradient-to-br from-neon-peach to-neon-pink flex items-center justify-center shadow-neon-peach text-3xl">
          ⏳
        </div>
        <div class="flex-1">
          <div class="mono text-xs text-neon-peach">REVIEW_STATUS: PENDING_APPROVAL</div>
          <div class="text-lg font-bold text-white mt-1">内容审核 · 等待您的决定</div>
          <div class="mono text-xs text-white/50">
            Thread: {{ workflowStore.currentThreadId }}
          </div>
        </div>
      </div>
    </div>

    <!-- 内容预览 -->
    <div class="grid grid-cols-2 gap-6 mb-6">
      <!-- 文案预览 -->
      <div class="glass rounded-xl p-4 border border-neon-purple/30">
        <div class="flex items-center gap-3 mb-4">
          <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-neon-purple to-purple-700 flex items-center justify-center text-xl">
            ✍️
          </div>
          <div class="text-neon-purple mono font-bold">文案内容</div>
        </div>

        <div class="bg-black/50 rounded-lg p-4 border-l-2 border-neon-pink">
          <div v-if="copyContent.title" class="text-neon-pink font-bold text-lg mb-2">
            {{ copyContent.title }}
          </div>
          <div v-if="copyContent.body" class="text-white/70 text-sm mb-2">
            {{ copyContent.body }}
          </div>
          <div v-if="copyContent.tags" class="flex gap-2">
            <span v-for="tag in copyContent.tags" :key="tag" class="px-2 py-1 rounded bg-neon-pink/20 text-neon-pink mono text-xs">
              #{{ tag }}
            </span>
          </div>
        </div>
      </div>

      <!-- 视觉方案预览 -->
      <div class="glass rounded-xl p-4 border border-neon-cyan/30">
        <div class="flex items-center gap-3 mb-4">
          <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-neon-cyan to-emerald-600 flex items-center justify-center text-xl">
            🎨
          </div>
          <div class="text-neon-cyan mono font-bold">视觉方案</div>
        </div>

        <div class="bg-black/50 rounded-lg p-4 border-l-2 border-neon-cyan">
          <div v-if="visualPlan.layout" class="text-neon-cyan font-bold mb-2">
            {{ visualPlan.layout }}
          </div>
          <div v-if="visualPlan.style" class="text-white/70 text-sm mb-2">
            {{ visualPlan.style }}
          </div>
          <div v-if="visualPlan.colors" class="flex gap-2 mt-2">
            <div v-for="color in visualPlan.colors" :key="color" class="w-6 h-6 rounded" :style="{ background: color }" />
          </div>
        </div>
      </div>
    </div>

    <!-- 操作按钮 -->
    <div class="glass rounded-xl p-6 border border-neon-pink/30">
      <div class="mono text-neon-cyan text-xs mb-4">审核操作 // SELECT_ACTION</div>

      <!-- Error display -->
      <div v-if="error" class="mb-4 p-3 rounded-lg bg-neon-pink/20 border border-neon-pink/50 text-neon-pink mono text-sm">
        ⚠️ {{ error }}
      </div>

      <div class="grid grid-cols-3 gap-4 mb-6">
        <NeonButton variant="cyan" size="lg" class="w-full" @click="handleDecision('approved')" :loading="isSubmitting" :disabled="isSubmitting">
          ✓ APPROVE
          <div class="text-xs opacity-70 mt-1">直接发布</div>
        </NeonButton>

        <NeonButton variant="purple" size="lg" class="w-full" @click="handleDecision('needs_revision')" :loading="isSubmitting" :disabled="isSubmitting">
          ✎ REVISE
          <div class="text-xs opacity-70 mt-1">要求修改</div>
        </NeonButton>

        <NeonButton variant="ghost" size="lg" class="w-full border-neon-pink text-neon-pink" @click="handleDecision('rejected')" :disabled="isSubmitting">
          ✗ REJECT
          <div class="text-xs opacity-70 mt-1">放弃此内容</div>
        </NeonButton>
      </div>

      <!-- 反馈输入 -->
      <div class="bg-black/50 rounded-lg p-4 border border-neon-purple/20">
        <div class="mono text-neon-purple text-xs mb-2">FEEDBACK_INPUT // 修改建议</div>
        <textarea
          v-model="comments"
          aria-label="审核意见输入框"
          class="w-full bg-transparent border-none text-white mono text-sm resize-none focus:outline-none"
          rows="3"
          placeholder="请输入审核意见或修改建议..."
        />
      </div>
    </div>
  </div>
</template>