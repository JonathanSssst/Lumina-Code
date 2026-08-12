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

from lumina import __version__
from lumina.config import get_settings, resolve_env_file
from lumina.factory import build_agent
from lumina.logging_setup import setup_logging
from lumina.types import Message

GITHUB_REPO = "JonathanSssst/Lumina-Code"

app = typer.Typer(
    name="lumina",
    help="LuminaCode - a local MCP-driven coding agent powered by DeepSeek V4 Flash.",
    no_args_is_help=True,
)
console = Console()


@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(False, "-version", "--version", help="Show version and exit."),
    latest: bool = typer.Option(False, "-latest", "--latest", help="With -version: check the latest GitHub release."),
) -> None:
    """LuminaCode 命令行入口。

    `lumina -version` / `lumina --version` 输出当前版本号后退出；
    加 `-latest` 时同时查询 GitHub 上的最新发布版本。
    不带参数时显示帮助信息。
    """
    if version:
        _print_version(latest)
        raise typer.Exit()


def _fetch_latest_release_tag() -> str | None:
    """Return the tag name of the latest GitHub release, or None on failure."""
    import httpx

    try:
        resp = httpx.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            timeout=10,
            follow_redirects=True,
        )
        resp.raise_for_status()
        tag = resp.json().get("tag_name")
        return tag if isinstance(tag, str) and tag else None
    except Exception:  # noqa: BLE001
        return None


def _parse_semver(text: str) -> tuple[int, ...]:
    """Best-effort parse of 'v1.2.3'-style versions into a comparable tuple."""
    digits = "".join(ch for ch in text if ch.isdigit() or ch == ".").strip(".")
    try:
        return tuple(int(part) for part in digits.split(".")[:3])
    except ValueError:
        return ()


def _print_version(latest: bool) -> None:
    console.print(f"LuminaCode version {__version__}")
    if not latest:
        return
    tag = _fetch_latest_release_tag()
    if tag is None:
        console.print("[yellow]Could not check the latest release (GitHub unreachable).[/]")
        return
    remote = _parse_semver(tag)
    current = _parse_semver(__version__)
    if current and remote and remote > current:
        console.print(
            f"[yellow]A newer release is available: [bold]{tag}[/] — upgrade recommended.[/]"
        )
    else:
        console.print(f"[green]You are up to date (latest: {tag}).[/]")


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
    """CLI hooks. 思考折叠为「已思考 n 秒」；工具调用紧凑展示、结果不刷屏；答案只在 Result 面板输出一次."""

    def __init__(self, quiet_stream: bool = False) -> None:
        self.quiet_stream = quiet_stream
        self._pending_thinking: float | None = None
        self._any_output = False
        self._last_was_label = False

    def _flush_thinking(self) -> None:
        if self._pending_thinking is None:
            return
        seconds = int(self._pending_thinking)
        self._pending_thinking = None
        if self.quiet_stream:
            return
        if self._any_output:
            console.print()
        console.print(f"  已思考 {seconds} 秒")
        self._any_output = True
        self._last_was_label = True

    def finish(self) -> None:
        """Flush the thinking label if the run ends mid-reasoning."""
        self._flush_thinking()

    async def on_thinking_done(self, seconds: float) -> None:
        # 思考耗时以整次 LLM 请求为准（该模型思考内容是响应末尾爆发返回，
        # 若按思考流计时窗口恒为 0）
        self._pending_thinking = seconds
        self._flush_thinking()

    async def on_tool_call(self, call) -> None:
        self._flush_thinking()
        if self.quiet_stream:
            return
        if self._last_was_label:
            console.print()
            self._last_was_label = False
        args = json.dumps(call.arguments, ensure_ascii=False)
        console.print(f"  [bold]{call.name}[/] {args[:400]}")
        self._any_output = True

    async def on_tool_result(self, result) -> None:
        # 成功的工具结果不刷屏（避免文件全文/搜索命中淹没终端）；错误给出紧凑提示
        if result.is_error and not self.quiet_stream:
            msg = result.content[:200].replace(chr(10), " ")
            console.print(f"  [red]✗ {result.name}: {msg}[/]")

    async def on_assistant_message(self, chunk: str) -> None:
        # 答案不在生成时流式重复打印，最终在 Result 面板统一渲染一次
        self._flush_thinking()

    async def on_reasoning(self, chunk: str) -> None:
        # 折叠思考：丢弃原始文本；耗时由 on_thinking_done 按请求时长计算
        pass


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
            "可在 .env 调大或移除 LUMINA_TOKEN_BUDGET（0 = 不限制）。[/]"
        )
    elif result.stopped_reason == "iterations_exhausted":
        console.print(
            "[yellow]已达最大迭代次数，任务被截断。"
            "可在 .env 调大或移除 LUMINA_MAX_ITERATIONS（0 = 不限制）。[/]"
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
    hooks = CliHooks(quiet_stream=quiet)
    agent = build_agent(workspace, settings, CliApprover(auto_yes=yes), hooks)
    try:
        result = await agent.run(task)
        hooks.finish()
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
            if cmd == "/continue":
                msgs = store.get_messages(session_id)
                last_user: Message | None = None
                last_user_index = -1
                user_index = -1
                for m in msgs:
                    if m.role == "user":
                        user_index += 1
                        last_user = m
                        last_user_index = user_index
                if last_user is None or not (last_user.content or "").strip():
                    console.print("[red]没有可继续的任务。[/]")
                    continue
                content = str(last_user.content)
                store.truncate_after_user(session_id, last_user_index)
                console.print(f"[cyan]Continue:[/] {content[:80]}")
                prompt = content  # replay the last task below
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

            hooks = CliHooks()
            agent = build_agent(workspace, settings, CliApprover(auto_yes=yes), hooks)
            try:
                result = await agent.run(
                    prompt.strip(),
                    history=history,
                    plan=store.get_plan(session_id) or None,
                    persist=lambda m, sid=session_id: store.append_message(sid, m),
                    persist_plan=lambda p, sid=session_id: store.set_plan(sid, p),
                )
                hooks.finish()
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
    console.print(f"  provider:    {settings.provider}")
    console.print(f"  base_url:    {settings.base_url}")
    console.print(f"  model:       {settings.model}")
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
    console.print(f"  tdd:         {'on' if settings.tdd_enabled else 'off'}")
    console.print(f"  memory:      {'on' if settings.project_memory else 'off'}")
    console.print(f"  auto_fix:    {settings.max_auto_fix_rounds}")
    console.print(f"  planner:     {'[green]ON[/] (' + settings.planner_model + ')' if settings.enable_planner else '[yellow]OFF[/] (reasoner 规划器，LUMINA_ENABLE_PLANNER=true 开启)'}")
    console.print(f"  safe cmds:   {', '.join(settings.safe_command_list)}")
    console.print(f"  danger cmds: {', '.join(settings.danger_command_list)}")
    if not settings.api_key:
        console.print(
            f"[red]Set {settings.key_env_var} (current provider: {settings.provider}) "
            "in your environment or .env file.[/]"
        )


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
    extra_workspaces = [Path(p.strip()) for p in settings.workspaces.split(",") if p.strip()]
    app_ = create_app(settings=settings, workspace=workspace, workspaces=extra_workspaces)

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
                _window = webview.create_window(
                    "LuminaCode", url, width=1200, height=820, min_size=(900, 620)
                )
                webview.start(func=lambda: _maximize_window(_window))
            except Exception as exc:  # noqa: BLE001
                console.print(f"[yellow]WebView failed to start ({exc}); opening the browser instead.[/]")
                webbrowser.open(url)
                server_thread.join()
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


def _maximize_window(window: Any) -> None:
    """Best-effort: start the desktop window maximized (Window API or WinForms)."""
    try:
        if window is not None and callable(getattr(window, "maximize", None)):
            window.maximize()
            return
    except Exception:  # noqa: BLE001, S110
        pass
    if sys.platform != "win32":
        return
    try:
        import clr  # type: ignore[import-not-found]  # pythonnet

        clr.AddReference("System.Windows.Forms")
        from System.Windows.Forms import FormWindowState  # type: ignore[import-not-found]

        if window is not None and getattr(window, "native", None) is not None:
            window.native.WindowState = FormWindowState.Maximized
    except Exception:  # noqa: BLE001, S110
        pass


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
