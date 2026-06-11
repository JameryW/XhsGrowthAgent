# Fix Liquid Glass Effect Visibility

## Goal

Make the Apple liquid glass design system actually visible — currently `backdrop-filter` produces no perceptible glass effect because background mesh colors are too faint to transmit through the glass layers.

## What I already know

* CSS classes are defined and applied across 20+ Vue files — the plumbing works
* `liquid-mesh-bg` provides 3 animated gradient blobs (rose 0.06, teal 0.06, violet 0.05 opacity)
* `.liquid-glass` base class uses `rgba(255,255,255,0.55)` fill + `blur(40px) saturate(180%) brightness(110%)`
* Background base color is `#f0f2f5` (near-white gray)
* Result: blur on nearly-white background = uniform white, no visible glass refraction

## Root Causes

1. **Mesh blob opacity too low** (0.05-0.06) — colors vanish after blur
2. **White fill too thick** (0.55 opacity) — blocks remaining color transmission
3. **`brightness(110%)`** washes out whatever faint color survives blur
4. **Missing Apple-specific glass features** — no specularity highlights, no edge refraction, no chromatic aberration hints

## Assumptions (temporary)

* Want a recognizable "Apple liquid glass" aesthetic, not just a generic frosted glass
* Pages should feel translucent — you can sense the mesh colors through the glass
* Dark mode is not in scope for this fix

## Open Questions

* (none currently blocking)

## Decision (ADR-lite)

**Context**: Glass effect currently invisible — backdrop-filter on near-white background produces uniform white, no refraction visible.
**Decision**: Mixed strategy — cards/panels use light transmission (readability first), Navbar/Hero areas use stronger refraction (visual impact first).
**Consequences**: Need two tiers of glass opacity values; card surfaces stay readable while nav/deep surfaces show dramatic color bleed.

## Requirements

* Two-tier glass system: **light** (cards, panels) and **strong** (nav, hero, deep)
* Light tier: mesh opacity ~0.18, white fill ~0.38, gentle color bleed, text-first readability
* Strong tier: mesh opacity ~0.25, white fill ~0.30, visible color refraction through glass
* Add Apple-style specularity: top-edge light streak (`inset 0 1px 0 rgba(255,255,255,0.5)`) — already exists, enhance with subtle gradient border
* Reduce/remove `brightness()` — drop to 0% or max 105% on light tier
* All tinted variants (rose/teal/violet/amber) keep their tint but increase base opacity slightly
* Maintain readability on all surfaces

## Acceptance Criteria (evolving)

* [ ] Glass cards (light tier) show subtle color bleed — rose/teal/violet hues faintly visible through glass, text fully readable
* [ ] Nav/hero (strong tier) show obvious color refraction — "colors flowing behind glass" feel
* [ ] Specularity effect visible on all glass surfaces (top-edge light streak, subtle border glow)
* [ ] Tinted variants (rose/teal/violet/amber) keep distinct hue character
* [ ] No regression on mobile/tablet layouts

## Definition of Done

* Lint / typecheck green
* Visual verification on Home, Dashboard, WorkflowReplay pages
* Cards.css + main.css changes are self-consistent

## Out of Scope

* Dark mode glass variants
* New glass variant classes
* Refactoring class naming scheme

## Technical Notes

* Key files: `frontend/src/styles/main.css` (lines 86-180), `frontend/src/styles/cards.css` (lines 8-21), `frontend/src/App.vue` (liquid-mesh-bg div at line 120)
* Mesh blob CSS: `.liquid-mesh-bg::before` (rose), `::after` (teal), inline div (violet) in App.vue
* Apple liquid glass reference: translucent surface + background color bleed + specular edge highlights + subtle chromatic tint at borders