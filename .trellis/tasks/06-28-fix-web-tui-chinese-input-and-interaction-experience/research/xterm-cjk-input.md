# Research: xterm.js v5 CJK/Chinese Input and IME Composition

- **Query**: How xterm.js v5 handles CJK/Chinese input and IME composition; does it need addons; recommended patterns; fontFamily config; known issues
- **Scope**: Mixed (internal codebase + external xterm.js source/issues/docs)
- **Date**: 2026-06-28

## Findings

### 1. Built-in IME/CJK Support in xterm.js v5

xterm.js v5 **has built-in IME support** via its internal `CompositionHelper` class. No addon is required for basic IME composition to work.

**How it works internally:**

1. xterm.js creates a hidden `<textarea>` element that captures keyboard input
2. It listens for `compositionstart`, `compositionupdate`, `compositionend` DOM events on that textarea
3. `CompositionHelper` manages the composition lifecycle:
   - `compositionstart()`: Sets `_isComposing = true`, records start position in textarea value
   - `compositionupdate()`: Updates the composition view (visual overlay near cursor)
   - `compositionend()`: Calls `_finalizeComposition(true)` which extracts the composed text from the textarea and fires `triggerDataEvent(input, true)`, which emits the composed string via the `onData` event
4. During composition, a visual overlay (`_compositionView` div) shows the in-progress text near the cursor position
5. The `keydown` handler intercepts `keyCode === 229` (the "composition character" keyCode) and routes it through `_handleAnyTextareaChanges()` instead of normal key processing

**Key source**: `src/browser/input/CompositionHelper.ts` in xterm.js repo (also embedded in `/test/xhs/frontend/node_modules/xterm/lib/xterm.js`)

**Critical detail for the project**: When IME composition completes, xterm.js fires the composed text (e.g., "你好") as a single string via `onData`. The project's `handleTermData` function receives this string, but the `code >= 32 && code < 127` check on line 223 of `AgentTUI.vue` rejects it because Chinese characters have `charCodeAt(0)` values in the range 19968-40959 (CJK Unified Ideographs).

### 2. Unicode Addons: @xterm/addon-unicode-graphemes vs @xterm/addon-unicode11

**These addons do NOT affect IME input handling.** They affect **character width calculation** (wcwidth), which determines how many terminal cells a character occupies.

| Addon | Version | Purpose | Status |
|---|---|---|---|
| `@xterm/addon-unicode11` | 0.9.0 | Updates wcwidth to Unicode 11 values | Stable |
| `@xterm/addon-unicode-graphemes` | 0.4.0 | Unicode 15 + grapheme cluster handling | **Experimental** |

**Default behavior**: xterm.js v5 ships with Unicode version "6" (class `UnicodeV6`). This has a basic wcwidth table that marks CJK ideographs (44032-55204 range) as width=2 (double-width). This is sufficient for basic CJK display.

**What the unicode-graphemes addon adds**:
- Registers two new Unicode versions: `"15"` and `"15-graphemes"`
- `"15-graphemes"` handles grapheme clusters (emoji sequences, combining characters)
- Sets `unicode.activeVersion = '15-graphemes'` on activation
- Provides more accurate wcwidth for emoji and complex Unicode sequences
- **Not required for basic CJK input/display** but helps with emoji rendering accuracy

**What the unicode11 addon adds**:
- Registers Unicode version `"11"` with updated wcwidth tables
- Simpler than unicode-graphemes, just updates character width data
- **Not required for basic CJK** but provides more accurate width for newer Unicode characters

**Recommendation for the project**: The unicode-graphemes addon is experimental (0.4.0 stable, 0.5.0 in perpetual beta). For CJK support, the default Unicode V6 provider already marks CJK characters as width=2. The addon is **not needed** to fix the Chinese input problem. It could be added later for better emoji/complex character handling.

### 3. Composition Event Handling Pattern with xterm.js

**The correct pattern for handling IME input with xterm.js when using a custom input handler (like `handleTermData`):**

The core issue is that xterm.js's built-in `CompositionHelper` is designed for a **passthrough terminal** (where `onData` output goes directly to a PTY/backend). When the application intercepts `onData` with custom logic (like the project's `handleTermData`), it must handle both:

1. **Single ASCII characters** from direct keypresses (via `_inputEvent` or `onKey`)
2. **Multi-character IME-composed strings** from `compositionend` (via `CompositionHelper._finalizeComposition`)

**The problem in AgentTUI.vue**:

```javascript
// Line 223 - THIS IS THE BUG
} else if (code >= 32 && code < 127) {
  // Printable character
  // ... handles the character
}
// Characters with code >= 127 (all CJK, emoji, etc.) are silently dropped
```

**Solution approaches**:

**Approach A: Broaden the character acceptance range**
Replace `code >= 32 && code < 127` with a check that accepts all printable characters including CJK. The simplest approach:

```javascript
} else if (code >= 32) {
  // Printable character (including CJK, emoji, etc.)
  // But must handle multi-byte strings correctly
}
```

However, this alone is insufficient because:
- CJK characters are width=2 in the terminal (occupy 2 cells)
- The cursor position tracking (`cursorPos.value++`) assumes width=1
- The `term.write()` for cursor repositioning (`\x1b[${after.length}D`) uses string length, not cell width

**Approach B: Handle IME composition via DOM events directly**
Attach `compositionstart`/`compositionend` listeners to `term.textarea` (the hidden textarea element) to track composition state. During composition, buffer input; on compositionend, process the full composed string.

```javascript
let isComposing = false
let compositionText = ''

term.textarea.addEventListener('compositionstart', () => {
  isComposing = true
  compositionText = ''
})

term.textarea.addEventListener('compositionend', () => {
  isComposing = false
  // The composed text will come through onData as a complete string
})
```

**Approach C: Use `onKey` event instead of `onData` for custom handling**
The `onKey` event provides `{ key: string, domEvent: KeyboardEvent }`. However, `onKey` does NOT fire for IME-composed text, so this approach alone is insufficient.

**Recommended pattern**: Combine Approach A (broaden character range) with Approach B (track composition state). During composition, ignore `onData` events (they contain partial/intermediate data). After composition ends, process the full composed string from `onData`.

**Critical: CJK character width handling**

CJK characters occupy 2 terminal cells. The input handler must:
1. Calculate the display width of each character (using `term.unicode` or a wcwidth function)
2. Advance `cursorPos` by the character's width, not by 1
3. Use display width (not string length) for cursor repositioning escape sequences

```javascript
function getStringWidth(str: string): number {
  let width = 0
  for (const char of str) {
    const code = char.codePointAt(0)!
    if (code >= 0x1100 && (
      code <= 0x115F ||  // Hangul Jamo
      code === 0x2329 || code === 0x232A ||
      (code >= 0x2E80 && code <= 0xA4CF && code !== 0x303F) ||  // CJK
      (code >= 0xAC00 && code <= 0xD7A3) ||  // Hangul Syllables
      (code >= 0xF900 && code <= 0xFAFF) ||  // CJK Compatibility
      (code >= 0xFE10 && code <= 0xFE19) ||  // Vertical forms
      (code >= 0xFE30 && code <= 0xFE6F) ||  // CJK Compatibility Forms
      (code >= 0xFF01 && code <= 0xFF60) ||  // Fullwidth Forms
      (code >= 0xFFE0 && code <= 0xFFE6) ||
      (code >= 0x20000 && code <= 0x2FFFD) ||
      (code >= 0x30000 && code <= 0x3FFFD)
    )) {
      width += 2
    } else {
      width += 1
    }
  }
  return width
}
```

Or use xterm.js's built-in: `term.unicode.getStringCellWidth(str)` (available via the experimental `unicode` API when `allowProposedApi: true` is set, which the project already does).

### 4. Font Configuration for CJK Characters

**Current configuration** (AgentTUI.vue line 558):
```javascript
fontFamily: "'Menlo', 'Consolas', 'Courier New', monospace"
```

This font stack contains no CJK-capable fonts. When a CJK character is encountered, the browser falls back to the generic `monospace` family, which may render CJK characters with inconsistent widths or as tofu (empty boxes).

**Recommended CJK font stack**:

```javascript
fontFamily: "'Menlo', 'Consolas', 'Courier New', 'Noto Sans Mono CJK SC', 'Source Han Mono SC', 'Microsoft YaHei', 'PingFang SC', 'WenQuanYi Micro Hei Mono', monospace"
```

**Font details**:

| Font | Platform | Notes |
|---|---|---|
| `Noto Sans Mono CJK SC` | Cross-platform (Google) | Best option; monospace CJK; SC = Simplified Chinese; available via Google Fonts CDN |
| `Source Han Mono SC` | Cross-platform (Adobe) | Monospace CJK; SC = Simplified Chinese |
| `Microsoft YaHei` | Windows | System font; not monospace but renders CJK well |
| `PingFang SC` | macOS/iOS | System font; not monospace but renders CJK well |
| `WenQuanYi Micro Hei Mono` | Linux | Common Linux CJK monospace font |
| `SimHei` | Windows | Legacy Windows CJK font |

**Important**: CJK characters in a terminal must be rendered at double width. xterm.js handles this via its wcwidth implementation, but the font must actually contain the CJK glyphs. If the font lacks CJK glyphs, the browser's font fallback mechanism will find a font that has them, but the character width may not match xterm.js's expectation.

**Using Google Fonts CDN for Noto Sans Mono CJK SC**:
```html
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Mono+CJK+SC&display=swap" rel="stylesheet">
```

Or use `@xterm/addon-web-fonts` to ensure fonts are loaded before the terminal renders.

**Alternative: Use `@xterm/addon-web-fonts`**:
This addon (available in xterm.js repo) waits for `document.fonts.ready` and triggers a relayout after web fonts load. This prevents the "flash of unstyled text" issue where CJK characters initially render with fallback font metrics and then shift when the web font loads.

### 5. Known Issues with Chinese Input in xterm.js v5

**Issue #1: Duplicate input with certain IMEs (Wubi method)**
- **GitHub**: #5023 (closed), fixed in PR #5024 (merged into v6.0.0)
- **Affected**: xterm v5.3.0 (the version installed in this project)
- **Cause**: `CompositionHelper._finalizeComposition` used `currentCompositionPosition.end` to extract composed text, but the end position was incorrect when a new composition started immediately after the previous one ended (common with Wubi input method)
- **Fix in v6.0.0**: Changed to use `this._compositionPosition.start` (start of new composition) instead of `currentCompositionPosition.end`
- **Impact on this project**: The installed v5.3.0 has the OLD buggy code. Users of Wubi input method will see duplicate characters. This is a known xterm.js bug that cannot be fixed without upgrading to v6.0.0+ or patching the CompositionHelper.

**Issue #2: Second character lost with keyCode=229 IMEs (Doubao, Baidu)**
- **GitHub**: #5887 (open, unfixed as of 2026-05)
- **Affected**: All xterm versions including v6.0.0+
- **Cause**: Some IMEs (Doubao/豆包 in English mode) report `keyCode=229` for every keystroke even when not composing. xterm.js routes these through composition fallback paths which drop the second character during rapid typing.
- **Impact**: Unlikely to affect this project's primary use case (Chinese input in Chinese mode), but could affect users with certain IMEs.

**Issue #3: iOS Chinese IME punctuation not working**
- **GitHub**: #5835 (open), #5614 (PR, open)
- **Affected**: iOS Safari/Chrome
- **Cause**: iOS Chinese IMEs produce punctuation via non-composition paths that xterm.js doesn't handle
- **Impact**: Only affects iOS users; not relevant for desktop web app.

**Issue #4: Various Chinese IME problems (third-party IMEs on macOS)**
- **GitHub**: #4486 (open)
- **Affected**: Third-party Chinese IMEs like Sogou on macOS
- **Cause**: Third-party IMEs may not follow standard composition event sequences
- **Impact**: May affect some users; the built-in macOS Chinese IME works correctly.

**Issue #5: The project's own handleTermData drops all non-ASCII characters**
- **Not an xterm.js bug** - this is a bug in the project's custom input handler
- **Location**: `AgentTUI.vue` line 223: `code >= 32 && code < 127`
- **Fix**: Broaden the range and handle multi-byte characters correctly (see Section 3)

### Files Found

| File Path | Description |
|---|---|
| `frontend/src/views/AgentTUI.vue` | Main TUI component with xterm.js; contains the buggy `handleTermData` function |
| `frontend/package.json` | Lists xterm@^5.3.0, @xterm/addon-fit, @xterm/addon-web-links |
| `frontend/node_modules/xterm/typings/xterm.d.ts` | xterm.js v5 type definitions; shows `IUnicodeHandling`, `IUnicodeVersionProvider` APIs |
| `frontend/node_modules/xterm/lib/xterm.js` | Minified xterm.js source; contains CompositionHelper, UnicodeV6, _inputEvent |

### Code Patterns

**Pattern 1: xterm.js CompositionHelper flow (internal, not directly accessible)**
- File: `node_modules/xterm/lib/xterm.js`
- `compositionstart` -> `_isComposing = true`, record textarea position
- `compositionupdate` -> update visual overlay
- `compositionend` -> `_finalizeComposition(true)` -> `setTimeout(() => triggerDataEvent(input))` -> fires `onData`
- `keydown(keyCode=229)` -> `_handleAnyTextareaChanges()` -> diff textarea value -> `triggerDataEvent(diff)`

**Pattern 2: The project's handleTermData (the bug)**
- File: `frontend/src/views/AgentTUI.vue:165-237`
- Uses `term.onData(handleTermData)` to intercept all input
- Checks `data.charCodeAt(0)` for each input event
- Only handles ASCII printable range (32-126), silently drops everything else
- No composition state tracking
- Cursor position tracking assumes all characters are width=1

**Pattern 3: xterm.js Unicode API (experimental, requires allowProposedApi: true)**
- File: `node_modules/xterm/typings/xterm.d.ts:795-798, 1763-1796`
- `terminal.unicode` provides `IUnicodeHandling`
- `terminal.unicode.register(provider)` registers custom Unicode version providers
- `terminal.unicode.activeVersion` gets/sets the active version
- `terminal.unicode.getStringCellWidth(str)` calculates display width (available in v5 with allowProposedApi)
- The project already sets `allowProposedApi: true` (line 582)

### External References

- [xterm.js README](https://github.com/xtermjs/xterm.js/blob/master/README.md) - Lists "Rich Unicode support: Supports CJK, emojis, and IMEs" as a feature
- [CompositionHelper.ts source](https://github.com/xtermjs/xterm.js/blob/master/src/browser/input/CompositionHelper.ts) - The internal IME handling class
- [Issue #5023: Duplicate input when using Chinese input methods](https://github.com/xtermjs/xterm.js/issues/5023) - Fixed in v6.0.0 via PR #5024
- [Issue #5887: Second character lost when IME reports keyCode=229](https://github.com/xtermjs/xterm.js/issues/5887) - Open, affects Doubao/Baidu IMEs
- [Issue #4486: Various problems with Chinese IMEs](https://github.com/xtermjs/xterm.js/issues/4486) - Open, third-party IME issues
- [Issue #5835: iOS Chinese IMEs cannot input punctuation](https://github.com/xtermjs/xterm.js/issues/5835) - Open, iOS-specific
- [@xterm/addon-unicode-graphemes on npm](https://www.npmjs.com/package/@xterm/addon-unicode-graphemes) - v0.4.0 stable, experimental status
- [@xterm/addon-unicode11 on npm](https://www.npmjs.com/package/@xterm/addon-unicode11) - v0.9.0, stable Unicode 11 width provider
- [UnicodeGraphemesAddon.ts source](https://github.com/xtermjs/xterm.js/blob/master/addons/addon-unicode-graphemes/src/UnicodeGraphemesAddon.ts) - Registers Unicode 15 + grapheme versions
- [xterm.js v6.0.0 release notes](https://github.com/xtermjs/xterm.js/releases/tag/6.0.0) - Contains IME duplicate input fix (#5024)

### Related Specs

- `.trellis/tasks/06-28-fix-web-tui-chinese-input-and-interaction-experience/prd.md` - Task PRD with known issues and acceptance criteria

## Caveats / Not Found

1. **xterm.js v5.3.0 has the duplicate IME input bug** (fixed only in v6.0.0). Upgrading to v6 would require changing the package from `xterm` to `@xterm/xterm` (the package was renamed). This is a breaking change that affects imports.

2. **`term.unicode.getStringCellWidth()`** is marked experimental. While the project sets `allowProposedApi: true`, this API could change in future versions. A self-contained wcwidth implementation may be more stable.

3. **The `term.textarea` property** is not part of the public API. Accessing it to attach composition event listeners works in v5 but is not guaranteed to remain stable.

4. **No comprehensive solution exists for all IME edge cases**. The xterm.js project itself has multiple open IME issues. The fix for the project's custom input handler should focus on the most common case (standard Chinese IME composition) and accept that some edge cases with third-party IMEs may not work perfectly.

5. **CJK full-width punctuation** (e.g., Chinese comma "，" U+FF0C, period "。" U+3002) also has `charCodeAt(0) > 127` and width=2. These must be handled the same way as CJK ideographs.

6. **Emoji rendering** requires either the unicode-graphemes addon or manual handling of emoji sequences (skin tone modifiers, ZWJ sequences). This is a separate concern from basic CJK input.
