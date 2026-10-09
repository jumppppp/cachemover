"""Windows environment layer: template expansion, registry env vars, broadcast.

Only the *user* scope is ever written by this package (see docs/DESIGN.md § 4);
the machine scope is read-only here on purpose.

Everything imports cleanly on non-Windows so the package can be installed,
imported and tested on Linux/macOS: registry access degrades to "not set" and
writes raise a clear error instead of an ImportError at import time.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

if sys.platform == "win32":
    import winreg
else:  # pragma: no cover - exercised by CI on non-Windows runners
    winreg = None  # type: ignore[assignment]

IS_WINDOWS = sys.platform == "win32"

USER_SUBKEY = r"Environment"
MACHINE_SUBKEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"

USER_REG_PATH = r"HKCU\Environment"
MACHINE_REG_PATH = r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment"

#: Lookup order when resolving "what is actually in effect".
SCOPE_ORDER = ("process", "user", "machine")


class UnsupportedPlatformError(RuntimeError):
    """Raised when a Windows-only operation is attempted elsewhere."""


def expand(value: str) -> str:
    """Expand ``%VAR%`` and a leading ``~`` the way a Windows shell would."""
    if not value:
        return value
    if value.startswith("~"):
        value = os.path.expanduser("~") + value[1:]
    return os.path.expandvars(value)


def _hive(scope: str):
    if winreg is None:
        raise UnsupportedPlatformError(
            f"reading the {scope!r} scope requires Windows (winreg)")
    if scope == "user":
        return winreg.HKEY_CURRENT_USER, USER_SUBKEY
    if scope == "machine":
        return winreg.HKEY_LOCAL_MACHINE, MACHINE_SUBKEY
    raise ValueError(f"unknown scope: {scope!r}")


def get_env(name: str, scope: str) -> Optional[str]:
    """Read one variable from an explicit scope, *without* expanding it.

    On non-Windows builds the registry scopes simply report "not set", so
    detection still works (it falls back to platform defaults).
    """
    if scope == "process":
        return os.environ.get(name)
    if winreg is None:
        return None
    hive, subkey = _hive(scope)
    try:
        with winreg.OpenKey(hive, subkey) as key:
            value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return value if isinstance(value, str) else None


def resolve_env(name: str) -> Tuple[Optional[str], str]:
    """First hit wins: process -> user -> machine. Returns (value, scope)."""
    for scope in SCOPE_ORDER:
        value = get_env(name, scope)
        if value:
            return value, scope
    return None, ""


def set_user_env(name: str, value: str) -> None:
    """Write a REG_EXPAND_SZ user variable. Never touches the machine hive."""
    if winreg is None:
        raise UnsupportedPlatformError(
            "writing environment variables is Windows-only")
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, USER_SUBKEY, 0,
        winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
    ) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_EXPAND_SZ, value)


def get_user_env_raw(name: str) -> Tuple[Optional[str], Optional[int]]:
    """Return (value, registry type) exactly as stored, unexpanded."""
    if winreg is None:
        return None, None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, USER_SUBKEY) as key:
            return winreg.QueryValueEx(key, name)
    except OSError:
        return None, None


def delete_user_env(name: str) -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, USER_SUBKEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, name)
        return True
    except OSError:
        return False


def broadcast_change(timeout_ms: int = 5000) -> None:
    """Tell already-running programs that the environment block changed."""
    if not IS_WINDOWS:
        return
    hwnd_broadcast = 0xFFFF
    wm_settingchange = 0x001A
    smto_abortifhung = 0x0002
    try:
        ctypes.windll.user32.SendMessageTimeoutW(
            hwnd_broadcast, wm_settingchange, 0, "Environment",
            smto_abortifhung, timeout_ms, None,
        )
    except Exception:  # pragma: no cover - best effort notification
        pass


def export_registry(destination: Path) -> List[Path]:
    """Dump both environment keys with reg.exe. Returns the files written."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if not IS_WINDOWS:
        return []
    written: List[Path] = []
    for label, reg_path in (("HKLM-Environment", MACHINE_REG_PATH),
                            ("HKCU-Environment", USER_REG_PATH)):
        out = destination / f"{label}.reg"
        try:
            proc = subprocess.run(
                ["reg", "export", reg_path, str(out), "/y"],
                capture_output=True, text=True, errors="replace",
            )
        except OSError:
            continue
        if proc.returncode == 0 and out.is_file():
            written.append(out)
    return written


def restore_registry(files: List[Path]) -> List[str]:
    """Import ``.reg`` files back. Returns human-readable log lines."""
    log: List[str] = []
    for path in files:
        path = Path(path)
        if not path.is_file():
            log.append(f"skip   {path} (missing)")
            continue
        if not IS_WINDOWS:
            log.append(f"skip   {path.name} (registry import is Windows-only)")
            continue
        try:
            proc = subprocess.run(["reg", "import", str(path)],
                                  capture_output=True, text=True, errors="replace")
        except OSError as exc:
            log.append(f"FAILED {path.name}: {exc}")
            continue
        status = "ok    " if proc.returncode == 0 else "FAILED"
        log.append(f"{status} {path.name}")
    return log