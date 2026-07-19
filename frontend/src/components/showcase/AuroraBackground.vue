<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

/**
 * AuroraBackground — animated ambient backdrop for the public pages.
 * Layered blurred gradient blobs drifting over a fine grid, plus a soft
 * spotlight that follows the pointer (fine pointers + full motion only).
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
    <div class="aurora-spotlight" />
    <div class="aurora-fade" />
  </div>
</template>

<style scoped>
.aurora-bg {
  position: absolute;
  inset: 0 0 auto;
  height: 42rem;
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
  filter: blur(70px);
  will-change: transform;
}

.aurora-blob-a {
  width: 30rem;
  height: 30rem;
  left: -8rem;
  top: -10rem;
  animation: aurora-drift-a 16s ease-in-out infinite;
}

.aurora-blob-b {
  width: 26rem;
  height: 26rem;
  right: -6rem;
  top: -4rem;
  animation: aurora-drift-b 19s ease-in-out infinite;
}

.aurora-blob-c {
  width: 22rem;
  height: 22rem;
  left: 38%;
  top: 8rem;
  animation: aurora-drift-c 22s ease-in-out infinite;
}

.aurora-rose .aurora-blob-a {
  background: radial-gradient(circle, rgb(244 63 94 / 0.32), transparent 68%);
}

.aurora-rose .aurora-blob-b {
  background: radial-gradient(circle, rgb(251 146 60 / 0.3), transparent 68%);
}

.aurora-rose .aurora-blob-c {
  background: radial-gradient(circle, rgb(20 184 166 / 0.24), transparent 68%);
}

.aurora-teal .aurora-blob-a {
  background: radial-gradient(circle, rgb(20 184 166 / 0.3), transparent 68%);
}

.aurora-teal .aurora-blob-b {
  background: radial-gradient(circle, rgb(139 92 246 / 0.24), transparent 68%);
}

.aurora-teal .aurora-blob-c {
  background: radial-gradient(circle, rgb(244 63 94 / 0.22), transparent 68%);
}

.aurora-spotlight {
  position: absolute;
  inset: 0;
  background: radial-gradient(26rem circle at var(--mx) var(--my), rgb(244 63 94 / 0.1), transparent 68%);
}

.aurora-teal .aurora-spotlight {
  background: radial-gradient(26rem circle at var(--mx) var(--my), rgb(20 184 166 / 0.12), transparent 68%);
}

.aurora-fade {
  position: absolute;
  inset: auto 0 0;
  height: 14rem;
  background: linear-gradient(to bottom, transparent, #f8fafc);
}

.dark .aurora-blob {
  filter: blur(80px);
}

.dark .aurora-rose .aurora-blob-a {
  background: radial-gradient(circle, rgb(244 63 94 / 0.2), transparent 68%);
}

.dark .aurora-rose .aurora-blob-b {
  background: radial-gradient(circle, rgb(251 146 60 / 0.16), transparent 68%);
}

.dark .aurora-rose .aurora-blob-c {
  background: radial-gradient(circle, rgb(20 184 166 / 0.16), transparent 68%);
}

.dark .aurora-teal .aurora-blob-a {
  background: radial-gradient(circle, rgb(20 184 166 / 0.2), transparent 68%);
}

.dark .aurora-teal .aurora-blob-b {
  background: radial-gradient(circle, rgb(139 92 246 / 0.18), transparent 68%);
}

.dark .aurora-teal .aurora-blob-c {
  background: radial-gradient(circle, rgb(244 63 94 / 0.15), transparent 68%);
}

.dark .aurora-spotlight {
  background: radial-gradient(26rem circle at var(--mx) var(--my), rgb(244 63 94 / 0.08), transparent 68%);
}

.dark .aurora-teal .aurora-spotlight {
  background: radial-gradient(26rem circle at var(--mx) var(--my), rgb(20 184 166 / 0.09), transparent 68%);
}

.dark .aurora-fade {
  background: linear-gradient(to bottom, transparent, #020617);
}

@keyframes aurora-drift-a {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(4rem, 2.5rem) scale(1.12); }
}

@keyframes aurora-drift-b {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(-3.5rem, 3rem) scale(1.08); }
}

@keyframes aurora-drift-c {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(2.5rem, -2rem) scale(1.15); }
}

@media (prefers-reduced-motion: reduce) {
  .aurora-blob {
    animation: none;
  }
}
</style>
