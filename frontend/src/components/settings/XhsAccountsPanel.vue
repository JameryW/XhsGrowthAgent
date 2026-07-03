<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAccountsStore } from '@/stores/accounts'
import { useToastStore } from '@/stores/toast'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import QrLoginModal from './QrLoginModal.vue'

const { t } = useI18n()
const store = useAccountsStore()
const toast = useToastStore()

// XHS account credentials are restricted to these two keys.
// All other keys live in the System Config layer.
const XHS_KEYS = ['XHS_COOKIE', 'XHS_USER_ID']

const newAccountName = ref('')
const isCreating = ref(false)
const editingAccountId = ref<string | null>(null)
const credEdits = ref<Record<string, string>>({})
const isSavingCreds = ref(false)

// ── Scan-login (QR) modal state ──
const qrLoginOpen = ref(false)
const qrLoginAccountId = ref<string>('')
const qrLoginAccountName = ref<string>('')

const qrLoginAccount = computed(() =>
  store.accounts.find(a => a.id === qrLoginAccountId.value)
)

const editingAccount = computed(() =>
  store.accounts.find(a => a.id === editingAccountId.value)
)

watch(editingAccountId, async (id) => {
  if (id) {
    await store.fetchCredentials(id)
    credEdits.value = {}
  } else {
    store.credentials = []
    credEdits.value = {}
  }
})

onMounted(async () => {
  await store.fetchAccounts()
  if (store.activeAccountId) {
    editingAccountId.value = store.activeAccountId
  }
})

async function createAccount() {
  if (!newAccountName.value.trim()) return
  isCreating.value = true
  try {
    const account = await store.createAccount(newAccountName.value.trim())
    newAccountName.value = ''
    toast.success(t('settings.toasts.accountCreated', { name: account.name }))
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
    if (editingAccountId.value === accountId) editingAccountId.value = null
    toast.success(t('settings.toasts.accountDeleted', { name }))
  } catch (e: any) {
    toast.error(e.message)
  }
}

async function saveCredentials() {
  if (!editingAccountId.value) return
  const toSave: Record<string, string> = {}
  for (const [k, v] of Object.entries(credEdits.value)) {
    if (v !== undefined) toSave[k] = v
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
  if (credEdits.value[keyName] !== undefined) {
    const v = credEdits.value[keyName]
    return v ? '●●●●' + v.slice(-4) : t('settings.willDelete')
  }
  return store.credentials.find(c => c.key_name === keyName)?.masked_value || t('settings.notSet')
}

function isCredSet(keyName: string): boolean {
  if (credEdits.value[keyName] !== undefined) return !!credEdits.value[keyName]
  return store.credentials.find(c => c.key_name === keyName)?.is_set ?? false
}

function startEditCred(keyName: string) { credEdits.value[keyName] = '' }
function cancelEditCred(keyName: string) { delete credEdits.value[keyName] }

function openQrLogin(accountId: string, accountName: string) {
  qrLoginAccountId.value = accountId
  qrLoginAccountName.value = accountName
  qrLoginOpen.value = true
}

function closeQrLogin() {
  qrLoginOpen.value = false
}

function onQrConfirmed() {
  toast.success(t('settings.toasts.qrLoginSuccess', { name: qrLoginAccountName.value }))
  qrLoginOpen.value = false
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h2 class="text-lg font-semibold text-slate-800">{{ t('settings.xhsAccounts.title') }}</h2>
      <p class="text-xs text-slate-400 mt-0.5">{{ t('settings.xhsAccounts.subtitle') }}</p>
    </div>

    <!-- Account list + creation -->
    <div class="rounded-xl border border-slate-200/50 bg-white/90 backdrop-blur-sm p-4 space-y-3">
      <div class="flex items-center justify-between">
        <h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wider">{{ t('settings.accounts') }}</h3>
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

      <div v-if="store.accounts.length === 0" class="text-center py-8 text-slate-400 text-sm">
        {{ t('settings.noAccounts') }}
      </div>

      <div v-for="account in store.accounts" :key="account.id"
        class="rounded-lg border p-3 flex items-center gap-3 transition-all cursor-pointer"
        :class="editingAccountId === account.id
          ? 'border-rose-200 bg-rose-50/50 shadow-sm'
          : 'border-slate-100 hover:border-slate-200 hover:bg-slate-50/50'"
        @click="editingAccountId = account.id"
      >
        <div class="w-2 h-2 rounded-full shrink-0" :class="account.is_active ? 'bg-emerald-500' : 'bg-slate-300'" />
        <span class="flex-1 text-sm font-medium" :class="account.is_active ? 'text-slate-800' : 'text-slate-500'">
          {{ account.name }}
        </span>
        <span v-if="account.is_active"
          class="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-600 font-medium"
        >
          {{ t('settings.active') }}
        </span>
        <div class="flex items-center gap-1" @click.stop>
          <button @click="openQrLogin(account.id, account.name)"
            class="text-xs text-rose-500 hover:text-rose-600 px-2 py-1 rounded hover:bg-rose-50 transition-colors flex items-center gap-1"
            :title="t('settings.xhsAccounts.qrLogin')"
          >
            <AppIcon name="LogIn" size="xs" variant="pink" />
            <span>{{ t('settings.xhsAccounts.qrLogin') }}</span>
          </button>
          <button v-if="!account.is_active" @click="activateAccount(account.id)"
            class="text-xs text-teal-600 hover:text-teal-700 px-2 py-1 rounded hover:bg-teal-50 transition-colors"
          >
            {{ t('settings.activate') }}
          </button>
          <button @click="removeAccount(account.id, account.name)"
            class="text-xs text-rose-400 hover:text-rose-500 px-1 py-1 rounded hover:bg-rose-50 transition-colors"
          >
            <AppIcon name="Trash2" size="xs" variant="pink" />
          </button>
        </div>
      </div>
    </div>

    <!-- XHS credentials for selected account -->
    <div v-if="editingAccount" class="rounded-xl border border-slate-200/50 bg-white/90 backdrop-blur-sm p-4 space-y-3">
      <div class="flex items-center justify-between">
        <h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wider">
          {{ t('settings.credentialsFor') }} — {{ editingAccount.name }}
        </h3>
        <NeonButton
          v-if="Object.keys(credEdits).length > 0"
          variant="cyan" size="sm"
          :loading="isSavingCreds"
          @click="saveCredentials"
        >
          <AppIcon name="Save" size="xs" variant="white" />
          <span class="ml-1">{{ t('settings.saveCredentials') }}</span>
        </NeonButton>
      </div>

      <div class="space-y-1">
        <div v-for="keyName in XHS_KEYS" :key="keyName"
          class="flex items-center gap-3 py-2 px-3 rounded-lg hover:bg-slate-50/80 transition-colors"
        >
          <span class="text-xs font-mono text-slate-500 w-44 shrink-0">{{ keyName }}</span>

          <div class="flex-1 min-w-0">
            <input
              v-if="credEdits[keyName] !== undefined"
              v-model="credEdits[keyName]"
              type="password"
              :placeholder="t('settings.enterValue')"
              class="w-full px-2 py-1 text-sm rounded border border-rose-200 bg-white focus:border-rose-400 outline-none"
              @keydown.escape="cancelEditCred(keyName)"
            />
            <span v-else class="text-sm" :class="isCredSet(keyName) ? 'text-slate-600' : 'text-slate-300'">
              {{ getCredDisplay(keyName) }}
            </span>
          </div>

          <div class="w-2 h-2 rounded-full shrink-0" :class="isCredSet(keyName) ? 'bg-emerald-500' : 'bg-slate-200'" />

          <div class="flex items-center gap-1 shrink-0">
            <template v-if="credEdits[keyName] !== undefined">
              <button @click="cancelEditCred(keyName)"
                class="p-1 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
              >
                <AppIcon name="X" size="xs" variant="pink" />
              </button>
            </template>
            <template v-else>
              <button @click="startEditCred(keyName)"
                class="p-1 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
                :title="t('settings.edit')"
              >
                <AppIcon name="Pencil" size="xs" variant="cyan" />
              </button>
              <button v-if="isCredSet(keyName)" @click="deleteCred(keyName)"
                class="p-1 rounded hover:bg-rose-50 text-slate-400 hover:text-rose-500 transition-colors"
                :title="t('settings.delete')"
              >
                <AppIcon name="Trash2" size="xs" variant="pink" />
              </button>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- Scan-login (QR) modal -->
    <QrLoginModal
      v-if="qrLoginOpen && qrLoginAccount"
      :account-id="qrLoginAccountId"
      :account-name="qrLoginAccountName"
      :is-open="qrLoginOpen"
      @close="closeQrLogin"
      @confirmed="onQrConfirmed"
    />
  </div>
</template>
