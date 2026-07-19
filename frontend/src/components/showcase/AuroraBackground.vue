<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

/**
 * AuroraBackground — animated ambient backdrop for the public pages.
 * Saturated drifting gradient blobs over a fine grid, an aurora curtain band,
 * floating glow particles, and a soft spotlight that follows the pointer
 * (fine pointers + full motion only).
 */
withDefaults(defineProps<{
  /** Dominant accent of the blob palette. */
  variant?: 'rose' | 'teal'
}>(), {
  variant: 'rose',
})

const root = ref<HTMLElement | null>(null)
let rafId = 0
let listening = false

function handlePointerMove(event: PointerEvent) {
  if (rafId) return
  rafId = window.requestAnimationFrame(() => {
    rafId = 0
    const el = root.value
    if (!el) return
    const rect = el.getBoundingClientRect()
    el.style.setProperty('--mx', `${Math.round(event.clientX - rect.left)}px`)
    el.style.setProperty('--my', `${Math.round(event.clientY - rect.top)}px`)
  })
}

onMounted(() => {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const coarse = window.matchMedia('(pointer: coarse)').matches
  if (reduced || coarse || !root.value) return
  root.value.addEventListener('pointermove', handlePointerMove)
  listening = true
})

onUnmounted(() => {
  if (listening) root.value?.removeEventListener('pointermove', handlePointerMove)
  if (rafId) window.cancelAnimationFrame(rafId)
})
</script>

<template>
  <div ref="root" class="aurora-bg" :class="`aurora-${variant}`" aria-hidden="true">
    <div class="aurora-grid bg-grid-pattern" />
    <div class="aurora-blob aurora-blob-a" />
    <div class="aurora-blob aurora-blob-b" />
    <div class="aurora-blob aurora-blob-c" />
    <div class="aurora-curtain" />
    <div class="aurora-particles">
      <i v-for="n in 14" :key="n" />
    </div>
    <div class="aurora-spotlight" />
    <div class="aurora-fade" />
  </div>
</template>

<style scoped>
.aurora-bg {
  position: absolute;
  inset: 0 0 auto;
  height: 46rem;
  overflow: hidden;
  pointer-events: none;
  --mx: 72%;
  --my: 10rem;
}

.aurora-grid {
  position: absolute;
  inset: 0;
  -webkit-mask-image: radial-gradient(ellipse 90% 70% at 50% 0%, #000 30%, transparent 75%);
  mask-image: radial-gradient(ellipse 90% 70% at 50% 0%, #000 30%, transparent 75%);
}

.aurora-blob {
  position: absolute;
  border-radius: 9999px;
  filter: blur(56px);
  will-change: transform;
}

.aurora-blob-a {
  width: 38rem;
  height: 38rem;
  left: -10rem;
  top: -12rem;
  animation: aurora-drift-a 16s ease-in-out infinite;
}

.aurora-blob-b {
  width: 34rem;
  height: 34rem;
  right: -8rem;
  top: -6rem;
  animation: aurora-drift-b 19s ease-in-out infinite;
}

.aurora-blob-c {
  width: 28rem;
  height: 28rem;
  left: 34%;
  top: 9rem;
  animation: aurora-drift-c 22s ease-in-out infinite;
}

.aurora-rose .aurora-blob-a {
  background: radial-gradient(circle, rgb(244 63 94 / 0.55), transparent 68%);
}

.aurora-rose .aurora-blob-b {
  background: radial-gradient(circle, rgb(251 146 60 / 0.5), transparent 68%);
}

.aurora-rose .aurora-blob-c {
  background: radial-gradient(circle, rgb(20 184 166 / 0.4), transparent 68%);
}

.aurora-teal .aurora-blob-a {
  background: radial-gradient(circle, rgb(20 184 166 / 0.5), transparent 68%);
}

.aurora-teal .aurora-blob-b {
  background: radial-gradient(circle, rgb(139 92 246 / 0.42), transparent 68%);
}

.aurora-teal .aurora-blob-c {
  background: radial-gradient(circle, rgb(244 63 94 / 0.36), transparent 68%);
}

/* Aurora curtain — a wide skewed light band sweeping slowly across the top. */
.aurora-curtain {
  position: absolute;
  top: -30%;
  left: 15%;
  width: 70%;
  height: 70%;
  background: linear-gradient(115deg, transparent 15%, rgb(244 63 94 / 0.14) 42%, rgb(251 146 60 / 0.12) 55%, rgb(20 184 166 / 0.1) 68%, transparent 88%);
  filter: blur(28px);
  transform: rotate(-10deg);
  animation: aurora-curtain-sweep 13s ease-in-out infinite;
  will-change: transform, opacity;
}

.aurora-teal .aurora-curtain {
  background: linear-gradient(115deg, transparent 15%, rgb(20 184 166 / 0.15) 42%, rgb(139 92 246 / 0.12) 58%, transparent 85%);
}

/* Floating glow particles. */
.aurora-particles {
  position: absolute;
  inset: 0;
}

.aurora-particles i {
  position: absolute;
  width: 5px;
  height: 5px;
  border-radius: 9999px;
  background: rgb(244 63 94 / 0.75);
  box-shadow: 0 0 10px 2px rgb(244 63 94 / 0.45);
  animation: particle-rise 9s ease-in-out infinite;
  opacity: 0;
}

.aurora-particles i:nth-child(3n) {
  background: rgb(20 184 166 / 0.8);
  box-shadow: 0 0 10px 2px rgb(20 184 166 / 0.45);
}

.aurora-particles i:nth-child(4n) {
  background: rgb(251 146 60 / 0.8);
  box-shadow: 0 0 10px 2px rgb(251 146 60 / 0.45);
}

.aurora-particles i:nth-child(5n) {
  width: 3px;
  height: 3px;
}

.aurora-particles i:nth-child(1) { left: 8%; top: 22%; animation-delay: 0s; }
.aurora-particles i:nth-child(2) { left: 18%; top: 48%; animation-delay: 1.2s; }
.aurora-particles i:nth-child(3) { left: 27%; top: 18%; animation-delay: 2.4s; }
.aurora-particles i:nth-child(4) { left: 36%; top: 38%; animation-delay: 0.6s; }
.aurora-particles i:nth-child(5) { left: 45%; top: 12%; animation-delay: 3.1s; }
.aurora-particles i:nth-child(6) { left: 52%; top: 30%; animation-delay: 1.8s; }
.aurora-particles i:nth-child(7) { left: 60%; top: 16%; animation-delay: 4s; }
.aurora-particles i:nth-child(8) { left: 68%; top: 42%; animation-delay: 0.9s; }
.aurora-particles i:nth-child(9) { left: 74%; top: 20%; animation-delay: 2.8s; }
.aurora-particles i:nth-child(10) { left: 82%; top: 36%; animation-delay: 1.5s; }
.aurora-particles i:nth-child(11) { left: 88%; top: 14%; animation-delay: 3.6s; }
.aurora-particles i:nth-child(12) { left: 14%; top: 60%; animation-delay: 4.4s; }
.aurora-particles i:nth-child(13) { left: 58%; top: 56%; animation-delay: 2.1s; }
.aurora-particles i:nth-child(14) { left: 92%; top: 52%; animation-delay: 5s; }

.aurora-spotlight {
  position: absolute;
  inset: 0;
  background: radial-gradient(30rem circle at var(--mx) var(--my), rgb(244 63 94 / 0.16), transparent 68%);
}

.aurora-teal .aurora-spotlight {
  background: radial-gradient(30rem circle at var(--mx) var(--my), rgb(20 184 166 / 0.18), transparent 68%);
}

.aurora-fade {
  position: absolute;
  inset: auto 0 0;
  height: 14rem;
  background: linear-gradient(to bottom, transparent, #f8fafc);
}

.dark .aurora-blob {
  filter: blur(64px);
}

.dark .aurora-rose .aurora-blob-a {
  background: radial-gradient(circle, rgb(244 63 94 / 0.38), transparent 68%);
}

.dark .aurora-rose .aurora-blob-b {
  background: radial-gradient(circle, rgb(251 146 60 / 0.3), transparent 68%);
}

.dark .aurora-rose .aurora-blob-c {
  background: radial-gradient(circle, rgb(20 184 166 / 0.28), transparent 68%);
}

.dark .aurora-teal .aurora-blob-a {
  background: radial-gradient(circle, rgb(20 184 166 / 0.36), transparent 68%);
}

.dark .aurora-teal .aurora-blob-b {
  background: radial-gradient(circle, rgb(139 92 246 / 0.32), transparent 68%);
}

.dark .aurora-teal .aurora-blob-c {
  background: radial-gradient(circle, rgb(244 63 94 / 0.26), transparent 68%);
}

.dark .aurora-curtain {
  background: linear-gradient(115deg, transparent 15%, rgb(244 63 94 / 0.18) 42%, rgb(251 146 60 / 0.14) 55%, rgb(20 184 166 / 0.12) 68%, transparent 88%);
}

.dark .aurora-teal .aurora-curtain {
  background: linear-gradient(115deg, transparent 15%, rgb(20 184 166 / 0.2) 42%, rgb(139 92 246 / 0.16) 58%, transparent 85%);
}

.dark .aurora-spotlight {
  background: radial-gradient(30rem circle at var(--mx) var(--my), rgb(244 63 94 / 0.12), transparent 68%);
}

.dark .aurora-teal .aurora-spotlight {
  background: radial-gradient(30rem circle at var(--mx) var(--my), rgb(20 184 166 / 0.13), transparent 68%);
}

.dark .aurora-fade {
  background: linear-gradient(to bottom, transparent, #020617);
}

@keyframes aurora-drift-a {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(5rem, 3rem) scale(1.15); }
}

@keyframes aurora-drift-b {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(-4.5rem, 3.5rem) scale(1.1); }
}

@keyframes aurora-drift-c {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(3rem, -2.5rem) scale(1.18); }
}

@keyframes aurora-curtain-sweep {
  0%, 100% { transform: rotate(-10deg) translateX(-12%); opacity: 0.75; }
  50% { transform: rotate(-10deg) translateX(14%); opacity: 1; }
}

@keyframes particle-rise {
  0% { transform: translateY(0) scale(1); opacity: 0; }
  12% { opacity: 1; }
  55% { opacity: 0.9; }
  100% { transform: translateY(-7rem) scale(0.4); opacity: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .aurora-blob,
  .aurora-curtain,
  .aurora-particles i {
    animation: none;
  }

  .aurora-particles i {
    opacity: 0.6;
  }
}
</style>
