"""CLI entry point — Typer-based command line interface."""

from __future__ import annotations

import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

app = typer.Typer(name="xhs-growth", help="小红书增长引擎 Agent")
console = Console()


@app.command()
def run(
    account_id: str = typer.Option("default", help="账号 ID"),
    phase: str = typer.Option("scouting", help="起始阶段"),
    dry_run: bool = typer.Option(False, help="模拟运行（不调用真实 API）"),
    dev: bool = typer.Option(True, help="开发模式（内存检查点）"),
):
    """启动增长引擎工作流"""
    console.print(Panel("🚀 小红书增长引擎", style="bold green"))

    async def _run():
        from backend.graph.builder import compile_graph_dev
        from backend.state.schema import WorkflowPhase
        from datetime import datetime, timezone
        import uuid

        graph = compile_graph_dev()
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
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        config = {"configurable": {"thread_id": thread_id}}

        console.print(f"[dim]Thread: {thread_id}[/dim]")
        console.print(f"[dim]Phase: {phase}[/dim]")

        if dry_run:
            console.print("[yellow]DRY RUN — 不调用真实 API[/yellow]")
            return

        try:
            result = await graph.ainvoke(initial_state, config)
            console.print(Panel(str(result), title="结果", style="green"))
        except Exception as e:
            console.print(Panel(f"错误: {e}", title="Error", style="red"))

    asyncio.run(_run())


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="监听地址"),
    port: int = typer.Option(8000, help="监听端口"),
):
    """启动 API 服务"""
    import uvicorn

    console.print(Panel(f"🌐 启动 API 服务: {host}:{port}", style="bold blue"))
    uvicorn.run("xhs_growth.api.app:app", host=host, port=port, reload=True)


@app.command()
def status(thread_id: str = typer.Argument(..., help="工作流线程 ID")):
    """查看工作流状态"""
    async def _status():
        from backend.graph.builder import compile_graph_dev

        graph = compile_graph_dev()
        config = {"configurable": {"thread_id": thread_id}}
        state = await graph.aget_state(config)

        console.print(Panel(
            f"Thread: {thread_id}\n"
            f"Next: {state.next}\n"
            f"Phase: {state.values.get('phase', 'unknown')}\n"
            f"Agent: {state.values.get('current_agent', 'unknown')}",
            title="工作流状态",
        ))

    asyncio.run(_status())


if __name__ == "__main__":
    app()
