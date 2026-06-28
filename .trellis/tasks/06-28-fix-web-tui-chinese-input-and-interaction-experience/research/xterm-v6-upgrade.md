# Research: xterm.js v5 to @xterm/xterm v6 Upgrade

- **Query**: Breaking changes when upgrading from xterm@5 to @xterm/xterm@6, addon compatibility, import path changes, new features, mobile/touch support
- **Scope**: External (npm registry, GitHub releases, type definitions)
- **Date**: 2026-06-28

## Findings

### 1. Import Path Changes

The package was migrated to the `@xterm` scope in v5.4.0. The old `xterm` package (last version 5.3.0) is **deprecated** on npm with the message: "This package is now deprecated. Move to @xterm/xterm instead."

| Old Import | New Import (v6) |
|---|---|
| `import { Terminal } from 'xterm'` | `import { Terminal } from '@xterm/xterm'` |
| `import 'xterm/css/xterm.css'` | `import '@xterm/xterm/css/xterm.css'` |
| `import { FitAddon } from '@xterm/addon-fit'` | Same (no change) |
| `import { WebLinksAddon } from '@xterm/addon-web-links'` | Same (no change) |

The CSS path in the package's `style` field is `css/xterm.css` in both v5 and v6, so the resolved path becomes `@xterm/xterm/css/xterm.css`.

**Package name changes:**
- `xterm` -> `@xterm/xterm` (deprecated since v5.4.0, but v6 is only published under `@xterm/xterm`)
- `xterm-addon-*` -> `@xterm/addon-*` (changed in v5.4.0)

### 2. Breaking Changes in v6.0.0

#### 2a. Removed Options (ITerminalOptions)

| Removed Option | Replacement | Notes |
|---|---|---|
| `windowsMode: boolean` | `windowsPty: { backend, buildNumber }` | Was deprecated in v5, now removed (#5462) |
| `fastScrollModifier: 'none' \| 'alt' \| 'ctrl' \| 'shift'` | No direct replacement | Was deprecated in v5, now removed (#5462). Use `attachCustomWheelEventHandler` for custom scroll behavior |
| `overviewRulerWidth: number` | `overviewRuler?.width` | Now a sub-property of `overviewRuler` object (#5107) |

**New options in v6 (not in v5.5.0):**
- `reflowCursorLine?: boolean` - Whether to reflow the cursor line when the terminal is resized (#5234)
- `overviewRuler?: IOverviewRulerOptions` - Object with `width`, `showTopBorder`, `showBottomBorder` properties (#5107)

#### 2b. Canvas Renderer Removed (#5105)

**The `@xterm/addon-canvas` addon no longer exists in v6.** The recommendation is to use either the DOM renderer (default) or the WebGL renderer (`@xterm/addon-webgl`).

Rationale: Since the DOM renderer was significantly improved in v5.3.0 (#4605) and WebGL2 has shipped in Safari/WebKit, the canvas renderer is no longer needed as a fallback. This removes ~1-2k lines of maintenance code.

**Impact on this project:** The task planned to add `@xterm/addon-canvas` as a fallback renderer. This is NOT possible in v6. Use `@xterm/addon-webgl` with automatic fallback to the DOM renderer instead.

#### 2c. Viewport/Scrollbar Overhaul (#5096)

The viewport and scrollbar have been completely replaced with VS Code's `DomScrollableElement`. This is a "potential breaking change" because:
- The scrollbar works very differently (VS Code-style overlay scrollbar)
- New CSS classes: `.xterm-scrollable-element > .scrollbar`, `.xterm-scrollable-element > .visible`, etc.
- CSS variables like `--vscode-scrollbar-shadow` are used
- The old `.xterm-scroll-area` element is gone
- The v6 CSS file grew from 218 lines (v5.5.0) to 285 lines

**Impact:** Any custom CSS targeting `.xterm-viewport` or `.xterm-scroll-area` may need updating. The new scrollbar is more reliable and has better UX.

#### 2d. Alt -> Ctrl+Arrow Hack Removed (#5346)

The built-in mapping of Alt+arrow to Ctrl+arrow (word navigation) has been removed. If this behavior is desired, it must be implemented in application code by handling `onKey` events.

**Impact on this project:** The AgentTUI handles input via `onData`, not `onKey`, and implements its own cursor movement. This change likely has no impact since the project doesn't rely on Alt+arrow word navigation.

#### 2e. EventEmitter Replaced with VS Code's Emitter (#5104)

Internal `EventEmitter` class replaced with `vs/base/common/event`'s `Emitter`. The public `IEvent<T, U>` interface signature is unchanged in the type definitions, so this is an internal change that should not affect consumers.

#### 2f. ESM Support (#5092)

v6 ships an ESM build via `lib/xterm.mjs` (the `module` field in package.json). v5.4.0 did not have a `module` field. This enables tree-shaking and better bundler integration.

### 3. Addon Compatibility

#### Current Project Addons

| Addon | Current Version | v6-Compatible Version | Status |
|---|---|---|---|
| `@xterm/addon-fit` | `^0.11.0` | `0.11.0` | **Compatible** - latest stable has no peerDeps constraint. However, the v6 FitAddon source uses `overviewRuler?.width` instead of `overviewRulerWidth`, so v0.11.0 may not work correctly with v6's new overviewRuler structure. The v6 release does NOT include a compatible addon version table. |
| `@xterm/addon-web-links` | `^0.12.0` | `0.12.0` | **Compatible** - latest stable has no peerDeps constraint. |

**Important caveat:** The v6.0.0 release notes do NOT include a "Compatible addon versions" table (unlike v5.4.0 and v5.5.0). The latest stable addon versions on npm (fit@0.11.0, web-links@0.12.0) have empty `peerDependencies`, meaning they don't enforce xterm version compatibility. However, the v6 FitAddon source code references `overviewRuler?.width` which is a v6-only API, so the published fit@0.11.0 may be the v6-compatible version already.

#### Planned New Addons

| Addon | v6-Compatible Version | Notes |
|---|---|---|
| `@xterm/addon-search` | `0.16.0` (stable) | Latest stable. Has `onDidChangeResults` event, `findNext`/`findPrevious`/`clearDecorations`/`clearActiveDecoration` methods. Constructor accepts `ISearchAddonOptions` with `highlightLimit`. |
| `@xterm/addon-webgl` | `0.19.0` (stable) | Latest stable. Constructor accepts `preserveDrawingBuffer?: boolean`. Has `onContextLoss`, `onChangeTextureAtlas`, `onAddTextureAtlasCanvas`, `onRemoveTextureAtlasCanvas` events. |
| `@xterm/addon-canvas` | **REMOVED in v6** | This addon does not exist for v6. Use DOM renderer (default) or WebGL instead. |

#### New Addons in v6

| Addon | Version | Description |
|---|---|---|
| `@xterm/addon-progress` | `0.2.0` | ConEmu progress sequence support (OSC 9;4). Tracks progress state (none/normal/error/indeterminate/pause) and value (0-100). |
| `@xterm/addon-clipboard` | `0.2.0` | System clipboard access via OSC 52 sequence. Supports system and primary clipboard selections. |

#### Beta Addons (for upcoming v6.1.0)

The following addon versions exist in beta and require `@xterm/xterm ^6.1.0-beta.*`:
- `@xterm/addon-fit@0.9.0-beta.*` (peerDeps: `@xterm/xterm ^5.0.0` - confusingly still v5)
- `@xterm/addon-web-links@0.13.0-beta.*` (peerDeps: `@xterm/xterm ^6.1.0-beta.*`)
- `@xterm/addon-search@0.17.0-beta.*` (peerDeps: `@xterm/xterm ^6.1.0-beta.*`)
- `@xterm/addon-webgl@0.20.0-beta.*` (peerDeps: `@xterm/xterm ^6.1.0-beta.*`)
- `@xterm/addon-canvas@0.8.0-beta.*` (peerDeps: `@xterm/xterm ^5.0.0` - still v5, likely abandoned)

### 4. IME (Input Method Editor) Fixes

#### In v6.0.0 (stable)

- **PR #5024**: "Fix duplicate input for some IMEs" - Fixes issue #5023 (Chinese input methods like Wubi producing duplicate characters). The fix removes the assumption that "the end position is stable" during composition, instead using the start position of the new composition as the end position of the previous composition. **This fix is NOT in v5.5.0** (merged 2024-04-08, after v5.5.0 release on 2024-04-05).

#### In v6.1.0-beta (not yet stable, merged to master)

Multiple additional IME improvements merged on 2026-03-11:
- **PR #5759**: "fix(ime): resync textarea position when composition starts" - Merged to master
- **PR #5743**: "fix(input): anchor IME composition to textarea cursor" - Uses textarea caret position instead of value.length
- **PR #5762**: "Fix RTL breaking IME composition rendering" - Merged to master
- **PR #5738**: "feat: support voice IMEs that update input via tail replacement" - For mobile voice IME flows
- **PR #5616**: "Fix IME composition overflow at right edge" - Not merged

These are all in the 6.1.0-beta stream and NOT yet in a stable release.

### 5. New Features in v6 Beyond IME Fix

| Feature | PR | Description |
|---|---|---|
| Synchronized Output (DEC mode 2026) | #5453 | BSU/ESU sequences allow batching terminal updates and rendering atomically, preventing screen tearing during rapid output. Safety timeout of 1 second auto-flushes. |
| ESM Support | #5092 | Ships `lib/xterm.mjs` via `module` field. Core ESM bundle reduced from 285KB to 253KB. |
| VS Code Scrollbar | #5096 | New overlay scrollbar from VS Code's `DomScrollableElement`. More reliable, better UX. |
| Shadow DOM in WebGL | #5334 | WebGL renderer now works inside Shadow DOM |
| Detailed Ligatures & Variants | #5285 | `fontFeatureSettings` option in ligatures addon. WebGL texture atlas inherits CSS `font-feature-settings`. |
| Progress Addon | #5251 | New `@xterm/addon-progress` for ConEmu progress sequences |
| Reflow Cursor Line | #5234 | New `reflowCursorLine` option to reflow cursor line on resize |
| PuTTY-style ED2 | #5224 | PuTTY-style ED2 sequence handling as terminal option |
| Overview Ruler Borders | #5107 | `overviewRuler.showTopBorder` and `showBottomBorder` options |
| OSC 52 Clipboard | #4220 | ANSI OSC52 sequence support for clipboard manipulation (via `@xterm/addon-clipboard`) |
| onWriteParsed | #5034 | New `onWriteParsed` event on Terminal API |
| CapsLock Fix (macOS) | #5282 | Fixed CapsLock triggering input twice on macOS |
| Make textarea readonly when disableStdin | #5263 | When `disableStdin` is set, the textarea becomes readonly |

### 6. Mobile/Touch Support

**v6 does NOT have significantly improved mobile/touch support compared to v5.** Specific findings:

- The VS Code scrollbar integration (#5096) may improve touch scrolling behavior since VS Code's `DomScrollableElement` is more robust, but this was not an explicit goal.
- WebGL2 now works in Safari (since Safari shipped WebGL2 support), which means the WebGL renderer is available on iOS/Safari. This was previously a major limitation that required the canvas renderer fallback.
- The canvas renderer removal (#5105) was justified partly because "webgl2 has shipped in Safari/WebKit", meaning iOS/Safari now has a GPU-accelerated renderer option.
- Voice IME support (#5738, in 6.1.0-beta) specifically targets "mobile browsers" where voice IMEs update input via tail replacement.
- No dedicated mobile/touch issue or PR was found in the v6 release.
- Touch scrolling on mobile remains a known limitation (issue #747 from 2017 is still open).

### 7. Project-Specific Impact Assessment

Current `AgentTUI.vue` uses these xterm APIs:

| API Call | v6 Compatibility | Notes |
|---|---|---|
| `new Terminal({...})` | Compatible | All used options (`cursorBlink`, `cursorStyle`, `fontSize`, `fontFamily`, `theme`, `allowProposedApi`, `scrollback`, `convertEol`) exist in v6 |
| `term.loadAddon(fitAddon)` | Compatible | No change |
| `term.loadAddon(new WebLinksAddon())` | Compatible | No change |
| `term.open(element)` | Compatible | No change |
| `fitAddon.fit()` | Compatible | No change |
| `term.onData(handler)` | Compatible | No change |
| `term.write(data)` | Compatible | No change |
| `term.writeln(data)` | Compatible | No change |
| `term.clear()` | Compatible | No change |
| `term.dispose()` | Compatible | No change |
| `import 'xterm/css/xterm.css'` | **Must change** | -> `import '@xterm/xterm/css/xterm.css'` |
| `import { Terminal } from 'xterm'` | **Must change** | -> `import { Terminal } from '@xterm/xterm'` |

**No used options are removed in v6.** The project does not use `windowsMode`, `fastScrollModifier`, or `overviewRulerWidth`.

### 8. Recommended Package Versions for v6 Upgrade

```json
{
  "@xterm/xterm": "^6.0.0",
  "@xterm/addon-fit": "^0.11.0",
  "@xterm/addon-web-links": "^0.12.0",
  "@xterm/addon-search": "^0.16.0",
  "@xterm/addon-webgl": "^0.19.0"
}
```

**Do NOT use `@xterm/addon-canvas`** - it is removed in v6. Use WebGL with DOM fallback instead.

## External References

- [xterm.js v6.0.0 Release](https://github.com/xtermjs/xterm.js/releases/tag/6.0.0) (2025-12-22)
- [xterm.js v5.4.0 Release - Package Scope Migration](https://github.com/xtermjs/xterm.js/releases/tag/5.4.0) (2024-03-01)
- [PR #5024 - Fix duplicate input for some IMEs](https://github.com/xtermjs/xterm.js/pull/5024)
- [Issue #5023 - Duplicate input when using Chinese input methods](https://github.com/xtermjs/xterm.js/issues/5023)
- [PR #5105 - Remove the canvas renderer](https://github.com/xtermjs/xterm.js/pull/5105)
- [Issue #4779 - Remove the canvas renderer addon](https://github.com/xtermjs/xterm.js/issues/4779)
- [PR #5096 - Integrate base/ platform from VS Code and adopt scroll bar](https://github.com/xtermjs/xterm.js/pull/5096)
- [PR #5107 - Add top/bottom border overview ruler options](https://github.com/xtermjs/xterm.js/pull/5107)
- [PR #5346 - Remove alt -> ctrl+arrow hack](https://github.com/xtermjs/xterm.js/pull/5346)
- [PR #5462 - Remove deprecated windowsMode and fastScrollModifier](https://github.com/xtermjs/xterm.js/pull/5462)
- [PR #5104 - Remove EventEmitter in favor of vs/base Emitter](https://github.com/xtermjs/xterm.js/pull/5104)
- [PR #5453 - Add synchronized output support (DEC mode 2026)](https://github.com/xtermjs/xterm.js/pull/5453)
- [PR #5092 - Add support for ESM via esbuild](https://github.com/xtermjs/xterm.js/pull/5092)
- [PR #4220 - Add support to ANSI OSC52](https://github.com/xtermjs/xterm.js/pull/4220)
- [npm: @xterm/xterm](https://www.npmjs.com/package/@xterm/xterm)
- [npm: xterm (deprecated)](https://www.npmjs.com/package/xterm)

## Caveats / Not Found

1. **No official migration guide** exists for v5 -> v6. The breaking changes must be inferred from the release notes and PR descriptions.
2. **v6.0.0 release lacks addon compatibility table** - unlike v5.4.0 and v5.5.0, the v6.0.0 release does not include a "Compatible addon versions" section. The stable addon versions on npm have empty `peerDependencies`, making it unclear which versions were tested with v6.
3. **6.1.0-beta has significant IME improvements** (5+ PRs merged 2026-03-11) that are NOT yet in a stable release. If Chinese IME is a primary concern, the project may need to track the 6.1.0-beta or wait for 6.1.0 stable.
4. **FitAddon v0.11.0 compatibility with v6 is uncertain** - the v6 source code for FitAddon uses `overviewRuler?.width` (v6 API), but the published npm version may or may not include this change. Testing is required.
5. **No dedicated mobile/touch improvements** in v6 beyond the indirect benefit of WebGL2 working in Safari.
