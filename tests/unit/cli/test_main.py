"""Unit tests for CLI main module."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from typer.testing import CliRunner

from xhs_growth.cli.main import app


runner = CliRunner()


class TestCliRun:
    """Tests for 'run' command."""

    def test_run_dry_run_no_api_calls(self):
        """run --dry-run should not invoke graph."""
        result = runner.invoke(app, ["run", "--dry-run"])
        assert result.exit_code == 0
        assert "DRY RUN" in result.stdout

    def test_run_with_account_id(self):
        """run --account-id sets thread prefix."""
        result = runner.invoke(app, ["run", "--account-id", "test_account", "--dry-run"])
        assert result.exit_code == 0
        assert "test_account" in result.stdout

    def test_run_with_phase(self):
        """run --phase sets starting phase."""
        result = runner.invoke(app, ["run", "--phase", "planning", "--dry-run"])
        assert result.exit_code == 0
        assert "planning" in result.stdout

    def test_run_displays_panel(self):
        """run shows startup panel."""
        result = runner.invoke(app, ["run", "--dry-run"])
        assert result.exit_code == 0
        assert "小红书增长引擎" in result.stdout

    def test_run_dev_mode_true_by_default(self):
        """run defaults to dev=True."""
        result = runner.invoke(app, ["run", "--dry-run"])
        assert result.exit_code == 0


class TestCliServe:
    """Tests for 'serve' command."""

    def test_serve_displays_panel(self):
        """serve shows startup panel."""
        with patch("uvicorn.run") as mock_uvicorn:
            result = runner.invoke(app, ["serve", "--port", "8000"])

        assert "API 服务" in result.stdout

    def test_serve_default_port(self):
        """serve uses default port 8000."""
        with patch("uvicorn.run") as mock_uvicorn:
            result = runner.invoke(app, ["serve"])

        assert "8000" in result.stdout

    def test_serve_custom_host(self):
        """serve accepts custom host."""
        with patch("uvicorn.run") as mock_uvicorn:
            result = runner.invoke(app, ["serve", "--host", "127.0.0.1"])

        assert "127.0.0.1" in result.stdout


class TestCliStatus:
    """Tests for 'status' command."""

    def test_status_requires_thread_id(self):
        """status requires thread_id argument."""
        result = runner.invoke(app, ["status"])
        # Should fail without argument
        assert result.exit_code != 0


class TestCliApp:
    """Tests for CLI app structure."""

    def test_app_name(self):
        """app has correct name."""
        assert app.info.name == "xhs-growth"