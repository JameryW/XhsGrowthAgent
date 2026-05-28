<!-- frontend/src/components/CelebrationEffect.vue -->
<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, computed } from 'vue'

/**
 * CelebrationEffect component
 * Canvas-based visual celebration effects (confetti, pulse, stars)
 */

interface Props {
  /** Whether the effect is active */
  isActive: boolean
  /** Type of celebration effect */
  type?: 'confetti' | 'pulse' | 'stars'
  /** Duration in milliseconds */
  duration?: number
}

const props = withDefaults(defineProps<Props>(), {
  type: 'confetti',
  duration: 3000
})

const canvasRef = ref<HTMLCanvasElement | null>(null)
const animationFrameId = ref<number | null>(null)
const startTime = ref<number>(0)

// Particle system for confetti
interface Particle {
  x: number
  y: number
  vx: number
  vy: number
  color: string
  size: number
  rotation: number
  rotationSpeed: number
  opacity: number
}

const particles = ref<Particle[]>([])

// Star system
interface Star {
  x: number
  y: number
  size: number
  opacity: number
  twinkleSpeed: number
  twinklePhase: number
}

const stars = ref<Star[]>([])

// Pulse ring system
interface PulseRing {
  x: number
  y: number
  radius: number
  maxRadius: number
  opacity: number
  color: string
}

const pulseRings = ref<PulseRing[]>([])

// Colors for effects
const COLORS = ['#f43f5e', '#8b5cf6', '#14b8a6', '#f59e0b', '#3b82f6', '#22c55e', '#ec4899']

// Initialize particles for confetti
function initConfetti(width: number, height: number) {
  const count = 50
  particles.value = []

  for (let i = 0; i < count; i++) {
    particles.value.push({
      x: Math.random() * width,
      y: -20 - Math.random() * height * 0.5,
      vx: (Math.random() - 0.5) * 4,
      vy: Math.random() * 3 + 2,
      color: COLORS[Math.floor(Math.random() * COLORS.length)],
      size: Math.random() * 8 + 4,
      rotation: Math.random() * 360,
      rotationSpeed: (Math.random() - 0.5) * 10,
      opacity: 1
    })
  }
}

// Initialize stars
function initStars(width: number, height: number) {
  const count = 30
  stars.value = []

  for (let i = 0; i < count; i++) {
    stars.value.push({
      x: Math.random() * width,
      y: Math.random() * height,
      size: Math.random() * 20 + 10,
      opacity: 0,
      twinkleSpeed: Math.random() * 2 + 1,
      twinklePhase: Math.random() * Math.PI * 2
    })
  }
}

// Initialize pulse rings
function initPulse(width: number, height: number) {
  pulseRings.value = []

  const centerX = width / 2
  const centerY = height / 2

  for (let i = 0; i < 5; i++) {
    pulseRings.value.push({
      x: centerX,
      y: centerY,
      radius: 0,
      maxRadius: Math.min(width, height) / 2,
      opacity: 1 - i * 0.15,
      color: COLORS[i % COLORS.length]
    })
  }
}

// Draw confetti
function drawConfetti(ctx: CanvasRenderingContext2D, progress: number) {
  const width = ctx.canvas.width
  const height = ctx.canvas.height

  ctx.clearRect(0, 0, width, height)

  particles.value.forEach((p) => {
    // Update position
    p.x += p.vx
    p.y += p.vy
    p.rotation += p.rotationSpeed
    p.opacity = Math.max(0, 1 - progress)

    // Draw particle
    ctx.save()
    ctx.translate(p.x, p.y)
    ctx.rotate(p.rotation * Math.PI / 180)
    ctx.globalAlpha = p.opacity
    ctx.fillStyle = p.color

    // Draw rectangle confetti
    ctx.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2)

    ctx.restore()
  })
}

// Draw stars
function drawStars(ctx: CanvasRenderingContext2D, progress: number) {
  const width = ctx.canvas.width
  const height = ctx.canvas.height

  ctx.clearRect(0, 0, width, height)

  stars.value.forEach((s) => {
    // Update twinkle
    s.twinklePhase += s.twinkleSpeed * 0.05
    s.opacity = Math.max(0, Math.min(1, (Math.sin(s.twinklePhase) + 1) / 2 * (1 - progress * 0.5)))

    // Draw star
    ctx.save()
    ctx.translate(s.x, s.y)
    ctx.globalAlpha = s.opacity
    ctx.fillStyle = '#f59e0b' // Gold stars

    // 5-pointed star
    ctx.beginPath()
    for (let i = 0; i < 5; i++) {
      const angle = (i * 4 * Math.PI) / 5 - Math.PI / 2
      const x = Math.cos(angle) * s.size
      const y = Math.sin(angle) * s.size
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.closePath()
    ctx.fill()

    ctx.restore()
  })
}

// Draw pulse rings
function drawPulse(ctx: CanvasRenderingContext2D, progress: number) {
  const width = ctx.canvas.width
  const height = ctx.canvas.height

  ctx.clearRect(0, 0, width, height)

  pulseRings.value.forEach((ring, i) => {
    // Update radius
    const ringProgress = Math.max(0, progress - i * 0.1)
    ring.radius = ring.maxRadius * ringProgress
    ring.opacity = Math.max(0, 1 - ringProgress)

    // Draw ring
    ctx.beginPath()
    ctx.arc(ring.x, ring.y, ring.radius, 0, Math.PI * 2)
    ctx.strokeStyle = ring.color
    ctx.lineWidth = 3
    ctx.globalAlpha = ring.opacity
    ctx.stroke()
  })
}

// Animation loop
function animate(timestamp: number) {
  if (!canvasRef.value) return

  const ctx = canvasRef.value.getContext('2d')
  if (!ctx) return

  const elapsed = timestamp - startTime.value
  const progress = Math.min(elapsed / props.duration, 1)

  // Draw based on type
  switch (props.type) {
    case 'confetti':
      drawConfetti(ctx, progress)
      break
    case 'stars':
      drawStars(ctx, progress)
      break
    case 'pulse':
      drawPulse(ctx, progress)
      break
  }

  // Continue animation if not complete
  if (progress < 1 && props.isActive) {
    animationFrameId.value = requestAnimationFrame(animate)
  } else {
    // Clear canvas when done
    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height)
    animationFrameId.value = null
  }
}

// Start animation
function startAnimation() {
  if (!canvasRef.value) return

  const width = canvasRef.value.width
  const height = canvasRef.value.height

  // Initialize based on type
  switch (props.type) {
    case 'confetti':
      initConfetti(width, height)
      break
    case 'stars':
      initStars(width, height)
      break
    case 'pulse':
      initPulse(width, height)
      break
  }

  startTime.value = performance.now()
  animationFrameId.value = requestAnimationFrame(animate)
}

// Stop animation
function stopAnimation() {
  if (animationFrameId.value !== null) {
    cancelAnimationFrame(animationFrameId.value)
    animationFrameId.value = null
  }

  // Clear canvas
  if (canvasRef.value) {
    const ctx = canvasRef.value.getContext('2d')
    if (ctx) {
      ctx.clearRect(0, 0, canvasRef.value.width, canvasRef.value.height)
    }
  }
}

// Watch isActive prop
watch(
  () => props.isActive,
  (active) => {
    if (active) {
      startAnimation()
    } else {
      stopAnimation()
    }
  }
)

// Setup canvas on mount
onMounted(() => {
  if (canvasRef.value) {
    // Set canvas size to parent container
    const parent = canvasRef.value.parentElement
    if (parent) {
      canvasRef.value.width = parent.clientWidth || 300
      canvasRef.value.height = parent.clientHeight || 200
    }
  }
})

// Cleanup on unmount
onUnmounted(() => {
  stopAnimation()
})

// Expose for testing
defineExpose({
  canvasRef,
  particles,
  stars,
  pulseRings,
  animationFrameId
})
</script>

<template>
  <div class="celebration-effect">
    <canvas
      ref="canvasRef"
      class="celebration-canvas"
      :class="{ 'is-active': props.isActive }"
    />
  </div>
</template>

<style scoped>
.celebration-effect {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
  pointer-events: none;
}

.celebration-canvas {
  width: 100%;
  height: 100%;
  opacity: 0;
  transition: opacity 0.2s ease-out;
}

.celebration-canvas.is-active {
  opacity: 1;
}
</style>