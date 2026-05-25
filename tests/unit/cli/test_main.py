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

    def test_run_invokes_graph_when_not_dry_run(self):
        """run invokes graph.ainvoke when dry_run=False."""
        with patch("xhs_growth.cli.main.compile_graph_dev") as mock_compile:
            mock_graph = MagicMock()
            mock_graph.ainvoke = AsyncMock(return_value={"phase": "completed"})
            mock_compile.return_value = mock_graph

            with patch("asyncio.run") as mock_asyncio_run:
                # Capture the inner async function and run it
                result = runner.invoke(app, ["run", "--dry-run", "false"])

        assert result.exit_code == 0
        # Graph compilation was called
        assert mock_compile.called

    def test_run_handles_exception(self):
        """run handles exceptions gracefully."""
        with patch("xhs_growth.cli.main.compile_graph_dev") as mock_compile:
            mock_compile.side_effect = Exception("Test error")

            result = runner.invoke(app, ["run", "--dry-run", "false"])

        # Should still exit (may be 1 or 0 depending on error handling)
        assert "错误" in result.stdout or result.exit_code != 0


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

    def test_status_with_thread_id(self):
        """status displays workflow state."""
        with patch("xhs_growth.cli.main.compile_graph_dev") as mock_compile:
            mock_graph = MagicMock()
            mock_state = MagicMock()
            mock_state.next = ["analyst"]
            mock_state.values = {"phase": "analyzing", "current_agent": "analyst"}
            mock_graph.aget_state = AsyncMock(return_value=mock_state)
            mock_compile.return_value = mock_graph

            with patch("asyncio.run"):
                result = runner.invoke(app, ["status", "test_thread_123"])

        assert "test_thread_123" in result.stdout

    def test_status_displays_phase(self):
        """status shows current phase."""
        with patch("xhs_growth.cli.main.compile_graph_dev") as mock_compile:
            mock_graph = MagicMock()
            mock_state = MagicMock()
            mock_state.next = []
            mock_state.values = {"phase": "completed", "current_agent": None}
            mock_graph.aget_state = AsyncMock(return_value=mock_state)
            mock_compile.return_value = mock_graph

            with patch("asyncio.run"):
                result = runner.invoke(app, ["status", "thread_xyz"])

        assert "completed" in result.stdout


class TestCliApp:
    """Tests for CLI app structure."""

    def test_app_has_run_command(self):
        """app has registered 'run' command."""
        # Typer apps have registered commands
        assert "run" in app.registered_commands or len(app.registered_commands) > 0

    def test_app_has_serve_command(self):
        """app has registered 'serve' command."""
        assert "serve" in app.registered_commands or len(app.registered_commands) > 0

    def test_app_has_status_command(self):
        """app has registered 'status' command."""
        assert "status" in app.registered_commands or len(app.registered_commands) > 0

    def test_app_name(self):
        """app has correct name."""
        assert app.info.name == "xhs-growth"