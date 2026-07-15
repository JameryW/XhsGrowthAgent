<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import { useShortcutsStore, useToastStore } from '@/stores'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const shortcutsStore = useShortcutsStore()
const toastStore = useToastStore()

const activeSection = computed(() => route.query.section === 'feedback' ? 'feedback' : 'faq')
const feedback = ref('')

const faqItems = [1, 2, 3, 4].map((id) => ({
  question: `help.faqItems.${id}.question`,
  answer: `help.faqItems.${id}.answer`,
}))

function selectSection(section: 'faq' | 'feedback') {
  router.replace({ query: section === 'faq' ? {} : { section } })
}

function openShortcuts() {
  shortcutsStore.showShortcutsPanel()
}

async function copyFeedbackTemplate() {
  const value = feedback.value.trim()
  if (!value) {
    toastStore.warning(t('help.feedbackRequired'))
    return
  }
  const template = `${t('help.feedbackTemplateTitle')}\n\n${value}`
  try {
    await navigator.clipboard.writeText(template)
    toastStore.success(t('help.feedbackCopied'))
  } catch {
    toastStore.error(t('help.feedbackCopyFailed'))
  }
}
</script>

<template>
  <div class="mx-auto max-w-4xl space-y-4 md:space-y-6">
    <header class="rounded-2xl border border-slate-200/60 bg-white/90 p-5 shadow-sm backdrop-blur-sm md:p-7">
      <div class="flex items-start justify-between gap-4">
        <div class="flex items-start gap-3">
          <div class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-400 to-violet-500 shadow-md">
            <AppIcon name="HelpCircle" size="md" variant="white" aria-hidden="true" />
          </div>
          <div>
            <h1 class="text-xl font-bold text-slate-800">{{ t('help.pageTitle') }}</h1>
            <p class="mt-1 text-sm text-slate-500">{{ t('help.pageDesc') }}</p>
          </div>
        </div>
        <NeonButton variant="ghost" size="sm" :aria-label="t('common.close')" @click="router.push('/dashboard')">
          <AppIcon name="X" size="sm" variant="cyan" aria-hidden="true" />
        </NeonButton>
      </div>

      <div class="mt-5 flex gap-2 overflow-x-auto border-b border-slate-100" role="tablist">
        <button
          class="min-h-11 shrink-0 border-b-2 px-3 text-sm font-medium transition-colors"
          :class="activeSection === 'faq' ? 'border-cyan-500 text-cyan-700' : 'border-transparent text-slate-400 hover:text-slate-600'"
          role="tab"
          :aria-selected="activeSection === 'faq'"
          @click="selectSection('faq')"
        >{{ t('help.faq') }}</button>
        <button
          class="min-h-11 shrink-0 border-b-2 px-3 text-sm font-medium transition-colors"
          :class="activeSection === 'feedback' ? 'border-cyan-500 text-cyan-700' : 'border-transparent text-slate-400 hover:text-slate-600'"
          role="tab"
          :aria-selected="activeSection === 'feedback'"
          @click="selectSection('feedback')"
        >{{ t('help.feedback') }}</button>
      </div>
    </header>

    <section v-if="activeSection === 'faq'" class="space-y-3" aria-labelledby="faq-title">
      <div class="flex items-center justify-between px-1">
        <h2 id="faq-title" class="text-base font-semibold text-slate-700">{{ t('help.faqTitle') }}</h2>
        <button class="inline-flex min-h-11 items-center gap-1.5 rounded-lg px-3 text-sm text-violet-600 hover:bg-violet-50" @click="openShortcuts">
          <AppIcon name="Keyboard" size="sm" variant="purple" aria-hidden="true" />
          {{ t('help.openShortcuts') }}
        </button>
      </div>
      <details v-for="item in faqItems" :key="item.question" class="group rounded-xl border border-slate-200/60 bg-white/90 p-4 shadow-sm">
        <summary class="cursor-pointer list-none pr-6 text-sm font-medium text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/50">
          <span class="flex items-center justify-between gap-3">
            {{ t(item.question) }}
            <AppIcon name="ChevronDown" size="sm" variant="cyan" class="transition-transform group-open:rotate-180" aria-hidden="true" />
          </span>
        </summary>
        <p class="mt-3 text-sm leading-6 text-slate-500">{{ t(item.answer) }}</p>
      </details>
    </section>

    <section v-else class="rounded-2xl border border-slate-200/60 bg-white/90 p-5 shadow-sm md:p-7" aria-labelledby="feedback-title">
      <h2 id="feedback-title" class="text-base font-semibold text-slate-700">{{ t('help.feedbackTitle') }}</h2>
      <p class="mt-1 text-sm text-slate-500">{{ t('help.feedbackDesc') }}</p>
      <textarea
        v-model="feedback"
        rows="6"
        class="mt-4 w-full resize-y rounded-xl border-2 border-slate-100 bg-slate-50/60 p-3 text-sm text-slate-700 outline-none transition focus:border-cyan-400/50 focus:bg-white"
        :placeholder="t('help.feedbackPlaceholder')"
        :aria-label="t('help.feedbackLabel')"
      />
      <div class="mt-4 flex flex-wrap items-center justify-between gap-3">
        <span class="text-xs text-slate-400">{{ t('help.feedbackHint') }}</span>
        <NeonButton variant="cyan" size="sm" @click="copyFeedbackTemplate">
          <AppIcon name="Copy" size="sm" variant="white" aria-hidden="true" />
          {{ t('help.copyFeedback') }}
        </NeonButton>
      </div>
    </section>
  </div>
</template>
