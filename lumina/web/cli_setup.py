r"""User-level `lumina` command-line entry management for the desktop app.

A pip-installed lumina registers a `lumina` console script on PATH, but users
who only download the desktop exe have no such command. This module lets the
desktop app install a tiny `lumina.cmd` shim that forwards to the bundled exe
(the exe detects CLI verbs in `app.py` and runs the typer CLI), and registers
its folder on the user PATH (HKCU\Environment, no admin rights needed).
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
from pathlib import Path

SHIM_NAME = "lumina.cmd"
ENV_SUBKEY = r"Environment"
ENV_VALUE = "Path"
_HWND_BROADCAST = 0xFFFF
_WM_SETTINGCHANGE = 0x001A
_SMTO_ABORTIFHUNG = 0x0002


def bin_dir() -> Path:
    """Folder that holds the `lumina.cmd` shim (%LOCALAPPDATA%\\LuminaCode\\bin)."""
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return base / "LuminaCode" / "bin"


def _reg() -> object | None:
    try:
        import winreg  # type: ignore
    except ImportError:
        return None
    return winreg


def cli_available() -> bool:
    """True if a `lumina` command resolves on PATH (pip install or our shim)."""
    return shutil.which("lumina") is not None


def cli_managed() -> bool:
    """True if our shim file exists and its folder is on the user PATH."""
    return (bin_dir() / SHIM_NAME).is_file() and _user_path_has(bin_dir())


def _path_entries(value: str) -> list[str]:
    """Split a PATH value into non-empty entries (quotes stripped)."""
    return [entry.strip().strip('"') for entry in value.split(";") if entry.strip()]


def _norm(entry: str) -> str:
    """Normalize a PATH entry for case-insensitive, trailing-slash-agnostic compare."""
    return str(Path(entry)).rstrip("\\/").lower()


def _user_path_value() -> tuple[str, int | None]:
    """(value, registry type) of the user PATH, or ("", None) if unset/absent."""
    winreg = _reg()
    if winreg is None:
        return "", None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ENV_SUBKEY) as key:
            value, typ = winreg.QueryValueEx(key, ENV_VALUE)
            return value, typ
    except OSError:
        return "", None


def _set_user_path_value(value: str, typ: int | None) -> None:
    """Write the user PATH, creating the key/value if needed."""
    winreg = _reg()
    if winreg is None:
        raise OSError("winreg unavailable (not Windows)")
    if typ is None:
        typ = winreg.REG_EXPAND_SZ
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, ENV_SUBKEY) as key:
        winreg.SetValueEx(key, ENV_VALUE, 0, typ, value)


def _user_path_has(dir_path: Path) -> bool:
    value, _ = _user_path_value()
    needle = _norm(str(dir_path))
    return any(_norm(entry) == needle for entry in _path_entries(value))


def _broadcast_env_change() -> None:
    """Notify the shell that PATH changed so new processes see the update."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SendMessageTimeoutW(  # type: ignore[attr-defined]
            _HWND_BROADCAST, _WM_SETTINGCHANGE, 0, "Environment", _SMTO_ABORTIFHUNG, 5000, None
        )
    except Exception:  # noqa: BLE001, S110
        pass


def install_cli(exe_path: str | None = None) -> tuple[bool, str]:
    """Write the `lumina.cmd` shim and register its folder on the user PATH."""
    if sys.platform != "win32":
        return False, "仅支持在 Windows 上添加命令行入口"
    exe = exe_path or (sys.executable if getattr(sys, "frozen", False) else None)
    if not exe:
        return False, "无法定位桌面应用路径（需在打包版 exe 中运行）"
    exe = str(Path(exe))
    folder = bin_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / SHIM_NAME).write_text(
            f'@echo off\r\n"{exe}" %*\r\nexit /b %errorlevel%\r\n',
            encoding="ascii",
        )
    except OSError as exc:
        return False, str(exc)

    value, typ = _user_path_value()
    if not _user_path_has(folder):
        entries = [entry for entry in _path_entries(value) if entry]
        entries.append(str(folder))
        try:
            _set_user_path_value(";".join(entries), typ)
        except OSError as exc:
            return False, str(exc)
    _broadcast_env_change()
    # Refresh the in-process PATH so `lumina` resolves right away.
    os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + str(folder)
    return True, "已添加命令行入口，重启终端后即可使用 lumina 指令"


def uninstall_cli() -> tuple[bool, str]:
    """Remove the shim file and drop its folder from the user PATH."""
    if sys.platform != "win32":
        return False, "仅支持在 Windows 上移除命令行入口"
    folder = bin_dir()
    removed_file = False
    try:
        (folder / SHIM_NAME).unlink(missing_ok=True)
        removed_file = True
    except OSError:
        pass
    value, typ = _user_path_value()
    if _user_path_has(folder):
        entries = [
            entry
            for entry in _path_entries(value)
            if entry and _norm(entry) != _norm(str(folder))
        ]
        try:
            _set_user_path_value(";".join(entries), typ)
        except OSError as exc:
            return False, str(exc)
    _broadcast_env_change()
    os.environ["PATH"] = os.pathsep.join(
        entry
        for entry in os.environ.get("PATH", "").split(os.pathsep)
        if _norm(entry) != _norm(str(folder))
    )
    if removed_file:
        return True, "已移除命令行入口"
    return True, "已移除 PATH 入口（未找到 lumina.cmd）"
