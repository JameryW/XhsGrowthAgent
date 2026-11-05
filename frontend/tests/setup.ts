// ponytail: globally install i18n + pinia plugins so component tests that mount
// useI18n()-using components don't each need to repeat `plugins: [i18n]`.
// Without this, ~14 spec files fail with "Need to install with `app.use`".
import { config } from '@vue/test-utils'
import { vi } from 'vitest'
import i18n from '@/locales'

config.global.plugins = [...(config.global.plugins ?? []), i18n]

// Node >= 22 ships a real (undici) WebSocket as a global. Component tests that
// mount views whose stores connect the realtime client would then open a real
// ws://localhost:3000 connection; after teardown that leaves an unhandled
// ECONNREFUSED and vitest exits 1 even though every assertion passed. Specs that
// need WebSocket behaviour replace this with vi.stubGlobal in their own setup.
class InertWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3

  readonly readyState = InertWebSocket.CLOSED

  close(): void {}
  send(): void {}
  addEventListener(): void {}
  removeEventListener(): void {}
  dispatchEvent(): boolean {
    return false
  }
}

vi.stubGlobal('WebSocket', InertWebSocket)
