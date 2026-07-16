<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useConsoleUsersStore } from '@/stores/console_users'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'

const { t, locale } = useI18n()
const store = useConsoleUsersStore()
const authStore = useAuthStore()
const toast = useToastStore()

const newUsername = ref('')
const newPassword = ref('')
const isCreating = ref(false)

const editingPasswordFor = ref<string | null>(null)
const newPasswordValue = ref('')
const isChangingPwd = ref(false)
const showDeleteModal = ref(false)
const deleteTarget = ref<{ id: string; username: string } | null>(null)

onMounted(async () => {
  await store.fetchUsers()
})

async function createUser() {
  const u = newUsername.value.trim()
  const p = newPassword.value
  if (!u || p.length < 6) {
    toast.error(t('settings.consoleUsers.validation'))
    return
  }
  isCreating.value = true
  try {
    await store.createUser(u, p)
    newUsername.value = ''
    newPassword.value = ''
    toast.success(t('settings.consoleUsers.toastCreated', { name: u }))
  } catch (e: any) {
    toast.error(e.message)
  } finally {
    isCreating.value = false
  }
}

function requestDeleteUser(userId: string, username: string) {
  deleteTarget.value = { id: userId, username }
  showDeleteModal.value = true
}

async function confirmDeleteUser() {
  if (!deleteTarget.value) return
  const { id: userId, username } = deleteTarget.value
  try {
    await store.removeUser(userId)
    toast.success(t('settings.consoleUsers.toastDeleted', { name: username }))
    showDeleteModal.value = false
    deleteTarget.value = null
  } catch (e: any) {
    toast.error(e.message)
  }
}

function startChangePassword(userId: string) {
  editingPasswordFor.value = userId
  newPasswordValue.value = ''
}

function cancelChangePassword() {
  editingPasswordFor.value = null
  newPasswordValue.value = ''
}

async function submitChangePassword() {
  if (!editingPasswordFor.value || newPasswordValue.value.length < 6) {
    toast.error(t('settings.consoleUsers.validation'))
    return
  }
  isChangingPwd.value = true
  try {
    await store.changePassword(editingPasswordFor.value, newPasswordValue.value)
    editingPasswordFor.value = null
    newPasswordValue.value = ''
    toast.success(t('settings.consoleUsers.toastPwdChanged'))
  } catch (e: any) {
    toast.error(e.message)
  } finally {
    isChangingPwd.value = false
  }
}

function formatDate(iso: string | null): string {
  if (!iso) return t('settings.consoleUsers.never')
  return new Date(iso).toLocaleString(locale.value || undefined, {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h2 class="text-lg font-semibold text-slate-800">{{ t('settings.consoleUsers.title') }}</h2>
      <p class="text-xs text-slate-400 mt-0.5">{{ t('settings.consoleUsers.subtitle') }}</p>
    </div>

    <!-- Create user -->
    <div class="rounded-xl border border-slate-200/50 bg-white/90 backdrop-blur-sm p-4 dark:bg-slate-900/90 dark:border-slate-700/55">
      <h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
        {{ t('settings.consoleUsers.addUser') }}
      </h3>
      <form @submit.prevent="createUser" class="flex items-center gap-2">
        <input
          v-model="newUsername"
          type="text"
          :placeholder="t('settings.consoleUsers.usernamePlaceholder')"
          class="flex-1 px-3 py-1.5 text-sm rounded-lg border border-slate-200 bg-white focus:border-rose-400 focus:ring-2 focus:ring-rose-400/20 outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200"
        />
        <input
          v-model="newPassword"
          type="password"
          :placeholder="t('settings.consoleUsers.passwordPlaceholder')"
          class="flex-1 px-3 py-1.5 text-sm rounded-lg border border-slate-200 bg-white focus:border-rose-400 focus:ring-2 focus:ring-rose-400/20 outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200"
        />
        <NeonButton variant="pink" size="sm" :loading="isCreating" type="submit">
          <AppIcon name="Plus" size="xs" variant="white" />
          <span class="ml-1">{{ t('settings.consoleUsers.create') }}</span>
        </NeonButton>
      </form>
    </div>

    <!-- User list -->
    <div class="rounded-xl border border-slate-200/50 bg-white/90 backdrop-blur-sm dark:bg-slate-900/90 dark:border-slate-700/55">
      <div class="px-4 py-3 border-b border-slate-100">
        <h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wider">
          {{ t('settings.consoleUsers.allUsers') }} ({{ store.users.length }})
        </h3>
      </div>
      <div v-if="store.users.length === 0" class="text-center py-8 text-slate-400 text-sm">
        {{ t('settings.consoleUsers.empty') }}
      </div>
      <div v-for="user in store.users" :key="user.id"
        class="px-4 py-3 border-b border-slate-50 last:border-b-0 flex items-center gap-3"
      >
        <div class="w-8 h-8 rounded-full bg-gradient-to-br from-rose-100 to-pink-100 flex items-center justify-center shrink-0">
          <AppIcon name="User" size="xs" variant="pink" />
        </div>

        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2">
            <span class="text-sm font-medium text-slate-800 truncate">{{ user.username }}</span>
            <span v-if="user.id === authStore.user?.id"
              class="text-[10px] px-1.5 py-0.5 rounded-full bg-rose-100 text-rose-600 font-medium"
            >
              {{ t('settings.consoleUsers.you') }}
            </span>
          </div>
          <div class="text-xs text-slate-400 mt-0.5">
            {{ t('settings.consoleUsers.lastLogin') }}: {{ formatDate(user.last_login_at) }}
          </div>
        </div>

        <!-- Inline password change -->
        <template v-if="editingPasswordFor === user.id">
          <input
            v-model="newPasswordValue"
            type="password"
            :placeholder="t('settings.consoleUsers.newPasswordPlaceholder')"
            class="w-44 px-2 py-1 text-sm rounded border border-rose-200 bg-white focus:border-rose-400 outline-none dark:border-rose-500/40 dark:bg-slate-900 dark:text-slate-200"
            @keydown.escape="cancelChangePassword"
          />
          <NeonButton variant="cyan" size="sm" :loading="isChangingPwd" @click="submitChangePassword">
            <AppIcon name="Check" size="xs" variant="white" />
          </NeonButton>
          <button type="button" @click="cancelChangePassword"
            class="min-h-11 min-w-11 p-1.5 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors dark:hover:bg-slate-800 dark:hover:text-slate-200"
          >
            <AppIcon name="X" size="xs" variant="pink" />
          </button>
        </template>
        <template v-else>
          <button type="button" @click="startChangePassword(user.id)"
            class="min-h-11 text-xs text-teal-600 hover:text-teal-700 px-2 py-1 rounded hover:bg-teal-50 transition-colors"
          >
            {{ t('settings.consoleUsers.changePassword') }}
          </button>
          <button
            type="button"
            v-if="user.id !== authStore.user?.id"
            @click="requestDeleteUser(user.id, user.username)"
            class="min-h-11 min-w-11 text-xs text-rose-400 hover:text-rose-500 px-1 py-1 rounded hover:bg-rose-50 transition-colors"
            :aria-label="t('settings.delete')"
          >
            <AppIcon name="Trash2" size="xs" variant="pink" />
          </button>
        </template>
      </div>
    </div>

    <ConfirmModal
      :is-open="showDeleteModal"
      :title="t('settings.delete')"
      :message="deleteTarget ? t('settings.consoleUsers.confirmDelete', { name: deleteTarget.username }) : ''"
      variant="danger"
      @confirm="confirmDeleteUser"
      @cancel="showDeleteModal = false; deleteTarget = null"
    />
  </div>
</template>
