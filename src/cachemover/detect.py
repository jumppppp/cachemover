"""Detection: where each app's cache actually lives, how big it is, its state.

A detection answers four questions per app:

* which path is *in effect* right now (env var beats platform default);
* where that answer came from (so the report can be audited);
* how much it occupies;
* whether it can be relocated by an official mechanism, is already moved,
  is currently in use by a running process, or has no official way at all.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Iterable, List, Optional, Set

from . import winenv
from .catalog import App
from .sizing import dir_size

PLATFORM_WINDOWS = "windows"

# --- status vocabulary (also used by plan.py and the CLI) -------------------
ALREADY_MOVED = "already-moved"
MOVABLE = "movable"
NO_OFFICIAL_WAY = "no-official-way"
RUNNING = "running"
MISSING = "missing"
UNSUPPORTED = "unsupported-platform"

#: Statuses that mean "nothing to do".
TERMINAL = (ALREADY_MOVED, UNSUPPORTED)


@dataclass
class Detection:
    app: App
    platform: str
    path: str                 # effective path (expanded), may be "" for unsupported
    source: str               # "env:NAME(scope)" | "default" | ""
    exists: bool
    size_bytes: int
    files: int
    status: str
    target_path: str
    reason: str = ""

    @property
    def size_human(self) -> str:
        from .sizing import human
        return human(self.size_bytes)


def resolve_path(app: App, platform: str) -> tuple:
    """Return ``(path, source)`` for the path currently in effect."""
    for name in app.detect.env:
        value, scope = winenv.resolve_env(name)
        if value:
            return winenv.expand(value), f"env:{name}({scope})"
    default = app.detect.default_for(platform)
    if default:
        return winenv.expand(default), "default"
    return "", ""


def target_path(app: App, target) -> str:
    """Where this app *would* live under ``--target``; "" if not expressible."""
    template = app.redirect.value_template
    if not template:
        return ""
    return template.replace("{target}", str(target))


def running_processes() -> Set[str]:
    """Lower-cased image names of every running process (best effort)."""
    try:
        proc = subprocess.run(["tasklist", "/fo", "csv", "/nh"],
                              capture_output=True, text=True, errors="ignore")
    except OSError:
        return set()
    names: Set[str] = set()
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        first = line.split('","')[0].strip('"').strip()
        if first:
            names.add(first.lower())
    return names


def is_running(app: App, processes: Set[str]) -> bool:
    return any(p.lower() in processes for p in app.processes)


def classify(app: App, path: str, exists: bool, running: bool, target) -> tuple:
    """Return ``(status, reason)``."""
    if app.redirect.method == "none":
        return NO_OFFICIAL_WAY, "官方没有提供重定向机制"

    if not exists:
        return MISSING, "目录不存在（未安装或从未使用）"

    wanted = target_path(app, target)
    if wanted and os.path.normcase(os.path.abspath(path)) == \
            os.path.normcase(os.path.abspath(wanted)):
        return ALREADY_MOVED, "已经在目标位置"

    if running:
        return RUNNING, "有进程正在运行，默认跳过"

    return MOVABLE, ""


def detect_all(apps: Iterable[App], target, *, platform: str = PLATFORM_WINDOWS,
               measure: bool = True, processes: Optional[Set[str]] = None
               ) -> List[Detection]:
    if processes is None:
        processes = running_processes()

    results: List[Detection] = []
    for app in apps:
        if platform not in app.platforms:
            results.append(Detection(app, platform, "", "", False, 0, 0,
                                     UNSUPPORTED, "", "catalog 未声明该平台"))
            continue

        path, source = resolve_path(app, platform)
        exists = bool(path) and os.path.isdir(path)
        size = files = 0
        if exists and measure:
            size, files = dir_size(path)

        status, reason = classify(app, path, exists,
                                  is_running(app, processes), target)
        results.append(Detection(app, platform, path, source, exists,
                                 size, files, status, target_path(app, target),
                                 reason))
    return results
