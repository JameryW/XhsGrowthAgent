"""CLI entry point — Typer-based command line interface."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import typer
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
):
    """启动增长引擎工作流"""
    from dotenv import load_dotenv

    # 加载 .env 文件
    load_dotenv(override=True)

    console.print(Panel("🚀 小红书增长引擎", style="bold green"))

    async def _run():
        from backend.graph.builder import compile_graph_dev
        from backend.state.schema import WorkflowPhase

        graph = await compile_graph_dev()
        thread_id = f"xhs_{account_id}_{uuid.uuid4().hex[:8]}"

        initial_state = {
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

        config = {"configurable": {"thread_id": thread_id}}

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
            console.print(Panel(
                f"最终阶段: {format_phase(final_phase)}\n"
                f"当前 Agent: {result.values.get('current_agent', 'unknown')}\n"
                f"Thread ID: {thread_id}",
                title="✅ 工作流结果",
                style="green",
            ))

        except KeyboardInterrupt:
            console.print("\n[yellow]⚠️ 工作流被中断[/yellow]")
            console.print(f"[dim]使用 'xhs-growth resume {thread_id}' 恢复[/dim]")
        except Exception as e:
            console.print(Panel(
                f"错误类型: {type(e).__name__}\n"
                f"详情: {e}\n\n"
                f"[dim]建议: 检查 API 配置或使用 --dry-run 测试[/dim]",
                title="❌ 执行失败",
                style="red",
            ))
            raise typer.Exit(1) from e

    asyncio.run(_run())


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="监听地址"),
    port: int = typer.Option(8000, help="监听端口"),
):
    """启动 API 服务"""
    import uvicorn
    from dotenv import load_dotenv

    # 加载 .env 文件
    load_dotenv(override=True)

    console.print(Panel(f"🌐 启动 API 服务: {host}:{port}", style="bold blue"))
    uvicorn.run("backend.api.app:app", host=host, port=port, reload=True)


@app.command()
def status(thread_id: str = typer.Argument(..., help="工作流线程 ID")):
    """查看工作流状态"""
    async def _status():
        from backend.graph.builder import compile_graph_dev
        from backend.state.machine import derive_status

        graph = await compile_graph_dev()
        config = {"configurable": {"thread_id": thread_id}}
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
):
    """列出活跃工作流"""
    console.print(Panel("📋 工作流列表", style="bold blue"))

    table = Table()
    table.add_column("Thread ID", style="cyan")
    table.add_column("阶段", style="white")
    table.add_column("Agent", style="white")
    table.add_column("创建时间", style="dim")

    async def _list():
        # In dev mode with memory checkpointer, we can't list threads
        # This is a placeholder for production mode with Postgres
        console.print("[dim]开发模式下无法列出工作流（使用内存检查点）[/dim]")
        console.print("[dim]生产模式将支持从 Postgres 查询[/dim]")

    asyncio.run(_list())


@app.command()
def resume(
    thread_id: str = typer.Argument(..., help="工作流线程 ID"),
    phase: str | None = typer.Option(None, help="指定恢复阶段"),
):
    """恢复中断的工作流"""
    async def _resume():
        from langgraph.types import Command

        from backend.graph.builder import compile_graph_dev
        from backend.state.machine import derive_status

        graph = await compile_graph_dev()
        config = {"configurable": {"thread_id": thread_id}}

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
            resume_value = None  # Default: ainvoke(None) for non-gate nodes

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
                console.print(Panel(
                    f"最终阶段: {format_phase(final_phase)}",
                    title="✅ 恢复结果",
                    style="green",
                ))
            except Exception as e:
                console.print(Panel(f"恢复失败: {e}", title="❌ 错误", style="red"))
        else:
            console.print("[yellow]工作流已完成，无需恢复[/yellow]")

    asyncio.run(_resume())


@app.command()
def logs(
    thread_id: str = typer.Argument(..., help="工作流线程 ID"),
    follow: bool = typer.Option(False, "--follow", "-f", help="实时跟踪日志"),
):
    """查看工作流日志"""
    async def _logs():
        from backend.graph.builder import compile_graph_dev

        graph = await compile_graph_dev()
        config = {"configurable": {"thread_id": thread_id}}

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


@app.command()
def version():
    """显示版本信息"""
    from importlib.metadata import version as get_version

    try:
        v = get_version("xhs-growth-engine")
    except Exception:
        v = "0.1.0 (dev)"

    console.print(Panel(
        f"版本: {v}\n"
        f"Python: 3.11+",
        title="📦 XhsGrowthEngine",
        style="bold green",
    ))


@app.command()
def config():
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
        ("XHS_COOKIE", "小红书 Cookie"),
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


if __name__ == "__main__":
    app()
