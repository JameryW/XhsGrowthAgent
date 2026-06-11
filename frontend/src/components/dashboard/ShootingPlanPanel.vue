<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import { useWorkflowStore } from '@/stores'
import type { ShootingPlan } from '@/types/workflow'

const { t } = useI18n()
const workflowStore = useWorkflowStore()

const shootingPlan = computed<ShootingPlan>(() =>
  workflowStore.workflowState?.shooting_plan || {}
)

const hasPlan = computed(() => Object.keys(shootingPlan.value).length > 0)

const outfits = computed(() => {
  const o = shootingPlan.value.outfits || {}
  return Object.entries(o).map(([scene, items]) => ({ scene, items: items as string[] }))
})

const shootingAngles = computed(() => shootingPlan.value.shooting_angles || [])

const exportPlan = () => {
  if (!workflowStore.currentThreadId) return
  const plan = shootingPlan.value
  const lines: string[] = []
  if (plan.creator_nickname) lines.push(`${t('shootingPlan.creator')}: ${plan.creator_nickname}`)
  if (plan.content_direction) lines.push(`${t('shootingPlan.direction')}: ${plan.content_direction}`)
  if (plan.content_type_label) lines.push(`${t('shootingPlan.type')}: ${plan.content_type_label}`)
  if (plan.product_specification) lines.push(`${t('shootingPlan.product')}: ${plan.product_specification}`)
  if (plan.draft_requirements) lines.push(`${t('shootingPlan.requirements')}: ${plan.draft_requirements}`)
  if (plan.title_candidates?.length) {
    lines.push(`\n${t('shootingPlan.titleCandidates')}:`)
    plan.title_candidates.forEach((tc, i) => lines.push(`  ${i + 1}. ${tc}`))
  }
  if (plan.body_copy) lines.push(`\n${t('shootingPlan.bodyCopy')}:\n${plan.body_copy}`)
  if (plan.required_hashtags?.length) lines.push(`\n${t('shootingPlan.requiredTags')}: ${plan.required_hashtags.join(' ')}`)
  if (plan.optional_hashtags?.length) lines.push(`${t('shootingPlan.optionalTags')}: ${plan.optional_hashtags.join(' ')}`)
  if (outfits.value.length) {
    lines.push(`\n${t('shootingPlan.outfits')}:`)
    outfits.value.forEach(o => lines.push(`  ${o.scene}: ${o.items.join(', ')}`))
  }
  if (shootingAngles.value.length) {
    lines.push(`\n${t('shootingPlan.shootingAngles')}:`)
    shootingAngles.value.forEach(a => {
      lines.push(`  ${a.angle}: ${a.description}`)
      if (a.tips) lines.push(`    ${t('shootingPlan.tip')}: ${a.tips}`)
    })
  }

  navigator.clipboard.writeText(lines.join('\n'))
}
</script>

<template>
  <div v-if="hasPlan" class="rounded-xl p-3 md:p-5 md:rounded-2xl bg-white border border-slate-200/50 shadow-sm">
    <div class="flex items-center justify-between mb-4">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-400 to-violet-500 flex items-center justify-center shadow-sm">
          <AppIcon name="Camera" size="md" variant="white" />
        </div>
        <div>
          <h3 class="text-base font-semibold text-slate-800">{{ t('shootingPlan.title') }}</h3>
          <p class="text-xs text-slate-400">{{ shootingPlan.content_direction || '' }}</p>
        </div>
      </div>
      <NeonButton variant="cyan" size="sm" @click="exportPlan">
        <span class="inline-flex items-center gap-1.5">
          <AppIcon name="Copy" size="sm" variant="white" />
          <span class="text-xs">{{ t('shootingPlan.copy') }}</span>
        </span>
      </NeonButton>
    </div>

    <!-- Creator info -->
    <div class="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-4">
      <div v-if="shootingPlan.creator_nickname" class="p-3 rounded-xl bg-slate-50 border border-slate-100">
        <span class="text-xs text-slate-400 uppercase tracking-wide">{{ t('shootingPlan.creator') }}</span>
        <p class="text-sm font-medium text-slate-700 mt-1">{{ shootingPlan.creator_nickname }}</p>
      </div>
      <div v-if="shootingPlan.content_type_label" class="p-3 rounded-xl bg-slate-50 border border-slate-100">
        <span class="text-xs text-slate-400 uppercase tracking-wide">{{ t('shootingPlan.type') }}</span>
        <p class="text-sm font-medium text-slate-700 mt-1">{{ shootingPlan.content_type_label }}</p>
      </div>
      <div v-if="shootingPlan.planned_publish_date" class="p-3 rounded-xl bg-slate-50 border border-slate-100">
        <span class="text-xs text-slate-400 uppercase tracking-wide">{{ t('shootingPlan.date') }}</span>
        <p class="text-sm font-medium text-slate-700 mt-1">{{ shootingPlan.planned_publish_date }}</p>
      </div>
    </div>

    <!-- Product specs -->
    <div v-if="shootingPlan.product_specification" class="mb-4 p-3 rounded-xl bg-rose-50 border border-rose-100">
      <span class="text-xs text-rose-500 uppercase tracking-wide font-medium">{{ t('shootingPlan.product') }}</span>
      <p class="text-sm text-rose-700 mt-1">{{ shootingPlan.product_specification }}</p>
    </div>

    <!-- Title candidates -->
    <div v-if="shootingPlan.title_candidates?.length" class="mb-4">
      <h4 class="text-xs text-slate-400 uppercase tracking-wide mb-2">{{ t('shootingPlan.titleCandidates') }}</h4>
      <div class="space-y-1.5">
        <div v-for="(title, idx) in shootingPlan.title_candidates" :key="idx"
          class="flex items-center gap-2 p-2 rounded-lg bg-white border border-slate-100 hover:border-slate-200 transition-colors">
          <span class="text-xs font-bold text-neon-pink w-5">{{ idx + 1 }}</span>
          <span class="text-sm text-slate-700">{{ title }}</span>
        </div>
      </div>
    </div>

    <!-- Body copy -->
    <div v-if="shootingPlan.body_copy" class="mb-4">
      <h4 class="text-xs text-slate-400 uppercase tracking-wide mb-2">{{ t('shootingPlan.bodyCopy') }}</h4>
      <div class="p-3 rounded-xl bg-slate-50 border border-slate-100 text-sm text-slate-600 whitespace-pre-wrap">{{ shootingPlan.body_copy }}</div>
    </div>

    <!-- Hashtags -->
    <div v-if="shootingPlan.required_hashtags?.length || shootingPlan.optional_hashtags?.length" class="mb-4">
      <h4 class="text-xs text-slate-400 uppercase tracking-wide mb-2">{{ t('shootingPlan.hashtags') }}</h4>
      <div class="flex flex-wrap gap-1.5">
        <span v-for="tag in (shootingPlan.required_hashtags || [])" :key="tag"
          class="text-xs px-2 py-1 rounded-full bg-rose-50 text-rose-600 border border-rose-200 font-medium">
          #{{ tag }}
        </span>
        <span v-for="tag in (shootingPlan.optional_hashtags || [])" :key="tag"
          class="text-xs px-2 py-1 rounded-full bg-slate-50 text-slate-500 border border-slate-200">
          #{{ tag }}
        </span>
      </div>
    </div>

    <!-- Outfits -->
    <div v-if="outfits.length" class="mb-4">
      <h4 class="text-xs text-slate-400 uppercase tracking-wide mb-2">{{ t('shootingPlan.outfits') }}</h4>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <div v-for="o in outfits" :key="o.scene"
          class="p-2.5 rounded-lg bg-violet-50 border border-violet-100">
          <span class="text-xs text-violet-500 font-medium">{{ o.scene }}</span>
          <p class="text-sm text-violet-700 mt-0.5">{{ o.items.join(', ') }}</p>
        </div>
      </div>
    </div>

    <!-- Shooting angles -->
    <div v-if="shootingAngles.length" class="mb-4">
      <h4 class="text-xs text-slate-400 uppercase tracking-wide mb-2">{{ t('shootingPlan.shootingAngles') }}</h4>
      <div class="space-y-2">
        <div v-for="(angle, idx) in shootingAngles" :key="idx"
          class="p-3 rounded-xl bg-slate-50 border border-slate-100">
          <div class="flex items-center gap-2 mb-1">
            <AppIcon name="Camera" size="sm" variant="cyan" />
            <span class="text-sm font-medium text-slate-700">{{ angle.angle }}</span>
          </div>
          <p class="text-xs text-slate-500">{{ angle.description }}</p>
          <p v-if="angle.tips" class="text-xs text-teal-500 mt-1">{{ t('shootingPlan.tip') }}: {{ angle.tips }}</p>
        </div>
      </div>
    </div>
  </div>
</template>
