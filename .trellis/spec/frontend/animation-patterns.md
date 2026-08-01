# Frontend Animation & Motion Patterns

> Conventions for CSS/Vue animations and `prefers-reduced-motion` handling.

---

## Gotcha: `animation-fill-mode: backwards` + `animation-delay` under reduced-motion

**Symptom**: Elements with a staggered entrance animation stay **invisible** when the user has `prefers-reduced-motion: reduce` enabled — they only appear after the full `animation-delay` elapses (e.g. up to ~420ms for an 8-card stagger), then snap in.

**Cause**: A common reduced-motion override is the blanket rule:

```css
@media (prefers-reduced-motion: reduce) {
  .page :deep(*) {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

This shrinks the **duration** but does **not** cancel `animation-delay`. With `animation-fill-mode: backwards`, the element holds the `from` keyframe (e.g. `opacity: 0; transform: translateY(14px)`) for the entire delay window before the 0.01ms animation runs. Result: the element is stuck at the invisible `from` state for the delay duration.

**Fix**: Explicitly nullify the animation on entrance-animated elements inside the reduced-motion block:

```css
@media (prefers-reduced-motion: reduce) {
  .page :deep(*) {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
  /* Entrance-animated elements: kill the animation entirely so they render at
     their natural (visible) state immediately, no delay-hold. */
  .staggered-card,
  .node-sweep {
    animation: none !important;
  }
}
```

> **Warning**: Any element that uses `animation-fill-mode: backwards` (or `both`) **and** `animation-delay` for an entrance effect must be listed in an explicit `animation: none !important` reduced-motion rule. The blanket `:deep(*)` duration override alone is not enough.

**Prevention**: When adding a staggered/entrance animation, audit the reduced-motion block the same commit and add the element to the explicit `animation: none` list.

---

## Convention: Global reduced-motion registry in `main.css`

**What**: All blanket reduced-motion degradation lives in a single
`@media (prefers-reduced-motion: reduce)` block in `src/styles/main.css`.
It currently covers:

- Tailwind animated utilities: `animate-pulse`, `animate-spin`, `animate-spin-slow`.
- Component-level custom animation classes: `scale-bounce-animation`, `mesh-drift-3`, and Review's scoped loading spinner `.spin` (`@keyframes review-spin`).
- Modal scale/fade transitions (`.modal-enter-active` / `.modal-leave-active`), killed via `transition: none`.
- `html { scroll-behavior }`, downgraded to `auto`.

**Rule for new animations**: register the new class name in that block in the
same commit — do **not** write a per-component media query. Per-component
entrance animations that use `animation-delay` + `fill-mode: backwards` still
need their explicit `animation: none` entry (see the delay-hold gotcha above);
the registry is the single place where both kinds live.

**JS side**: `scrollIntoView` and other smooth-scroll calls must choose
`behavior` via `useReducedMotion()` (`prefersReduced ? 'auto' : 'smooth'`,
see `AccountScopeBar.vue`) instead of hardcoding `'smooth'`.

---

## Pattern: Initial count-up with `AnimatedCounter.vue`

**Problem**: `AnimatedCounter.vue` watches its `value` prop and animates from the previous value to the new one — but it **skips animation when `oldValue === undefined`** (the initial mount). So binding `:value="stats.total"` directly renders the final number with no count-up on first paint.

**Solution**: Seed the prop at `0` and flip a `ready` flag via `nextTick()` after the data loads, so the prop transitions `0 → actual` and triggers the rAF animation.

```vue
<script setup lang="ts">
import { ref, nextTick } from 'vue'
import AnimatedCounter from '@/components/AnimatedCounter.vue'

const statsReady = ref(false)

async function fetchData() {
  // ... populate stats ...
  await nextTick()
  statsReady.value = true   // 0 → actual transition fires the count-up
}
</script>

<template>
  <!-- Binds 0 until ready, then the real value → AnimatedCounter animates -->
  <AnimatedCounter :value="statsReady ? stats.total : 0" :duration="800" />
</template>
```

**Why**: The `watch` in `AnimatedCounter` has `{ immediate: false }` and an `oldValue === undefined` guard. The `0 → actual` change is the first real prop transition, so it animates. Setting `statsReady` synchronously (without `nextTick`) can batch in the same render as the data update and still read as the initial value; `nextTick` guarantees the `0` state is committed first.

**Related**: `composables/useAnimation.ts` exposes `animatedCounter(start, end, duration, onUpdate)` for cases where you need direct control outside the component.

---

## Convention: SMIL vs CSS for continuous motion

**What**: Prefer CSS keyframe animations over SVG SMIL (`<animate>`, `<animateMotion>`) for continuous/looping motion, especially when many run concurrently.

**Why**: Multiple concurrent SMIL animations (e.g. a comet `animateMotion` + several `<animate>` energy pulses) are harder for browsers to optimize and can cause jank on lower-end devices. CSS keyframe animations are compositor-friendly and cheaper to batch.

**Example**: The Showcase closed-loop replaced six SMIL `<animate>` node-energy pulses with a single CSS `@keyframes` "sweep" ring per node (staggered `animation-delay`), keeping the SMIL `animateMotion` comet as the one path-following element.

**When to keep SMIL**: Path-following motion (`animateMotion` along an SVG `<path>`) is still reasonable to keep as SMIL unless you want `offset-path` (CSS) — convert only when profiling shows cost.

---

## Pattern: Ambient background layering without visual emptiness

**Problem**: Adding many background layers (glow orbs, dot grid, aurora, particles) can still read as "empty" if each layer is independently weak and they dilute each other — symptom: layer count looks rich in code, but the rendered page has large dead areas.

**Causes** (any combination):
- Each layer's `opacity` set low (≤0.5) "to be safe" → all layers cancel out.
- A `mask-image` restricting a layer to a small region (e.g. dots only visible in top 30%) leaves the rest bare.
- Few-particle layers (`background-repeat: no-repeat` with only 5 `radial-gradient` points) → sparse coverage.
- Heavy `filter: blur(70px)` on a low-opacity conic/aurora → washes the color out entirely.

**Solution — balance opacity budget, add structure**:
1. **Raise opacity per layer** into the 0.6–0.75 band (don't cap everything at 0.5).
2. **Remove or widen masks** so texture covers the whole page; if you want fade, use a `linear-gradient` edge fade, not a small central ellipse.
3. **Dense up particle/point layers** to ~20 positions spread across the viewport, not 5.
4. **Reduce blur on color layers** (70px → 40–48px) so hue survives the blur at low opacity.
5. **Add structural layers** (fine grid, constellation lines, mesh blobs) — these give the eye a "skeleton" so the page reads as composed, not just lit. Pure light/blob layers read as empty even when bright.

**Example**: The Showcase background went from 5 sparse particles + mask-limited dots + blur(70px) aurora (read empty) → 20 particles + whole-page grid + constellation SVG + mesh blobs + blur(44px) aurora at opacity 0.65 (reads layered). Same layer count, rebalanced budget + added structure.

**Anti-pattern**: "I'll keep all layers at opacity 0.4 to be subtle." This is the direct cause of the empty look — subtlety is per-layer calibration, not a universal cap.

**Related**: every new ambient layer still needs an explicit `animation: none` (or static opacity) entry in the `prefers-reduced-motion` block — the blanket `:deep(*)` duration override does not cover `opacity` animation or `transform` drift.
