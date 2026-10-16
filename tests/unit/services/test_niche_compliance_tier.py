"""P2-2: niche compliance tier + qualification hints + 医美 lexicon overlay."""

from __future__ import annotations

from backend.services.compliance.lexicon import clear_lexicon_cache, scan_text
from backend.services.compliance_policy import (
    HIGH_RISK_NICHES,
    get_niche_compliance_tier,
    is_high_risk_niche,
    niche_qualification_hint,
)


def test_yimei_is_high_risk() -> None:
    assert "医美" in HIGH_RISK_NICHES
    assert is_high_risk_niche("医美") is True
    assert is_high_risk_niche("穿搭") is False


def test_tier_lookup_and_qualification_hint() -> None:
    tier = get_niche_compliance_tier("医美")
    assert tier["tier"] == "high"
    assert tier["is_high_risk"] is True
    assert tier["lexicon_stricter"] is True
    assert tier["lexicon_overlay"] == "niche_aesthetic.yaml"
    hint = niche_qualification_hint("医美")
    assert hint is not None
    assert "资质" in hint

    standard = get_niche_compliance_tier("穿搭")
    assert standard["tier"] == "standard"
    assert standard["is_high_risk"] is False
    assert standard["qualification_hint"] is None
    assert standard["lexicon_overlay"] is None


def test_aesthetic_lexicon_overlay_blocks() -> None:
    clear_lexicon_cache()
    hit = scan_text("这次医美零风险医美立刻变美", niche="医美")
    assert hit.is_blocking is True
    assert any(h.term == "零风险医美" for h in hit.hits)
    assert any(h.source == "niche:医美" for h in hit.hits)

    miss = scan_text("日常护肤分享", niche="医美")
    assert miss.is_blocking is False
