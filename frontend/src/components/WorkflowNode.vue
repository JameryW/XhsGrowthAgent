<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'

const { t } = useI18n()

interface Props {
  icon: string // lucide icon name
  label: string
  status: 'completed' | 'running' | 'pending' | 'error'
  focused?: boolean
  tabindex?: number
  clickable?: boolean
  selected?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  focused: false,
  tabindex: -1,
  clickable: false,
  selected: false,
})

const emit = defineEmits<{
  click: []
}>()

// Badge type definition
interface BadgeConfig {
  show: boolean
  icon?: string
  color?: string
  animate?: boolean
}

// Pre-defined status styles - refined light theme
const statusStyles: Record<string, {
  shape: string
  iconVariant: 'pink' | 'cyan' | 'purple' | 'peach' | 'white'
  animate: boolean
  labelClass: string
  badge: BadgeConfig
}> = {
  completed: {
    shape: 'bg-gradient-to-br from-emerald-400 to-emerald-500 shadow-sm',
    iconVariant: 'white',
    animate: false,
    labelClass: 'text-slate-800',
    badge: { show: true, icon: 'Check', color: 'text-emerald-600', animate: false },
  },
  running: {
    shape: 'bg-gradient-to-br from-teal-300 to-teal-400 shadow-sm',
    iconVariant: 'white',
    animate: true,
    labelClass: 'text-teal-600 font-semibold',
    badge: { show: true, icon: 'Clock', color: 'text-teal-500', animate: true },
  },
  pending: {
    shape: 'bg-slate-100 border border-slate-200 dark:bg-slate-800 dark:border-slate-600',
    iconVariant: 'cyan',
    animate: false,
    labelClass: 'text-slate-400',
    badge: { show: false },
  },
  error: {
    shape: 'bg-gradient-to-br from-rose-400 to-rose-500 shadow-sm',
    iconVariant: 'white',
    animate: false,
    labelClass: 'text-rose-600 font-semibold',
    badge: { show: true, icon: 'AlertTriangle', color: 'text-rose-500', animate: true },
  },
}

const currentStyle = computed(() => statusStyles[props.status])

const focusClass = computed(() => {
  if (props.selected) {
    return 'ring-2 ring-violet-400 ring-offset-2 ring-offset-white scale-110 shadow-lg shadow-violet-200'
  }
  if (props.focused) {
    return 'ring-2 ring-teal-400 ring-offset-2 ring-offset-white scale-105'
  }
  return ''
})

const clickableClass = computed(() => {
  return props.clickable ? 'cursor-pointer' : ''
})
</script>

<template>
  <div
    class="text-center group relative outline-none"
    :class="clickableClass"
    :tabindex="props.tabindex"
    :aria-label="($attrs['aria-label'] as string | undefined)"
    :aria-describedby="($attrs['aria-describedby'] as string | undefined)"
    @click="props.clickable && emit('click')"
  >
    <!-- Node shape -->
    <div :class="[
      'w-10 h-10 md:w-16 md:h-16 rounded-lg md:rounded-xl flex items-center justify-center mx-auto transition-all duration-300 ease-out group-hover:scale-105',
      currentStyle.shape,
      focusClass,
    ]">
      <AppIcon
        :name="props.status === 'running' ? 'Loader2' : props.icon"
        size="lg"
        :variant="currentStyle.iconVariant"
        :animate="currentStyle.animate"
        :aria-label="props.label"
      />
    </div>

    <!-- Label -->
    <div :class="['mt-1 md:mt-2 text-[10px] md:text-xs font-medium transition-colors duration-200 leading-tight', currentStyle.labelClass]">
      {{ props.label }}
    </div>

    <!-- Status badge -->
    <div v-if="currentStyle.badge.show && currentStyle.badge.icon" class="mt-0.5 md:mt-1.5 flex items-center justify-center gap-0.5 md:gap-1">
      <AppIcon :name="currentStyle.badge.icon" size="sm" :variant="props.status === 'completed' ? 'cyan' : 'peach'" :animate="currentStyle.badge.animate" />
      <span v-if="currentStyle.badge.color" :class="['text-[10px] md:text-xs', currentStyle.badge.color]">
        {{ props.status === 'completed' ? t('workflowNode.completed') : props.status === 'error' ? t('workflowNode.error') : t('workflowNode.running') }}
      </span>
    </div>
  </div>
</template>