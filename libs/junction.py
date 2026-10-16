"""NTFS junction 底层操作 —— 故意做得很难被触发。

junction 从来不是厂商官方机制，所以按设计它是 opt-in 且有护栏的：

* 必须显式传 --allow-destructive；
* 没有 TTY（非交互）时拒绝执行，避免在 CI/管道里被误触发；
* 必须已经存在备份目录。

删除 junction 一律用 rmdir。Remove-Item -Recurse 之类**会跟随 reparse
point** 的递归删除会穿透链接，把目标目录里的真实数据删掉。
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Union

PathLike = Union[str, os.PathLike]

IO_REPARSE_TAG_SYMLINK = 0xA000000C


class JunctionRefused(RuntimeError):
    """Raised whenever the guard rails say no."""


def guards_ok(*, interactive: bool, allow_destructive: bool,
              backup_dir: PathLike = None) -> None:
    """Raise :class:`JunctionRefused` unless every precondition holds."""
    if not allow_destructive:
        raise JunctionRefused(
            "junction relocation requires --allow-destructive")
    if not interactive:
        raise JunctionRefused(
            "junction relocation is refused in non-interactive runs")
    if not backup_dir or not Path(backup_dir).is_dir():
        raise JunctionRefused(
            "junction relocation requires an existing backup directory")


def is_junction(path: PathLike) -> bool:
    """True for an NTFS directory junction (not for symlinks or plain dirs)."""
    path = Path(path)
    try:
        info = os.lstat(path)
    except OSError:
        return False
    attrs = getattr(info, "st_file_attributes", 0)
    if not attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    tag = getattr(info, "st_reparse_tag", 0)
    return tag != IO_REPARSE_TAG_SYMLINK


def is_link_like(path: PathLike) -> bool:
    """A junction *or* a symlink — i.e. a path that must not be descended into."""
    path = Path(path)
    return is_junction(path) or path.is_symlink()


def create_junction(link: PathLike, target: PathLike) -> str:
    """Create ``link`` -> ``target``. The caller must already have moved data."""
    link, target = Path(link), Path(target)
    if not target.is_dir():
        raise JunctionRefused(f"target is not a directory: {target}")
    if link.exists() or is_junction(link):
        raise JunctionRefused(f"link path already exists: {link}")
    link.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                          capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise JunctionRefused(
            f"mklink failed (exit {proc.returncode}): {proc.stdout}{proc.stderr}")
    return proc.stdout.strip()


def remove_junction(link: PathLike) -> str:
    """Unlink a junction only. Refuses anything that is not a junction."""
    link = Path(link)
    if not is_junction(link):
        raise JunctionRefused(f"not a junction, refusing to remove: {link}")
    proc = subprocess.run(["cmd", "/c", "rmdir", str(link)],
                          capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise JunctionRefused(
            f"rmdir failed (exit {proc.returncode}): {proc.stdout}{proc.stderr}")
    return proc.stdout.strip()
