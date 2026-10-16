"""检测：每个工具的缓存在哪、有多大、处于什么状态。

一次检测回答四个问题：

* 当前**实际生效**的路径是哪个（环境变量优先于平台默认值）；
* 这个答案来自哪里（便于审计报告）；
* 它占用多少空间；
* 它能否用官方机制重定向，是否已经搬过，是否正在被进程占用，或者官方
  根本没有提供机制。
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
#: 数据已不在 C 盘，但也没落在 --target 下（例如被移到了 D:/R: 的别处）。
#: 这类不该叫 movable —— 它并不需要搬迁，只是"没统一"。
ELSEWHERE = "elsewhere"

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

    # "movable" means: it is still on C: and could be relocated. Something
    # already living on another drive is not movable — it is merely not unified.
    drive = os.path.splitdrive(os.path.abspath(path))[0].upper()
    if drive and drive != "C:":
        return ELSEWHERE, f"已在 {drive} 盘，只是没统一到目标目录"

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
