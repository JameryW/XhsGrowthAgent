# Require explicit resolution before Action execution

Creator Agent will persist Action Intents in `pending_confirmation` and keep `confirmed` separate from `executed`. The first Action seam is therefore auditable and machine-readable without allowing a recommendation to trigger a purchase, booking, message, or other external side effect before a later Tool/Skill executor receives an explicit resolution.
