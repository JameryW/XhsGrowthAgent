# Multi-Account Local View

> Product contract for browsing data owned by one of several XHS accounts
> without always flipping the global workspace active account.

## Core rules

1. **Workspace active account** (`accountsStore.activeAccountId`) is the default
   scope for create / publish / analytics when no local override exists.
2. **Local view account** may differ on History, Review, Analytics, Evaluation.
   Switching chips must **not** call `setActiveAccount` unless the user clicks
   「设为工作区」.
3. **URL `?account=`** (when present) outranks session prefs; workspace is last.
4. **Intentional browse is sticky**: if the user is viewing account B while
   workspace is A, a navbar workspace flip A→C must not yank the view off B.
   Auto-follow only when the previous view *was* the previous workspace.
5. **Empty preferred scope may soft-jump** (History / Review once per mount) to
   a sibling with data; show an auto-browse notice; never flip workspace.
6. **Logout / user switch** clears multi-account session keys
   (`utils/accountViewSession.ts`).

## Surfaces

| Surface | Mechanism |
|---------|-----------|
| History | `useHistoryAccountScope` + list cache + bulk `/workflow/account-totals` |
| Review | Local `reviewAccountId` + `crossAccountHints` awaiting counts |
| Analytics | `analyticsStore.viewAccountId` override |
| Evaluation | `useLocalAccountBrowse` + session sticky (`EVALUATION_VIEW_ACCOUNT_KEY`) |
| Dashboard | Banner when thread `account_id` ≠ workspace; tab amber dot |
| Nav / Mobile | `crossAccountHints.reviewAwaitingCount` badge |

## Ownership resolution (workflows)

1. `status.account_id` from API (authoritative)
2. Else parse `xhs_{account_id}_{8hex}` via `accountIdFromThreadId`
3. Store normalizes in `withAccountId` on every status refresh

## Cross-surface deep links

When navigating between surfaces while browsing a non-workspace account, pass
`?account=` via `accountQuery` / `withAccountQuery` from
`utils/accountViewSession.ts`:

| From → To | Behavior |
|-----------|----------|
| History → Dashboard | include local `historyAccountId` |
| Dashboard → Review / History | include thread owner (`status.account_id` or thread parse) |
| Evaluation → detail / Review / Dashboard | include `selectedAccountId` |
| ActionButtons → Review | include thread owner |
| `/review/:threadId` | seed view from query → thread owner → session → workspace; **do not** soft auto-browse away from a deep-linked thread |

Publish approve default account = current review view account (not workspace).

## Performance

- History list cache TTL 30s + hover prefetch (debounced 140ms)
- Bulk `GET /workflow/account-totals` (optional `status=`) instead of N× `limit=1`
- `crossAccountHints` review totals TTL 20s + in-flight coalesce (Navbar / Mobile / Review)
- History `probeAccountTotals` in-flight coalesce on remount / auto-browse
- DB composite index `(account_id, status)` for status-scoped counts

## Do not

- Aggregate private content across accounts in a single list response
- Retry `POST /workflow/start` (create-once)
- Use `default` as a real account id for scoped queries
- Fall back to a `default` pseudo-account when the accounts API fails or
  returns empty — surface a localized error/empty state with retry and a
  Settings entry (`/settings?tab=xhs-accounts`) instead (see
  `WorkflowStartForm.vue`)
- Soft auto-browse when the user arrived via `/review/:threadId`
