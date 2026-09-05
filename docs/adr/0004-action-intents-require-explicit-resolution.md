# Require explicit resolution before Action execution

Creator Agent will persist Action Intents in `pending_confirmation` and keep `confirmed` separate from `executed`. The first Action seam is therefore auditable and machine-readable without allowing a recommendation to trigger a purchase, booking, message, or other external side effect before a later Tool/Skill executor receives an explicit resolution.

## Deterministic local execution receipts

After confirmation, the first executor is deliberately local and side-effect
free. It reads the immutable Decision Record snapshot and writes exactly one
account-scoped `Action Execution Receipt` for the Action Intent. The receipt
records the capability-specific result and `executor_version`; it does not
contact merchants, search providers, messaging tools, or platform automation.

Execution remains a separate explicit call. Pending and cancelled intents are
rejected with a typed conflict, and receipt creation is protected by the same
memory lock or Postgres action-row lock used to enforce the confirmation gate.
