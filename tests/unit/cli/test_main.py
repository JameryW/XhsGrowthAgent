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
        with patch("backend.cli.main._serve_uvicorn") as serve_uvicorn:
            result = runner.invoke(app, ["serve", "--port", "8000"])

        assert "API 服务" in result.stdout
        serve_uvicorn.assert_called_once()
        assert serve_uvicorn.call_args.kwargs["port"] == 8000

    def test_serve_default_port(self):
        """serve uses default port 8000."""
        with patch("backend.cli.main._serve_uvicorn"):
            result = runner.invoke(app, ["serve"])

        assert "8000" in result.stdout

    def test_serve_custom_host(self):
        """serve accepts custom host."""
        with patch("backend.cli.main._serve_uvicorn"):
            result = runner.invoke(app, ["serve", "--host", "127.0.0.1"])

        assert "127.0.0.1" in result.stdout

    def test_serve_reload_uses_uvicorn_runner(self):
        """--reload takes the uvicorn reload path instead of the selector-loop one."""
        with (
            patch("uvicorn.run") as uvicorn_run,
            patch("backend.cli.main._serve_uvicorn") as serve_uvicorn,
        ):
            result = runner.invoke(app, ["serve", "--reload"])

        assert result.exit_code == 0
        uvicorn_run.assert_called_once()
        assert uvicorn_run.call_args.kwargs["reload"] is True
        serve_uvicorn.assert_not_called()


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

    def test_login_opens_persistent_context(self, tmp_path):
        """Happy path: launch_persistent_context called with the account's profile."""
        from backend.db.accounts import AccountRow

        # A profile path must be writable in the test process: a hard-coded
        # ``/tmp/...`` resolves to the current drive root on Windows and the
        # sandbox can refuse the mkdir, which made this test depend on whether
        # some earlier run had already created the directory.  tmp_path is the
        # same portability rule tests/unit/test_no_hardcoded_tmp_paths.py
        # enforces for backend code.
        profile_path = tmp_path / "xhs-login-test"
        account = AccountRow(
            id="acc-1",
            name="acc",
            is_active=True,
            cdp_port=9223,
            chrome_profile_path=str(profile_path),
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
        assert call_kwargs["user_data_dir"] == str(profile_path)
        assert call_kwargs["headless"] is False
        fake_context.close.assert_awaited_once()
        fake_page.goto.assert_awaited_once()
        # Navigated to the XHS creator login page.
        assert "creator.xiaohongshu.com/login" in fake_page.goto.await_args.args[0]


class TestConsoleEncoding:
    """The CLI must survive a GBK console (Chinese Windows default)."""

    class _FakeStream:
        def __init__(self, encoding: str) -> None:
            self.encoding = encoding
            self.calls: list[dict[str, str]] = []

        def reconfigure(self, **kwargs: str) -> None:
            self.calls.append(dict(kwargs))
            self.encoding = kwargs.get("encoding", self.encoding)

    def test_gbk_stream_is_reconfigured_to_utf8(self, monkeypatch):
        import backend.cli.main as cli_main

        stdout = self._FakeStream("gbk")
        stderr = self._FakeStream("cp936")
        monkeypatch.setattr(cli_main.sys, "stdout", stdout)
        monkeypatch.setattr(cli_main.sys, "stderr", stderr)

        cli_main._ensure_utf8_console_streams()

        assert stdout.calls == [{"encoding": "utf-8", "errors": "replace"}]
        assert stderr.calls == [{"encoding": "utf-8", "errors": "replace"}]

    def test_utf8_streams_are_left_alone(self, monkeypatch):
        import backend.cli.main as cli_main

        stdout = self._FakeStream("utf-8")
        stderr = self._FakeStream("UTF8")
        monkeypatch.setattr(cli_main.sys, "stdout", stdout)
        monkeypatch.setattr(cli_main.sys, "stderr", stderr)

        cli_main._ensure_utf8_console_streams()

        assert stdout.calls == []
        assert stderr.calls == []


class TestNicheRequirement:
    """D2': the CLI must not start a workflow without a niche."""

    def test_dry_run_does_not_require_a_niche(self):
        result = runner.invoke(app, ["run", "--account-id", "smoke", "--dry-run"])
        assert result.exit_code == 0
        assert "DRY RUN" in result.stdout

    def test_missing_niche_fails_with_an_actionable_hint(self):
        result = runner.invoke(app, ["run", "--account-id", "smoke"])
        assert result.exit_code == 2
        assert "--niche" in result.stdout


class TestUnknownThread:
    """status/logs/resume must not claim success for a thread that never existed."""

    def test_status_unknown_thread_exits_1(self):
        result = runner.invoke(app, ["status", "functional-smoke-unknown-thread"])
        assert result.exit_code == 1
        assert "线程不存在" in result.stdout

    def test_logs_unknown_thread_exits_1(self):
        result = runner.invoke(app, ["logs", "functional-smoke-unknown-thread"])
        assert result.exit_code == 1
        assert "线程不存在" in result.stdout

    def test_resume_unknown_thread_exits_1(self):
        result = runner.invoke(app, ["resume", "functional-smoke-unknown-thread"])
        assert result.exit_code == 1
        assert "线程不存在" in result.stdout


class TestServeOptions:
    """serve must be production-safe by default and offer reload explicitly."""

    def test_serve_help_exposes_opt_in_reload(self):
        # Assert on the Click command model, not the rendered help text: Rich
        # wraps/truncates option lines differently per terminal width, which made
        # the text assertion pass locally and fail on CI.
        from click import Command
        from typer.main import get_command

        command: Command = get_command(app)
        serve = command.commands["serve"]  # type: ignore[attr-defined]
        reload_param = next(param for param in serve.params if param.name == "reload")
        assert "--reload" in reload_param.opts
        assert reload_param.default is False
