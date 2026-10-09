"""NTFS junction relocation — deliberately hard to trigger.

Junction relocation is never an official vendor mechanism, so per DESIGN.md § 7
it is opt-in and guarded:

* requires an explicit ``--allow-destructive`` flag;
* refuses to run without a TTY (so it can never fire inside CI/pipes);
* requires a backup directory to already exist.

Removing a junction must use ``rmdir``. ``Remove-Item -Recurse`` (and any
recursive delete that follows reparse points) can walk *through* the link and
destroy the target directory's contents instead of just unlinking it.
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
