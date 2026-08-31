# Free Draft Review Route Context Design

## Existing seams

- `History.vue` owns the History tab and local-view account query.
- `FreeDraftHistoryPanel.vue` owns the account-scoped draft list, local filters, preview queue and next-step navigation.
- `AgentTUI.vue` validates free-mode account and draft deep links before running commands.

The panel is already a deep module: one `accountId` prop hides list fetching, filters, stale guards, mutations and preview orchestration. Expanding its external interface with several route-state props/emits would make callers learn internal review state. The route context should therefore remain an internal dependency used by the panel and TUI.

## Dependency classification

Route-context encoding is in-process pure computation. It needs no adapter seam. Tests should exercise its exported interface directly and UI tests should assert only observable navigation/restoration behavior.

## Selected interface shape

Use one module to own:

1. accepted review filter values;
2. query field names and normalization limits;
3. parsing History/TUI source query into a normalized context;
4. building namespaced TUI source query; and
5. building a fixed History route query from a normalized context plus the resolved owned account.

No caller may provide a route name or path. The History destination is fixed inside the module. This makes arbitrary redirect behavior impossible by construction.

## State ownership

- The URL is durable navigation state, not a data cache.
- History keeps reactive list/filter/preview ownership and mirrors only the small restorable context into query.
- TUI derives account ownership from `accountsStore`; raw query account IDs never become return authority.
- A pending draft ID is resolved against the loaded, filtered, account-scoped list before opening the drawer.

## Test surface

- Pure module: normalized round trips and rejected input.
- History panel: route state mirrors/restores and stale account/list safety.
- TUI: conditional return entry and fixed safe navigation.

Do not assert private helper calls or internal query field constants outside the module tests.
