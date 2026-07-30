<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'

const { t } = useI18n()

interface Props {
  title: string
  content: Record<string, any>
  icon: string // lucide icon name
  variant?: 'pink' | 'cyan' | 'purple' | 'peach'
  completed?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'pink',
  completed: false,
})

// Check if content has data
const hasContent = computed(() => Object.keys(props.content).length > 0)

// Check if a value is a simple primitive
function isSimple(value: unknown): boolean {
  return value === null || value === undefined || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
}

// Check if value is an array of primitives
function isStringArray(value: unknown): boolean {
  return Array.isArray(value) && value.length > 0 && value.every(isSimple)
}

// Check if value is an array of objects
function isObjectArray(value: unknown): boolean {
  return Array.isArray(value) && value.length > 0 && value.some(v => typeof v === 'object' && v !== null)
}

// Format snake_case/camelCase keys to readable labels
function formatKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/\b\w/g, c => c.toUpperCase())
}

const styles = {
  pink: {
    border: 'border-neon-pink/10',
    iconBg: 'from-neon-pink via-neon-pinkLight to-neon-peach',
    glow: 'shadow-neon-pink-sm',
    accent: 'border-neon-pink',
    textLight: 'text-neon-pinkLight',
    text: 'text-neon-pink',
  },
  cyan: {
    border: 'border-neon-cyan/10',
    iconBg: 'from-neon-cyan via-neon-cyanLight to-neon-green',
    glow: 'shadow-neon-cyan-sm',
    accent: 'border-neon-cyan',
    textLight: 'text-neon-cyan',
    text: 'text-neon-cyan',
  },
  purple: {
    border: 'border-neon-purple/10',
    iconBg: 'from-neon-purple via-neon-purpleLight to-neon-blue',
    glow: 'shadow-neon-purple-sm',
    accent: 'border-neon-purple',
    textLight: 'text-neon-purple',
    text: 'text-neon-purple',
  },
  peach: {
    border: 'border-neon-peach/10',
    iconBg: 'from-neon-peach via-neon-peachLight to-neon-yellow',
    glow: 'shadow-neon-peach',
    accent: 'border-neon-peach',
    textLight: 'text-neon-peach',
    text: 'text-neon-peach',
  },
}
</script>

<template>
  <div :class="['content-card-surface rounded-xl p-5 relative overflow-hidden bg-white/90 backdrop-blur-sm border transition-all duration-200 hover:shadow-lg hover:-translate-y-0.5 dark:bg-slate-900/80 dark:border-slate-700/50', styles[props.variant].border]" role="region" :aria-label="`${title} ${t('common.moduleOutput')}`">
    <!-- Header -->
    <div class="flex items-center gap-3 mb-4">
      <div :class="['w-11 h-11 rounded-xl bg-gradient-to-br flex items-center justify-center shadow-sm', styles[props.variant].iconBg]" aria-hidden="true">
        <AppIcon :name="props.icon" size="md" variant="white" />
      </div>
      <div class="flex-1">
        <div class="text-slate-800 font-semibold text-sm">{{ props.title }}</div>
        <div class="text-xs text-slate-400 uppercase tracking-wide">{{ t('common.moduleOutput') }}</div>
      </div>
      <div v-if="props.completed" :class="['px-2.5 py-1 rounded-lg flex items-center gap-1.5 bg-teal-50 border border-teal-100']">
        <AppIcon name="Check" size="sm" variant="cyan" :aria-label="t('common.completed')" />
        <span class="text-xs text-teal-600 font-medium">{{ t('common.completed') }}</span>
      </div>
    </div>

    <!-- Content -->
    <div v-if="hasContent" :class="['bg-slate-50 rounded-lg p-4 border-l-2 dark:bg-slate-800/70', styles[props.variant].accent]" role="status" aria-live="polite">
      <div class="text-xs text-slate-600 space-y-2">
        <template v-for="(value, key) in props.content" :key="key">
          <!-- Simple values (string, number, boolean) -->
          <div v-if="isSimple(value)" class="flex items-start gap-2">
            <span :class="styles[props.variant].text" aria-hidden="true">▸</span>
            <span class="text-slate-400 shrink-0">{{ formatKey(String(key)) }}:</span>
            <span :class="styles[props.variant].textLight">{{ String(value) }}</span>
          </div>

          <!-- Array of simple values -->
          <div v-else-if="isStringArray(value)" class="flex items-start gap-2">
            <span :class="styles[props.variant].text" aria-hidden="true">▸</span>
            <span class="text-slate-400 shrink-0">{{ formatKey(String(key)) }}:</span>
            <div class="flex flex-wrap gap-1">
              <span v-for="(item, i) in value" :key="i" :class="['px-1.5 py-0.5 rounded bg-white border text-[11px] dark:bg-slate-900/80', styles[props.variant].border, styles[props.variant].textLight]">{{ item }}</span>
            </div>
          </div>

          <!-- Array of objects -->
          <div v-else-if="isObjectArray(value)" class="space-y-1.5">
            <div class="flex items-center gap-2">
              <span :class="styles[props.variant].text" aria-hidden="true">▸</span>
              <span class="text-slate-400 font-medium">{{ formatKey(String(key)) }}</span>
              <span class="text-slate-300 text-[11px]">({{ value.length }})</span>
            </div>
            <div class="ml-4 space-y-1">
              <div v-for="(item, i) in value.slice(0, 5)" :key="i" class="bg-white rounded-md px-3 py-2 border border-slate-100 dark:bg-slate-900/80 dark:border-slate-700/50">
                <div class="flex flex-wrap gap-x-3 gap-y-0.5">
                  <span v-for="(v, k) in item" :key="k" class="text-[11px]">
                    <span class="text-slate-400">{{ formatKey(String(k)) }}:</span>
                    <span :class="styles[props.variant].textLight" class="ml-0.5">{{ isSimple(v) ? String(v) : JSON.stringify(v) }}</span>
                  </span>
                </div>
              </div>
              <div v-if="value.length > 5" class="text-[11px] text-slate-300 ml-1">+{{ value.length - 5 }} more</div>
            </div>
          </div>

          <!-- Nested object -->
          <div v-else-if="typeof value === 'object' && value !== null" class="space-y-1.5">
            <div class="flex items-center gap-2">
              <span :class="styles[props.variant].text" aria-hidden="true">▸</span>
              <span class="text-slate-400 font-medium">{{ formatKey(String(key)) }}</span>
            </div>
            <div class="ml-4 space-y-0.5">
              <div v-for="(v, k) in value" :key="k" class="flex items-start gap-1.5 text-[11px]">
                <span class="text-slate-400">{{ formatKey(String(k)) }}:</span>
                <span :class="styles[props.variant].textLight">{{ isSimple(v) ? String(v) : JSON.stringify(v) }}</span>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- Loading state -->
    <div v-else class="bg-slate-50 rounded-lg p-4 border-l-2 border-slate-200 dark:bg-slate-800/70 dark:border-slate-600" role="status" aria-live="polite" :aria-label="t('common.loadingState')">
      <div class="h-4 w-full rounded bg-slate-200 animate-pulse" />
    </div>
  </div>
</template>