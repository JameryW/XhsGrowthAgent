<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'

const { t } = useI18n()

const props = defineProps<{
  isUploading?: boolean
  uploadedText?: string | null
  sourceType?: string | null
  threadId?: string
  pendingFileName?: string | null
  error?: string | null
}>()

const emit = defineEmits<{
  upload: [file: File]
  confirm: [text: string]
  clear: []
}>()

const MAX_FILE_SIZE = 10 * 1024 * 1024

const localError = ref<string | null>(null)
const fileName = ref<string | null>(null)
const editableText = ref('')
const isDragging = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

const displayError = computed(() => localError.value || props.error)
const hasUploadedText = computed(() => !!props.uploadedText)
const isConfirmable = computed(() => editableText.value.trim().length > 0)
const hasPendingFile = computed(() => !!props.pendingFileName && !hasUploadedText.value)

// When uploaded text arrives, populate the editable preview (do NOT auto-confirm)
watch(() => props.uploadedText, (text) => {
  if (text && text.trim()) {
    editableText.value = text
  }
})

// When source is cleared, reset local state
watch(() => props.uploadedText, (text) => {
  if (!text) {
    editableText.value = ''
    fileName.value = null
    localError.value = null
  }
})

function handleFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  validateAndUpload(file)
  input.value = '' // Reset so same file can be re-selected
}

function handleDrop(event: DragEvent) {
  isDragging.value = false
  const file = event.dataTransfer?.files[0]
  if (!file) return
  validateAndUpload(file)
}

function validateAndUpload(file: File) {
  localError.value = null

  if (file.size > MAX_FILE_SIZE) {
    localError.value = t('brief.fileTooLarge')
    return
  }

  if (!file.name.toLowerCase().endsWith('.pdf')) {
    localError.value = t('brief.unsupportedFormat')
    return
  }

  fileName.value = file.name
  emit('upload', file)
}

function confirm() {
  if (!isConfirmable.value) return
  emit('confirm', editableText.value.trim())
}

function clear() {
  editableText.value = ''
  fileName.value = null
  localError.value = null
  emit('clear')
}
</script>

<template>
  <div class="space-y-4">
    <!-- Upload area (shown before upload) -->
    <div v-if="!hasUploadedText" class="group">
      <label class="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400 mb-2">
        <AppIcon name="FileUp" size="sm" variant="pink" />
        {{ t('brief.uploadLabel') }}
      </label>

      <div
        @dragover.prevent="isDragging = true"
        @dragleave.prevent="isDragging = false"
        @drop.prevent="handleDrop"
        @click="fileInputRef?.click()"
        :class="[
          'relative flex flex-col items-center justify-center gap-3 p-6 rounded-xl border-2 cursor-pointer',
          'transition-all duration-300 ease-out',
          isDragging
            ? 'border-neon-pink/50 bg-gradient-to-br from-neon-pink/10 to-neon-peach/5'
            : 'border-slate-100 bg-slate-50/50 hover:border-neon-pink/30 hover:bg-neon-pink/[0.02] hover:shadow-sm dark:border-slate-700/55 dark:bg-slate-900/70 dark:hover:border-neon-pink/40'
        ]"
      >
        <input
          ref="fileInputRef"
          type="file"
          accept=".pdf"
          class="hidden"
          @change="handleFileSelect"
        />

        <div class="flex items-center justify-center w-10 h-10 rounded-full bg-neon-pink/10">
          <AppIcon name="Upload" size="md" variant="pink" />
        </div>

        <div class="text-center">
          <p class="text-sm font-semibold text-slate-700">
            {{ isDragging ? t('brief.dragActive') : t('brief.dragHint') }}
          </p>
          <p class="text-xs text-slate-400 mt-1">
            {{ t('brief.dragFormatHint') }}
          </p>
        </div>

        <!-- Loading spinner -->
        <div v-if="isUploading" class="absolute inset-0 flex items-center justify-center bg-white/80 rounded-xl dark:bg-slate-950/80">
          <div class="flex items-center gap-2 text-neon-pink">
            <div class="w-5 h-5 border-2 border-neon-pink border-t-transparent rounded-full animate-spin" />
            <span class="text-sm font-medium">{{ t('brief.extracting') }}</span>
          </div>
        </div>
      </div>

      <!-- Error display -->
      <div v-if="displayError" class="flex items-center gap-2 mt-2 p-3 rounded-xl bg-rose-50 border border-rose-200">
        <AppIcon name="AlertCircle" size="sm" variant="pink" />
        <span class="text-sm text-rose-700">{{ displayError }}</span>
      </div>
    </div>

    <!-- Pending file indicator (shown when file is queued but not yet extracted) -->
    <div v-if="hasPendingFile" class="space-y-3">
      <div class="flex items-center justify-between p-3 rounded-xl border-2 border-teal-200/50 bg-gradient-to-r from-teal-50/50 to-transparent">
        <div class="flex items-center gap-2">
          <AppIcon name="FileText" size="sm" variant="cyan" />
          <span class="text-sm font-semibold text-teal-700">{{ pendingFileName }}</span>
          <span class="text-xs text-slate-400 px-1.5 py-0.5 bg-teal-50 rounded-full">
            {{ t('brief.queued') }}
          </span>
        </div>
        <button
          @click="clear"
          class="flex items-center gap-1 text-xs text-slate-400 hover:text-rose-500 transition-colors cursor-pointer"
        >
          <AppIcon name="X" size="sm" />
          {{ t('brief.removeFile') }}
        </button>
      </div>
      <p class="text-xs text-slate-400 pl-1">{{ t('brief.queuedHint') }}</p>
    </div>

    <!-- Preview + edit area (shown after upload) -->
    <div v-if="hasUploadedText" class="space-y-3">
      <!-- File info -->
      <div class="flex items-center justify-between p-3 rounded-xl border-2 border-neon-pink/20 bg-gradient-to-r from-neon-pink/5 to-transparent">
        <div class="flex items-center gap-2">
          <AppIcon name="FileText" size="sm" variant="pink" />
          <span class="text-sm font-semibold text-neon-pinkDark">{{ fileName }}</span>
          <span class="text-xs text-slate-400 px-1.5 py-0.5 bg-slate-100 rounded-full">
            {{ sourceType === 'pdf' ? t('brief.sourcePdf') : t('brief.sourceText') }}
          </span>
        </div>
        <button
          @click="clear"
          class="flex items-center gap-1 text-xs text-slate-400 hover:text-rose-500 transition-colors cursor-pointer"
        >
          <AppIcon name="X" size="sm" />
          {{ t('brief.removeFile') }}
        </button>
      </div>

      <!-- Editable text preview -->
      <div>
        <label class="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400 mb-2">
          <AppIcon name="Pencil" size="sm" variant="cyan" />
          {{ t('brief.previewLabel') }}
        </label>
        <textarea
          v-model="editableText"
          rows="8"
          class="w-full pl-4 pr-4 py-3 rounded-xl border-2 border-slate-100 bg-slate-50/50 text-sm text-slate-700 font-medium dark:border-slate-700/55 dark:bg-slate-900/70 dark:text-slate-200
                 transition-all duration-300 ease-out resize-y
                 focus:outline-none focus:border-neon-pink/40 focus:bg-white focus:shadow-neon-pink-sm dark:focus:bg-slate-900
                 placeholder:text-slate-300 placeholder:font-normal"
          :placeholder="t('brief.previewPlaceholder')"
        />
        <p class="text-xs text-slate-400 mt-1.5 pl-1">{{ t('brief.previewHint') }}</p>
      </div>

      <!-- Confirm button -->
      <div class="flex justify-end">
        <NeonButton
          variant="pink"
          :disabled="!isConfirmable"
          @click="confirm"
        >
          <AppIcon name="Check" size="sm" variant="white" class="mr-1" />
          {{ t('brief.confirm') }}
        </NeonButton>
      </div>
    </div>
  </div>
</template>