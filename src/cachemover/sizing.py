"""Directory size accounting.

Reparse points (junctions / symlinks) are skipped rather than followed:
following them double-counts the target and can loop forever on
self-referential junctions such as ``%LOCALAPPDATA%\\Application Data``.
"""
from __future__ import annotations

import os
import stat
from typing import Tuple, Union

PathLike = Union[str, os.PathLike]

REPARSE_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def is_reparse_point(entry: os.DirEntry) -> bool:
    try:
        info = entry.stat(follow_symlinks=False)
    except OSError:
        return True                       # unreadable: treat as "do not descend"
    return bool(getattr(info, "st_file_attributes", 0) & REPARSE_FLAG)


def is_reparse_path(path: PathLike) -> bool:
    """True if *path* itself is a reparse point (junction or symlink).

    An already-relocated cache is a junction, so its apparent size must be
    reported as zero rather than the size of the real target.
    """
    try:
        info = os.lstat(os.fspath(path))
    except OSError:
        return False
    return bool(getattr(info, "st_file_attributes", 0) & REPARSE_FLAG)


def dir_size(path: PathLike) -> Tuple[int, int]:
    """Return ``(bytes, file_count)`` for *path*; ``(0, 0)`` if it is not a dir."""
    path = os.fspath(path)
    if not os.path.isdir(path):
        return 0, 0
    if is_reparse_path(path):
        return 0, 0                       # junction/symlink: don't follow it

    total = 0
    files = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if not is_reparse_point(entry):
                                stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        continue          # vanished mid-walk / permission
        except OSError:
            continue                      # vanished mid-walk / permission
    return total, files


def human(n: int) -> str:
    """Compact human-readable size, e.g. ``126.8 GB``."""
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} B" if unit == "B" else f"{value:,.1f} {unit}"
        value /= 1024
    return f"{value:,.1f} TB"
