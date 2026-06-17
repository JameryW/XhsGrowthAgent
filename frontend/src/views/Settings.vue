<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAccountsStore } from '@/stores/accounts'
import { useToastStore } from '@/stores/toast'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'

const { t } = useI18n()
const store = useAccountsStore()
const toast = useToastStore()

// ── Account form ──
const newAccountName = ref('')
const isCreating = ref(false)

// ── Credential editing ──
const editingAccountId = ref<string | null>(null)
const credEdits = ref<Record<string, string>>({})
const isSavingCreds = ref(false)

// ── Credential key groups ──
const CRED_GROUPS = [
  { labelKey: 'settings.groups.llmProviders', keys: ['ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'DEEPSEEK_API_KEY', 'DASHSCOPE_API_KEY', 'XIAOMIMIMO_API_KEY'] },
  { labelKey: 'settings.groups.xhsPlatform', keys: ['XHS_COOKIE', 'XHS_USER_ID'] },
  { labelKey: 'settings.groups.rippleCas', keys: ['RIPPLE_BASE_URL', 'RIPPLE_API_TOKEN', 'RIPPLE_ENABLED', 'RIPPLE_LLM_MODEL_PLATFORM', 'RIPPLE_LLM_MODEL_NAME', 'RIPPLE_LLM_API_KEY', 'RIPPLE_LLM_URL'] },
  { labelKey: 'settings.groups.searchEmbedding', keys: ['TAVILY_API_KEY', 'XHS_EMBED_MODEL', 'XHS_EMBED_BASE_URL'] },
]

const editingAccount = computed(() =>
  store.accounts.find(a => a.id === editingAccountId.value)
)


// When selecting an account, load its credentials
watch(editingAccountId, async (id) => {
  if (id) {
    await store.fetchCredentials(id)
    credEdits.value = {}
  } else {
    store.credentials = []
    credEdits.value = {}
  }
})

onMounted(() => {
  store.fetchAccounts()
})

async function createAccount() {
  if (!newAccountName.value.trim()) return
  isCreating.value = true
  try {
    const account = await store.createAccount(newAccountName.value.trim())
    newAccountName.value = ''
    toast.success(t('settings.toasts.accountCreated', { name: account.name }))
    // Auto-select the new account
    editingAccountId.value = account.id
  } catch (e: any) {
    toast.error(e.message)
  } finally {
    isCreating.value = false
  }
}

async function activateAccount(accountId: string) {
  try {
    await store.setActiveAccount(accountId)
    toast.success(t('settings.toasts.activeSwitched'))
  } catch (e: any) {
    toast.error(e.message)
  }
}

async function removeAccount(accountId: string, name: string) {
  if (!confirm(t('settings.confirm.delete', { name }))) return
  try {
    await store.removeAccount(accountId)
    if (editingAccountId.value === accountId) {
      editingAccountId.value = null
    }
    toast.success(t('settings.toasts.accountDeleted', { name }))
  } catch (e: any) {
    toast.error(e.message)
  }
}

async function saveCredentials() {
  if (!editingAccountId.value) return
  // Only send keys that were edited and have a value
  const toSave: Record<string, string> = {}
  for (const [key, val] of Object.entries(credEdits.value)) {
    if (val !== undefined) {
      toSave[key] = val
    }
  }
  if (Object.keys(toSave).length === 0) return

  isSavingCreds.value = true
  try {
    await store.saveCredentials(editingAccountId.value, toSave)
    credEdits.value = {}
    toast.success(t('settings.toasts.credsSaved'))
  } catch (e: any) {
    toast.error(e.message)
  } finally {
    isSavingCreds.value = false
  }
}

async function deleteCred(keyName: string) {
  if (!editingAccountId.value) return
  try {
    await store.removeCredential(editingAccountId.value, keyName)
    toast.success(t('settings.toasts.credDeleted', { key: keyName }))
  } catch (e: any) {
    toast.error(e.message)
  }
}

function getCredDisplay(keyName: string): string {
  // If user is editing this key, show the edit value
  if (credEdits.value[keyName] !== undefined) {
    const val = credEdits.value[keyName]
    return val ? '●●●●' + val.slice(-4) : t('settings.willDelete')
  }
  // Otherwise show from DB
  const cred = store.credentials.find(c => c.key_name === keyName)
  return cred?.masked_value || t('settings.notSet')
}

function isCredSet(keyName: string): boolean {
  if (credEdits.value[keyName] !== undefined) {
    return !!credEdits.value[keyName]
  }
  const cred = store.credentials.find(c => c.key_name === keyName)
  return cred?.is_set ?? false
}

function startEditCred(keyName: string) {
  // Initialize with empty string (new value) — user types the new secret
  credEdits.value[keyName] = ''
}

function cancelEditCred(keyName: string) {
  delete credEdits.value[keyName]
}
</script>

<template>
  <div class="max-w-4xl mx-auto space-y-6">
    <!-- Header -->
    <div class="flex items-center gap-3 mb-2">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-slate-700 to-slate-600 flex items-center justify-center shadow-md">
        <AppIcon name="Settings" size="md" variant="white" />
      </div>
      <div>
        <h1 class="text-xl font-bold text-slate-800">{{ t('settings.title') }}</h1>
        <p class="text-xs text-slate-400">{{ t('settings.subtitle') }}</p>
      </div>
    </div>

    <!-- Account List -->
    <div class="rounded-xl border border-slate-200/50 bg-white/90 backdrop-blur-sm p-4 space-y-3">
      <div class="flex items-center justify-between">
        <h2 class="text-sm font-semibold text-slate-700">{{ t('settings.accounts') }}</h2>
        <!-- Create new account -->
        <form @submit.prevent="createAccount" class="flex items-center gap-2">
          <input
            v-model="newAccountName"
            type="text"
            :placeholder="t('settings.accountNamePlaceholder')"
            class="px-3 py-1.5 text-sm rounded-lg border border-slate-200 bg-white focus:border-rose-400 focus:ring-2 focus:ring-rose-400/20 outline-none w-40"
          />
          <NeonButton variant="pink" size="sm" :loading="isCreating" type="submit">
            <AppIcon name="Plus" size="xs" variant="white" />
            <span class="ml-1">{{ t('settings.addAccount') }}</span>
          </NeonButton>
        </form>
      </div>

      <!-- Empty state -->
      <div v-if="store.accounts.length === 0" class="text-center py-8 text-slate-400 text-sm">
        {{ t('settings.noAccounts') }}
      </div>

      <!-- Account cards -->
      <div v-for="account in store.accounts" :key="account.id"
        class="rounded-lg border p-3 flex items-center gap-3 transition-all cursor-pointer"
        :class="editingAccountId === account.id
          ? 'border-rose-200 bg-rose-50/50 shadow-sm'
          : 'border-slate-100 hover:border-slate-200 hover:bg-slate-50/50'"
        @click="editingAccountId = account.id"
      >
        <!-- Active indicator -->
        <div class="w-2 h-2 rounded-full shrink-0" :class="account.is_active ? 'bg-emerald-500' : 'bg-slate-300'" />
        <!-- Name -->
        <span class="flex-1 text-sm font-medium" :class="account.is_active ? 'text-slate-800' : 'text-slate-500'">
          {{ account.name }}
        </span>
        <!-- Active badge -->
        <span v-if="account.is_active" class="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-600 font-medium">
          {{ t('settings.active') }}
        </span>
        <!-- Actions -->
        <div class="flex items-center gap-1" @click.stop>
          <button
            v-if="!account.is_active"
            @click="activateAccount(account.id)"
            class="text-xs text-teal-600 hover:text-teal-700 px-2 py-1 rounded hover:bg-teal-50 transition-colors"
          >
            {{ t('settings.activate') }}
          </button>
          <button
            @click="removeAccount(account.id, account.name)"
            class="text-xs text-rose-400 hover:text-rose-500 px-1 py-1 rounded hover:bg-rose-50 transition-colors"
          >
            <AppIcon name="Trash2" size="xs" variant="pink" />
          </button>
        </div>
      </div>
    </div>

    <!-- Credentials Panel (shown when account is selected) -->
    <div v-if="editingAccount" class="rounded-xl border border-slate-200/50 bg-white/90 backdrop-blur-sm p-4 space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="text-sm font-semibold text-slate-700">
          {{ t('settings.credentialsFor') }} — {{ editingAccount.name }}
        </h2>
        <NeonButton
          v-if="Object.keys(credEdits).length > 0"
          variant="cyan"
          size="sm"
          :loading="isSavingCreds"
          @click="saveCredentials"
        >
          <AppIcon name="Save" size="xs" variant="white" />
          <span class="ml-1">{{ t('settings.saveCredentials') }}</span>
        </NeonButton>
      </div>

      <!-- Credential groups -->
      <div v-for="group in CRED_GROUPS" :key="group.labelKey" class="space-y-2">
        <h3 class="text-xs font-medium text-slate-400 uppercase tracking-wider">{{ t(group.labelKey) }}</h3>
        <div class="space-y-1.5">
          <div v-for="keyName in group.keys" :key="keyName"
            class="flex items-center gap-3 py-2 px-3 rounded-lg hover:bg-slate-50/80 transition-colors"
          >
            <!-- Key label -->
            <span class="text-xs font-mono text-slate-500 w-44 shrink-0">{{ keyName }}</span>

            <!-- Current value / edit field -->
            <div class="flex-1 min-w-0">
              <!-- Editing mode -->
              <input
                v-if="credEdits[keyName] !== undefined"
                v-model="credEdits[keyName]"
                type="password"
                :placeholder="t('settings.enterValue')"
                class="w-full px-2 py-1 text-sm rounded border border-rose-200 bg-white focus:border-rose-400 outline-none"
                @keydown.escape="cancelEditCred(keyName)"
              />
              <!-- Display mode -->
              <span v-else class="text-sm" :class="isCredSet(keyName) ? 'text-slate-600' : 'text-slate-300'">
                {{ getCredDisplay(keyName) }}
              </span>
            </div>

            <!-- Status dot -->
            <div class="w-2 h-2 rounded-full shrink-0" :class="isCredSet(keyName) ? 'bg-emerald-500' : 'bg-slate-200'" />

            <!-- Actions -->
            <div class="flex items-center gap-1 shrink-0">
              <template v-if="credEdits[keyName] !== undefined">
                <button @click="cancelEditCred(keyName)" class="p-1 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors">
                  <AppIcon name="X" size="xs" variant="pink" />
                </button>
              </template>
              <template v-else>
                <button @click="startEditCred(keyName)" class="p-1 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors" :title="t('settings.edit')">
                  <AppIcon name="Pencil" size="xs" variant="cyan" />
                </button>
                <button v-if="isCredSet(keyName)" @click="deleteCred(keyName)" class="p-1 rounded hover:bg-rose-50 text-slate-400 hover:text-rose-500 transition-colors" :title="t('settings.delete')">
                  <AppIcon name="Trash2" size="xs" variant="pink" />
                </button>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
