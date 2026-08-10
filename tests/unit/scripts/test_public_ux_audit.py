"""Unit coverage for public UX audit readiness gates."""

from unittest.mock import Mock

import pytest

from scripts.acceptance.public_ux_audit import wait_for_showcase_data


def _page(*, cards: int, headings: int) -> Mock:
    page = Mock()
    page.locator.side_effect = lambda selector: Mock(
        count=Mock(return_value=cards if "case-card" in selector else headings)
    )
    return page


def test_wait_for_showcase_data_uses_stable_heading_and_attached_card() -> None:
    page = _page(cards=1, headings=1)

    wait_for_showcase_data(page)

    page.wait_for_selector.assert_called_once_with("#cases-heading", state="visible")
    page.wait_for_function.assert_called_once()


def test_wait_for_showcase_data_rejects_unrendered_result() -> None:
    page = _page(cards=0, headings=0)

    with pytest.raises(AssertionError, match="did not render"):
        wait_for_showcase_data(page)
