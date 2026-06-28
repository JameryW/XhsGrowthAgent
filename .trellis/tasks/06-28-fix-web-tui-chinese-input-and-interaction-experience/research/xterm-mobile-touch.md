# Research: xterm.js Mobile Touch Input and Responsive Layout

- **Query**: How does xterm.js handle touch events on mobile devices? What are the common problems with xterm.js on mobile (soft keyboard, viewport resize, touch input)? What CSS/layout patterns work for responsive terminal UIs? How to handle the mobile soft keyboard with xterm.js hidden textarea and IME? Are there xterm.js configuration options specifically for mobile? What's the best approach for a command input on mobile: keep xterm-only, or add a separate mobile-friendly input bar?
- **Scope**: Mixed (external: xterm.js GitHub issues/source + internal codebase)
- **Date**: 2026-06-28

## Findings

### 1. xterm.js Touch Event Handling

xterm.js **does have built-in touch gesture handling**, but it is limited to scrolling only. There is no native support for touch selection, long-press, double-tap word selection, or pinch-to-zoom.

**Internal architecture (from source):**

xterm.js uses a `Gesture` class (`src/browser/scrollable/touch.ts`) that wraps raw `touchstart`/`touchmove`/`touchend` events into higher-level gesture events:

| Gesture Event | Trigger | What It Does |
|---|---|---|
| `EventType.START` | `touchstart` | Records initial touch position |
| `EventType.CHANGE` | `touchmove` | Calculates `translationX`/`translationY` for scroll |
| `EventType.TAP` | `touchend` (short hold, small movement) | Single tap -- currently unused by terminal |
| `EventType.CONTEXT_MENU` | `touchend` (long hold >= 700ms, small movement) | Long-press context menu -- currently unused by terminal |
| `EventType.END` | `touchend` | Touch ended |

The `MouseService` (`src/browser/services/MouseService.ts`) handles these gesture events:

```
_handleTouchChange(ctx, e):
  1. If mouse protocol has wheel events active -> send as mouse wheel events
  2. If in alt buffer (no scrollback) -> send as up/down arrow key sequences
  3. Otherwise -> delegate to Viewport.handleTouchScroll(translationY) for native scrolling
```

**What works:**
- Touch scrolling in scrollback buffer (normal mode)
- Touch scrolling sending arrow keys in alt buffer (e.g., Midnight Commander)
- Touch scrolling sending mouse wheel events when mouse protocol is active
- Inertia-based momentum scrolling (friction coefficient -0.005)

**What does NOT work:**
- Touch text selection (no selection handles, no magnifying glass)
- Long-press context menu (Gesture class fires the event but nothing handles it)
- Double-tap word selection (tap count is tracked but not consumed)
- Pinch-to-zoom (not implemented)
- Touch cursor positioning (no tap-to-position)

**Key source files:**
- `src/browser/scrollable/touch.ts` -- Gesture class (derived from VS Code's touch handling)
- `src/browser/services/MouseService.ts` -- `_handleTouchStart`, `_handleTouchChange`, `_handleTouchScrollAsKeys`, `_handleTouchScrollAsWheel`
- `src/browser/Viewport.ts` -- `handleTouchScroll(translationY)` for viewport-based scrolling

### 2. Common Mobile Problems with xterm.js

#### 2a. Soft Keyboard and IME Issues

**iOS Chinese IME punctuation drop (Issue #5835, open, 2026-04):**

On iOS, Chinese IME punctuation (including space) is often dropped. The root cause is that iOS Chinese IMEs produce punctuation via non-composition paths that are not reliably available at `keydown` time. Keydown-only handling misses these inputs.

Event sequence for Chinese comma on iOS:
```
keydown: keyCode=229, isComposing=false
beforeinput: inputType="insertText", data=",", isComposing=false, composed=true
input: inputType="insertText", data=","
keyup: keyCode=0, key=","
```

The `composed=true` flag means the input is part of an IME composition but `isComposing=false` -- this is inconsistent and causes xterm.js to miss the input.

**Android GBoard erratic text / duplication (Issue #3600, open, 2022-01):**

Chrome Android with GBoard surrounds enter/backspace with composition event bursts (`compositionstart` -> `compositionupdate` -> keydown -> `compositionend`). If the keystroke is processed between start and end, characters get duplicated.

CodeMirror documented the same problem and uses a workaround: `delayAndroidKey()` that delays processing DOM changes for a moment when enter/backspace is detected, then dispatches the key event, throwing away DOM changes if it gets handled.

Reference: https://github.com/codemirror/view/blob/46c9816df1ab0987235174e6e136f7952d5ca473/src/domobserver.ts#L226

**Android WebView buffered input (Issue #5108, open, 2024-07):**

On Android WebView (React Native), `term.onData` only fires when Enter is pressed twice -- data is buffered instead of sent immediately per keypress. iOS works correctly.

**PR #6009 (open):** "Fix Android WebView keyboard input not forwarding onData immediately"

**Predictive/autocorrect keyboard interference (Issue #2403, closed):**

Mobile "smart" keyboards add predictive text that appears ahead of the cursor, and backspace behaves counter-intuitively (deleting from the prediction buffer, not the terminal). Workaround found: changing the textarea to `<input type="password">` disables predictive text, but this shows a password manager button and is a hack.

**PR #6024 (open):** "Handle IME-transformed printable input" -- aims to fix IME input handling more broadly.

#### 2b. Copy/Paste on Touch Devices (Issue #3727, open, 2022-04)

Text selection via touch does not work. Copy (Cmd+C on iPad) does not copy to clipboard. Paste works with keyboard. This makes the terminal essentially unusable for copy operations on touch devices.

The root cause is that xterm.js selection is driven by mouse events, and touch events are only translated to scroll gestures, not selection drag events.

#### 2c. Viewport Resize When Keyboard Opens

When the soft keyboard opens, the browser's visual viewport shrinks. xterm.js uses `ResizeObserver` on its container to trigger `fitAddon.fit()`, but the container's layout dimensions depend on how the CSS handles the viewport change:

- `100vh` = layout viewport height (does NOT change when keyboard opens on most mobile browsers)
- `100dvh` = dynamic viewport height (DOES change when keyboard opens)
- `window.visualViewport.height` = the actual visible area

Without using the Visual Viewport API, the terminal container may remain at full height, causing the bottom portion to be hidden behind the keyboard.

#### 2d. Scrolling Issues on v6 (Issue #5377 comments)

In xterm.js v6.0.0, mobile scrolling got worse -- fast drags often "detach" and stop sending scroll events after 1-2 lines. Only slow drags work consistently. The scrollbar also detaches from finger position on Android (Tauri WebView).

#### 2e. WebGL Renderer Not Working on Mobile (from wetty source)

The wetty project explicitly disables the WebGL addon on mobile devices:
```typescript
const isMobile = /iPhone|iPad|iPod|Android|webOS|BlackBerry|Opera Mini|IEMobile/i.test(navigator.userAgent);
if (!isMobile) {
  try { this.loadAddon(new WebglAddon()); } catch { /* fallback */ }
}
```
WebGL context creation often fails on mobile browsers, and the canvas renderer is more reliable.

### 3. CSS/Layout Patterns for Responsive Terminal UIs

#### 3a. Container Height with Dynamic Viewport

The key challenge is the soft keyboard changing the available viewport. Three approaches:

**Approach 1: `dvh` units (modern, recommended)**
```css
.terminal-container {
  height: 100dvh; /* Changes when soft keyboard opens */
}
```
Supported in Safari 15.4+, Chrome 108+, Firefox 108+. Falls back to `vh` for older browsers.

**Approach 2: Visual Viewport API**
```typescript
window.visualViewport?.addEventListener('resize', () => {
  const height = window.visualViewport!.height;
  terminalContainer.style.height = `${height}px`;
  fitAddon.fit();
});
```
Works on Safari iOS, Chrome Android. This gives the most accurate measurement.

**Approach 3: CSS environment variables for safe areas**
```css
.terminal-container {
  height: calc(100dvh - env(safe-area-inset-top) - env(safe-area-inset-bottom));
  padding-left: env(safe-area-inset-left);
  padding-right: env(safe-area-inset-right);
}
```
Handles notches, home indicators on modern iPhones.

#### 3b. Preventing Unwanted Browser Behaviors

```css
/* Prevent pull-to-refresh on mobile */
html, body {
  overscroll-behavior: none;
  overflow: hidden;
  touch-action: none; /* Let xterm.js handle all touch events */
}

/* Prevent iOS text selection outside terminal */
.terminal-wrapper {
  -webkit-user-select: none;
  user-select: none;
}

/* But allow selection inside xterm */
.xterm-screen {
  -webkit-user-select: text;
  user-select: text;
}
```

#### 3c. Meta Viewport Tag

Essential for mobile terminal:
```html
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
```
- `maximum-scale=1.0, user-scalable=no`: Prevents pinch-zoom which interferes with terminal touch handling
- `viewport-fit=cover`: Allows content to extend into safe area insets

### 4. Mobile Soft Keyboard and xterm.js Hidden Textarea

#### 4a. How the Hidden Textarea Works

xterm.js creates a hidden `<textarea class="xterm-helper-textarea">` that captures keyboard input. Key attributes set by xterm.js:
```
autocorrect="off"
autocapitalize="off"
spellcheck="false"
```

The textarea is positioned under the cursor during composition (via `CompositionHelper.updateCompositionElements()`) so the IME popup appears near the terminal cursor.

#### 4b. Mobile-Specific Textarea Attributes

Additional attributes that help on mobile (not set by xterm.js by default):

| Attribute | Effect | Set by xterm.js? |
|---|---|---|
| `autocorrect="off"` | Disables autocorrect | YES |
| `autocapitalize="off"` | Disables auto-capitalization | YES |
| `spellcheck="false"` | Disables spell checking | YES |
| `autocomplete="off"` | Disables autocomplete suggestions | NO |
| `enterkeyhint="send"` | Changes Enter key label to "Send" | NO |
| `inputmode="text"` | Forces text keyboard (vs numeric) | NO |

The wetty project adds `contenteditable="true"` to the `.xterm-screen` element as an alternative approach:
```typescript
function mobileKeyboard(): void {
  const screen = document.querySelector('.xterm-screen');
  if (screen == null) return;
  screen.setAttribute('contenteditable', 'true');
  screen.setAttribute('spellcheck', 'false');
  screen.setAttribute('autocorrect', 'false');
  screen.setAttribute('autocomplete', 'false');
  screen.setAttribute('autocapitalize', 'false');
}
```
This makes the screen element itself editable, which can improve mobile keyboard integration in some browsers.

#### 4c. The Password Input Hack

From issue #2403: Changing the textarea to `<input type="password">` disables predictive text on mobile keyboards. A recent comment (2026-06) confirms this still works for GBoard. However, it shows a password manager button on the suggestion bar.

Comment from @MatthewScholefield on issue #5377: "I've swapped the input element for a password field and it successfully fixes it for gboard for me so far, but of course this is kind of a hack and shows my password manager button on the suggestion bar instead."

#### 4d. IME Composition on Mobile

The `CompositionHelper` class handles IME composition, but mobile IMEs have platform-specific quirks:

- **iOS**: `compositionstart`/`compositionend` events fire for Pinyin input, but punctuation and some characters bypass the composition path entirely (firing `beforeinput/input` with `composed=true` but `isComposing=false`)
- **Android (GBoard)**: Enter/backspace are surrounded by spurious composition events that can cause character duplication if processed between `compositionstart` and `compositionend`
- **Android WebView**: Input is buffered and only sent on double-Enter

### 5. xterm.js Configuration Options for Mobile

There are no options specifically labeled "mobile", but several affect mobile behavior:

| Option | Default | Mobile Relevance |
|---|---|---|
| `scrollOnUserInput` | `true` | Scrolls to bottom on input -- useful on mobile where viewport is small |
| `scrollSensitivity` | `1` | Adjusts scroll speed -- may need higher value on mobile for touch scrolling |
| `smoothScrollDuration` | `0` | Smooth scrolling improves touch scroll feel; set to ~100ms |
| `scrollback` | `1000` | Larger scrollback = more content to scroll through via touch |
| `screenReaderMode` | `false` | When true, uses DOM renderer which has better accessibility but may interact differently with mobile assistive technologies |
| `disableStdin` | `false` | Can be used to prevent keyboard from appearing on read-only views |
| `lineHeight` | `1.0` | Higher values (1.15-1.2) improve CJK readability on small mobile screens |
| `fontSize` | `15` | May need to be smaller on mobile (12-14) to fit more content |
| `minimumContrastRatio` | `1` | Set to 4.5 for WCAG AA -- important on mobile in bright environments |
| `convertEol` | `false` | Helps with non-PTY data sources |
| `mouseEventsRequireAlt` | `false` | When true, allows normal touch selection even when mouse protocol is active |

**Notable:** The `scrollbar` option (with `IScrollbarOptions`) can configure the scrollbar width and visibility. On mobile, a narrower or hidden scrollbar may be preferable since touch scrolling is the primary mechanism.

**Configuration from current AgentTUI.vue:**
```typescript
new Terminal({
  cursorBlink: true,
  cursorStyle: 'block',
  fontSize: 14,
  fontFamily: "'Menlo', 'Consolas', 'Courier New', monospace",
  allowProposedApi: true,
  scrollback: 5000,
  convertEol: true,
})
```
Missing options that would help on mobile: `smoothScrollDuration`, `lineHeight`, `minimumContrastRatio`, `scrollSensitivity`.

### 6. Mobile Command Input: xterm-Only vs Separate Input Bar

This is the key architectural decision. There are three approaches observed in production:

#### Approach A: xterm-Only (current project approach)

All input goes through xterm.js's `onData` handler. The user types directly into the terminal.

**Pros:**
- Single input model, no state synchronization
- Consistent with desktop experience
- Less code to maintain

**Cons:**
- Mobile soft keyboard issues (duplicated characters, dropped punctuation, IME quirks)
- No control over keyboard type (can't show numeric keyboard for numeric input)
- Predictive text interferes with terminal input
- Can't position cursor in the middle of input line by tapping
- No way to add mobile-specific keys (Tab, Ctrl, Esc, arrows)

**Used by:** Basic xterm.js deployments, projects that don't prioritize mobile

#### Approach B: Separate Mobile Input Bar (recommended for this project)

A dedicated `<input>` or `<div contenteditable>` element below the terminal that captures keyboard input on mobile, then sends it to the terminal via `term.input()` or the data handler.

**Pros:**
- Full control over the mobile keyboard experience
- Can set `inputmode`, `enterkeyhint`, `autocomplete="off"` etc.
- Can show/hide the input bar based on device type
- Can add special key buttons (Ctrl, Esc, Tab, arrows) alongside the input
- Avoids xterm.js's internal textarea quirks on mobile
- Works well with IME because the native input element handles composition correctly

**Cons:**
- Two input models to maintain (desktop xterm, mobile input bar)
- Need to synchronize input state between the bar and terminal display
- Requires device detection or responsive logic
- More code

**Used by:** wetty (partially -- onscreen Ctrl/ESC/Tab/arrow buttons), several custom terminal apps

#### Approach C: Hybrid (xterm for display + external keyboard, input bar for soft keyboard)

Use xterm.js's native input when a hardware keyboard is connected, and show a separate input bar when the soft keyboard is active.

**Detection methods:**
```typescript
// Detect if soft keyboard is visible
window.visualViewport?.addEventListener('resize', () => {
  const isKeyboardOpen = window.visualViewport!.height < window.innerHeight * 0.8;
  showInputBar.value = isKeyboardOpen;
});
```

Or detect touch devices:
```typescript
const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
```

**Pros:**
- Best of both worlds
- Desktop/hardware keyboard users get native xterm experience
- Mobile soft keyboard users get reliable input

**Cons:**
- Most complex to implement
- Keyboard state transitions can be janky
- Edge cases with Bluetooth keyboards on tablets

#### Wetty's Implementation (Reference)

Wetty takes a practical approach:
1. Detects mobile via user agent
2. Disables WebGL on mobile (canvas renderer instead)
3. Adds onscreen buttons for special keys: Ctrl, Esc, Tab, Up, Down, Left, Right
4. Uses `term.input(data, wasUserInput)` API to inject keystrokes from onscreen buttons
5. Uses `contenteditable="true"` on `.xterm-screen` for better mobile keyboard integration
6. The Ctrl button toggles a `ctrlFlag` that modifies subsequent key presses

Key API: `term.input(data: string, wasUserInput: boolean)` -- this sends data directly to the terminal's input handler, bypassing the textarea. Available in xterm.js v5+.

#### Recommended Approach for This Project

Given the project's architecture (Vue 3, chat-like agent interface with command mode):

**Use Approach B (separate mobile input bar)** because:
1. The TUI already has a command-line model (not a raw PTY shell), so the input bar fits naturally
2. The project already manages `currentInput` state externally (not relying on xterm's internal buffer for the input line)
3. A dedicated input element gives full control over IME, keyboard type, and autocomplete
4. The agent mode (chat with AI) is especially well-suited for a chat-style input bar on mobile
5. Special keys (Ctrl+C for abort, Tab for autocomplete, arrow keys for history) can be exposed as buttons

**Implementation pattern:**
```vue
<!-- Mobile: show input bar below terminal -->
<div v-if="isMobile" class="mobile-input-bar">
  <div class="special-keys">
    <button @click="sendSpecialKey('esc')">Esc</button>
    <button @click="sendSpecialKey('tab')">Tab</button>
    <button @click="sendSpecialKey('up')">↑</button>
    <button @click="sendSpecialKey('down')">↓</button>
    <button @click="toggleCtrl">Ctrl</button>
  </div>
  <input
    ref="mobileInput"
    v-model="mobileInputText"
    type="text"
    autocomplete="off"
    autocorrect="off"
    autocapitalize="off"
    spellcheck="false"
    enterkeyhint="send"
    @keydown.enter="submitMobileInput"
    @compositionstart="onCompositionStart"
    @compositionend="onCompositionEnd"
  />
  <button @click="submitMobileInput">Send</button>
</div>
```

On desktop, continue using `term.onData(handleTermData)` for native xterm.js keyboard handling.

### 7. Key GitHub Issues Reference

| Issue | Status | Description |
|---|---|---|
| [#5377](https://github.com/xtermjs/xterm.js/issues/5377) | Open | Limited touch support on mobile -- comprehensive proposal for touch handling |
| [#3727](https://github.com/xtermjs/xterm.js/issues/3727) | Open | Copy/paste don't work on touch devices |
| [#3600](https://github.com/xtermjs/xterm.js/issues/3600) | Open | Erratic text on Chrome Android (GBoard duplication) |
| [#5835](https://github.com/xtermjs/xterm.js/issues/5835) | Open | iOS Chinese IMEs cannot input punctuation/space |
| [#5108](https://github.com/xtermjs/xterm.js/issues/5108) | Open | Inconsistent onData between iOS and Android |
| [#2403](https://github.com/xtermjs/xterm.js/issues/2403) | Closed | Predictive keyboard on mobile (password input workaround) |
| [#1101](https://github.com/xtermjs/xterm.js/issues/1101) | Closed | Support mobile platforms (Ace editor approach) |
| [#1007](https://github.com/xtermjs/xterm.js/issues/1007) | Closed | Touch scrolling should send arrow keys |
| [#1815](https://github.com/xtermjs/xterm.js/issues/1815) | Closed | CompositionHelper keyCode 229 iOS bug |
| [PR #6024](https://github.com/xtermjs/xterm.js/pull/6024) | Open | Handle IME-transformed printable input |
| [PR #6009](https://github.com/xtermjs/xterm.js/pull/6009) | Open | Fix Android WebView keyboard input |
| [PR #747](https://github.com/xtermjs/xterm.js/pull/747) | Closed | Add scroll functionality for mobile |

### 8. External References

- [xterm.js CompositionHelper source](https://github.com/xtermjs/xterm.js/blob/master/src/browser/input/CompositionHelper.ts) -- IME composition handling
- [xterm.js Gesture/touch.ts source](https://github.com/xtermjs/xterm.js/blob/master/src/browser/scrollable/touch.ts) -- Touch gesture recognition (derived from VS Code)
- [xterm.js MouseService source](https://github.com/xtermjs/xterm.js/blob/master/src/browser/services/MouseService.ts) -- Touch scroll routing
- [xterm.js Viewport.ts source](https://github.com/xtermjs/xterm.js/blob/master/src/browser/Viewport.ts) -- Viewport scroll and handleTouchScroll
- [xterm.js ITerminalOptions](https://github.com/xtermjs/xterm.js/blob/master/typings/xterm.d.ts) -- All configuration options
- [CodeMirror Android workaround](https://github.com/codemirror/view/blob/46c9816df1ab0987235174e6e136f7952d5ca473/src/domobserver.ts#L226) -- `delayAndroidKey` pattern for GBoard
- [Wetty terminal.ts](https://github.com/butlerx/wetty/blob/master/src/client/wetty/term.ts) -- Production mobile terminal with onscreen buttons
- [Wetty mobile.ts](https://github.com/butlerx/wetty/blob/master/src/client/wetty/mobile.ts) -- `contenteditable` mobile keyboard hack
- [Visual Viewport API (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/Visual_Viewport_API) -- For keyboard resize detection
- [CSS dvh units (MDN)](https://developer.mozilla.org/en-US/docs/Web/CSS/length#dvh) -- Dynamic viewport height

### Related Specs

- `.trellis/tasks/06-28-fix-web-tui-chinese-input-and-interaction-experience/prd.md` -- Task PRD
- `.trellis/tasks/06-28-fix-web-tui-chinese-input-and-interaction-experience/research/xterm-cjk-input.md` -- CJK/IME input details
- `.trellis/tasks/06-28-fix-web-tui-chinese-input-and-interaction-experience/research/xterm-ux-addons.md` -- Addon catalog and configuration

## Caveats / Not Found

- **No official xterm.js mobile documentation** exists. The project does not test on mobile in CI, and the maintainers have stated mobile is not a priority.
- **The `term.input()` API** (used by wetty for injecting keystrokes from onscreen buttons) is available in xterm.js v5 but its behavior with IME composition is undocumented. Testing is needed.
- **iOS vs Android keyboard behavior** differs significantly. iOS Safari and Android Chrome have different event sequences for IME input. Any mobile solution must be tested on both platforms.
- **xterm.js v6** has regressed mobile scrolling (per issue #5377 comments). This project uses v5 (`xterm@5.3.0`), which may have different scrolling behavior.
- **The `contenteditable` approach** (wetty's `mobileKeyboard()`) is untested in the context of this project's custom `handleTermData` input model. It may interact unexpectedly with the existing input handling.
- **No production example found** of a Vue 3 + xterm.js mobile terminal with a separate input bar. The closest reference is wetty's vanilla JS approach.
