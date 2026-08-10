"""LuminaCoder desktop entry point.

Launch the web UI inside a native desktop window (pywebview) and keep the
HTTP server running in the background. This file is the packaging entry:
PyInstaller can build `python -m PyInstaller --windowed app.py` directly.

Usage:
    python app.py                 # open desktop window (falls back to browser)
    python app.py --port 1300     # choose a different starting port
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent


def app_data_dir() -> Path:
    """Directory for .env / state / logs.

    Source checkout: the project root (so the existing .env keeps working).
    Packaged exe: %APPDATA%\\LuminaCoder (or $LUMINA_HOME if set).
    """
    if getattr(sys, "frozen", False):
        base = os.environ.get("LUMINA_HOME")
        return Path(base) if base else Path(os.environ.get("APPDATA", str(Path.home()))) / "LuminaCoder"
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


def _default_workspace(state: dict[str, Any], frozen: bool) -> Path:
    last = state.get("last_workspace")
    if last and Path(last).is_dir():
        return Path(last).resolve()
    if not frozen and (_PROJECT_ROOT / ".env").exists():
        return _PROJECT_ROOT
    return Path.home()


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

    extras = [Path(p.strip()) for p in settings.workspaces.split(",") if p.strip()]
    if workspace != _PROJECT_ROOT and _PROJECT_ROOT not in extras:
        extras.append(_PROJECT_ROOT)

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
    while not server.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{chosen}"

    bridge = DesktopBridge(state_file)
    if not no_webview:
        try:
            import webview
        except ImportError:
            webview = None
        if webview is not None:
            try:
                webview.create_window(
                    "LuminaCoder",
                    url,
                    width=1200,
                    height=820,
                    min_size=(900, 620),
                    js_api=bridge,
                )
                webview.start()
                server.should_exit = True
                thread.join(timeout=10)
                return
            except Exception:  # noqa: BLE001, S110
                pass

    import webbrowser

    webbrowser.open(url)
    print(f"LuminaCoder running at {url} — close this window to quit.")
    try:
        thread.join()
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(prog="lumina-app", description="LuminaCoder desktop app")
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
