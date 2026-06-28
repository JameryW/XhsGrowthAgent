# Research: xterm.js UX Addons and Configuration

- **Query**: What xterm.js addons exist for search, selection/copy, image rendering, canvas/WebGL rendering; what the omp native TUI supports; what xterm.js configuration options improve UX; best practices for xterm.js terminal UX in a web app
- **Scope**: Mixed (internal codebase + external npm registry + xterm.js GitHub)
- **Date**: 2026-06-28

## Findings

### 1. Official xterm.js Addon Catalog (npm)

The xterm.js team maintains 13 official addons. The project currently installs only 2 of them.

| Addon | npm Version | Installed? | Purpose |
|---|---|---|---|
| `@xterm/addon-fit` | 0.11.0 | YES | Fits terminal to containing element dimensions |
| `@xterm/addon-web-links` | 0.12.0 | YES | Detects and makes web URLs clickable |
| `@xterm/addon-search` | 0.16.0 | NO | Search buffer with findNext/findPrevious, regex, decorations, overview ruler |
| `@xterm/addon-webgl` | 0.19.0 | NO | GPU-accelerated rendering via WebGL2 context |
| `@xterm/addon-canvas` | 0.7.0 | NO | Canvas 2D renderer (faster than DOM, slower than WebGL) |
| `@xterm/addon-image` | 0.9.0 | NO | Inline image output (SIXEL, iTerm IIP, Kitty protocols) |
| `@xterm/addon-serialize` | 0.14.0 | NO | Serialize buffer to VT sequences or HTML (for copy, session restore) |
| `@xterm/addon-ligatures` | 0.10.0 | NO | Programming font ligatures (calt font feature) |
| `@xterm/addon-clipboard` | 0.2.0 | NO | System clipboard access (OSC 52 support) |
| `@xterm/addon-unicode-graphemes` | 0.4.0 | NO | Unicode 15 + grapheme cluster handling (EXPERIMENTAL) |
| `@xterm/addon-unicode11` | 0.9.0 | NO | Unicode 11 character width rules |
| `@xterm/addon-web-fonts` | 0.1.0 | NO | Web font loading and relayout |
| `@xterm/addon-attach` | 0.12.0 | NO | Attach terminal to a WebSocket (passthrough) |
| `@xterm/addon-progress` | 0.2.0 | NO | ConEmu progress sequence (OSC 9;4) |

**Third-party addons of note:**
- `xterm-addon-search-bar@0.2.0` — UI search bar widget (not official)
- `xterm-readline@1.2.2` — Readline-like input editing addon

### 2. Addon API Details

#### @xterm/addon-search (0.16.0)

**Key API:**
```typescript
class SearchAddon implements ITerminalAddon {
  constructor(options?: Partial<ISearchAddonOptions>)
  findNext(term: string, searchOptions?: ISearchOptions): boolean
  findPrevious(term: string, searchOptions?: ISearchOptions): boolean
  clearDecorations(): void
  clearActiveDecoration(): void
  readonly onAfterSearch: IEvent<void>
  readonly onBeforeSearch: IEvent<void>
  readonly onDidChangeResults: IEvent<ISearchResultChangeEvent>
}

interface ISearchOptions {
  regex?: boolean
  wholeWord?: boolean
  caseSensitive?: boolean
  incremental?: boolean
  decorations?: ISearchDecorationOptions  // highlight matches + overview ruler
}

interface ISearchDecorationOptions {
  matchBackground?: string          // #RRGGBB
  matchBorder?: string
  matchOverviewRuler: string        // color in overview ruler
  activeMatchBackground?: string
  activeMatchBorder?: string
  activeMatchColorOverviewRuler: string
}

interface ISearchAddonOptions {
  highlightLimit: number  // default 1000
}

interface ISearchResultChangeEvent {
  resultIndex: number   // -1 when threshold exceeded
  resultCount: number
}
```

**Integration pattern:** Load the addon, then call `findNext`/`findPrevious` from a search UI. The `onDidChangeResults` event provides match count for display. Decorations highlight matches in the buffer and overview ruler.

#### @xterm/addon-webgl (0.19.0)

**Key API:**
```typescript
class WebglAddon implements ITerminalAddon {
  constructor(options?: IWebglAddonOptions)
  readonly onContextLoss: IEvent<void>
  readonly onChangeTextureAtlas: IEvent<HTMLCanvasElement>
  clearTextureAtlas(): void
}

interface IWebglAddonOptions {
  customGlyphs?: boolean           // default true; draws box drawing, block elements, powerline, etc.
  preserveDrawingBuffer?: boolean  // default false; useful for tests
}
```

**Usage pattern:** Load after terminal is open. Falls back to canvas/DOM renderer if WebGL context is lost. The `onContextLoss` event should trigger fallback:
```javascript
const webglAddon = new WebglAddon()
webglAddon.onContextLoss(() => {
  webglAddon.dispose()
  // fall back to canvas or DOM renderer
})
term.loadAddon(webglAddon)
```

**Performance:** WebGL renderer is the fastest option, using GPU texture atlas for glyph rendering. VS Code uses this renderer by default.

#### @xterm/addon-canvas (0.7.0)

**Key API:**
```typescript
// Simple addon, no custom options beyond ITerminalAddon
class CanvasAddon implements ITerminalAddon {
  constructor()
  activate(terminal: Terminal): void
  dispose(): void
}
```

**Peer dependency:** `@xterm/xterm: ^5.0.0`

**Usage:** Middle-ground renderer. Faster than DOM, slower than WebGL. Good fallback when WebGL is unavailable.

#### @xterm/addon-image (0.9.0)

**Key API:**
```typescript
class ImageAddon implements ITerminalAddon {
  constructor(options?: IImageAddonOptions)
  reset(): void
  storageLimit: number              // getter/setter, MB
  readonly storageUsage: number     // current MB
  showPlaceholder: boolean          // getter/setter
  readonly onImageAdded: IEvent<void>
  getImageAtBufferCell(x: number, y: number): HTMLCanvasElement | undefined
  extractTileAtBufferCell(x: number, y: number): HTMLCanvasElement | undefined
}

interface IImageAddonOptions {
  enableSizeReports?: boolean       // default true; CSI 14t, 16t, 18t
  pixelLimit?: number               // default 2^16 (4096x4096)
  storageLimit?: number             // default 128 MB
  showPlaceholder?: boolean         // default true
  sixelSupport?: boolean            // default true
  sixelScrolling?: boolean          // default true
  sixelPaletteLimit?: number        // default 256
  sixelSizeLimit?: number           // default 25000000 bytes
  iipSupport?: boolean              // default true (iTerm image protocol)
  iipSizeLimit?: number             // default 20000000 bytes
  kittySupport?: boolean            // default true
  kittySizeLimit?: number           // default 20000000 bytes
}
```

**Protocols supported:** SIXEL, iTerm Inline Image Protocol (IIP), Kitty Graphics Protocol. This is relevant if the backend sends image data (e.g., generated content previews) through the terminal.

#### @xterm/addon-serialize (0.14.0)

**Key API:**
```typescript
class SerializeAddon implements ITerminalAddon {
  serialize(options?: ISerializeOptions): string
  serializeAsHTML(options?: Partial<IHTMLSerializeOptions>): string
}

interface ISerializeOptions {
  range?: ISerializeRange
  scrollback?: number
  excludeModes?: boolean
  excludeAltBuffer?: boolean
}

interface IHTMLSerializeOptions {
  scrollback: number
  onlySelection: boolean
  includeGlobalBackground: boolean
  range?: ISerializeBufferRange
}
```

**Use cases:**
1. **Copy as HTML** — `serializeAsHTML({ onlySelection: true })` for rich-text clipboard copy
2. **Session restore** — `serialize()` to save terminal state, write it back on reconnect
3. **Export** — Save terminal output as HTML document

#### @xterm/addon-ligatures (0.10.0)

**Key API:**
```typescript
class LigaturesAddon implements ITerminalAddon {
  constructor(options?: Partial<ILigatureOptions>)
}

interface ILigatureOptions {
  fallbackLigatures: string[]       // default: Iosevka "calt" set (==, !=, ->, =>, etc.)
  fontFeatureSettings: string       // default: '"calt" on'
}
```

**Important:** If WebGL is also used, ligatures addon must be activated BEFORE WebGL, then WebGL reactivated after, so `fontFeatureSettings` applies to the texture atlas.

**Browser requirement:** Uses the Font Access API (`navigator.fonts.query()`) when available. Falls back to `fallbackLigatures` list when API is unavailable or denied.

#### @xterm/addon-clipboard (0.2.0)

**Key API:**
```typescript
class ClipboardAddon implements ITerminalAddon {
  constructor(base64?: IBase64, provider?: IClipboardProvider)
}

interface IClipboardProvider {
  readText(selection: string): string | Promise<string>
  writeText(selection: string, text: string): void | Promise<void>
}

class BrowserClipboardProvider implements IClipboardProvider {
  readText(selection: string): Promise<string>
  writeText(selection: string, data: string): Promise<void>
}
```

**Purpose:** Enables OSC 52 clipboard operations. When a terminal application sends `OSC 52 ; c ; <base64-data> ST`, this addon decodes it and writes to the browser clipboard. Without this addon, OSC 52 sequences are ignored.

**Custom provider:** Can provide a custom `IClipboardProvider` to integrate with non-browser clipboard APIs (e.g., Electron's clipboard API).

#### @xterm/addon-unicode-graphemes (0.4.0)

**Key API:**
```typescript
class UnicodeGraphemesAddon implements ITerminalAddon {
  constructor()
  activate(terminal: Terminal): void
  dispose(): void
}
```

**What it does:** Registers Unicode versions `"15"` and `"15-graphemes"` with the terminal. The `"15-graphemes"` version handles grapheme clusters (emoji ZWJ sequences, combining characters). Sets `terminal.unicode.activeVersion = '15-graphemes'` on activation.

**Status:** EXPERIMENTAL. The xterm.js team warns it "may introduce unexpected and non-standard behavior."

**For CJK:** Not required. The default Unicode V6 provider already marks CJK characters as width=2. This addon helps with emoji and complex Unicode sequences.

#### @xterm/addon-web-fonts (0.1.0)

**Key API:**
```typescript
class WebFontsAddon implements ITerminalAddon {
  constructor(initialRelayout?: boolean)  // default true
  loadFonts(fonts?: (string | FontFace)[]): Promise<FontFace[]>
  relayout(): Promise<void>
}
```

**Purpose:** Ensures web fonts are loaded before terminal renders. Prevents "flash of unstyled text" where CJK characters initially render with fallback font metrics and shift when the web font loads.

**Peer dependency:** `@xterm/xterm: ^6.1.0-beta.86` — This means it requires the new `@xterm/xterm` package (v6+), NOT the old `xterm` package (v5). **Incompatible with the project's current `xterm@^5.3.0`.**

### 3. omp Native TUI Capabilities

The omp (oh-my-pi) native TUI is a terminal-based AI agent interface. The project's extension (`backend/omp/extensions/xhsagent-ext/`) provides domain tools and commands that integrate with it.

**What the omp native TUI provides (inferred from extension API):**

| Capability | Extension API Used | Description |
|---|---|---|
| Tool registration | `pi.registerTool(tool)` | 7 domain tools registered (workflow start/status/pause/resume/cancel, review approve/reject) |
| Command registration | `pi.registerCommand(name, {description, handler})` | 2 commands: `/xhs`, `/xhs-review` |
| Event hooks | `pi.on("session_start", ...)`, `pi.on("before_agent_start", ...)` | Health check on session start, context injection before agent |
| Agent messaging | `pi.sendUserMessage(text)` | Send messages to the AI agent |
| Zod schema | `pi.zod` | Parameter validation for tools |
| UI notifications | `ctx.ui.notify(message, level)` | Toast notifications in the TUI |
| Context awareness | `ctx.hasUI` | Detect if running with UI |

**What the native TUI likely supports that the web TUI lacks:**

1. **Native IME input** — Terminal emulators (iTerm2, Windows Terminal, etc.) handle IME natively; no custom input handler needed
2. **Native selection/copy** — Terminal selection and clipboard work via OS mechanisms
3. **Native scrolling** — Scrollback via terminal emulator's built-in scroll
4. **Search** — Terminal emulator's built-in find (Ctrl+Shift+F in most terminals)
5. **Font rendering** — Native terminal uses system fonts with full CJK support
6. **Keyboard shortcuts** — Full terminal keyboard support (no browser key conflicts)
7. **Mouse support** — Native mouse events pass through to terminal applications
8. **Image support** — Some terminals (Kitty, iTerm2) support inline images natively

**The web TUI gap:** The web TUI (AgentTUI.vue) intercepts all input via `term.onData(handleTermData)` and implements its own input handling, which:
- Only accepts ASCII printable characters (line 223: `code >= 32 && code < 127`)
- Has no IME composition awareness
- Has no search functionality
- Has no copy-as-HTML support
- Uses the DOM renderer (no WebGL/canvas acceleration)
- Has no image rendering capability
- Has limited font configuration (no CJK fonts in stack)

### 4. xterm.js Configuration Options for UX Improvement

The project's current Terminal configuration (AgentTUI.vue lines 554-585):

```javascript
term = new Terminal({
  cursorBlink: true,
  cursorStyle: 'block',
  fontSize: 14,
  fontFamily: "'Menlo', 'Consolas', 'Courier New', monospace",
  theme: { /* 16-color ANSI theme */ },
  allowProposedApi: true,
  scrollback: 5000,
  convertEol: true,
})
```

**Options NOT currently set that would improve UX:**

| Option | Default | Recommended | Why |
|---|---|---|---|
| `smoothScrollDuration` | 0 (disabled) | 80-150 | Smooth scrolling instead of instant jumps; much better UX for reading output |
| `scrollSensitivity` | 1 | 1 | Already fine; controls scroll speed multiplier |
| `fastScrollModifier` | 'none' | 'alt' | Hold Alt to scroll faster through long output |
| `fastScrollSensitivity` | 1 | 5 | Speed multiplier when fast scroll modifier is held |
| `scrollOnUserInput` | true | true | Already fine; scrolls to bottom on input |
| `fontFamily` | (current) | Add CJK fallback fonts | See CJK font research file |
| `fontSize` | 14 | 14-16 | Fine for desktop; may need 18+ for mobile |
| `lineHeight` | 1 (normal) | 1.1-1.2 | Slightly increased line height improves readability, especially for CJK |
| `letterSpacing` | 0 | 0 | Fine; don't add spacing for CJK (breaks double-width alignment) |
| `customGlyphs` | true | true | Draws box-drawing, block elements, powerline symbols as custom glyphs (better rendering). Only works with canvas/WebGL renderer, not DOM |
| `minimumContrastRatio` | 1 | 4.5 | WCAG AA compliance; dynamically adjusts foreground color for readability |
| `rightClickSelectsWord` | false | true (macOS) / false (others) | Standard macOS behavior; right-click selects word under cursor |
| `wordSeparator` | (default) | Customize for agent output | Default includes `~./!@#$%^&*()-=+[{]}\|;:'",<>/?`. May want to adjust for Chinese punctuation |
| `macOptionIsMeta` | false | true | Treat Option key as Meta on macOS (enables Alt+key shortcuts) |
| `macOptionClickForcesSelection` | false | true | Allow selection in mouse-mode apps (like tmux) by holding Option |
| `altClickMovesCursor` | true | true | Already fine; Alt+click moves cursor to position |
| `ignoreBracketedPasteMode` | false | false | Respect bracketed paste mode; important for proper paste handling |
| `screenReaderMode` | false | false | Enable for accessibility; adds ARIA labels |
| `cursorInactiveStyle` | 'outline' | 'outline' | Shows cursor position even when terminal is unfocused |
| `drawBoldTextInBrightColors` | true | true | Fine; bold text uses bright color variants |
| `overviewRulerWidth` | 0 (hidden) | 14-20 | Shows overview ruler on right side; useful with search addon decorations |

**Theme options not currently set:**

| Option | Description |
|---|---|
| `selectionForeground` | Text color during selection (default: theme-dependent) |
| `selectionInactiveBackground` | Selection color when terminal is unfocused |
| `extendedAnsi` | ANSI colors 16-255 (for 256-color support) |

### 5. Best Practices for xterm.js Terminal UX in a Web App

#### Keyboard Shortcuts

**Standard terminal shortcuts the web TUI should support:**

| Shortcut | Action | Current Support |
|---|---|---|
| Ctrl+C | Abort/interrupt | YES (line 196-204) |
| Ctrl+L | Clear screen | NO (not handled) |
| Ctrl+U | Clear input line | NO |
| Ctrl+W | Delete word backward | NO |
| Ctrl+A | Move cursor to start | NO |
| Ctrl+E | Move cursor to end | NO |
| Ctrl+K | Kill to end of line | NO |
| Ctrl+R | Reverse search history | NO |
| Ctrl+Shift+F | Find/search | NO (no search addon) |
| Ctrl+Shift+C | Copy selection | Partially (browser default) |
| Ctrl+Shift+V | Paste | Partially (browser default) |
| Home/End | Line start/end | NO |
| Delete | Delete forward | NO |
| Page Up/Down | Scroll buffer | NO (handled by xterm internally) |

**Implementation approach:** Use `term.attachCustomKeyEventHandler()` to intercept key combinations before xterm processes them. Return `false` to prevent xterm's default handling, `true` to allow it.

```javascript
term.attachCustomKeyEventHandler((ev: KeyboardEvent) => {
  if (ev.type !== 'keydown') return true

  // Ctrl+Shift+F: open search
  if (ev.ctrlKey && ev.shiftKey && ev.key === 'F') {
    openSearch()
    return false
  }
  // Ctrl+L: clear
  if (ev.ctrlKey && ev.key === 'l') {
    term.clear()
    return false
  }
  // ... etc
  return true
})
```

#### Paste Handling

**Current behavior:** The project uses `term.onData(handleTermData)` which receives pasted text as a single string. The `handleTermData` function processes it character by character, which means:
- Multi-line paste is not handled (each character goes through the ASCII check)
- CJK paste is dropped (same ASCII filter bug)
- No bracketed paste mode support

**Best practice for paste:**
1. Detect paste by checking if the data string has length > 1 (or contains newlines)
2. For multi-line paste, process the entire string rather than character-by-character
3. Consider using `term.onKey` for single-key handling and `term.onData` for paste/composed text
4. The `ignoreBracketedPasteMode` option should remain `false` so the terminal can signal paste to applications

**Alternative approach:** Use `attachCustomKeyEventHandler` to intercept Ctrl+V and handle paste explicitly, rather than relying on xterm's built-in paste which goes through `onData`.

#### Drag-Select and Copy

**xterm.js built-in selection:**
- Click: Position cursor (in the project's custom handler, this is overridden)
- Double-click: Select word (uses `wordSeparator` option)
- Triple-click: Select line
- Click+drag: Select range
- Shift+click: Extend selection

**The project's current issue:** The custom `handleTermData` intercepts all input, but xterm.js's built-in selection still works for display purposes. However, the project doesn't expose a way to copy the selection.

**Copy implementation options:**
1. **Browser default:** `document.execCommand('copy')` on Ctrl+Shift+C (deprecated but works)
2. **Clipboard API:** `navigator.clipboard.writeText(term.getSelection())` (modern, requires HTTPS or localhost)
3. **@xterm/addon-clipboard:** Enables OSC 52 clipboard operations (for remote terminal scenarios)
4. **@xterm/addon-serialize:** `serializeAddon.serializeAsHTML({ onlySelection: true })` for rich-text copy

**Right-click context menu:**
xterm.js does not provide a built-in context menu. Implementation requires:
1. Listen for `contextmenu` event on the terminal container
2. Show a custom menu with Copy, Paste, Select All, Search options
3. Use `term.getSelection()` to check if text is selected (enable/disable Copy)
4. Use `navigator.clipboard` for copy/paste operations

#### IME Composition Best Practices (Summary)

(Detailed analysis in `xterm-cjk-input.md`)

1. **Track composition state** via `term.textarea` composition events
2. **During composition**, ignore `onData` events (they contain partial data)
3. **After compositionend**, process the full composed string from `onData`
4. **Handle CJK width** — CJK characters are width=2; advance cursor by width, not by 1
5. **Use `term.unicode.getStringCellWidth(str)`** (experimental API, already enabled via `allowProposedApi: true`)

#### Renderer Selection Strategy

**Recommended renderer priority:**
1. **WebGL** (fastest, GPU-accelerated) — try first, fall back on context loss
2. **Canvas** (good performance, no GPU dependency) — fallback from WebGL
3. **DOM** (default, slowest) — final fallback

```javascript
try {
  const webglAddon = new WebglAddon()
  webglAddon.onContextLoss(() => {
    webglAddon.dispose()
    // Optionally try canvas fallback
  })
  term.loadAddon(webglAddon)
} catch {
  // WebGL not available, use default DOM renderer
  // Or try canvas:
  // term.loadAddon(new CanvasAddon())
}
```

**Note on customGlyphs:** The `customGlyphs: true` option (default) only works with canvas/WebGL renderers. The DOM renderer renders all characters using the font. If the project stays on the DOM renderer, box-drawing characters may have gaps at non-default line heights.

### 6. Package Version Compatibility

**Current project setup:**
- `xterm: ^5.3.0` (old package name, deprecated)
- `@xterm/addon-fit: ^0.11.0`
- `@xterm/addon-web-links: ^0.12.0`

**Latest versions:**
- `@xterm/xterm: 6.0.0` (new package name, replaces `xterm`)
- All `@xterm/addon-*` packages are compatible with both `xterm@5` and `@xterm/xterm@6`

**Key compatibility notes:**
- `@xterm/addon-web-fonts` requires `@xterm/xterm@^6.1.0-beta.86` — **incompatible with `xterm@5`**
- `@xterm/addon-canvas` peer-depends on `@xterm/xterm@^5.0.0` — may work with old `xterm@5` package
- All other addons have no peer dependencies declared
- Upgrading from `xterm@5` to `@xterm/xterm@6` requires changing `import { Terminal } from 'xterm'` to `import { Terminal } from '@xterm/xterm'`
- The v6 release includes the IME duplicate input fix (issue #5023)

### Files Found

| File Path | Description |
|---|---|
| `frontend/src/views/AgentTUI.vue` | Main TUI component; xterm.js Terminal init at lines 554-585, handleTermData at 165-237 |
| `frontend/package.json` | Lists xterm@^5.3.0, @xterm/addon-fit@^0.11.0, @xterm/addon-web-links@^0.12.0 |
| `frontend/node_modules/xterm/typings/xterm.d.ts` | Full xterm.js v5 type definitions; all ITerminalOptions, events, methods |
| `frontend/node_modules/xterm/src/browser/input/CompositionHelper.ts` | Internal IME handling; compositionstart/update/end lifecycle |
| `frontend/node_modules/@xterm/addon-fit/typings/addon-fit.d.ts` | FitAddon API (fit, proposeDimensions) |
| `frontend/node_modules/@xterm/addon-web-links/typings/addon-web-links.d.ts` | WebLinksAddon API (hover, leave, urlRegex) |
| `frontend/src/utils/markdownToAnsi.ts` | Markdown-to-ANSI converter; handles code blocks, bold, italic, links |
| `backend/omp/extensions/xhsagent-ext/src/index.ts` | Extension entry; registers 7 tools, 2 commands, 2 event hooks |
| `backend/omp/extensions/xhsagent-ext/src/types.ts` | API response types (WorkflowStartResponse, WorkflowStatusResponse, etc.) |
| `backend/omp/extensions/xhsagent-ext/src/commands/xhs.ts` | /xhs command handler; sends user message to agent |
| `backend/omp/extensions/xhsagent-ext/src/commands/xhs_review.ts` | /xhs-review command handler |
| `backend/omp/extensions/xhsagent-ext/src/events.ts` | Event hooks: session_start health check, before_agent_start context injection |
| `backend/omp/extensions/xhsagent-ext/src/api_client.ts` | HTTP + SSE client for backend API |
| `backend/omp/extensions/xhsagent-ext/src/config.ts` | Extension config (apiBase, timeout, sseTimeout) |
| `backend/omp/extensions/xhsagent-ext/package.json` | Extension package; depends on @oh-my-pi/pi-coding-agent >=16.0.0 |

### Code Patterns

**Pattern 1: Current xterm.js initialization (AgentTUI.vue:554-594)**
- Creates Terminal with minimal options
- Loads FitAddon and WebLinksAddon
- Opens on DOM element, fits to container
- Attaches `onData` handler for all input
- ResizeObserver for auto-fit

**Pattern 2: Custom input handling (AgentTUI.vue:165-237)**
- `handleTermData(data: string)` processes each input event
- Switch on `data.charCodeAt(0)` for special keys (Enter, Backspace, Tab, Ctrl+C, arrows)
- ASCII printable range only: `code >= 32 && code < 127`
- No composition state tracking
- No paste detection
- No CJK width handling

**Pattern 3: omp extension registration (xhsagent-ext/src/index.ts)**
- Single entry function receives `ExtensionAPI` (pi)
- `pi.registerTool()` for domain tools with Zod schemas
- `pi.registerCommand()` for slash commands
- `pi.on()` for event hooks
- `pi.sendUserMessage()` to inject messages into agent conversation

**Pattern 4: xterm.js CompositionHelper (internal, node_modules)**
- Manages composition lifecycle via DOM events on hidden textarea
- `compositionstart` -> `_isComposing = true`
- `compositionend` -> `_finalizeComposition(true)` -> `triggerDataEvent(input)` -> fires `onData`
- `keydown(keyCode=229)` -> routes through composition fallback
- Visual overlay (`_compositionView`) shows in-progress text near cursor

### External References

- [xterm.js README](https://github.com/xtermjs/xterm.js/blob/master/README.md) — Official addon list, features, browser support
- [xterm.js typings/xterm.d.ts](https://github.com/xtermjs/xterm.js/blob/master/typings/xterm.d.ts) — Complete API reference
- [@xterm/addon-search on npm](https://www.npmjs.com/package/@xterm/addon-search) — v0.16.0, search with decorations
- [@xterm/addon-webgl on npm](https://www.npmjs.com/package/@xterm/addon-webgl) — v0.19.0, GPU-accelerated renderer
- [@xterm/addon-canvas on npm](https://www.npmjs.com/package/@xterm/addon-canvas) — v0.7.0, canvas 2D renderer
- [@xterm/addon-image on npm](https://www.npmjs.com/package/@xterm/addon-image) — v0.9.0, SIXEL/IIP/Kitty image protocols
- [@xterm/addon-serialize on npm](https://www.npmjs.com/package/@xterm/addon-serialize) — v0.14.0, buffer serialization
- [@xterm/addon-ligatures on npm](https://www.npmjs.com/package/@xterm/addon-ligatures) — v0.10.0, font ligatures
- [@xterm/addon-clipboard on npm](https://www.npmjs.com/package/@xterm/addon-clipboard) — v0.2.0, OSC 52 clipboard
- [@xterm/addon-unicode-graphemes on npm](https://www.npmjs.com/package/@xterm/addon-unicode-graphemes) — v0.4.0, experimental
- [@xterm/addon-web-fonts on npm](https://www.npmjs.com/package/@xterm/addon-web-fonts) — v0.1.0, requires @xterm/xterm@6+
- [@xterm/xterm on npm](https://www.npmjs.com/package/@xterm/xterm) — v6.0.0, new package name
- [VS Code terminal implementation](https://github.com/microsoft/vscode/tree/main/src/vs/workbench/contrib/terminal) — Reference implementation using xterm.js with all addons

### Related Specs

- `.trellis/tasks/06-28-fix-web-tui-chinese-input-and-interaction-experience/prd.md` — Task PRD
- `.trellis/tasks/06-28-fix-web-tui-chinese-input-and-interaction-experience/research/xterm-cjk-input.md` — CJK/IME input research (companion file)

## Caveats / Not Found

1. **@xterm/addon-web-fonts is incompatible with xterm@5.** It requires `@xterm/xterm@^6.1.0-beta.86`. If the project wants web font loading, it must either upgrade to `@xterm/xterm@6` or implement font loading manually.

2. **@xterm/addon-canvas type definitions returned 404** from the GitHub master branch. The addon exists on npm (v0.7.0) but its typings may be in a different location or only available within the installed package.

3. **The `term.textarea` property** used for composition event listeners is not part of the public API. It works in v5 but is not guaranteed to remain stable across versions.

4. **WebGL renderer availability** depends on browser/device. Mobile browsers and older devices may not support WebGL2. The implementation should always have a fallback path.

5. **The `customGlyphs` option** (default true) only works with canvas/WebGL renderers. If the project stays on the DOM renderer, box-drawing characters may have visual gaps.

6. **No official xterm.js addon for a search UI widget.** The `@xterm/addon-search` provides the search logic but no UI. The project would need to build its own search bar component or use the third-party `xterm-addon-search-bar`.

7. **Right-click context menu** is not built into xterm.js. It must be implemented as a custom overlay component.

8. **The omp native TUI's exact capabilities** are inferred from the extension API surface. The actual TUI may have additional features (syntax highlighting, markdown rendering, etc.) not visible from the extension code alone.
