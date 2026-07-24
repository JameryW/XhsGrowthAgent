/**
 * ansiCards — adaptive ANSI card/box primitives for the free-mode TUI.
 *
 * Pure string builders (plus a write-based title helper) shared by the
 * AgentTUI command handlers so every output block gets the same adaptive
 * width, border style and alignment. All width math is CJK-aware.
 */
import { ANSI, getStringWidth } from './markdownToAnsi'

// Re-export so existing importers (AgentTUI, tests) keep a single entry point.
export { getStringWidth }

/** Pad a string on the right with spaces to a fixed display width. */
export function padEndDisplay(str: string, width: number): string {
  const w = getStringWidth(str)
  return w >= width ? str : str + ' '.repeat(width - w)
}

/** Truncate a string to a max display width, appending … when cut. */
export function truncateDisplay(str: string, maxWidth: number): string {
  if (maxWidth < 1) return ''
  if (getStringWidth(str) <= maxWidth) return str
  let out = ''
  let w = 0
  for (const char of str) {
    const cw = getStringWidth(char)
    if (w + cw > maxWidth - 1) break
    out += char
    w += cw
  }
  return out + '…'
}

/** Unified adaptive card width for every free-mode output box. */
export function cardWidth(termCols: number): number {
  return Math.max(36, Math.min(termCols - 4, 64))
}

export interface WrapOptions {
  /** Spaces prepended to continuation lines of the same paragraph. */
  hangingIndent?: number
}

/**
 * Word-wrap text to a display width (CJK-aware). Latin text prefers breaking
 * at spaces; CJK runs and overlong words hard-break at the width limit.
 * Paragraphs (\n) are preserved — empty ones yield an empty line.
 */
export function wrapDisplay(text: string, width: number, opts: WrapOptions = {}): string[] {
  const { hangingIndent = 0 } = opts
  const lines: string[] = []
  for (const para of text.split('\n')) {
    if (!para) { lines.push(''); continue }
    const firstLimit = Math.max(8, width)
    const contLimit = Math.max(8, width - hangingIndent)
    const paraLines: string[] = []
    let cur = ''
    let curW = 0
    let lastSpace = -1
    const limit = () => (paraLines.length === 0 ? firstLimit : contLimit)
    for (const ch of para) {
      const cw = getStringWidth(ch)
      if (curW + cw > limit()) {
        if (ch === ' ') {
          // natural break at a space — drop the space itself
          paraLines.push(cur)
          cur = ''; curW = 0; lastSpace = -1
          continue
        }
        if (lastSpace > 0) {
          // break at the last space; carry the tail into the next line
          const tail = cur.slice(lastSpace + 1)
          paraLines.push(cur.slice(0, lastSpace))
          cur = tail
          curW = getStringWidth(tail)
          lastSpace = -1
        } else {
          // no break point (CJK run or overlong word) — hard break
          paraLines.push(cur)
          cur = ''; curW = 0; lastSpace = -1
        }
      }
      // Strip spaces orphaned at a wrapped line start (keep paragraph indent)
      if (ch === ' ' && cur === '' && paraLines.length > 0) continue
      cur += ch
      curW += cw
      if (ch === ' ') lastSpace = cur.length - 1
    }
    if (cur) paraLines.push(cur)
    lines.push(...paraLines.map((l, i) => (i === 0 ? l : ' '.repeat(hangingIndent) + l)))
  }
  return lines
}

export interface BoxTitleOptions {
  /** Total box width including the corner glyphs. */
  width: number
  align?: 'left' | 'center'
  borderColor?: string
  titleColor?: string
}

/**
 * Title embedded in the top border: `╭─ Title ─────╮`.
 * The rendered display width always equals opts.width; long titles are
 * truncated so the border never breaks.
 */
export function boxTitleLine(title: string, opts: BoxTitleOptions): string {
  const { width, align = 'left', borderColor = ANSI.BRIGHT_CYAN, titleColor = ANSI.BRIGHT_WHITE } = opts
  const inner = Math.max(8, width - 2)
  const text = truncateDisplay(title, inner - 4)
  const tw = getStringWidth(text)
  const R = ANSI.RESET
  if (align === 'center') {
    const pool = inner - tw - 2 // dashes on both sides + single spaces around the title
    const left = Math.max(1, Math.floor(pool / 2))
    const right = Math.max(1, pool - left)
    return `${borderColor}╭${'─'.repeat(left)}${R} ${titleColor}${text}${R} ${borderColor}${'─'.repeat(right)}╮${R}`
  }
  const right = Math.max(1, inner - 3 - tw)
  return `${borderColor}╭─${R} ${titleColor}${text}${R} ${borderColor}${'─'.repeat(right)}╮${R}`
}

/** Write the card title bar (`╭─ Title ─────╮`) via the given writer. */
export function writeBoxTitle(write: (line: string) => void, title: string, opts: BoxTitleOptions): void {
  write(boxTitleLine(title, opts))
}

/** Left card border + content line. Long content simply overflows right —
 *  there is no right border so CJK text never breaks the box. */
export function boxLine(content = '', borderColor: string = ANSI.BRIGHT_CYAN): string {
  return `${borderColor}│${ANSI.RESET}${content ? ` ${content}` : ''}`
}

/** Bottom card border: `╰──────╯`. */
export function boxBottom(width: number, borderColor: string = ANSI.BRIGHT_CYAN): string {
  return `${borderColor}╰${'─'.repeat(Math.max(2, width - 2))}╯${ANSI.RESET}`
}

/** Adaptive dim separator line. */
export function hr(width: number): string {
  return `${ANSI.DIM}${'─'.repeat(Math.max(1, width))}${ANSI.RESET}`
}

export interface KvLineOptions {
  /** Display width the label column is padded to (CJK-aware). */
  labelWidth?: number
  /** Color applied to the value; omit when the value is already colored. */
  valueColor?: string
}

/** Aligned `label(dim): value(colored)` row. */
export function kvLine(label: string, value: string, opts: KvLineOptions = {}): string {
  const { labelWidth = 0, valueColor } = opts
  const padded = labelWidth > 0 ? padEndDisplay(label, labelWidth) : label
  const val = valueColor ? `${valueColor}${value}${ANSI.RESET}` : value
  return `${ANSI.DIM}${padded}${ANSI.RESET}: ${val}`
}

/** `[text]` badge in the given color. */
export function badge(text: string, color: string = ANSI.BRIGHT_CYAN): string {
  return `${color}[${text}]${ANSI.RESET}`
}

export interface EmptyStateOptions {
  /** Card width the state is centered in (from cardWidth). */
  width: number
  /** Single glyph/emoji shown on its own centered row (bright cyan). */
  icon?: string
  /** Main message (bright white, centered, truncated to fit). */
  title: string
  /** Guidance line (dim, centered, truncated to fit). */
  hint?: string
}

/**
 * Guided empty state inside a card: blank / icon / title / hint / blank,
 * all centered. The caller wraps it with writeBoxTitle + boxBottom.
 */
export function writeEmptyState(write: (line: string) => void, opts: EmptyStateOptions): void {
  const { width, icon, title, hint } = opts
  const center = (plain: string, colored: string): string => {
    const pad = Math.max(1, Math.floor((width - 2 - getStringWidth(plain)) / 2))
    return boxLine(' '.repeat(pad) + colored)
  }
  write(boxLine())
  if (icon) write(center(icon, `${ANSI.BRIGHT_CYAN}${icon}${ANSI.RESET}`))
  const titleText = truncateDisplay(title, width - 6)
  write(center(titleText, `${ANSI.BRIGHT_WHITE}${titleText}${ANSI.RESET}`))
  if (hint) {
    const hintText = truncateDisplay(hint, width - 6)
    write(center(hintText, `${ANSI.DIM}${hintText}${ANSI.RESET}`))
  }
  write(boxLine())
}

/** Uniform error output: red ✗ mark + bright-red message + optional dim hint. */
export function writeError(write: (line: string) => void, message: string, hint?: string): void {
  write(`${ANSI.RED}✗${ANSI.RESET} ${ANSI.BRIGHT_RED}${message}${ANSI.RESET}`)
  if (hint) write(`  ${ANSI.DIM}${hint}${ANSI.RESET}`)
}
