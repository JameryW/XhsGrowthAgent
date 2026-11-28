"""Contract tests for the tool payload budget (ledger scheme #46)."""

import pytest

from backend.services.interaction_contracts import RETENTION_CONTRACTS
from backend.services.tool_budget import (
    CAPABILITY_CONTRACTS,
    TOOL_BUDGET_ENV,
    UNMATCHED_CONTRACTS,
    BudgetMode,
    PayloadShape,
    budget_enabled,
    budget_mode,
    contract_for,
    payload_shape,
    project_capability,
)
from backend.tools.runtime.catalog import build_registry


@pytest.fixture(autouse=True)
def _reset_unknown_warning(monkeypatch):
    """The "unknown value" warning is once-per-process; pin it per test."""
    monkeypatch.setattr("backend.services.tool_budget._warned_unknown", False)


class TestSwitch:
    def test_default_is_off(self, monkeypatch):
        monkeypatch.delenv(TOOL_BUDGET_ENV, raising=False)
        assert budget_mode() is BudgetMode.OFF
        assert budget_enabled() is False

    @pytest.mark.parametrize("value", ["report", "REPORT", " report ", "1", "true", "yes", "on"])
    def test_report_spellings(self, monkeypatch, value):
        monkeypatch.setenv(TOOL_BUDGET_ENV, value)
        assert budget_mode() is BudgetMode.REPORT
        assert budget_enabled() is True

    def test_trim(self, monkeypatch):
        monkeypatch.setenv(TOOL_BUDGET_ENV, "TRIM")
        assert budget_mode() is BudgetMode.TRIM
        assert budget_enabled() is True

    @pytest.mark.parametrize("value", ["", "off", "OFF", "  "])
    def test_explicit_off(self, monkeypatch, value):
        monkeypatch.setenv(TOOL_BUDGET_ENV, value)
        assert budget_mode() is BudgetMode.OFF

    def test_unknown_value_falls_back_to_off(self, monkeypatch):
        monkeypatch.setenv(TOOL_BUDGET_ENV, "yes-please")
        assert budget_mode() is BudgetMode.OFF


class TestAliases:
    def test_every_alias_points_at_a_real_contract(self):
        for key in CAPABILITY_CONTRACTS.values():
            assert key in RETENTION_CONTRACTS, key

    def test_every_alias_points_at_a_real_capability(self):
        registry = build_registry()
        for capability in CAPABILITY_CONTRACTS:
            assert registry.spec(capability).capability == capability

    def test_contract_for_translates(self):
        contract = contract_for("xhs.trending")
        assert contract is not None
        assert contract.tool == "xhs_trending"

    def test_contract_for_unknown_capability(self):
        assert contract_for("demo.echo") is None

    def test_unmatched_contracts_still_exist(self):
        """A contract with no capability is declared, not deleted."""
        for key in UNMATCHED_CONTRACTS:
            assert key in RETENTION_CONTRACTS
        assert not set(UNMATCHED_CONTRACTS) & set(CAPABILITY_CONTRACTS.values())


class TestShape:
    @pytest.mark.parametrize(
        ("value", "shape"),
        [
            ({}, PayloadShape.MAPPING),
            ([], PayloadShape.LIST),
            ((), PayloadShape.LIST),
            ("text", PayloadShape.SCALAR),
            (42, PayloadShape.SCALAR),
            (None, PayloadShape.SCALAR),
        ],
    )
    def test_payload_shape(self, value, shape):
        assert payload_shape(value) is shape


class TestMappingProjection:
    def test_report_mode_measures_without_touching_the_value(self, monkeypatch):
        monkeypatch.setenv(TOOL_BUDGET_ENV, "report")
        payload = {"prediction": {"reach": 1200}, "job_id": "job-1", "debug": "x" * 400}
        report, value = project_capability("ripple.predict_spread", payload)
        assert value is payload
        assert report.trimmed is False
        assert report.contract == "ripple_predict"
        assert report.note == "measured_only"
        assert report.dropped_keys == ("debug",)
        assert 0.0 < report.retention_ratio < 1.0
        assert report.original_chars > report.projected_chars

    def test_trim_mode_returns_the_projection(self, monkeypatch):
        monkeypatch.setenv(TOOL_BUDGET_ENV, "trim")
        payload = {"prediction": {"reach": 1200}, "job_id": "job-1", "debug": "x" * 400}
        report, value = project_capability("ripple.predict_spread", payload)
        assert report.trimmed is True
        assert report.note == "trimmed"
        assert value == {"prediction": {"reach": 1200}, "job_id": "job-1"}

    def test_mapping_without_a_contract_is_never_trimmed(self, monkeypatch):
        monkeypatch.setenv(TOOL_BUDGET_ENV, "trim")
        payload = {"anything": "x" * 100}
        report, value = project_capability("demo.echo", payload)
        assert value is payload
        assert report.trimmed is False
        assert report.contract == ""
        assert report.note == "no_retention_contract"
        assert report.retention_ratio == 1.0

    def test_report_serialises(self, monkeypatch):
        monkeypatch.setenv(TOOL_BUDGET_ENV, "report")
        report, _ = project_capability(
            "xhs.keyword_monitor", {"keywords": ["川西"], "captured_at": "now", "extra": 1}
        )
        payload = report.as_dict()
        assert payload["capability"] == "xhs.keyword_monitor"
        assert payload["mode"] == "report"
        assert payload["shape"] == "mapping"
        assert payload["dropped_keys"] == ["extra"]
        assert payload["trimmed"] is False


class TestOtherPayloads:
    def test_list_payload_is_measured_only(self, monkeypatch):
        monkeypatch.setenv(TOOL_BUDGET_ENV, "trim")
        rows = [{"title": "a", "likes": 1, "noise": "x" * 50}]
        report, value = project_capability("xhs.trending", rows)
        assert value is rows
        assert report.trimmed is False
        assert report.shape == "list"
        assert report.note == "list_payload_measured_only"
        assert report.contract == ""

    def test_scalar_payload_is_measured_only(self, monkeypatch):
        monkeypatch.setenv(TOOL_BUDGET_ENV, "trim")
        report, value = project_capability("ripple.predict_spread", "done")
        assert value == "done"
        assert report.shape == "scalar"
        assert report.note == "scalar_payload_measured_only"
        assert report.retention_ratio == 1.0

    def test_empty_payload_is_measured_not_trimmed(self, monkeypatch):
        """Nothing to drop means ratio 1.0 — never a misleading 0.0."""
        monkeypatch.setenv(TOOL_BUDGET_ENV, "trim")
        report, value = project_capability("ripple.predict_spread", {})
        assert value == {}
        assert report.trimmed is True
        assert report.dropped_keys == ()
        assert report.retention_ratio == 1.0


class TestExplicitMode:
    def test_explicit_mode_beats_the_environment(self, monkeypatch):
        monkeypatch.setenv(TOOL_BUDGET_ENV, "off")
        report, value = project_capability(
            "ripple.predict_spread",
            {"prediction": 1, "job_id": "j", "debug": "x" * 100},
            mode=BudgetMode.TRIM,
        )
        assert report.trimmed is True
        assert value == {"prediction": 1, "job_id": "j"}
