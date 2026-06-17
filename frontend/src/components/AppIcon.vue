<script setup lang="ts">
import { computed, type Component } from 'vue'
import { cn } from '@/utils/cn'

import {
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  Baby,
  BarChart3,
  BookOpen,
  Calendar,
  Check,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Circle,
  ClipboardList,
  Clock,
  Columns,
  Compass,
  Copy,
  Cpu,
  Camera,
  Database,
  DollarSign,
  Dumbbell,
  Edit3,
  ExternalLink,
  FileText,
  FlaskConical,
  GitBranch,
  Globe,
  HelpCircle,
  History,
  Home,
  Inbox,
  Keyboard,
  Lightbulb,
  List,
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
  PawPrint,
  Pencil,
  Plane,
  Plus,
  RefreshCw,
  Rocket,
  Scan,
  Search,
  SearchX,
  Send,
  Settings,
  Shirt,
  Smartphone,
  Sparkles,
  Star,
  Trash2,
  TrendingUp,
  Upload,
  UtensilsCrossed,
  Wand2,
  Wifi,
  WifiOff,
  X,
  XCircle,
  Zap,
  Eye,
} from '@lucide/vue'

const iconMap: Record<string, Component> = {
  AlertCircle, AlertTriangle, ArrowLeft, Baby, BarChart3, BookOpen, Calendar,
  Check, CheckCircle, ChevronDown, ChevronRight, ChevronUp, Circle, ClipboardList,
  Clock, Columns, Compass, Copy, Cpu, Camera, Database, DollarSign, Dumbbell,
  Edit3, FileText, FlaskConical, GitBranch, Globe, HelpCircle, History,
  ExternalLink, Home, Inbox, Keyboard, Lightbulb, List, Loader, Loader2, Lock, LogIn,
  LogOut, MessageCircle, MessageSquare, Minus, Palette, Pause, PawPrint,
  Pencil, Plane, Plus, RefreshCw, Rocket, Scan, Search, SearchX, Send,
  Settings, Shirt, Smartphone, Sparkles, Star, Trash2, TrendingUp, Upload,
  UtensilsCrossed, Wand2, Wifi, WifiOff, X, XCircle, Zap, Eye,
}

interface Props {
  name: string
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
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
  xs: 12,
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
