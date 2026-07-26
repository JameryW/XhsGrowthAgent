/**
 * Reactive multi-account attention hints (nav badges, etc.).
 * Session-backed so Review/Navbar/MobileTabBar share one source of truth.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { getWorkflowAccountTotals } from '@/api/workflow'
import {
  REVIEW_AWAITING_TOTALS_KEY,
  readSessionTotals,
  sumAllAccountTotals,
  writeSessionTotals,
} from '@/utils/accountViewSession'
import { useAccountsStore } from './accounts'
import { useAuthStore } from './auth'

/** Skip network when Navbar + MobileTabBar + route watches all refresh close together. */
export const REVIEW_AWAITING_TOTALS_TTL_MS = 20_000

export const useCrossAccountHintsStore = defineStore('crossAccountHints', () => {
  const reviewAwaitingTotals = ref<Record<string, number>>(
    readSessionTotals(REVIEW_AWAITING_TOTALS_KEY),
  )
  let refreshInFlight: Promise<void> | null = null
  let lastRefreshAt = 0

  const reviewAwaitingCount = computed(() => sumAllAccountTotals(reviewAwaitingTotals.value))

  function setReviewAwaitingTotals(totals: Record<string, number>) {
    reviewAwaitingTotals.value = { ...totals }
    writeSessionTotals(REVIEW_AWAITING_TOTALS_KEY, reviewAwaitingTotals.value)
  }

  function hydrateFromSession() {
    reviewAwaitingTotals.value = readSessionTotals(REVIEW_AWAITING_TOTALS_KEY)
  }

  async function refreshReviewAwaitingTotals(force = false): Promise<void> {
    const auth = useAuthStore()
    const accounts = useAccountsStore()
    if (!auth.isAuthenticated) return
    if (!force && accounts.accounts.length <= 1) {
      // Still hydrate from session for single-account installs.
      hydrateFromSession()
      return
    }
    if (
      !force
      && lastRefreshAt > 0
      && Date.now() - lastRefreshAt < REVIEW_AWAITING_TOTALS_TTL_MS
    ) {
      return
    }
    if (refreshInFlight) return refreshInFlight

    refreshInFlight = (async () => {
      try {
        const res = await getWorkflowAccountTotals(
          { status: 'awaiting_review' },
          { suppressToast: true },
        )
        if (res?.totals) setReviewAwaitingTotals(res.totals)
        lastRefreshAt = Date.now()
      } catch {
        hydrateFromSession()
      } finally {
        refreshInFlight = null
      }
    })()
    return refreshInFlight
  }

  return {
    reviewAwaitingTotals,
    reviewAwaitingCount,
    setReviewAwaitingTotals,
    hydrateFromSession,
    refreshReviewAwaitingTotals,
  }
})
