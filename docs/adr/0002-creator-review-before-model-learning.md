# Require Creator Review Before Model Learning

Learning Signals are persisted as reviewable observations, but they cannot mutate the Creator Model on their own. A creator review must either dismiss the signal or explicitly submit the complete next model revision with optimistic concurrency; this keeps user feedback useful without turning an ambiguous correction into an unapproved normative rule.
