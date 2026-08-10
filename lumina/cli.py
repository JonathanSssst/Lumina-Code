from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import typer

# Windows pipes default to the locale codepage (e.g. GBK), which cannot encode
# common LLM output (•, emoji, CJK). Force UTF-8 to avoid crashes.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from lumina.config import get_settings, resolve_env_file
from lumina.factory import build_agent
from lumina.logging_setup import setup_logging
from lumina.types import Message

app = typer.Typer(
    name="lumina",
    help="LuminaCoder - a local MCP-driven coding agent powered by DeepSeek V4 Flash.",
    no_args_is_help=True,
)
console = Console()


class CliApprover:
    """Interactive approver: confirms unknown/dangerous tool calls."""

    def __init__(self, auto_yes: bool = False) -> None:
        self.auto_yes = auto_yes

    async def approve(self, name: str, arguments: dict[str, Any], reason: str) -> bool:
        if self.auto_yes:
            return True
        args_json = json.dumps(arguments, ensure_ascii=False, indent=2)
        console.print(
            Panel(
                f"[bold yellow]Tool:[/] {name}\n[bold yellow]Reason:[/] {reason}\n"
                f"[bold yellow]Args:[/]\n{args_json}",
                title="Approval required",
                border_style="yellow",
            )
        )
        return Confirm.ask("Allow this tool call?", default=False)


class CliHooks:
    def __init__(self, quiet_stream: bool = False) -> None:
        self.quiet_stream = quiet_stream

    async def on_tool_call(self, call) -> None:
        console.print()
        console.print(
            f"  [cyan][tool][/] [bold]{call.name}[/] {json.dumps(call.arguments, ensure_ascii=False)[:400]}"
        )

    async def on_tool_result(self, result) -> None:
        status = "ok" if not result.is_error else "error"
        color = "green" if not result.is_error else "red"
        console.print(f"  [{color}][{status}][/] {result.content[:300].replace(chr(10), ' ')}")

    async def on_assistant_message(self, chunk: str) -> None:
        if not self.quiet_stream:
            console.print(chunk, end="")

    async def on_reasoning(self, chunk: str) -> None:
        if not self.quiet_stream:
            console.print(f"[dim]{chunk}[/]", end="")


def _print_result(result) -> None:
    console.print()
    console.print(Rule("Result", style="dim"))
    console.print(Markdown(result.final_content) if result.final_content else Text("(no text output)"))
    console.print(Rule(style="dim"))
    stats = Text(
        f"iterations={result.iterations}  tool_calls={result.tool_calls_made}  "
        f"tokens={result.total_tokens}  stop={result.stopped_reason}"
    )
    stats.stylize("dim")
    console.print(stats)
    if result.stopped_reason == "budget_exhausted":
        console.print(
            "[yellow]已达累计 token 预算上限，任务被截断。"
            "可在 .env 调大 LUMINA_TOKEN_BUDGET（当前默认 30000）。[/]"
        )
    elif result.stopped_reason == "auto_fix_exhausted":
        console.print("[yellow]自动修复轮数已用尽，测试仍未通过。可调大 LUMINA_MAX_AUTO_FIX_ROUNDS。[/]")


@app.command()
def run(
    task: str = typer.Argument(..., help="Task description, e.g. 'fix the failing tests'"),
    workdir: Path = typer.Option(".", "--workdir", "-w", help="Workspace directory"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-approve all tool calls"),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress streaming output"),
) -> None:
    """Execute a single task and exit."""
    settings = _load_settings()
    asyncio.run(_run_once(settings, workdir, task, yes=yes, quiet=quiet))


async def _run_once(settings, workdir: Path, task: str, yes: bool = False, quiet: bool = False) -> None:
    workspace = workdir.resolve()
    setup_logging(workspace)
    agent = build_agent(workspace, settings, CliApprover(auto_yes=yes), CliHooks(quiet_stream=quiet))
    try:
        result = await agent.run(task)
        _print_result(result)
    finally:
        await agent.client.aclose()


@app.command()
def chat(
    workdir: Path = typer.Option(".", "--workdir", "-w", help="Workspace directory"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-approve all tool calls"),
    resume: int | None = typer.Option(None, "--resume", "-r", help="Resume session by id"),
    list_sessions: bool = typer.Option(False, "--list", help="List saved sessions and exit"),
) -> None:
    """Interactive chat with persistent sessions. Slash commands: /list /resume <id> /new /delete <id> /exit."""
    settings = _load_settings()
    workspace = workdir.resolve()
    setup_logging(workspace)
    if list_sessions:
        _print_sessions(_open_store(workspace))
        return
    store = _open_store(workspace)
    session_id = resume if resume is not None else store.create_session(workspace)
    console.print(
        Panel(
            f"[bold]Lumina[/] working in [cyan]{workspace}[/]\n"
            f"Session [bold]#{session_id}[/] — /exit 退出，/list 列表，/resume <id> 恢复，/new 新会话"
        )
    )
    asyncio.run(_chat(settings, workspace, yes=yes, store=store, session_id=session_id))


def _open_store(workspace: Path):
    from lumina.store import SessionStore, default_db_path

    return SessionStore(default_db_path(workspace))


def _print_sessions(store) -> None:
    sessions = store.list_sessions()
    if not sessions:
        console.print("[yellow]No sessions yet.[/]")
        return
    table = Table(title="Sessions")
    table.add_column("id", justify="right")
    table.add_column("title")
    table.add_column("messages", justify="right")
    table.add_column("updated")
    for s in sessions:
        table.add_row(str(s.id), s.title[:40], str(s.message_count), s.updated_at)
    console.print(table)


async def _chat(settings, workspace: Path, yes: bool, store, session_id: int) -> None:
    try:
        while True:
            try:
                prompt = Prompt.ask("\n[bold magenta]you[/]")
            except (EOFError, KeyboardInterrupt):
                break
            cmd = prompt.strip()
            if cmd in {"/exit", "/quit", "exit", "quit"}:
                break
            if cmd in {"/list", "/sessions"}:
                _print_sessions(store)
                continue
            if cmd == "/new":
                session_id = store.create_session(workspace)
                console.print(f"[green]New session #{session_id}[/]")
                continue
            if cmd == "/resume" or cmd.startswith("/resume "):
                parts = cmd.split()
                if len(parts) != 2 or not parts[1].isdigit():
                    console.print("[red]Usage: /resume <id>[/]")
                    continue
                session_id = int(parts[1])
                if store.get_session(session_id) is None:
                    console.print(f"[red]Session {session_id} not found.[/]")
                else:
                    console.print(f"[green]Resumed session #{session_id}[/]")
                continue
            if cmd.startswith("/delete "):
                parts = cmd.split()
                if len(parts) == 2 and parts[1].isdigit():
                    store.delete_session(int(parts[1]))
                    console.print(f"[yellow]Deleted session {parts[1]}[/]")
                continue
            if not prompt.strip():
                continue

            history = store.get_messages(session_id)
            store.append_message(session_id, Message(role="user", content=prompt.strip()))
            session = store.get_session(session_id)
            if session and session.message_count <= 1:
                store.set_title(session_id, prompt.strip()[:40])

            agent = build_agent(workspace, settings, CliApprover(auto_yes=yes), CliHooks())
            try:
                result = await agent.run(
                    prompt.strip(),
                    history=history,
                    persist=lambda m, sid=session_id: store.append_message(sid, m),
                )
                _print_result(result)
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]Error:[/] {exc}")
            finally:
                await agent.client.aclose()
    finally:
        store.close()


@app.command()
def doctor() -> None:
    """Check configuration and environment health."""
    settings = _load_settings(validate_key=False)
    env_file = resolve_env_file(Path.cwd())
    console.print(f"  base_url:    {settings.deepseek_base_url}")
    console.print(f"  model:       {settings.deepseek_model}")
    console.print(f"  api_key:     {'[green]set[/]' if settings.api_key else '[red]MISSING[/]'}")
    console.print(f"  .env file:   {env_file or '[yellow]not found[/] (see .env.example)'}")
    console.print(f"  max_iter:    {settings.max_iterations}")
    console.print(f"  max_tokens:  {settings.max_tokens} (per request)")
    console.print(f"  token_budget:{settings.token_budget} (cumulative per task)")
    console.print(
        f"  compress:    {'on' if settings.compression_enabled else 'off'}"
        f" (at {int(settings.compress_at_percent * 100)}% of budget, keep {settings.compress_keep_messages})"
    )
    console.print(f"  self_review: {'on' if settings.self_review else 'off'}")
    console.print(f"  auto_fix:    {settings.max_auto_fix_rounds}")
    console.print(f"  planner:     {'[green]ON[/] (' + settings.deepseek_planner_model + ')' if settings.enable_planner else '[yellow]OFF[/] (reasoner 规划器，LUMINA_ENABLE_PLANNER=true 开启)'}")
    console.print(f"  safe cmds:   {', '.join(settings.safe_command_list)}")
    console.print(f"  danger cmds: {', '.join(settings.danger_command_list)}")
    if not settings.api_key:
        console.print("[red]Set DEEPSEEK_API_KEY in your environment or .env file.[/]")


@app.command()
def web(
    workdir: Path = typer.Option(".", "--workdir", "-w", help="Workspace directory"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(1200, "--port"),
    port_range: int = typer.Option(100, "--port-range", help="Max ports to scan above --port when busy"),
    use_webview: bool = typer.Option(
        True, "--webview/--no-webview",
        help="Open in a desktop WebView window (default) instead of the browser",
    ),
) -> None:
    """Launch the web UI (requires the 'web' extra: pip install lumina[web])."""
    try:
        import uvicorn

        from lumina.web.app import create_app
    except ImportError as exc:
        console.print(
            f"[red]Missing web dependencies:[/] {exc}\n"
            "Install with: pip install lumina[web]"
        )
        raise typer.Exit(code=1)
    settings = _load_settings()
    workspace = workdir.resolve()
    setup_logging(workspace)
    app_ = create_app(settings=settings, workspace=workspace)

    chosen = _find_free_port(host, port, port_range)
    if chosen is None:
        console.print(
            f"[red]No free port found in range {port}..{port + port_range}.[/] "
            "Release a port or pass --port."
        )
        raise typer.Exit(code=1)
    if chosen != port:
        console.print(f"[yellow]Port {port} in use, using {chosen} instead.[/]")
    console.print(f"[green]Web UI:[/] http://{host}:{chosen}  (workdir: {workspace})")

    import time
    import webbrowser

    url = f"http://{host}:{chosen}"
    if use_webview:
        try:
            import webview
        except ImportError:
            webview = None
            console.print(
                "[yellow]pywebview not installed; falling back to the browser. "
                "Install with: pip install \"lumina[webview]\"[/]"
            )
        if webview is not None:
            import threading

            server_config = uvicorn.Config(app_, host=host, port=chosen, log_level="warning")
            server = uvicorn.Server(server_config)
            server_thread = threading.Thread(target=server.run, daemon=True)
            server_thread.start()
            while not server.started:
                time.sleep(0.05)
            try:
                webview.create_window(
                    "LuminaCoder", url, width=1200, height=820, min_size=(900, 620)
                )
                webview.start()
            except Exception as exc:  # noqa: BLE001
                console.print(f"[yellow]WebView failed to start ({exc}); opening the browser instead.[/]")
                webbrowser.open(url)
                while server.is_serving():
                    time.sleep(1)
            finally:
                server.should_exit = True
                server_thread.join(timeout=10)
            return

    webbrowser.open(url)
    uvicorn.run(app_, host=host, port=chosen)


def _find_free_port(host: str, start: int, range_size: int) -> int | None:
    """Return the first free TCP port in [start, start + range_size), else None."""
    import socket

    for candidate in range(start, start + range_size):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, candidate))
                return candidate
            except OSError:
                continue
    return None


def _load_settings(validate_key: bool = True) -> Any:
    settings = get_settings()
    try:
        if validate_key:
            settings.validate_for_run()
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1)
    return settings


if __name__ == "__main__":
    app()
