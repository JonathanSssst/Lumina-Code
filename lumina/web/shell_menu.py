r"""Windows context-menu ("open Lumina chat here") registration.

The desktop app exposes a toggle that adds/removes two entries to the
Explorer "Directory\Background" context menu:

  - "在此打开 lumina chat"            -> cmd /k lumina chat
  - "在此打开 lumina chat（无限模式）" -> cmd /k set LUMINA_MAX_ITERATIONS=0 && set LUMINA_TOKEN_BUDGET=0 && lumina chat

Both live under HKCU\Software\Classes\Directory\Background\shell so no
administrator rights are needed.
"""

from __future__ import annotations

import sys

SHELL_ROOT = r"Software\Classes\Directory\Background\shell"
MENU_KEYS = ("LuminaChat", "LuminaChatUnlimited")
MENU_LABELS = {
    "LuminaChat": "在此打开 lumina chat",
    "LuminaChatUnlimited": "在此打开 lumina chat（无限模式）",
}
MENU_COMMANDS = {
    "LuminaChat": "cmd /k lumina chat",
    "LuminaChatUnlimited": (
        "cmd /k set LUMINA_MAX_ITERATIONS=0 && set LUMINA_TOKEN_BUDGET=0 && lumina chat"
    ),
}


def _icon_path() -> str:
    from pathlib import Path

    return str(Path.home() / "AppData" / "Local" / "LuminaCode" / "icon.ico")


def _delete_tree(winreg, root, sub_key: str) -> None:
    """Recursively delete a registry key and all its subkeys."""
    try:
        with winreg.OpenKey(root, sub_key) as key:
            subkeys = []
            for i in range(winreg.QueryInfoKey(key)[0]):
                subkeys.append(winreg.EnumKey(key, i))
        for child in subkeys:
            _delete_tree(winreg, root, sub_key + "\\" + child)
        winreg.DeleteKey(root, sub_key)
    except OSError:
        pass


def _reg() -> object | None:
    try:
        import winreg  # type: ignore
    except ImportError:
        return None
    return winreg


def context_menu_enabled() -> bool:
    """True if the context-menu entries are registered (all present)."""
    winreg = _reg()
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SHELL_ROOT) as root:
            subkeys = []
            for i in range(winreg.QueryInfoKey(root)[0]):
                subkeys.append(winreg.EnumKey(root, i))
            return all(k in subkeys for k in MENU_KEYS)
    except OSError:
        return False


def set_context_menu(enabled: bool) -> tuple[bool, str]:
    """Add (enabled=True) or remove (enabled=False) the context-menu entries."""
    winreg = _reg()
    if winreg is None:
        return False, "当前平台不支持注册表菜单（需要 Windows）"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SHELL_ROOT, 0, winreg.KEY_WRITE) as root:
            if enabled:
                for key in MENU_KEYS:
                    with winreg.CreateKey(root, key) as sub:
                        winreg.SetValueEx(sub, None, 0, winreg.REG_SZ, MENU_LABELS[key])
                        winreg.SetValueEx(sub, "Icon", 0, winreg.REG_SZ, _icon_path())
                        with winreg.CreateKey(sub, "command") as cmd:
                            winreg.SetValueEx(cmd, None, 0, winreg.REG_SZ, MENU_COMMANDS[key])
            else:
                for key in MENU_KEYS:
                    _delete_tree(winreg, root, key)
        return True, "已添加" if enabled else "已移除"
    except OSError as exc:
        return False, str(exc)


def _is_windows() -> bool:
    return sys.platform == "win32"
