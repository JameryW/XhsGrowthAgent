<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import PageHeader from '@/components/PageHeader.vue'
import ConsoleUsersPanel from '@/components/settings/ConsoleUsersPanel.vue'
import XhsAccountsPanel from '@/components/settings/XhsAccountsPanel.vue'
import SystemConfigPanel from '@/components/settings/SystemConfigPanel.vue'
import PublicUxTelemetryPanel from '@/components/settings/PublicUxTelemetryPanel.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

type TabId = 'console-users' | 'xhs-accounts' | 'system-config' | 'public-ux-telemetry'

const TABS: { id: TabId; labelKey: string; icon: string; descKey: string }[] = [
  { id: 'console-users', labelKey: 'settings.nav.consoleUsers', icon: 'User', descKey: 'settings.nav.consoleUsersDesc' },
  { id: 'xhs-accounts', labelKey: 'settings.nav.xhsAccounts', icon: 'Users', descKey: 'settings.nav.xhsAccountsDesc' },
  { id: 'system-config', labelKey: 'settings.nav.systemConfig', icon: 'Settings', descKey: 'settings.nav.systemConfigDesc' },
  { id: 'public-ux-telemetry', labelKey: 'settings.nav.publicUxTelemetry', icon: 'BarChart3', descKey: 'settings.nav.publicUxTelemetryDesc' },
]

const activeTab = ref<TabId>('xhs-accounts')

function syncFromRoute() {
  const q = route.query.tab
  if (typeof q === 'string' && TABS.some(t => t.id === q)) {
    activeTab.value = q as TabId
  }
}

onMounted(syncFromRoute)
watch(() => route.query.tab, syncFromRoute)

function selectTab(id: TabId) {
  activeTab.value = id
  router.replace({ query: { ...route.query, tab: id } })
}

const currentTab = computed(() => TABS.find(t => t.id === activeTab.value)!)
</script>

<template>
  <div class="app-page-content space-y-4 md:space-y-6">
    <PageHeader
      :title="t('settings.title')"
      :description="t('settings.subtitle')"
      :eyebrow="t('nav.systemInfo')"
      icon="Settings"
      tone="slate"
    />

    <!-- Two-column layout: sidebar nav + content -->
    <div class="flex flex-col gap-4 sm:flex-row sm:gap-6">
      <!-- Sidebar -->
      <aside class="w-full shrink-0 sm:w-56">
        <nav class="flex gap-1 overflow-x-auto rounded-xl border border-slate-200/50 bg-white/90 p-2 backdrop-blur-sm dark:bg-slate-900/90 dark:border-slate-700/55 sm:sticky sm:top-4 sm:block sm:space-y-1">
          <button
            v-for="tab in TABS"
            :key="tab.id"
            @click="selectTab(tab.id)"
            class="min-h-11 min-w-[142px] flex-1 text-left px-3 py-2.5 rounded-lg transition-all flex items-start gap-2.5 group sm:w-full sm:min-w-0 sm:flex-none"
            :class="activeTab === tab.id
              ? 'bg-gradient-to-r from-rose-50 to-pink-50 border border-rose-200/60 shadow-sm dark:from-rose-950/50 dark:to-pink-950/40 dark:border-rose-500/30'
              : 'border border-transparent hover:bg-slate-50/80 dark:hover:bg-slate-800/60'"
          >
            <div
              class="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 transition-colors"
              :class="activeTab === tab.id
                ? 'bg-gradient-to-br from-rose-400 to-pink-400'
                : 'bg-slate-100 group-hover:bg-slate-200 dark:bg-slate-800 dark:group-hover:bg-slate-700'"
            >
              <AppIcon :name="tab.icon" size="xs" :variant="activeTab === tab.id ? 'white' : 'pink'" />
            </div>
            <div class="flex-1 min-w-0">
              <div class="text-sm font-medium" :class="activeTab === tab.id ? 'text-rose-700' : 'text-slate-700'">
                {{ t(tab.labelKey) }}
              </div>
              <div class="hidden text-[10px] mt-0.5 leading-tight sm:block" :class="activeTab === tab.id ? 'text-rose-500/80' : 'text-slate-400'">
                {{ t(tab.descKey) }}
              </div>
            </div>
          </button>
        </nav>
      </aside>

      <!-- Content -->
      <main class="flex-1 min-w-0">
        <ConsoleUsersPanel v-if="currentTab.id === 'console-users'" />
        <XhsAccountsPanel v-else-if="currentTab.id === 'xhs-accounts'" />
        <SystemConfigPanel v-else-if="currentTab.id === 'system-config'" />
        <PublicUxTelemetryPanel v-else />
      </main>
    </div>
  </div>
</template>
