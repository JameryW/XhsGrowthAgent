# Remove automatic engagement workflow

## Context

The workflow still contains an EngagementAgent that can read comments and
private messages and send model-generated replies. The user wants automatic
comment/DM interaction removed entirely from the workflow; explicit operator
tools and post-publish analytics remain separate capabilities.

## Requirements

1. Remove the workflow EngagementAgent, engagement node, graph routes, retry
   policy, and prompt that perform automatic comment/DM reads or sends.
2. Remove the unused `XHS_AUTO_ENGAGEMENT` setting and deployment wiring.
3. Keep the persistent-CDP `XHSEngagement` service and explicit engagement
   tools available for deliberate operator actions.
4. Preserve state/API compatibility for historical engagement fields and
   phases, but ensure stale engagement workflow states terminate safely rather
   than invoking an interaction node.
5. Update tests and Trellis specifications so no test or documentation claims
   the workflow automatically engages.

## Acceptance criteria

- No workflow path instantiates `EngagementAgent` or reaches an `engagement`
  node/router.
- No automatic workflow code calls `get_comments`, `get_direct_messages`,
  `reply_to_comment`, or `send_dm`.
- `XHS_AUTO_ENGAGEMENT` is absent from runtime configuration and deployment
  wiring.
- Explicit `backend/tools/xhs/engagement.py` operations remain intact.
- Full tests, Ruff, formatting, mypy, and compile checks pass.
