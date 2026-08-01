<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import PageHeader from '@/components/PageHeader.vue'
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
  // Preserve unrelated query params; only the section key changes.
  const query = { ...route.query }
  if (section === 'faq') delete query.section
  else query.section = section
  void router.replace({ query })
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
  <div class="app-page-content space-y-4 md:space-y-6">
    <PageHeader
      :title="t('help.pageTitle')"
      :description="t('help.pageDesc')"
      :eyebrow="t('nav.sections.workspace')"
      icon="HelpCircle"
      tone="cyan"
      title-id="help-title"
    >
      <template #actions>
        <NeonButton variant="ghost" size="sm" class="min-h-11" :aria-label="t('common.close')" @click="router.push('/dashboard')">
          <AppIcon name="X" size="sm" variant="cyan" aria-hidden="true" />
          <span class="hidden sm:inline">{{ t('common.close') }}</span>
        </NeonButton>
      </template>
    </PageHeader>

    <div class="flex gap-2 overflow-x-auto rounded-2xl border border-slate-200/60 bg-white/80 px-3 shadow-sm backdrop-blur-sm dark:border-slate-700/60 dark:bg-slate-900/70" role="group" aria-labelledby="help-title">
        <button
          class="min-h-11 shrink-0 border-b-2 px-3 text-sm font-medium transition-colors"
          :class="activeSection === 'faq' ? 'border-cyan-500 text-cyan-700 dark:text-cyan-300' : 'border-transparent text-slate-400 hover:text-slate-600'"
          :aria-pressed="activeSection === 'faq'"
          @click="selectSection('faq')"
        >{{ t('help.faq') }}</button>
        <button
          class="min-h-11 shrink-0 border-b-2 px-3 text-sm font-medium transition-colors"
          :class="activeSection === 'feedback' ? 'border-cyan-500 text-cyan-700 dark:text-cyan-300' : 'border-transparent text-slate-400 hover:text-slate-600'"
          :aria-pressed="activeSection === 'feedback'"
          @click="selectSection('feedback')"
        >{{ t('help.feedback') }}</button>
    </div>

    <section v-if="activeSection === 'faq'" class="space-y-3" aria-labelledby="faq-title">
      <div class="flex items-center justify-between px-1">
        <!-- Kept for the section landmark only; the active tab already says
             "常见问题" visibly. -->
        <h2 id="faq-title" class="sr-only">{{ t('help.faqTitle') }}</h2>
        <button class="inline-flex min-h-11 items-center gap-1.5 rounded-lg px-3 text-sm text-violet-600 hover:bg-violet-50 dark:text-violet-300 dark:hover:bg-violet-950/40" @click="openShortcuts">
          <AppIcon name="Keyboard" size="sm" variant="purple" aria-hidden="true" />
          {{ t('help.openShortcuts') }}
        </button>
      </div>
      <details v-for="item in faqItems" :key="item.question" class="group rounded-xl border border-slate-200/60 bg-white/90 p-4 shadow-sm dark:border-slate-700/60 dark:bg-slate-900/75">
        <summary class="cursor-pointer list-none pr-6 text-sm font-medium text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/50">
          <span class="flex items-center justify-between gap-3">
            {{ t(item.question) }}
            <AppIcon name="ChevronDown" size="sm" variant="cyan" class="transition-transform group-open:rotate-180" aria-hidden="true" />
          </span>
        </summary>
        <p class="mt-3 text-sm leading-6 text-slate-500">{{ t(item.answer) }}</p>
      </details>
    </section>

    <section v-else class="rounded-2xl border border-slate-200/60 bg-white/90 p-5 shadow-sm md:p-7 dark:border-slate-700/60 dark:bg-slate-900/75" aria-labelledby="feedback-title">
      <h2 id="feedback-title" class="text-base font-semibold text-slate-700">{{ t('help.feedbackTitle') }}</h2>
      <p class="mt-1 text-sm text-slate-500">{{ t('help.feedbackDesc') }}</p>
      <textarea
        v-model="feedback"
        rows="6"
        class="mt-4 w-full resize-y rounded-xl border-2 border-slate-100 bg-slate-50/60 p-3 text-sm text-slate-700 outline-none transition focus:border-cyan-400/50 focus:bg-white dark:border-slate-600/50 dark:bg-slate-800/70 dark:focus:border-cyan-400/40 dark:focus:bg-slate-900"
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
