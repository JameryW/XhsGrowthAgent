import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import QrLoginModal from '@/components/settings/QrLoginModal.vue'
import {
  getQrLoginStatus,
  startQrLogin,
  stopQrLogin,
  type QrLoginStatusResponse,
} from '@/api/accounts'

vi.mock('@/api/accounts', async importOriginal => {
  const actual = await importOriginal<typeof import('@/api/accounts')>()
  return {
    ...actual,
    getQrLoginStatus: vi.fn(),
    startQrLogin: vi.fn(),
    stopQrLogin: vi.fn(),
  }
})

const mockedGetQrLoginStatus = vi.mocked(getQrLoginStatus)
const mockedStartQrLogin = vi.mocked(startQrLogin)
const mockedStopQrLogin = vi.mocked(stopQrLogin)

const mountedWrappers: Array<ReturnType<typeof mount>> = []

function qrStatus(
  status: QrLoginStatusResponse['status'],
  verificationRequired = false,
): QrLoginStatusResponse {
  return {
    status,
    qr_id: 'qr-1',
    account_id: 'account-1',
    verification_required: verificationRequired,
  }
}

async function mountAfterPoll(statusResponse: QrLoginStatusResponse) {
  mockedGetQrLoginStatus.mockResolvedValue(statusResponse)
  const wrapper = mount(QrLoginModal, {
    props: {
      accountId: 'account-1',
      accountName: '测试账号',
      isOpen: true,
    },
    global: {
      stubs: {
        AppIcon: { template: '<span />' },
        NeonButton: {
          props: ['disabled', 'loading'],
          template: '<button :disabled="disabled"><slot /></button>',
        },
        Teleport: { template: '<div><slot /></div>' },
      },
    },
  })
  mountedWrappers.push(wrapper)

  await flushPromises()
  await vi.advanceTimersByTimeAsync(2000)
  await flushPromises()

  return wrapper
}

describe('QrLoginModal verification input gate', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    mockedStartQrLogin.mockResolvedValue({
      qr_id: 'qr-1',
      url: 'data:image/png;base64,qr',
      account_id: 'account-1',
    })
    mockedStopQrLogin.mockResolvedValue({ stopped: true, account_id: 'account-1' })
  })

  afterEach(() => {
    for (const wrapper of mountedWrappers.splice(0)) {
      wrapper.unmount()
    }
    vi.useRealTimers()
  })

  it('hides the numeric input when scanning does not require verification', async () => {
    const wrapper = await mountAfterPoll(qrStatus('scanned'))

    expect(wrapper.find('input[inputmode="numeric"]').exists()).toBe(false)
  })

  it('shows the numeric input when scanning requires verification', async () => {
    const wrapper = await mountAfterPoll(qrStatus('scanned', true))

    expect(wrapper.find('input[inputmode="numeric"]').exists()).toBe(true)
  })

  it('clears the numeric input when a later poll no longer requires verification', async () => {
    mockedGetQrLoginStatus
      .mockResolvedValueOnce(qrStatus('scanned', true))
      .mockResolvedValueOnce(qrStatus('scanned', false))
    const wrapper = mount(QrLoginModal, {
      props: {
        accountId: 'account-1',
        accountName: '测试账号',
        isOpen: true,
      },
      global: {
        stubs: {
          AppIcon: { template: '<span />' },
          NeonButton: {
            props: ['disabled', 'loading'],
            template: '<button :disabled="disabled"><slot /></button>',
          },
          Teleport: { template: '<div><slot /></div>' },
        },
      },
    })
    mountedWrappers.push(wrapper)

    await flushPromises()
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()
    expect(wrapper.find('input[inputmode="numeric"]').exists()).toBe(true)

    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()
    expect(wrapper.find('input[inputmode="numeric"]').exists()).toBe(false)
  })

  it('hides the numeric input after the session is confirmed', async () => {
    const wrapper = await mountAfterPoll(qrStatus('confirmed', true))

    expect(wrapper.find('input[inputmode="numeric"]').exists()).toBe(false)
  })
})
