"""LuminaCode desktop entry point.

Launch the web UI inside a native desktop window (pywebview) and keep the
HTTP server running in the background. This file is the packaging entry:
PyInstaller can build `python -m PyInstaller --windowed app.py` directly.

Usage:
    python app.py                 # open desktop window (falls back to browser)
    python app.py --port 1300     # choose a different starting port
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("lumina.app")

if sys.stdout is None:  # frozen --windowed GUI has no console attached
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

_PROJECT_ROOT = Path(__file__).resolve().parent


def app_data_dir() -> Path:
    """Directory for .env / state / logs.

    Source checkout: the project root (so the existing .env keeps working).
    Packaged exe: %APPDATA%\\LuminaCode (or $LUMINA_HOME if set).
    """
    if getattr(sys, "frozen", False):
        base = os.environ.get("LUMINA_HOME")
        return Path(base) if base else Path(os.environ.get("APPDATA", str(Path.home()))) / "LuminaCode"
    return _PROJECT_ROOT


def load_state(state_file: Path) -> dict[str, Any]:
    import json

    try:
        return json.loads(Path(state_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state_file: Path, state: dict[str, Any]) -> None:
    import json

    try:
        Path(state_file).parent.mkdir(parents=True, exist_ok=True)
        Path(state_file).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def find_free_port(start: int, span: int) -> int:
    """Return the first free TCP port in [start, start + span), else start."""
    for candidate in range(start, start + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", candidate))
                return candidate
            except OSError:
                continue
    return start


class DesktopBridge:
    """Methods callable from the webview window through `pywebview.api`."""

    def __init__(self, state_file: Path) -> None:
        self.state_file = Path(state_file)

    def pick_folder(self) -> str | None:
        """Open a native folder dialog; return the chosen path or None."""
        try:
            import webview

            window = webview.windows[0] if webview.windows else None
            if window is not None:
                paths = window.create_file_dialog(webview.FOLDER_DIALOG)
                if paths:
                    return str(paths[0])
        except Exception:  # noqa: BLE001, S110
            pass
        return None

    def reveal_folder(self, path: str) -> None:
        """Open the given folder in the OS file explorer (best effort)."""
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass

    def open_url(self, url: str) -> None:
        """Open a URL in the default browser (best effort)."""
        import webbrowser

        try:
            webbrowser.open(url)
        except OSError:  # pragma: no cover
            pass


def _default_workspace(state: dict[str, Any], frozen: bool) -> Path:
    last = state.get("last_workspace")
    if last and Path(last).is_dir():
        return Path(last).resolve()
    if not frozen and (_PROJECT_ROOT / ".env").exists():
        return _PROJECT_ROOT
    return Path.home()


def _resolve_workspaces(workspace: Path, frozen: bool, extra: str) -> list[Path]:
    """Workspaces shown in the UI: configured extras + the project root (source mode only).

    In frozen builds the project root is the temporary PyInstaller extraction
    directory (_MEIPASS), so it must never be added as a workspace.
    """
    extras = [Path(p.strip()) for p in extra.split(",") if p.strip()]
    if not frozen and workspace != _PROJECT_ROOT and _PROJECT_ROOT not in extras:
        extras.append(_PROJECT_ROOT)
    return extras


def _wait_for_server(server: Any, timeout: float = 20.0) -> bool:
    """Wait until uvicorn reports `started`, or give up on timeout / shutdown."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.started:
            return True
        if server.should_exit:
            return False
        time.sleep(0.05)
    return False


def _icon_path() -> Path | None:
    """Resolve the bundled app icon (.ico) in source or frozen builds."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", "."))
    else:
        base = _PROJECT_ROOT
    cand = base / "assets" / "icon.ico"
    return cand if cand.is_file() else None


def _apply_window_icon(window: Any) -> None:
    """Best-effort: set the native WinForms window icon on Windows.

    pywebview 6 has no `icon=` argument, so reach into the WinForms Form
    through pythonnet (already loaded by the winforms backend).
    """
    if sys.platform != "win32":
        return
    icon = _icon_path()
    if icon is None:
        return
    try:
        import clr  # type: ignore[import-not-found]  # pythonnet

        clr.AddReference("System.Drawing")
        from System.Drawing import Icon  # type: ignore[import-not-found]

        if window is not None and getattr(window, "native", None) is not None:
            window.native.Icon = Icon(str(icon))
    except Exception:
        logger.debug("could not set window icon", exc_info=True)


def run_desktop(port: int = 1200, port_span: int = 200, no_webview: bool = False) -> None:
    import uvicorn

    from lumina.config import get_settings
    from lumina.logging_setup import setup_logging
    from lumina.web.app import create_app

    frozen = getattr(sys, "frozen", False)
    data_dir = app_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    if frozen:
        os.chdir(data_dir)  # .env / pydantic settings resolve from the app data dir
    else:
        os.chdir(_PROJECT_ROOT)

    settings = get_settings()
    state_file = data_dir / ".lumina_state.json"
    state = load_state(state_file)
    workspace = _default_workspace(state, frozen)
    workspace.mkdir(parents=True, exist_ok=True)

    extras = _resolve_workspaces(workspace, frozen, settings.workspaces)

    setup_logging(workspace)
    app_ = create_app(
        settings=settings,
        workspace=workspace,
        workspaces=extras,
        config_env=data_dir / ".env",
        state_file=state_file,
    )

    chosen = find_free_port(port, port_span)
    server_config = uvicorn.Config(app_, host="127.0.0.1", port=chosen, log_level="warning")
    server = uvicorn.Server(server_config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    if not _wait_for_server(server):
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError(
            f"LuminaCode server failed to start on 127.0.0.1:{chosen} "
            "(port busy or a startup error; check lumina.log)."
        )
    url = f"http://127.0.0.1:{chosen}"

    bridge = DesktopBridge(state_file)
    if not no_webview:
        try:
            import webview
        except ImportError:
            webview = None
        if webview is not None:
            try:
                _window = webview.create_window(
                    "LuminaCode",
                    url,
                    width=1200,
                    height=820,
                    min_size=(900, 620),
                    js_api=bridge,
                )
                _apply_window_icon(_window)
                webview.start()
                server.should_exit = True
                thread.join(timeout=10)
                return
            except Exception:
                logger.exception("webview failed, falling back to browser")

    import webbrowser

    webbrowser.open(url)
    print(f"LuminaCode running at {url} — close this window to quit.")
    try:
        thread.join()
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(prog="lumina-app", description="LuminaCode desktop app")
    parser.add_argument("--port", type=int, default=1200, help="starting HTTP port (default: 1200)")
    parser.add_argument("--port-span", type=int, default=200, help="ports scanned above --port when busy")
    parser.add_argument(
        "--no-webview",
        action="store_true",
        help="open the UI in the default browser instead of a desktop window",
    )
    args = parser.parse_args()
    run_desktop(port=args.port, port_span=args.port_span, no_webview=args.no_webview)


if __name__ == "__main__":
    main()
