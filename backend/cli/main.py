"""CLI entry point — Typer-based command line interface."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime
from typing import Any

import typer
from langchain_core.runnables.config import RunnableConfig
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

app = typer.Typer(name="xhs-growth", help="小红书增长引擎 Agent")
console = Console()


# Phase display configuration
PHASE_STYLES = {
    "idle": "dim",
    "scouting": "cyan",
    "planning": "blue",
    "creating": "yellow",
    "reviewing": "magenta",
    "publishing": "green",
    "analyzing": "orange3",
    "engaging": "purple",
    "completed": "bold green",
    "error": "bold red",
    "stale": "bold yellow",
}

PHASE_ICONS = {
    "idle": "💤",
    "scouting": "🔍",
    "planning": "📋",
    "creating": "✨",
    "reviewing": "👁",
    "publishing": "📤",
    "analyzing": "📊",
    "engaging": "💬",
    "completed": "✅",
    "error": "❌",
    "stale": "⚠️",
}


def format_phase(phase: str) -> str:
    """Format phase with icon and color."""
    icon = PHASE_ICONS.get(phase, "•")
    style = PHASE_STYLES.get(phase, "white")
    return f"[{style}]{icon} {phase}[/{style}]"


@app.command()
def run(
    account_id: str = typer.Option("default", help="账号 ID"),
    phase: str = typer.Option("scouting", help="起始阶段"),
    dry_run: bool = typer.Option(False, help="模拟运行（不调用真实 API）"),
    dev: bool = typer.Option(True, help="开发模式（内存检查点）"),
    verbose: bool = typer.Option(False, help="显示详细日志"),
) -> None:
    """启动增长引擎工作流"""
    from dotenv import load_dotenv

    # 加载 .env 文件
    load_dotenv(override=True)

    console.print(Panel("🚀 小红书增长引擎", style="bold green"))

    async def _run() -> None:
        from backend.graph.builder import dev_graph
        from backend.state.schema import WorkflowPhase

        async with dev_graph() as graph:
            thread_id = f"xhs_{account_id}_{uuid.uuid4().hex[:8]}"

            initial_state: dict[str, Any] = {
                "phase": WorkflowPhase(phase),
                "current_agent": "orchestrator",
                "error": None,
                "retry_count": 0,
                "messages": [],
                "trend_data": {},
                "content_plan": {},
                "copy_content": {},
                "visual_plan": {},
                "publish_result": {},
                "analytics": {},
                "engagement_actions": [],
                "human_feedback": {},
                "content_history": [],
                "performance_log": [],
                "account_id": account_id,
                "session_id": thread_id,
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
            }

            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

            console.print(f"[dim]Thread: {thread_id}[/dim]")
            console.print(f"[dim]起始阶段: {format_phase(phase)}[/dim]")

            if dry_run:
                console.print("[yellow]⚠️ DRY RUN — 不调用真实 API[/yellow]")
                return

            try:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    console=console,
                ) as progress:
                    task = progress.add_task("执行工作流...", total=None)

                    async for event in graph.astream_events(initial_state, config, version="v1"):
                        if event["event"] == "on_chain_start":
                            agent = event.get("name", "unknown")
                            progress.update(task, description=f"[cyan]执行: {agent}[/cyan]")
                            if verbose:
                                console.print(f"[dim]→ {agent}[/dim]")
                        elif event["event"] == "on_chain_end":
                            agent = event.get("name", "unknown")
                            progress.update(task, description=f"[green]完成: {agent}[/green]")
                            if verbose:
                                console.print(f"[dim]✓ {agent}[/dim]")

                    progress.update(
                        task,
                        description="[bold green]工作流完成[/bold green]",
                        completed=True,
                    )

                result = await graph.aget_state(config)
                final_phase = result.values.get("phase", "unknown")
                console.print(
                    Panel(
                        f"最终阶段: {format_phase(final_phase)}\n"
                        f"当前 Agent: {result.values.get('current_agent', 'unknown')}\n"
                        f"Thread ID: {thread_id}",
                        title="✅ 工作流结果",
                        style="green",
                    )
                )

            except KeyboardInterrupt:
                console.print("\n[yellow]⚠️ 工作流被中断[/yellow]")
                console.print(f"[dim]使用 'xhs-growth resume {thread_id}' 恢复[/dim]")
            except Exception as e:
                console.print(
                    Panel(
                        f"错误类型: {type(e).__name__}\n"
                        f"详情: {e}\n\n"
                        f"[dim]建议: 检查 API 配置或使用 --dry-run 测试[/dim]",
                        title="❌ 执行失败",
                        style="red",
                    )
                )
                raise typer.Exit(1) from e

    asyncio.run(_run())


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="监听地址"),
    port: int = typer.Option(8000, help="监听端口"),
) -> None:
    """启动 API 服务"""
    import uvicorn
    from dotenv import load_dotenv

    # 加载 .env 文件
    load_dotenv(override=True)

    console.print(Panel(f"🌐 启动 API 服务: {host}:{port}", style="bold blue"))
    uvicorn.run("backend.api.app:app", host=host, port=port, reload=True)


@app.command()
def status(thread_id: str = typer.Argument(..., help="工作流线程 ID")) -> None:
    """查看工作流状态"""

    async def _status() -> None:
        from backend.graph.builder import dev_graph
        from backend.state.machine import derive_status

        async with dev_graph() as graph:
            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
            snapshot = await graph.aget_state(config)

            # Use derive_status for accurate status (handles stale, gates, etc.)
            derived = derive_status(snapshot, has_active_task=False)
            phase = snapshot.values.get("phase", "unknown")
            agent = snapshot.values.get("current_agent", "unknown")

            table = Table(title=f"工作流状态: {thread_id}")
            table.add_column("属性", style="cyan")
            table.add_column("值", style="white")

            table.add_row("状态", format_phase(derived.value))
            table.add_row("阶段", format_phase(phase))
            table.add_row("当前 Agent", agent)
            table.add_row("下一步", ", ".join(snapshot.next) if snapshot.next else "完成")
            table.add_row("错误", snapshot.values.get("error", "无") or "无")

            console.print(table)

            if derived.value == "stale":
                console.print(
                    "\n[yellow]⚠️ 工作流处于 STALE 状态（后台任务已终止但仍有待执行节点）[/yellow]"
                )
                console.print("[dim]使用 xhs-growth resume <thread_id> 恢复执行[/dim]")

            # Show performance log if available
            perf_log = snapshot.values.get("performance_log", [])
            if perf_log and len(perf_log) > 0:
                console.print("\n[dim]性能日志:[/dim]")
                for entry in perf_log[-3:]:
                    console.print(f"  [dim]• {entry}[/dim]")

    asyncio.run(_status())


@app.command("list")
def list_workflows(
    account_id: str | None = typer.Option(None, help="筛选账号 ID"),
    limit: int = typer.Option(10, help="显示数量"),
) -> None:
    """列出活跃工作流"""
    console.print(Panel("📋 工作流列表", style="bold blue"))

    table = Table()
    table.add_column("Thread ID", style="cyan")
    table.add_column("阶段", style="white")
    table.add_column("Agent", style="white")
    table.add_column("创建时间", style="dim")

    async def _list() -> None:
        # In dev mode with memory checkpointer, we can't list threads
        # This is a placeholder for production mode with Postgres
        console.print("[dim]开发模式下无法列出工作流（使用内存检查点）[/dim]")
        console.print("[dim]生产模式将支持从 Postgres 查询[/dim]")

    asyncio.run(_list())


@app.command()
def resume(
    thread_id: str = typer.Argument(..., help="工作流线程 ID"),
    phase: str | None = typer.Option(None, help="指定恢复阶段"),
) -> None:
    """恢复中断的工作流"""

    async def _resume() -> None:
        from langgraph.types import Command

        from backend.graph.builder import compile_graph_dev
        from backend.state.machine import derive_status

        graph = await compile_graph_dev()
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        state = await graph.aget_state(config)
        current_phase = state.values.get("phase", "unknown")
        derived = derive_status(state, has_active_task=False)

        console.print(f"[cyan]恢复工作流: {thread_id}[/cyan]")
        console.print(f"[dim]当前阶段: {format_phase(current_phase)}[/dim]")
        console.print(f"[dim]状态: {format_phase(derived.value)}[/dim]")

        if state.next:
            console.print(f"[dim]下一步: {', '.join(state.next)}[/dim]")

            # Determine resume input based on gate type
            next_nodes = state.next
            resume_value: Command[Any] | None = None  # Default: ainvoke(None) for non-gate nodes

            if "review_gate" in next_nodes:
                console.print("[yellow]⚠️ 工作流停在 review_gate（人工审核）[/yellow]")
                console.print("[dim]CLI 无法提交审核决定。请通过 API 或前端界面操作：[/dim]")
                console.print("[dim]  POST /api/review/submit/{thread_id}[/dim]")
                return  # Don't auto-resume review gate — it needs human decision

            if "draft_gate" in next_nodes:
                console.print("[yellow]⚠️ 工作流停在 draft_gate（草稿确认）[/yellow]")
                console.print("[dim]CLI 无法提交草稿。请通过 API 或前端界面操作：[/dim]")
                console.print("[dim]  POST /api/workflow/submit-draft/{thread_id}[/dim]")
                return  # Don't auto-resume draft gate — it needs user input

            if "choice_gate" in next_nodes:
                console.print("[yellow]⚠️ 工作流停在 choice_gate（版本选择）[/yellow]")
                console.print("[dim]CLI 无法选择版本。请通过 API 或前端界面操作：[/dim]")
                return  # Don't auto-resume choice gate

            # For dynamic interrupts (ripple_gate, blogger_gate), the node already ran
            # its logic and called interrupt() with a payload — resume with a default
            if state.interrupts:
                interrupt_val = state.interrupts[0].value
                if isinstance(interrupt_val, dict):
                    gate_type = interrupt_val.get("gate")
                    if gate_type == "ripple":
                        console.print("[dim]Ripple gate 中断 — 自动 accept[/dim]")
                        resume_value = Command(resume={"action": "accept"})
                    elif gate_type == "blogger":
                        console.print("[dim]Blogger gate 中断 — 自动 skip[/dim]")
                        resume_value = Command(resume={"skip": True})
                    elif gate_type == "draft":
                        console.print("[yellow]⚠️ Draft gate 中断 — 需要用户输入[/yellow]")
                        console.print("[dim]请通过 API 提交草稿[/dim]")
                        return
                    elif gate_type == "choice":
                        console.print("[yellow]⚠️ Choice gate 中断 — 需要用户选择[/yellow]")
                        return

            try:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=console,
                ) as progress:
                    task = progress.add_task("恢复执行...", total=None)
                    await graph.ainvoke(resume_value, config)
                    progress.update(task, description="[green]恢复完成[/green]")

                final_state = await graph.aget_state(config)
                final_phase = final_state.values.get("phase", "unknown")
                console.print(
                    Panel(
                        f"最终阶段: {format_phase(final_phase)}",
                        title="✅ 恢复结果",
                        style="green",
                    )
                )
            except Exception as e:
                console.print(Panel(f"恢复失败: {e}", title="❌ 错误", style="red"))
        else:
            console.print("[yellow]工作流已完成，无需恢复[/yellow]")

    asyncio.run(_resume())


@app.command()
def logs(
    thread_id: str = typer.Argument(..., help="工作流线程 ID"),
    follow: bool = typer.Option(False, "--follow", "-f", help="实时跟踪日志"),
) -> None:
    """查看工作流日志"""

    async def _logs() -> None:
        from backend.graph.builder import compile_graph_dev

        graph = await compile_graph_dev()
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        state = await graph.aget_state(config)

        console.print(Panel(f"📝 工作流日志: {thread_id}", style="bold blue"))

        # Show messages
        messages = state.values.get("messages", [])
        if messages:
            console.print("\n[cyan]对话历史:[/cyan]")
            for msg in messages[-10:]:
                msg_type = type(msg).__name__
                console.print(f"  [dim]• [{msg_type}] {str(msg)[:100]}...[/dim]")
        else:
            console.print("[dim]无对话记录[/dim]")

        # Show performance log
        perf_log = state.values.get("performance_log", [])
        if perf_log:
            console.print("\n[cyan]性能记录:[/cyan]")
            for entry in perf_log:
                console.print(f"  [dim]• {entry}[/dim]")

    asyncio.run(_logs())


@app.command("sync-stats")
def sync_stats(
    account_id: str = typer.Option("default", help="账号 ID"),
    dry_run: bool = typer.Option(
        True, help="使用 fixture 跑完整导入链路（不访问 creator.xiaohongshu.com）"
    ),
    cookie: str = typer.Option("", help="创作者中心 Cookie（live 同步）"),
    period: str = typer.Option("30d", help="统计周期"),
) -> None:
    """从创作者中心统计页导入账户/笔记数据，分析并沉淀创作风格。"""
    from dotenv import load_dotenv

    load_dotenv(override=True)
    console.print(Panel("📊 同步创作者中心统计", style="bold cyan"))

    async def _sync() -> None:
        from backend.db.accounts import (
            ensure_tables as ensure_account_tables,
        )
        from backend.db.accounts import get_account_cdp_endpoint
        from backend.db.creative_memory import ensure_tables as ensure_creative_memory_tables
        from backend.db.creator_stats import ensure_tables as ensure_creator_stats_tables
        from backend.db.pool import close_pool, init_pool, is_pool_ready
        from backend.services.creator_stats.pipeline import sync_account_stats

        # CLI has no FastAPI lifespan. A live import must open/prepare the app
        # DB explicitly so account stats and CreativeMemory deposits survive
        # process exit instead of falling back to process-local dictionaries.
        # A fixture dry-run intentionally retains its offline/memory-only
        # behavior, which keeps it usable in CI and on a developer laptop
        # without PostgreSQL.
        opened_pool_here = False
        try:
            if not dry_run:
                try:
                    if not is_pool_ready():
                        await init_pool()
                        opened_pool_here = True
                    # ``init_pool`` opens the pool lazily; acquiring a schema
                    # connection here verifies reachability before a live pull.
                    await asyncio.wait_for(
                        asyncio.gather(
                            ensure_account_tables(),
                            ensure_creator_stats_tables(),
                            ensure_creative_memory_tables(),
                        ),
                        timeout=5.0,
                    )
                except Exception as e:
                    if opened_pool_here:
                        with contextlib.suppress(Exception):
                            await close_pool()
                        opened_pool_here = False
                    console.print(
                        "[red]同步失败：Postgres 不可用；为避免真实导入仅保留在内存中，"
                        f"本次同步未开始（{type(e).__name__}）。[/red]"
                    )
                    raise typer.Exit(1) from e

            # 非干跑：优先 CDP 连账号常驻 Chrome（已登录，cookie jar 自带）；
            # 无绑定再 fallback cookie。
            cdp_endpoint = ""
            if not dry_run:
                try:
                    cdp_endpoint = (await get_account_cdp_endpoint(account_id)).strip()
                except Exception:
                    cdp_endpoint = ""

            # Pass dry_run as-is: no cdp + empty cookie + live mode returns a
            # clear error (never silently write fixture rows under a real id).
            result = await sync_account_stats(
                account_id,
                cookie=cookie,
                dry_run=dry_run,
                period=period,
                cdp_endpoint=cdp_endpoint,
            )
            if result.error:
                console.print(f"[red]同步失败: {result.error}[/red]")
                # Partial success: import may have succeeded while analysis failed
                if (
                    result.account_synced
                    and result.notes_imported + result.notes_updated + result.notes_deleted > 0
                ):
                    console.print(
                        f"[yellow]已导入 notes_imported={result.notes_imported} "
                        f"notes_updated={result.notes_updated} "
                        f"notes_deleted={result.notes_deleted}（分析阶段失败）[/yellow]"
                    )
                raise typer.Exit(1)

            table = Table(title=f"同步结果 — {result.account_id}")
            table.add_column("指标", style="cyan")
            table.add_column("值", style="white")
            table.add_row("source", result.source)
            table.add_row("notes_imported", str(result.notes_imported))
            table.add_row("notes_updated", str(result.notes_updated))
            table.add_row("notes_deleted", str(result.notes_deleted))
            table.add_row("account_synced", str(result.account_synced))
            if result.analysis:
                table.add_row("note_count", str(result.analysis.note_count))
                table.add_row("avg_engagement_rate", f"{result.analysis.avg_engagement_rate:.2%}")
                table.add_row("styles_deposited", str(result.analysis.styles_deposited))
                table.add_row("findings", str(len(result.analysis.findings)))
            if result.niche_resolution:
                nr = result.niche_resolution
                table.add_row(
                    "niche",
                    f"{nr.get('niche') or '—'} ({nr.get('source') or '?'})",
                )
            for mode, items in (result.suggestions or {}).items():
                table.add_row(f"suggestions[{mode}]", str(len(items)))
            console.print(table)
        finally:
            if opened_pool_here:
                with contextlib.suppress(Exception):
                    await close_pool()

    asyncio.run(_sync())


@app.command()
def version() -> None:
    """显示版本信息"""
    from importlib.metadata import version as get_version

    try:
        v = get_version("xhs-growth-engine")
    except Exception:
        v = "0.1.0 (dev)"

    console.print(
        Panel(
            f"版本: {v}\nPython: 3.11+",
            title="📦 XhsGrowthEngine",
            style="bold green",
        )
    )


@app.command()
def config() -> None:
    """检查配置状态"""
    import os

    from dotenv import load_dotenv

    # 加载 .env 文件
    load_dotenv(override=True)

    console.print(Panel("🔧 配置检查", style="bold blue"))

    required_vars = [
        ("ANTHROPIC_API_KEY", "Anthropic Claude API"),
        ("OPENAI_API_KEY", "OpenAI GPT API"),
        ("DEEPSEEK_API_KEY", "DeepSeek API"),
        ("DASHSCOPE_API_KEY", "阿里云 Qwen API"),
        ("XIAOMIMIMO_API_KEY", "MiMo API"),
        ("RIPPLE_BASE_URL", "Ripple CAS 服务"),
    ]

    table = Table()
    table.add_column("变量", style="cyan")
    table.add_column("状态", style="white")
    table.add_column("用途", style="dim")

    for var, purpose in required_vars:
        value = os.environ.get(var, "")
        status = "[green]✅ 已配置[/green]" if value else "[yellow]⚠️ 未配置[/yellow]"
        table.add_row(var, status, purpose)

    console.print(table)

    # Check optional vars
    optional_vars = [
        ("POSTGRES_URI", "生产持久化"),
        ("REDIS_URI", "缓存/队列"),
    ]

    console.print("\n[dim]可选配置:[/dim]")
    for var, purpose in optional_vars:
        value = os.environ.get(var, "")
        status = "✅" if value else "⚪"
        console.print(f"  [dim]{status} {var} ({purpose})[/dim]")


@app.command()
def login(
    account_id: str = typer.Argument(
        ..., help="账号 ID（需已绑定 chrome_profile_path + cdp_port）"
    ),
    timeout: int = typer.Option(
        300, help="扫码等待超时（秒），超时后自动关闭浏览器（登录态已写入 profile）"
    ),
) -> None:
    """打开该账号 profile 的 headed Chrome 走小红书 creator 扫码登录。

    用 Playwright ``launch_persistent_context(user_data_dir=<account.chrome_profile_path>,
    headless=False)`` 打开 ``https://creator.xiaohongshu.com/login``，等用户扫码。
    登录态写入该账号的 user_data_dir，持久——之后 launcher 启的常驻 CDP Chrome
    复用同一 profile，发布时无需再扫码。

    账号需已绑定 chrome_profile_path（创建账号时自动分配，或经账号管理 API 设置）。
    无绑定 → 报错提示先配置。
    """
    from dotenv import load_dotenv

    load_dotenv(override=True)

    async def _login() -> None:
        from backend.db.accounts import get_account
        from backend.db.pool import init_pool, is_pool_ready

        # The login command is run on the host (Chrome lives there); the DB may
        # be in a container. init_pool is a no-op if already initialized.
        if not is_pool_ready():
            try:
                await init_pool()
            except Exception as e:
                console.print(Panel(f"无法连接数据库: {e}", title="❌ 错误", style="red"))
                raise typer.Exit(1) from e

        account = await get_account(account_id)
        if account is None:
            console.print(
                Panel(
                    f"账号 {account_id} 不存在。先用 `xhs-growth config` 或 API 创建账号。",
                    title="❌ 错误",
                    style="red",
                )
            )
            raise typer.Exit(1)

        if not account.chrome_profile_path:
            console.print(
                Panel(
                    f"账号 {account_id} 未绑定 chrome_profile_path。\n"
                    "创建账号时会自动分配（需设 XHS_CHROME_PROFILES_DIR）；或经账号管理 API 设置。",
                    title="❌ 错误",
                    style="red",
                )
            )
            raise typer.Exit(1)

        from pathlib import Path

        profile_path = account.chrome_profile_path
        Path(profile_path).mkdir(parents=True, exist_ok=True)

        console.print(
            Panel(
                f"账号: {account.name} ({account.id})\n"
                f"Profile: {profile_path}\n"
                f"CDP port: {account.cdp_port or '(未绑定，仅登录用)'}\n"
                f"扫码超时: {timeout}s",
                title="🌐 小红书扫码登录",
                style="bold cyan",
            )
        )

        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            console.print(
                Panel(
                    "playwright 未安装。运行: pip install -e '.[browser]'",
                    title="❌ 错误",
                    style="red",
                )
            )
            raise typer.Exit(1) from e

        login_url = "https://creator.xiaohongshu.com/login"
        console.print(f"[cyan]打开登录页: {login_url}[/cyan]")
        console.print("[dim]扫码完成后登录态会写入 profile，可关闭浏览器。Ctrl-C 提前退出。[/dim]")

        async with async_playwright() as pw:
            # launch_persistent_context owns the Chrome lifecycle here — this is
            # a one-shot login browser, NOT the always-on CDP Chrome the launcher
            # manages. Closing the context kills it. Login state persists in
            # profile_path for the launcher's CDP Chrome to reuse.
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=profile_path,
                headless=False,
                args=[
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                await page.goto(login_url, wait_until="domcontentloaded")
                # Block until timeout or the user closes the window / Ctrl-C.
                # We don't auto-detect login success — the operator closes the
                # browser when done; the profile is already written by then.
                try:
                    await page.wait_for_event("close", timeout=timeout * 1000)
                except Exception:
                    # Timeout — close the browser ourselves. Login state written
                    # so far is persisted in profile_path regardless.
                    console.print(
                        f"[yellow]扫码超时 ({timeout}s)，关闭浏览器。"
                        "已写入的登录态保留在 profile。[/yellow]"
                    )
            except KeyboardInterrupt:
                console.print("\n[yellow]用户中断，关闭浏览器。登录态已写入 profile。[/yellow]")
            finally:
                await context.close()

        console.print(
            Panel(
                f"登录流程结束。Profile: {profile_path}\n"
                "下一步: scripts/chrome-profiles.sh start 启动常驻 CDP Chrome 复用此登录态。",
                title="✅ 完成",
                style="green",
            )
        )

    asyncio.run(_login())


if __name__ == "__main__":
    app()
