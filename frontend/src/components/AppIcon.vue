<script setup lang="ts">
import { computed, type Component } from 'vue'
import { cn } from '@/utils/cn'

import {
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Baby,
  BarChart3,
  BookOpen,
  Brain,
  Calendar,
  Check,
  CheckCircle,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Circle,
  ClipboardCheck,
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
  FileUp,
  FileText,
  Flame,
  FlaskConical,
  GitBranch,
  Globe,
  HelpCircle,
  History,
  Home,
  Inbox,
  Keyboard,
  Lightbulb,
  Layers,
  List,
  Loader,
  Loader2,
  Lock,
  LogIn,
  LogOut,
  MessageCircle,
  MessageSquare,
  Minus,
  Moon,
  MoreHorizontal,
  Palette,
  Pause,
  Play,
  PawPrint,
  Pencil,
  Plane,
  Plus,
  RefreshCw,
  RotateCcw,
  Rocket,
  Save,
  Scan,
  Search,
  SearchX,
  Send,
  Settings,
  Shirt,
  Smartphone,
  Sparkles,
  Star,
  Sun,
  Trash2,
  TrendingUp,
  Upload,
  UserCheck,
  Users,
  UtensilsCrossed,
  Wand2,
  Wifi,
  WifiOff,
  Workflow,
  X,
  XCircle,
  Zap,
  ZapOff,
  Eye,
  MousePointerClick,
  Terminal,
} from '@lucide/vue'

const iconMap: Record<string, Component> = {
  AlertCircle, AlertTriangle, ArrowLeft, ArrowRight, Baby, BarChart3, BookOpen, Brain,
  Calendar, Check, CheckCircle, CheckSquare, ChevronDown, ChevronRight, ChevronUp, Circle, ClipboardCheck, ClipboardList,
  Clock, Columns, Compass, Copy, Cpu, Camera, Database, DollarSign, Dumbbell,
  Edit3, FileText, FlaskConical, GitBranch, Globe, HelpCircle, History,
  ExternalLink, FileUp, Flame, Home, Inbox, Keyboard, Layers, Lightbulb, List, Loader, Loader2, Lock, LogIn,
  LogOut, MessageCircle, MessageSquare, Minus, Moon, MoreHorizontal, Palette, Pause, PawPrint,
  Pencil, Plane, Play, Plus, RefreshCw, RotateCcw, Rocket, Save, Scan, Search, SearchX, Send,
  Settings, Shirt, Smartphone, Sparkles, Star, Sun, Trash2, TrendingUp, Upload, UserCheck,
  Users, UtensilsCrossed, Wand2, Wifi, WifiOff, Workflow, X, XCircle, Zap, ZapOff, Eye,
  MousePointerClick, Terminal,
}

interface Props {
  name: string
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  variant?: 'pink' | 'cyan' | 'purple' | 'peach' | 'white' | 'muted'
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
  muted: 'text-slate-400 dark:text-slate-500',
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
  <!-- Decorative by default: only icons with an explicit label are exposed as images. -->
  <component
    :is="IconComponent"
    :size="iconSize"
    :class="iconClasses"
    :aria-label="ariaLabel || undefined"
    :role="ariaLabel ? 'img' : undefined"
    :aria-hidden="ariaLabel ? undefined : 'true'"
  />
</template>
