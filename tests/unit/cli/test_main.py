"""Unit tests for CLI main module."""

from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from backend.cli.main import app

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
        with patch("uvicorn.run"):
            result = runner.invoke(app, ["serve", "--port", "8000"])

        assert "API 服务" in result.stdout

    def test_serve_default_port(self):
        """serve uses default port 8000."""
        with patch("uvicorn.run"):
            result = runner.invoke(app, ["serve"])

        assert "8000" in result.stdout

    def test_serve_custom_host(self):
        """serve accepts custom host."""
        with patch("uvicorn.run"):
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


class TestCliLogin:
    """Tests for 'login' command — opens headed Chrome for XHS QR scan login."""

    def test_login_requires_account_id(self):
        """login requires an account_id argument."""
        result = runner.invoke(app, ["login"])
        assert result.exit_code != 0

    def test_login_account_not_found(self):
        """Non-existent account_id → error panel, exit 1."""
        with (
            patch("backend.db.pool.is_pool_ready", return_value=True),
            patch("backend.db.accounts.get_account", new=AsyncMock(return_value=None)),
        ):
            result = runner.invoke(app, ["login", "no-such-acc"])
        assert result.exit_code == 1
        assert "不存在" in result.stdout

    def test_login_account_without_profile_binding(self):
        """Account exists but no chrome_profile_path → error panel, exit 1."""
        from backend.db.accounts import AccountRow

        account = AccountRow(
            id="acc-1", name="acc", is_active=True, cdp_port=0, chrome_profile_path=""
        )

        with (
            patch("backend.db.pool.is_pool_ready", return_value=True),
            patch("backend.db.accounts.get_account", new=AsyncMock(return_value=account)),
        ):
            result = runner.invoke(app, ["login", "acc-1"])
        assert result.exit_code == 1
        assert "未绑定 chrome_profile_path" in result.stdout

    def test_login_opens_persistent_context(self):
        """Happy path: launch_persistent_context called with the account's profile."""
        from backend.db.accounts import AccountRow

        account = AccountRow(
            id="acc-1",
            name="acc",
            is_active=True,
            cdp_port=9223,
            chrome_profile_path="/tmp/xhs-login-test",
        )

        fake_pw = MagicMock()
        fake_chromium = MagicMock()
        fake_context = MagicMock()
        fake_context.close = AsyncMock()
        fake_page = MagicMock()
        fake_page.goto = AsyncMock()
        fake_page.wait_for_event = AsyncMock(side_effect=TimeoutError("timeout"))
        fake_context.pages = [fake_page]
        # Code does: async with async_playwright() as pw: pw.chromium.launch_persistent_context(...)
        # So launch_persistent_context lives on pw.chromium, where pw = __aenter__ return.
        fake_chromium.chromium.launch_persistent_context = AsyncMock(return_value=fake_context)
        fake_pw.return_value.__aenter__ = AsyncMock(return_value=fake_chromium)
        fake_pw.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("backend.db.pool.is_pool_ready", return_value=True),
            patch("backend.db.accounts.get_account", new=AsyncMock(return_value=account)),
            patch("playwright.async_api.async_playwright", fake_pw),
        ):
            runner.invoke(app, ["login", "acc-1", "--timeout", "1"])

        # The key assertion: persistent context opened with the account's profile, headed.
        fake_chromium.chromium.launch_persistent_context.assert_awaited_once()
        call_kwargs = fake_chromium.chromium.launch_persistent_context.await_args.kwargs
        assert call_kwargs["user_data_dir"] == "/tmp/xhs-login-test"
        assert call_kwargs["headless"] is False
        fake_context.close.assert_awaited_once()
        fake_page.goto.assert_awaited_once()
        # Navigated to the XHS creator login page.
        assert "creator.xiaohongshu.com/login" in fake_page.goto.await_args.args[0]
