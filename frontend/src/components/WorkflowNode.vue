<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

interface Props {
  icon: string // lucide icon name
  label: string
  status: 'completed' | 'running' | 'pending'
  focused?: boolean
  tabindex?: number
}

const props = withDefaults(defineProps<Props>(), {
  focused: false,
  tabindex: -1,
})

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
    shape: 'bg-gradient-to-br from-rose-400 to-amber-400 shadow-sm',
    iconVariant: 'white',
    animate: false,
    labelClass: 'text-slate-800',
    badge: { show: true, icon: 'Check', color: 'text-teal-600', animate: false },
  },
  running: {
    shape: 'bg-gradient-to-br from-amber-300 to-amber-400 shadow-sm',
    iconVariant: 'white',
    animate: true,
    labelClass: 'text-amber-600 font-semibold',
    badge: { show: true, icon: 'Clock', color: 'text-amber-500', animate: true },
  },
  pending: {
    shape: 'bg-slate-100 border border-slate-200',
    iconVariant: 'cyan',
    animate: false,
    labelClass: 'text-slate-400',
    badge: { show: false },
  },
}

const currentStyle = computed(() => statusStyles[props.status])

const focusClass = computed(() => {
  if (props.focused) {
    return 'ring-2 ring-teal-400 ring-offset-2 ring-offset-white scale-105'
  }
  return ''
})
</script>

<template>
  <div
    class="text-center group relative outline-none"
    :tabindex="props.tabindex"
    :aria-label="$attrs['aria-label']"
    :aria-describedby="$attrs['aria-describedby']"
  >
    <!-- Node shape -->
    <div :class="[
      'w-16 h-16 rounded-xl flex items-center justify-center mx-auto transition-all duration-300 ease-out group-hover:scale-105',
      currentStyle.shape,
      focusClass,
    ]">
      <AppIcon
        :name="props.status === 'running' ? 'Loader2' : props.icon"
        :size="props.status === 'running' ? 'lg' : 'lg'"
        :variant="currentStyle.iconVariant"
        :animate="currentStyle.animate"
        :aria-label="props.label"
      />
    </div>

    <!-- Label -->
    <div :class="['mt-2 text-xs font-medium transition-colors duration-200', currentStyle.labelClass]">
      {{ props.label }}
    </div>

    <!-- Status badge -->
    <div v-if="currentStyle.badge.show && currentStyle.badge.icon" class="mt-1.5 flex items-center justify-center gap-1">
      <AppIcon :name="currentStyle.badge.icon" size="sm" :variant="props.status === 'completed' ? 'cyan' : 'peach'" :animate="currentStyle.badge.animate" />
      <span v-if="currentStyle.badge.color" :class="['text-xs', currentStyle.badge.color]">
        {{ props.status === 'completed' ? '完成' : '进行中' }}
      </span>
    </div>
  </div>
</template>