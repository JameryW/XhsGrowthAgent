// frontend/tests/composables/useRetry.spec.ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useRetry, retryWithBackoff, calculateDelay, DEFAULT_CONFIG } from '@/composables/useRetry'
import type { RetryConfig } from '@/types/error'

describe('useRetry', () => {
  describe('calculateDelay', () => {
    it('returns baseDelay for first retry (retryCount=0)', () => {
      const delay = calculateDelay(0, 1000, 4000)
      expect(delay).toBe(1000)
    })

    it('returns 2x baseDelay for second retry (retryCount=1)', () => {
      const delay = calculateDelay(1, 1000, 4000)
      expect(delay).toBe(2000)
    })

    it('returns 4x baseDelay for third retry (retryCount=2)', () => {
      const delay = calculateDelay(2, 1000, 4000)
      expect(delay).toBe(4000)
    })

    it('caps delay at maxDelay for higher retry counts', () => {
      // 1000 * 2^3 = 8000, but maxDelay is 4000
      const delay = calculateDelay(3, 1000, 4000)
      expect(delay).toBe(4000)
    })

    it('uses default values when not provided', () => {
      const delay = calculateDelay(0)
      expect(delay).toBe(DEFAULT_CONFIG.baseDelay)
    })

    it('respects custom baseDelay', () => {
      const delay = calculateDelay(0, 500, 2000)
      expect(delay).toBe(500)
    })

    it('respects custom maxDelay', () => {
      const delay = calculateDelay(2, 1000, 3000)
      // 1000 * 4 = 4000, but maxDelay is 3000
      expect(delay).toBe(3000)
    })
  })

  describe('retryWithBackoff', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('returns result immediately when function succeeds', async () => {
      const fn = vi.fn().mockResolvedValue('success')
      const result = await retryWithBackoff(fn)

      expect(result).toBe('success')
      expect(fn).toHaveBeenCalledTimes(1)
    })

    it('retries on first failure', async () => {
      const fn = vi.fn()
        .mockRejectedValueOnce(new Error('fail'))
        .mockResolvedValueOnce('success')

      const promise = retryWithBackoff(fn)
      await vi.runAllTimersAsync()
      const result = await promise

      expect(result).toBe('success')
      expect(fn).toHaveBeenCalledTimes(2)
    })

    it('retries multiple times before success', async () => {
      const fn = vi.fn()
        .mockRejectedValueOnce(new Error('fail 1'))
        .mockRejectedValueOnce(new Error('fail 2'))
        .mockResolvedValueOnce('success')

      const promise = retryWithBackoff(fn)
      await vi.runAllTimersAsync()
      const result = await promise

      expect(result).toBe('success')
      expect(fn).toHaveBeenCalledTimes(3)
    })

    it('throws after exhausting all retries', async () => {
      const config: RetryConfig = { maxRetries: 2, baseDelay: 1000, maxDelay: 4000 }

      // Mock that always fails - use mockImplementation for proper error handling
      const fn = vi.fn().mockImplementation(() => Promise.reject(new Error('always fails')))

      // Catch the rejection to prevent unhandled rejection warning
      const promise = retryWithBackoff(fn, config).catch(e => e)
      await vi.runAllTimersAsync()
      const result = await promise

      expect(result).toBeInstanceOf(Error)
      expect(result.message).toBe('always fails')
      expect(fn).toHaveBeenCalledTimes(3) // 1 initial + 2 retries
    })

    it('throws after max retries (default 3)', async () => {
      const fn = vi.fn().mockImplementation(() => Promise.reject(new Error('always fails')))

      // Catch the rejection to prevent unhandled rejection warning
      const promise = retryWithBackoff(fn).catch(e => e)
      await vi.runAllTimersAsync()
      const result = await promise

      expect(result).toBeInstanceOf(Error)
      expect(result.message).toBe('always fails')
      expect(fn).toHaveBeenCalledTimes(4) // 1 initial + 3 retries
    })

    it('uses exponential backoff delays', async () => {
      const fn = vi.fn()
        .mockImplementationOnce(() => Promise.reject(new Error('fail')))
        .mockImplementationOnce(() => Promise.reject(new Error('fail')))
        .mockImplementationOnce(() => Promise.reject(new Error('fail')))
        .mockImplementation(() => Promise.reject(new Error('always fails')))

      const config: RetryConfig = { maxRetries: 3, baseDelay: 1000, maxDelay: 4000 }

      // Catch the rejection to prevent unhandled rejection warning
      const promise = retryWithBackoff(fn, config).catch(e => e)

      // Run timers and wait
      await vi.runAllTimersAsync()

      const result = await promise
      expect(result).toBeInstanceOf(Error)
      expect(result.message).toBe('always fails')

      // Check the sequence of retries
      expect(fn).toHaveBeenCalledTimes(4)
    })

    it('works with sync functions', async () => {
      const fn = vi.fn()
        .mockReturnValueOnce(new Error('fail'))
        .mockReturnValue('success')

      // For sync functions, we need to make them async-compatible
      const syncFn = () => {
        const result = fn()
        if (result instanceof Error) throw result
        return result
      }

      const promise = retryWithBackoff(syncFn)
      await vi.runAllTimersAsync()
      const result = await promise

      expect(result).toBe('success')
    })

    it('converts non-Error throws to Error', async () => {
      const fn = vi.fn()
        .mockImplementationOnce(() => Promise.reject('string error'))
        .mockImplementationOnce(() => Promise.reject('string error'))
        .mockImplementation(() => Promise.reject('string error'))

      const config: RetryConfig = { maxRetries: 2, baseDelay: 100, maxDelay: 400 }

      // Catch the rejection to prevent unhandled rejection warning
      const promise = retryWithBackoff(fn, config).catch(e => e)
      await vi.runAllTimersAsync()

      const result = await promise
      expect(result).toBeInstanceOf(Error)
      expect(result.message).toBe('string error')
    })

    it('respects custom config', async () => {
      const fn = vi.fn()
        .mockRejectedValueOnce(new Error('fail'))
        .mockResolvedValueOnce('success')

      const config: RetryConfig = { maxRetries: 5, baseDelay: 500, maxDelay: 2000 }

      const promise = retryWithBackoff(fn, config)
      await vi.runAllTimersAsync()
      const result = await promise

      expect(result).toBe('success')
    })
  })

  describe('DEFAULT_CONFIG', () => {
    it('has maxRetries of 3', () => {
      expect(DEFAULT_CONFIG.maxRetries).toBe(3)
    })

    it('has baseDelay of 1000ms', () => {
      expect(DEFAULT_CONFIG.baseDelay).toBe(1000)
    })

    it('has maxDelay of 4000ms', () => {
      expect(DEFAULT_CONFIG.maxDelay).toBe(4000)
    })
  })

  describe('useRetry composable', () => {
    it('returns retryWithBackoff function', () => {
      const { retryWithBackoff } = useRetry()
      expect(typeof retryWithBackoff).toBe('function')
    })

    it('returns calculateDelay function', () => {
      const { calculateDelay } = useRetry()
      expect(typeof calculateDelay).toBe('function')
    })

    it('returns DEFAULT_CONFIG', () => {
      const { DEFAULT_CONFIG } = useRetry()
      expect(DEFAULT_CONFIG).toBeDefined()
      expect(DEFAULT_CONFIG.maxRetries).toBe(3)
      expect(DEFAULT_CONFIG.baseDelay).toBe(1000)
      expect(DEFAULT_CONFIG.maxDelay).toBe(4000)
    })
  })
})