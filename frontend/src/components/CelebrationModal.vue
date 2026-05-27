<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

interface Props {
  show: boolean
  title?: string
  message?: string
}

const props = withDefaults(defineProps<Props>(), {
  title: '恭喜！工作流完成',
  message: '内容已成功发布',
})

// Confetti particles
const particles = ref<{ id: number; x: number; y: number; color: string; delay: number; size: number }[]>([])

// Generate confetti particles
onMounted(() => {
  const colors = ['#f43f5e', '#f97316', '#eab308', '#22c55e', '#06b6d4', '#8b5cf6', '#ec4899']
  const particleCount = 50

  for (let i = 0; i < particleCount; i++) {
    particles.value.push({
      id: i,
      x: Math.random() * 100,
      y: -10 - Math.random() * 20,
      color: colors[Math.floor(Math.random() * colors.length)],
      delay: Math.random() * 0.5,
      size: 8 + Math.random() * 8,
    })
  }
})

const emit = defineEmits<{
  (e: 'close'): void
}>()

const handleClose = () => emit('close')
</script>

<template>
  <Teleport to="body">
    <Transition name="celebration">
      <div
        v-if="show"
        class="fixed inset-0 z-50 flex items-center justify-center"
        role="dialog"
        aria-modal="true"
        aria-labelledby="celebration-title"
      >
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-slate-900/30 backdrop-blur-sm" @click="handleClose" aria-hidden="true" />

        <!-- Confetti particles -->
        <div class="absolute inset-0 overflow-hidden pointer-events-none" aria-hidden="true">
          <div
            v-for="particle in particles"
            :key="particle.id"
            :class="[
              'absolute rounded-full animate-confetti',
            ]"
            :style="{
              left: `${particle.x}%`,
              top: `${particle.y}%`,
              width: `${particle.size}px`,
              height: `${particle.size}px`,
              background: particle.color,
              animationDelay: `${particle.delay}s`,
            }"
          />
        </div>

        <!-- Celebration Card -->
        <div class="relative w-full max-w-md p-8 rounded-2xl bg-white/98 shadow-2xl border border-teal-200/50 text-center">
          <!-- Success Icon with animation -->
          <div class="w-20 h-20 mx-auto rounded-full bg-gradient-to-br from-teal-400 to-teal-500 flex items-center justify-center shadow-lg animate-bounce-slow">
            <AppIcon name="CheckCircle" size="xl" variant="white" />
          </div>

          <!-- Title -->
          <h2 id="celebration-title" class="text-2xl font-bold text-slate-800 mt-6 mb-2">
            {{ title }}
          </h2>

          <!-- Message -->
          <p class="text-slate-600 mb-6">{{ message }}</p>

          <!-- Stats Preview -->
          <div class="grid grid-cols-3 gap-3 mb-6">
            <div class="p-3 rounded-lg bg-rose-50 border border-rose-100">
              <div class="text-rose-500 font-bold text-lg">✓</div>
              <div class="text-xs text-slate-500">内容发布</div>
            </div>
            <div class="p-3 rounded-lg bg-teal-50 border border-teal-100">
              <div class="text-teal-500 font-bold text-lg">100%</div>
              <div class="text-xs text-slate-500">进度完成</div>
            </div>
            <div class="p-3 rounded-lg bg-violet-50 border border-violet-100">
              <div class="text-violet-500 font-bold text-lg">🎉</div>
              <div class="text-xs text-slate-500">工作流结束</div>
            </div>
          </div>

          <!-- Close Button -->
          <button
            class="w-full px-6 py-3 rounded-lg bg-gradient-to-r from-teal-500 to-teal-400 text-white font-medium hover:from-teal-600 hover:to-teal-500 transition-all shadow-sm"
            @click="handleClose"
          >
            返回仪表盘
          </button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.celebration-enter-active {
  transition: all 0.5s ease-out;
}

.celebration-leave-active {
  transition: all 0.3s ease-in;
}

.celebration-enter-from {
  opacity: 0;
}

.celebration-leave-to {
  opacity: 0;
}

.celebration-enter-from > div:last-child {
  transform: scale(0.8);
}

.celebration-leave-to > div:last-child {
  transform: scale(0.9);
}

.animate-confetti {
  animation: confetti-fall 3s ease-out forwards;
}

@keyframes confetti-fall {
  0% {
    transform: translateY(0) rotate(0deg);
    opacity: 1;
  }
  100% {
    transform: translateY(100vh) rotate(720deg);
    opacity: 0;
  }
}

.animate-bounce-slow {
  animation: bounce-slow 2s ease-in-out infinite;
}

@keyframes bounce-slow {
  0%, 100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-10px);
  }
}
</style>