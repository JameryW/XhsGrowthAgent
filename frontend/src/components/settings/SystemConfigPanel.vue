<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSystemConfigStore } from '@/stores/system_config'
import { useToastStore } from '@/stores/toast'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'

const { t } = useI18n()
const store = useSystemConfigStore()
const toast = useToastStore()

const edits = ref<Record<string, string>>({})
const isSaving = ref(false)
const showDeleteModal = ref(false)
const deleteTarget = ref<string | null>(null)

const groupLabels: Record<string, string> = {
  llm_providers: 'settings.groups.llmProviders',
  ripple_cas: 'settings.groups.rippleCas',
  search_embedding: 'settings.groups.searchEmbedding',
}

const hasEdits = computed(() => Object.keys(edits.value).length > 0)

onMounted(async () => {
  await store.fetchConfig()
})

function isParam(keyName: string): boolean {
  return store.getItem(keyName)?.is_param ?? false
}

function startEdit(keyName: string) {
  // ponytail: pre-fill param keys with current value so user can tweak, not re-type
  edits.value[keyName] = isParam(keyName) ? (store.getItem(keyName)?.masked_value || '') : ''
}

function cancelEdit(keyName: string) {
  delete edits.value[keyName]
}

function getDisplay(keyName: string): string {
  if (edits.value[keyName] !== undefined) {
    const v = edits.value[keyName]
    if (isParam(keyName)) return v || t('settings.notSet')
    return v ? '●●●●' + v.slice(-4) : t('settings.willDelete')
  }
  return store.getItem(keyName)?.masked_value || t('settings.notSet')
}

function isSet(keyName: string): boolean {
  if (edits.value[keyName] !== undefined) return !!edits.value[keyName]
  return store.getItem(keyName)?.is_set ?? false
}

async function save() {
  if (!hasEdits.value) return
  isSaving.value = true
  try {
    await store.saveConfig(edits.value)
    edits.value = {}
    toast.success(t('settings.toasts.systemConfigSaved'))
  } catch (e: any) {
    toast.error(e.message)
  } finally {
    isSaving.value = false
  }
}

function requestDeleteKey(keyName: string) {
  deleteTarget.value = keyName
  showDeleteModal.value = true
}

async function confirmDeleteKey() {
  if (!deleteTarget.value) return
  const keyName = deleteTarget.value
  try {
    await store.saveConfig({ [keyName]: '' })
    toast.success(t('settings.toasts.credDeleted', { key: keyName }))
    showDeleteModal.value = false
    deleteTarget.value = null
  } catch (e: any) {
    toast.error(e.message)
  }
}
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-lg font-semibold text-slate-800">{{ t('settings.systemConfig.title') }}</h2>
        <p class="text-xs text-slate-400 mt-0.5">{{ t('settings.systemConfig.subtitle') }}</p>
      </div>
      <NeonButton
        v-if="hasEdits"
        variant="cyan"
        size="sm"
        :loading="isSaving"
        @click="save"
      >
        <AppIcon name="Save" size="xs" variant="white" />
        <span class="ml-1">{{ t('settings.saveCredentials') }}</span>
      </NeonButton>
    </div>

    <div v-for="group in store.groups" :key="group.id"
      class="rounded-xl border border-slate-200/50 bg-white/90 backdrop-blur-sm p-4 space-y-3 dark:bg-slate-900/90 dark:border-slate-700/55"
    >
      <h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wider">
        {{ t(groupLabels[group.id] || group.id) }}
      </h3>
      <div class="space-y-1">
        <div v-for="keyName in group.keys" :key="keyName"
          class="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 px-3 rounded-lg hover:bg-slate-50/80 transition-colors dark:hover:bg-slate-800/50"
          :class="isParam(keyName) ? 'bg-slate-50/40 dark:bg-slate-800/40' : ''"
        >
          <span class="text-xs font-mono w-full sm:w-44 shrink-0 break-all" :class="isParam(keyName) ? 'text-teal-600' : 'text-slate-500'">{{ keyName }}</span>

          <div class="flex-1 min-w-0">
            <!-- ponytail: param keys use text input (visible value), secrets use password -->
            <input
              v-if="edits[keyName] !== undefined"
              v-model="edits[keyName]"
              :type="isParam(keyName) ? 'text' : 'password'"
              :placeholder="isParam(keyName) ? keyName : t('settings.enterValue')"
              class="w-full px-2 py-1 text-sm rounded border bg-white focus:border-rose-400 outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200"
              :class="isParam(keyName) ? 'border-teal-200' : 'border-rose-200'"
              @keydown.escape="cancelEdit(keyName)"
            />
            <span v-else class="text-sm" :class="isSet(keyName) ? (isParam(keyName) ? 'text-teal-700 font-mono' : 'text-slate-600') : 'text-slate-300'">
              {{ getDisplay(keyName) }}
            </span>
          </div>

          <div class="w-2 h-2 rounded-full shrink-0" :class="isSet(keyName) ? 'bg-emerald-500' : 'bg-slate-200'" />

          <div class="flex items-center gap-1 shrink-0">
            <template v-if="edits[keyName] !== undefined">
              <button type="button" @click="cancelEdit(keyName)"
                class="min-h-11 min-w-11 p-1 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors dark:hover:bg-slate-800 dark:hover:text-slate-200"
              >
                <AppIcon name="X" size="xs" variant="pink" />
              </button>
            </template>
            <template v-else>
              <button type="button" @click="startEdit(keyName)"
                class="min-h-11 min-w-11 p-1 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors dark:hover:bg-slate-800 dark:hover:text-slate-200"
                :title="t('settings.edit')"
              >
                <AppIcon name="Pencil" size="xs" variant="cyan" />
              </button>
              <button type="button" v-if="isSet(keyName)" @click="requestDeleteKey(keyName)"
                class="min-h-11 min-w-11 p-1 rounded hover:bg-rose-50 text-slate-400 hover:text-rose-500 transition-colors"
                :title="t('settings.delete')"
              >
                <AppIcon name="Trash2" size="xs" variant="pink" />
              </button>
            </template>
          </div>
        </div>
      </div>
    </div>

    <ConfirmModal
      :is-open="showDeleteModal"
      :title="t('settings.delete')"
      :message="deleteTarget ? t('settings.confirm.deleteKey', { key: deleteTarget }) : ''"
      variant="danger"
      @confirm="confirmDeleteKey"
      @cancel="showDeleteModal = false; deleteTarget = null"
    />
  </div>
</template>
