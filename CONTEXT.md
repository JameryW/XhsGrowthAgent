# Creator Agent

This context describes the durable creator intelligence that turns a creator's judgement into evidence-backed decisions for individual audience members. It is distinct from the existing content-production workflow, which remains one consumer of that intelligence.

## Identity and intelligence

**Creator ID**:
A platform-independent identifier for one creator's durable digital identity. An XHS Account is a platform binding and may change without changing the Creator ID.
_Avoid_: Account ID, profile ID

**Creator Model**:
A revisioned snapshot of a creator's explicit preferences, knowledge claims, and decision policies. It represents how the creator judges choices, not the content they have published.
_Avoid_: Persona, prompt, Style DNA

**Preference**:
A creator-authored inclination or aversion that affects a decision in a stated context and carries evidence.
_Avoid_: Style, taste tag

**Knowledge Claim**:
A statement the Creator Model may rely on when deciding, with confidence and supporting Evidence.
_Avoid_: Fact, document chunk

**Decision Policy**:
A creator-authored rule that says which signals matter, what should be preferred or excluded, and why in a stated context.
_Avoid_: Prompt, heuristic

## Evidence and decisions

**Evidence**:
A traceable observation supporting a Preference, Knowledge Claim, Decision Policy, or candidate. It always names its source kind and source reference.
_Avoid_: Context, citation text

**Evidence Graph**:
A creator-scoped provenance map of Evidence nodes and the Creator Model items, decisions, candidates, and Learning Signals that cite them.
_Avoid_: Vector index, citation list

**Evidence Reference**:
A typed edge from one Evidence node to the durable Creator Agent object that cites it, including the relevant Model Revision when one exists.
_Avoid_: Link, foreign key

**Decision Request**:
One Audience Member's goal, context, constraints, and candidate choices submitted to a Creator Agent.
_Avoid_: Prompt, brief

**Decision Record**:
The immutable result of evaluating a Decision Request against one Creator Model revision, including exclusions, ranking, rationale, confidence, and Evidence used.
_Avoid_: Recommendation, answer

**Decision Dataset**:
The growing history of Decision Records and User Feedback used to inspect and improve a Creator Model.
_Avoid_: Chat history, analytics

## Relationship and learning

**Audience Member**:
A person receiving decisions from a Creator Agent, identified independently from the creator's console user and platform followers.
_Avoid_: User, follower, customer

**Relationship Memory**:
The durable, creator-scoped history of one Audience Member's interactions, accepted choices, rejected choices, and stated corrections.
_Avoid_: Audience preference, chat memory

**User Feedback**:
An append-only observation about whether an Audience Member considered, accepted, purchased, liked, or rejected a decision, optionally including a correction.
_Avoid_: Rating, analytics event

**Learning Signal**:
An explicit, reviewable observation derived from User Feedback that may justify a future Creator Model revision. It remains pending until the creator decides whether and how to change the model; it never mutates the Creator Model automatically.
_Avoid_: Model update, training example

**Creator Review**:
The creator's explicit disposition of a Learning Signal, including whether it is accepted or dismissed and, when accepted, which new Creator Model revision embodies the decision.
_Avoid_: Automatic learning, moderation

**Model Revision**:
One complete, creator-approved version of a Creator Model. A revision is immutable once it has been used by a Decision Record.
_Avoid_: Prompt version, chat turn

## Action and execution

**Action Intent**:
A durable, scoped request to perform one declared non-transactional action for an Audience Member using one Decision Record.
_Avoid_: Command, transaction

**Action Resolution**:
The explicit confirmation or cancellation of an Action Intent; confirmation authorizes a future executor but does not itself perform an external side effect.
_Avoid_: Execution, approval

## Existing adjacent concepts

**XHS Account**:
A platform-specific operational binding for publishing, analytics, and imported Creator Center data. It can be linked to a Creator ID but does not own creator intelligence.
_Avoid_: Creator

**Creative Memory**:
Derived Style DNA, conversion plays, and reusable materials used to improve content production. It may contribute Evidence to a Creator Model but is not itself the Creator Model.
_Avoid_: Creator Model, Relationship Memory
