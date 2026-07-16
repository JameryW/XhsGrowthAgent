<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import CreatorQualityPanel from '@/components/settings/CreatorQualityPanel.vue'
import CreatorNoteQualityPanel from '@/components/settings/CreatorNoteQualityPanel.vue'
import { useAccountsStore } from '@/stores/accounts'

const { t } = useI18n()
const router = useRouter()
const accountsStore = useAccountsStore()

const selectedAccountId = ref('')
const hasUserSelectedAccount = ref(false)
const selectedAccount = computed(() =>
  accountsStore.accounts.find((account) => account.id === selectedAccountId.value)
)
const hasAccounts = computed(() => accountsStore.accounts.length > 0)

function selectDefaultAccount() {
  const selectedStillExists = accountsStore.accounts.some(
    (account) => account.id === selectedAccountId.value
  )
  if (hasUserSelectedAccount.value && selectedStillExists) return
  const activeAccountExists = accountsStore.accounts.some(
    (account) => account.id === accountsStore.activeAccountId
  )
  selectedAccountId.value = activeAccountExists
    ? accountsStore.activeAccountId!
    : accountsStore.accounts[0]?.id || ''
}

async function refreshAccounts() {
  await accountsStore.fetchAccounts()
  selectDefaultAccount()
}

function openSettings() {
  void router.push('/settings')
}

watch(
  () => [accountsStore.activeAccountId, accountsStore.accounts] as const,
  selectDefaultAccount,
  { immediate: true }
)

onMounted(() => {
  void refreshAccounts()
})
</script>

<template>
  <section class="space-y-4 md:space-y-6" :aria-label="t('creatorQuality.title')">
    <header
      class="relative overflow-hidden rounded-2xl border border-cyan-100/80 bg-gradient-to-br from-cyan-50 via-white to-violet-50 p-4 shadow-sm md:p-6 dark:border-cyan-500/25 dark:from-slate-900/95 dark:via-slate-900/90 dark:to-violet-950/40"
    >
      <div class="pointer-events-none absolute -right-14 -top-16 h-48 w-48 rounded-full bg-cyan-200/35 blur-3xl dark:bg-cyan-500/15" />
      <div class="pointer-events-none absolute -bottom-20 left-1/3 h-40 w-40 rounded-full bg-violet-200/30 blur-3xl dark:bg-violet-500/15" />

      <div class="relative flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div class="min-w-0 max-w-2xl">
          <div class="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-700 dark:text-cyan-300">
            <span class="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-500 to-blue-600 shadow-sm">
              <AppIcon name="Brain" size="sm" variant="white" />
            </span>
            {{ t('creatorQuality.page.eyebrow') }}
          </div>
          <h2 class="mt-3 text-xl font-semibold tracking-tight text-slate-800 md:text-2xl">
            {{ t('creatorQuality.title') }}
          </h2>
          <p class="mt-2 max-w-xl text-sm leading-6 text-slate-500">
            {{ t('creatorQuality.page.description') }}
          </p>
        </div>

        <div v-if="hasAccounts" class="flex w-full flex-col gap-2 sm:flex-row lg:w-auto">
          <label class="min-w-0 flex-1 lg:w-64">
            <span class="mb-1.5 block text-xs font-semibold text-slate-500">
              {{ t('creatorQuality.page.accountLabel') }}
            </span>
            <span class="relative block">
              <select
                v-model="selectedAccountId"
                class="w-full appearance-none rounded-xl border border-slate-200 bg-white/90 py-2.5 pl-3 pr-9 text-sm font-medium text-slate-700 shadow-sm outline-none transition focus:border-cyan-400 focus:ring-4 focus:ring-cyan-100 dark:border-slate-600/60 dark:bg-slate-900/80 dark:text-slate-200 dark:focus:border-cyan-400/50 dark:focus:ring-cyan-900/40"
                :aria-label="t('creatorQuality.page.accountLabel')"
                @change="hasUserSelectedAccount = true"
              >
                <option v-for="account in accountsStore.accounts" :key="account.id" :value="account.id">
                  {{ account.name }}{{ account.is_active ? ` (${t('settings.active')})` : '' }}
                </option>
              </select>
              <AppIcon
                name="ChevronDown"
                size="sm"
                variant="cyan"
                class="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2"
              />
            </span>
          </label>
          <button
            type="button"
            class="inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-white/80 px-3 py-2.5 text-xs font-semibold text-slate-600 shadow-sm transition hover:border-violet-200 hover:bg-violet-50 hover:text-violet-700 disabled:cursor-not-allowed disabled:opacity-60 sm:self-end dark:border-slate-600/60 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:border-violet-400/40 dark:hover:bg-violet-950/35 dark:hover:text-violet-200"
            :disabled="accountsStore.isLoading"
            :aria-label="t('creatorQuality.page.refreshAccounts')"
            :title="t('creatorQuality.page.refreshAccounts')"
            @click="refreshAccounts"
          >
            <AppIcon name="RefreshCw" size="xs" variant="cyan" :animate="accountsStore.isLoading" />
            <span>{{ t('creatorQuality.page.refresh') }}</span>
          </button>
        </div>
      </div>
    </header>

    <CreatorQualityPanel
      v-if="selectedAccount"
      :account-id="selectedAccount.id"
      :account-name="selectedAccount.name"
      class="shadow-sm"
    />

    <CreatorNoteQualityPanel
      v-if="selectedAccount"
      :account-id="selectedAccount.id"
      :account-name="selectedAccount.name"
      class="shadow-sm"
    />

    <section
      v-else
      class="rounded-2xl border border-dashed border-slate-300 bg-white/70 px-5 py-10 text-center shadow-sm md:px-8 dark:border-slate-600 dark:bg-slate-900/60"
    >
      <div class="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 dark:bg-slate-800">
        <AppIcon name="Database" size="lg" variant="cyan" />
      </div>
      <h3 class="mt-4 text-base font-semibold text-slate-700">
        {{ t('creatorQuality.page.noAccountTitle') }}
      </h3>
      <p class="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">
        {{ t('creatorQuality.page.noAccountDescription') }}
      </p>
      <button
        type="button"
        class="mt-5 inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-rose-500 to-amber-500 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:shadow-md"
        @click="openSettings"
      >
        <AppIcon name="Settings" size="sm" variant="white" />
        {{ t('creatorQuality.page.manageAccounts') }}
      </button>
    </section>

    <div class="flex flex-col gap-3 rounded-xl border border-violet-100 bg-violet-50/60 p-3 text-xs text-violet-800 sm:flex-row sm:items-center sm:justify-between sm:p-4 dark:border-violet-500/30 dark:bg-violet-950/40 dark:text-violet-200">
      <div class="flex min-w-0 items-start gap-2">
        <AppIcon name="HelpCircle" size="sm" variant="purple" class="mt-0.5 shrink-0" />
        <p class="leading-5">{{ t('creatorQuality.page.importHint') }}</p>
      </div>
      <button
        type="button"
        class="inline-flex shrink-0 items-center gap-1.5 font-semibold text-violet-700 transition hover:text-violet-900"
        @click="openSettings"
      >
        {{ t('creatorQuality.page.manageData') }}
        <AppIcon name="ArrowRight" size="xs" variant="purple" />
      </button>
    </div>
  </section>
</template>
