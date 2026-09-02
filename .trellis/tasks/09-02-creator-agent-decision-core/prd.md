# Creator Agent Decision Core

## Problem

XHS Growth Agent currently learns Style DNA, conversion plays, reusable materials, and performance patterns in order to make better content. Those assets still answer "how should we create the next post?" They do not represent the creator as an independent identity, cannot answer "what would this creator recommend for this person and why?", and do not retain the resulting decision/feedback loop.

The missing product layer is a durable decision core that converts creator judgement into a small machine-callable interface while preserving evidence, account isolation, and creator control over learning.

## Product thesis

Creator Agent is not an AI copywriter. It is a platform-independent Creator ID plus a revisioned Creator Model and creator-scoped Relationship Memory. Its primary output is an evidence-backed Decision Record; content is only one downstream expression of that intelligence.

## Goal

Ship the first backend vertical slice of Creator Agent:

1. create and revise an account-linked but platform-independent Creator Model;
2. evaluate structured candidate choices with explicit Decision Policies;
3. reject unsupported certainty and expose the Evidence used;
4. persist every Decision Record as the start of the Decision Dataset;
5. append User Feedback and update Relationship Memory without silently mutating the Creator Model.

## Domain contract

Canonical language is defined in `CONTEXT.md`.

A Creator Model contains:

- a generated, stable Creator ID;
- a monotonically increasing revision;
- an identity summary and declared domains;
- Preferences with contextual applicability, strength, and Evidence links;
- Knowledge Claims with confidence and Evidence links;
- Decision Policies with contextual applicability, signal weights, preferred tags, excluded tags, rationale, and Evidence links;
- an Evidence collection with source kind, source reference, claim, observation time, and confidence.

A Decision Request contains:

- one concrete XHS Account binding and Audience Member;
- a goal and structured context;
- zero or more exact hard constraints;
- two or more candidates with attributes, normalized signals, tags, and optional candidate Evidence.

A Decision Record contains:

- the Creator ID and exact model revision used;
- matched policy IDs;
- ranked eligible candidates and excluded candidates;
- deterministic score explanations and Evidence snapshots;
- evidence coverage and a bounded confidence score;
- a status of `recommended`, `insufficient_evidence`, or `no_eligible_candidate`;
- append-only User Feedback entries.

Relationship Memory contains creator-scoped interaction counts, accepted/rejected candidate IDs, the latest stated correction, and the last interaction time. The same Audience Member ID under two creators is two separate relationships.

## Deep module interface

The external seam is a `CreatorAdvisor` module with two behavioural methods:

- `decide(request) -> DecisionRecord`
- `record_feedback(decision_id, feedback) -> FeedbackResult`

Model administration is kept separate from decision behaviour through a `CreatorModelStore` module. HTTP routes are adapters over these interfaces; scoring, evidence coverage, feedback classification, and relationship updates remain hidden inside the modules.

## Decision semantics

1. Match policies whose declared context conditions equal the Decision Request context. Empty conditions mean globally applicable.
2. Exclude candidates that fail exact hard constraints or carry a tag excluded by a matched policy.
3. Score eligible candidates from matched policy signal weights and Preference tag adjustments. Candidate signals are normalized to `[0, 1]`.
4. Link only Evidence IDs that exist in the exact Creator Model revision or on the candidate.
5. Return `insufficient_evidence` rather than a recommendation when no policy matches or no linked evidence supports the decision.
6. Return `no_eligible_candidate` when every candidate is excluded.
7. Derive confidence from evidence confidence/coverage and ranking separation; never present it as probability of real-world success.
8. Persist the complete Decision Record before returning it.

## Feedback semantics

- Outcomes are `considered`, `accepted`, `purchased`, `satisfied`, `rejected`, or `dissatisfied`.
- Feedback is append-only on the Decision Record.
- Accepted/purchased/satisfied outcomes add the selected candidate to Relationship Memory's accepted history; rejected/dissatisfied outcomes add it to rejected history.
- A correction or dissatisfied outcome creates a Learning Signal with `pending_creator_review`.
- Feedback never changes Creator Model preferences, claims, policies, or revision.

## HTTP adapter

All endpoints are authenticated and scoped through the existing account ownership rules:

- `GET /api/creator-agent/model?account_id=...`
- `PUT /api/creator-agent/model`
- `POST /api/creator-agent/decisions`
- `GET /api/creator-agent/decisions/{decision_id}?account_id=...`
- `POST /api/creator-agent/decisions/{decision_id}/feedback`
- `GET /api/creator-agent/relationships/{audience_id}?account_id=...`

Model writes use optimistic concurrency. `expected_revision=0` creates a model; later writes must provide the current revision. A revision conflict returns a typed API error.

## Persistence

Follow the repository's existing Postgres-with-process-memory-fallback convention. Durable storage owns:

- the latest Creator Model snapshot per account/Creator ID;
- Decision Records keyed by account and decision ID;
- Relationship Memory keyed by account and Audience Member ID.

Table creation is idempotent and included in application startup. Tests can reset the memory fallback without requiring Postgres.

## Compatibility and integration

- XHS Account remains the operational/platform binding and authorization scope.
- Creator ID is generated independently and persisted in the Creator Model.
- Existing Creative Memory is unchanged in this increment. Its records may be referenced as `creator_content` Evidence by callers, but no automatic projection is introduced yet.
- Existing trend/brief/free workflows remain unchanged. A later increment can consume `CreatorAdvisor.decide` instead of constructing mode-specific suggestion strings.

## Out of scope

- Natural-language chat orchestration or LLM-generated recommendations.
- Automatic extraction of a full Creator Model from historical posts.
- Search, price tracking, purchasing, booking, merchant contact, and after-sales tools.
- Public Audience Member authentication or cross-platform API credentials.
- Frontend management/decision UI.
- Automatic Creator Model updates from feedback or performance.

## Acceptance criteria

- A first model write generates a stable Creator ID and revision `1`; a valid later write increments the revision; stale writes fail without data loss.
- Account ownership is enforced for every route and cross-account Decision Record access returns not found.
- The same request and model revision produce the same candidate ordering, explanations, and confidence.
- Unsupported decisions return `insufficient_evidence` and do not invent a rationale or citation.
- Every recommended item exposes the supporting Evidence used and every Decision Record stores the model revision.
- Hard constraints and policy exclusions are visible in the Decision Record.
- Feedback is append-only, idempotent by feedback ID, and updates only the matching creator/audience Relationship Memory.
- Dissatisfaction/correction returns `pending_creator_review`; the Creator Model revision and payload remain unchanged.
- Postgres DDL and the in-memory fallback are covered by focused tests.
- API contract tests cover authentication/ownership, model revision conflicts, decision statuses, evidence provenance, feedback, and relationship isolation.
- Ruff, mypy, focused pytest, and the OpenAPI contract tests pass.
