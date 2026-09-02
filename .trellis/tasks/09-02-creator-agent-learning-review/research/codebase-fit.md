# Codebase fit: Creator Agent learning review

The existing `backend/creator_agent` package already owns the deep domain seam:
`CreatorAdvisor.record_feedback` classifies correction/dissatisfaction and the
`DurableCreatorAgentRepository` atomically stores the decision and relationship
memory. The next increment should extend that seam instead of teaching routes
or FastAPI handlers about learning rules.

## Recommended extension

- Add `LearningSignal` and review request/result models to
  `backend/creator_agent/models.py`.
- Extend the repository protocol with signal listing, signal lookup, feedback
  signal creation, and review application. Keep model revision checks inside
  the adapter transaction.
- Extend the memory and Postgres stores in `backend/db/creator_agent.py` with a
  `creator_agent_learning_signals` table and unique `(account_id, feedback_id)`.
- Keep `CreatorAdvisor` as the public decision/learning module. It should create
  a signal from a persisted Decision Record snapshot and require a complete
  `CreatorModelDefinition` for approval.
- Add authenticated routes under `/api/creator-agent/learning-signals` and
  typed errors for missing/conflicting reviews.

## Risks to preserve

- Feedback retries must return the original signal and learning status.
- Approval must update signal and model atomically; no partial approval may
  publish a model without a signal disposition.
- A review cannot infer a structured model patch from free-form correction.
- Account and Creator ID are different: every query remains scoped by account,
  while the model's Creator ID remains stable across revisions.
