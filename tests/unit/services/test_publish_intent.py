"""The derivable half of a durable publish intent (票 5ba).

These pin the two facts P1 needs from the mainline before any control-plane
wiring happens, and pin that deriving them invents nothing:

1. **Principal**: the named account when one was named, otherwise explicitly the
   deployment (the identity the credential resolver already uses for a blank
   account — not a made-up account id).
2. **Content material**: the submitted content as a canonical body, stored as
   ``artifact://publish_content/<publish_id>`` with its sha256 — the pair a
   durable intent carries.

The module is derivation only: no submit, no authorization, no decision.  A
storage failure must leave the fields empty rather than break a publish.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.services.publish_intent import (
    PUBLISH_CONTENT_KIND,
    publish_content_body,
    publish_intent_material,
    resolve_publish_principal,
    write_publish_content_artifact,
)

_STATE: dict[str, Any] = {
    "copy_content": {
        "selected_title": "春季通勤",
        "body_text": "正文",
        "hashtags": ["穿搭", "#通勤"],
    },
    "visual_plan": {"image_paths": ["/tmp/a.png", "/tmp/b.png"]},
}


class TestPrincipalIsClassifiedNotInvented:
    @pytest.mark.parametrize(
        "options,kind,account_id",
        [
            ({"account_id": "acc-1"}, "account", "acc-1"),
            ({"account_id": "  acc-1  "}, "account", "acc-1"),
            ({}, "deployment", ""),
            ({"account_id": ""}, "deployment", ""),
            ({"account_id": "   "}, "deployment", ""),
            (None, "deployment", ""),
        ],
    )
    def test_a_named_account_is_an_account_and_a_blank_one_is_the_deployment(
        self, options, kind, account_id
    ):
        principal = resolve_publish_principal(options)

        assert principal.kind == kind
        assert principal.account_id == account_id
        assert principal.is_account is (kind == "account")


class TestPublishContentBodyIsTheSubmittedContent:
    def test_the_body_is_the_copy_and_the_images_the_publish_submits(self):
        body = publish_content_body(_STATE)

        assert body == {
            "title": "春季通勤",
            "body": "正文",
            "hashtags": ["穿搭", "#通勤"],
            "image_paths": ["/tmp/a.png", "/tmp/b.png"],
        }

    def test_missing_sub_bodies_keep_the_same_shape(self):
        body = publish_content_body({})

        assert body == {"title": "", "body": "", "hashtags": [], "image_paths": []}

    def test_values_are_coerced_to_strings_without_dropping_them(self):
        body = publish_content_body(
            {
                "copy_content": {"selected_title": 42, "hashtags": [1, None]},
                "visual_plan": {"image_paths": [3]},
            }
        )

        assert body["title"] == "42"
        assert body["hashtags"] == ["1", "None"]
        assert body["image_paths"] == ["3"]

    async def test_the_same_content_hashes_the_same_and_changed_content_does_not(self):
        first = await publish_intent_material(AsyncMock(), "t-1", "p-1", _STATE)
        again = await publish_intent_material(AsyncMock(), "t-1", "p-1", _STATE)
        changed = await publish_intent_material(
            AsyncMock(), "t-1", "p-1", {**_STATE, "copy_content": {"selected_title": "别的"}}
        )

        assert first.content_hash == again.content_hash
        assert len(first.content_hash) == 64
        assert changed.content_hash != first.content_hash


class TestTheArtifactHoldsWhatTheHashDescribes:
    async def test_ref_and_hash_come_from_the_stored_body(self):
        store = AsyncMock()
        state_publish_id = "publish-abc"

        ref = await write_publish_content_artifact(store, "t-1", state_publish_id, _STATE)

        assert ref is not None
        assert ref["ref"] == f"artifact://{PUBLISH_CONTENT_KIND}/{state_publish_id}"
        assert ref["kind"] == PUBLISH_CONTENT_KIND
        assert ref["content_hash"] and len(ref["content_hash"]) == 64
        namespace, artifact_id, payload = store.aput.await_args.args
        assert namespace == ("artifacts", "t-1", PUBLISH_CONTENT_KIND)
        assert artifact_id == state_publish_id
        assert payload["body"] == publish_content_body(_STATE)

    async def test_no_store_thread_or_publish_id_means_no_material(self):
        for store, thread_id, publish_id in (
            (None, "t-1", "p-1"),
            (AsyncMock(), "", "p-1"),
            (AsyncMock(), "t-1", ""),
        ):
            assert (
                await write_publish_content_artifact(store, thread_id, publish_id, _STATE) is None
            )

    async def test_a_storage_failure_is_empty_material_not_an_exception(self):
        store = AsyncMock()
        store.aput.side_effect = RuntimeError("store down")

        material = await publish_intent_material(store, "t-1", "p-1", _STATE)

        assert material.artifact_ref == ""
        assert material.content_hash == ""
        assert material.principal.kind == "deployment"

    async def test_material_carries_the_caller_classified_principal(self):
        from backend.services.publish_intent import PublishPrincipal

        principal = PublishPrincipal(kind="account", account_id="acc-1")

        material = await publish_intent_material(
            AsyncMock(), "t-1", "p-1", _STATE, principal=principal
        )

        assert material.principal == principal
        assert material.artifact_ref.startswith(f"artifact://{PUBLISH_CONTENT_KIND}/")
