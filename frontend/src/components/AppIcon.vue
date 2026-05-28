<script setup lang="ts">
import { computed, type Component } from 'vue'
import { cn } from '@/utils/cn'

import {
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  BookOpen,
  Calendar,
  Check,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Circle,
  ClipboardList,
  Clock,
  Compass,
  Edit3,
  FileText,
  GitBranch,
  HelpCircle,
  Home,
  Inbox,
  Keyboard,
  Loader,
  Loader2,
  Lock,
  LogIn,
  LogOut,
  MessageCircle,
  MessageSquare,
  Minus,
  Palette,
  Pause,
  Pencil,
  RefreshCw,
  Rocket,
  Scan,
  Search,
  SearchX,
  Sparkles,
  Star,
  TrendingUp,
  Wand2,
  Wifi,
  WifiOff,
  X,
  XCircle,
  Zap,
} from '@lucide/vue'

const iconMap: Record<string, Component> = {
  AlertCircle, AlertTriangle, ArrowLeft, BarChart3, BookOpen, Calendar,
  Check, CheckCircle, ChevronDown, ChevronRight, Circle, ClipboardList,
  Clock, Compass, Edit3, FileText, GitBranch, HelpCircle, Home, Inbox,
  Keyboard, Loader, Loader2, Lock, LogIn, LogOut, MessageCircle,
  MessageSquare, Minus, Palette, Pause, Pencil, RefreshCw, Rocket, Scan,
  Search, SearchX, Sparkles, Star, TrendingUp, Wand2, Wifi, WifiOff, X,
  XCircle, Zap,
}

interface Props {
  name: string
  size?: 'sm' | 'md' | 'lg' | 'xl'
  variant?: 'pink' | 'cyan' | 'purple' | 'peach' | 'white'
  animate?: boolean
  ariaLabel?: string
}

const props = withDefaults(defineProps<Props>(), {
  size: 'md',
  variant: 'white',
  animate: false,
  ariaLabel: '',
})

const sizeMap = {
  sm: 16,
  md: 20,
  lg: 24,
  xl: 32,
}

const colorClasses = {
  pink: 'text-neon-pink',
  cyan: 'text-neon-cyan',
  purple: 'text-neon-purple',
  peach: 'text-neon-peach',
  white: 'text-white',
}

const iconSize = computed(() => sizeMap[props.size])
const colorClass = computed(() => colorClasses[props.variant])

const IconComponent = computed(() => iconMap[props.name] || HelpCircle)

const iconClasses = computed(() =>
  cn(
    colorClass.value,
    props.animate && 'animate-spin-slow'
  )
)
</script>

<template>
  <component
    :is="IconComponent"
    :size="iconSize"
    :class="iconClasses"
    :aria-label="ariaLabel || undefined"
    role="img"
  />
</template>
