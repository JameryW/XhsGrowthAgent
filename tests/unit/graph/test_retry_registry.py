"""P0-W3 regression tests: explicit retry-policy registry + no auto-retry on side-effect nodes.

LangGraph RetryPolicy only fires on exceptions raised from the node wrapper.
Two invariants being locked here:

1. `publisher` performs an external side effect (real XHS posting) — generic
   framework auto-retry is forbidden; a retry must be an explicit, guarded
   human/action decision (publish-retry with reconciliation).
2. "Does this node have a framework-level retry?" must be an explicit registry
   decision for every node. An unknown node name must raise KeyError instead
   of silently returning None via dict.get.
"""

import pytest
from langgraph.types import RetryPolicy

from backend.graph.builder import build_graph
from backend.graph.error_handling import RETRY_POLICIES, get_retry_policy


class TestRetryPolicyRegistry:
    def test_publisher_has_no_framework_retry_policy(self):
        """Side-effect node: generic auto-retry must be removed (P0-W3)."""
        assert get_retry_policy("publisher") is None

    def test_unknown_node_raises_keyerror_not_silent_none(self):
        with pytest.raises(KeyError):
            get_retry_policy("no_such_node")

    def test_no_retry_nodes_are_explicit_none_entries(self):
        # These previously got None implicitly because the dict lacked the key.
        # After the registry is made exhaustive they must be explicit None.
        for node in ("evaluator_gate", "brief_analyzer", "shooting_planner"):
            assert node in RETRY_POLICIES, f"{node} missing from explicit registry"
            assert get_retry_policy(node) is None

    def test_registry_values_are_policies_or_none(self):
        for node, policy in RETRY_POLICIES.items():
            assert policy is None or isinstance(policy, RetryPolicy), node

    def test_every_graph_node_is_registered(self):
        """Full node inventory: every node added in build_graph must have an
        explicit (possibly None) retry-policy entry — no implicit fallthrough."""
        graph = build_graph()
        for node in graph.nodes:
            if node in ("__start__", "__end__"):
                continue
            assert node in RETRY_POLICIES, f"node {node!r} missing from RETRY_POLICIES"

    def test_read_only_llm_nodes_keep_policies(self):
        # Non-side-effect nodes retain their previous policies.
        assert get_retry_policy("trend_scout") is not None
        assert get_retry_policy("trend_scout").max_attempts == 3
        assert get_retry_policy("copywriter") is not None
        assert get_retry_policy("copywriter").max_attempts == 2
