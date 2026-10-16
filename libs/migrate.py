"""兜底迁移：给没有官方重定向机制的应用建立 junction。

这是最后手段，绝不自动、绝不静默。设计规则按优先级排列：

1. **绝不丢数据。** 迁移不删除源目录，而是把它**改名**为影子目录（同盘 O(1)
   元数据操作），所以还原是瞬时且完整的；删除影子目录是另一条明确命令。
2. **切换前先校验。** 复制完成后先双向比对文件数与字节数，确认一致才动原路径。
3. **一切记账。** 每次迁移写入 %USERPROFILE%\\.cachemover\\manifest.json：
   原路径、目标路径、影子路径、校验后的大小、时间戳、状态。status 与
   restore 只依据账本，不靠猜。
4. **绝不递归删除。** 删链接只用 cmd /c rmdir，它只解除 reparse point。
5. **不安全就拒绝。** 进程在跑、目标是网络盘/移动盘、源已是链接、目标非空、
   目标盘空间不足，都是硬失败而不是警告。
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from . import junction, winenv
from .detect import running_processes
from .sizing import dir_size, human

MANIFEST_VERSION = 1
DEFAULT_MANIFEST = r"%USERPROFILE%\.cachemover\manifest.json"
SHADOW_SUFFIX = ".cachemover-old-"
DRIVE_FIXED = 3


class MigrationError(RuntimeError):
    """Any refusal or failure in the migration path."""


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------
@dataclass
class MigrationEntry:
    id: str
    name: str
    original_path: str
    target_path: str
    shadow_path: Optional[str] = None
    link_type: str = "junction"
    migrated_at: str = ""
    restored_at: str = ""
    files: int = 0
    bytes: int = 0
    state: str = "active"          # active | restored
    processes: List[str] = field(default_factory=list)
    notes: str = ""

    @property
    def size_human(self) -> str:
        return human(self.bytes)


@dataclass
class Manifest:
    path: Path
    entries: Dict[str, MigrationEntry] = field(default_factory=dict)

    @classmethod
    def load(cls, path=None) -> "Manifest":
        p = Path(winenv.expand(str(path or DEFAULT_MANIFEST)))
        if not p.is_file():
            return cls(path=p)
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise MigrationError(f"manifest unreadable ({p}): {exc}") from exc
        if raw.get("version") != MANIFEST_VERSION:
            raise MigrationError(
                f"manifest version {raw.get('version')!r} not supported "
                f"(this build understands {MANIFEST_VERSION})")
        fields = set(MigrationEntry.__dataclass_fields__)
        entries: Dict[str, MigrationEntry] = {}
        for item in raw.get("entries", []):
            entry = MigrationEntry(**{k: v for k, v in item.items() if k in fields})
            entries[entry.id] = entry
        return cls(path=p, entries=entries)

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": MANIFEST_VERSION,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "entries": [asdict(e) for e in sorted(self.entries.values(),
                                                  key=lambda e: e.id)],
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, self.path)
        return self.path

    def find(self, entry_id: str) -> MigrationEntry:
        entry = self.entries.get(entry_id)
        if entry is None:
            known = ", ".join(sorted(self.entries)) or "(none)"
            raise MigrationError(f"no such entry {entry_id!r}; known: {known}")
        return entry

    def upsert(self, entry: MigrationEntry) -> None:
        if entry.id in self.entries:
            entry.migrated_at = self.entries[entry.id].migrated_at or entry.migrated_at
        self.entries[entry.id] = entry


# --------------------------------------------------------------------------
# preconditions
# --------------------------------------------------------------------------
def free_bytes(path) -> int:
    """Free bytes on the volume holding *path* (0 if it cannot be determined)."""
    if not sys.platform == "win32":
        return 0
    free = ctypes.c_ulonglong(0)
    ok = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
        ctypes.c_wchar_p(os.path.abspath(str(path))),
        ctypes.byref(free), None, None)
    return free.value if ok else 0


def is_fixed_drive(path) -> bool:
    """True only for a local fixed volume (no network, no removable media)."""
    if not sys.platform == "win32":
        return False
    drive = os.path.splitdrive(os.path.abspath(str(path)))[0]
    if not drive:
        return False
    try:
        return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == DRIVE_FIXED
    except Exception:
        return False


def check_migration(src: Path, dst: Path, *, processes: Optional[List[str]] = None,
                    busy: Optional[set] = None) -> List[str]:
    """Return refusal reasons; an empty list means "safe to proceed"."""
    problems: List[str] = []

    if junction.is_junction(src):
        problems.append(f"源目录本身已经是 junction，无需迁移: {src}")
    elif not src.exists():
        problems.append(f"源目录不存在: {src}")
    elif not src.is_dir():
        problems.append(f"源不是目录: {src}")

    if dst.exists() or junction.is_junction(dst):
        try:
            empty = dst.is_dir() and not any(dst.iterdir())
        except OSError:
            empty = False
        if not empty:
            problems.append(f"目标已存在且非空: {dst}")

    if not is_fixed_drive(dst):
        problems.append(f"目标不是本机固定磁盘（拒绝网络盘/移动盘）: {dst}")

    if src.exists() and src.is_dir():
        size, _ = dir_size(src)
        available = free_bytes(dst)
        if size and available and available < size:
            problems.append(
                f"目标盘空间不足：需要 {human(size)}，可用 {human(available)}")

    if processes:
        names = busy if busy is not None else running_processes()
        hits = sorted({p.lower() for p in processes} & names)
        if hits:
            problems.append("以下进程仍在运行，请先完全退出: " + ", ".join(hits))

    return problems


# --------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------
def _robocopy(src: Path, dst: Path) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        # /XJ: never descend into junctions. Without it, a self-referential
        # junction (e.g. AppData\Local\"Application Data") recurses forever,
        # and ordinary junctions get copied as duplicate payload.
        ["robocopy", str(src), str(dst), "/E", "/COPY:DAT", "/R:1", "/W:1",
         "/MT:16", "/XJ", "/NFL", "/NDL", "/NP", "/NJH"],
        capture_output=True, text=True, errors="replace")
    return proc.returncode          # robocopy: <8 means success


def strip_object_prefix(raw: str) -> str:
    """Drop the NTFS object-path prefix from a link target, for display."""
    if not raw:
        return raw
    for prefix in ("\\\\?\\", "\\??\\", "\\\\.\\"):
        if raw.startswith(prefix):
            return raw[len(prefix):]
    return raw


def normalize_link_target(raw: str) -> str:
    """Normalize a link target so it compares equal to a recorded path.

    ``os.readlink`` on a junction returns the kernel substitution name —
    ``\\\\?\\R:\\path``, the same ``\\??\\`` form ``fsutil`` prints — which is
    never literally equal to the plain ``R:\\path`` stored in the manifest.
    """
    return os.path.normcase(os.path.normpath(strip_object_prefix(raw or "")))


def remove_tree(path: Path) -> None:
    """Delete a directory tree, clearing read-only bits as needed.

    Vendors ship read-only resource files inside their caches (JianyingPro's
    ``User Data/Resources`` is full of them) and plain ``shutil.rmtree`` dies on
    those with ``WinError 5`` — the whole cleanup aborts half-way. Clear the bit
    and retry per entry instead.
    """
    def _force(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_force)
    else:
        shutil.rmtree(path, onerror=_force)


def _shadow_path(src: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return src.with_name(src.name + SHADOW_SUFFIX + stamp)


def verify_copy(src: Path, dst: Path) -> tuple:
    """Return (ok, message) comparing file counts and byte totals both ways."""
    s_bytes, s_files = dir_size(src)
    d_bytes, d_files = dir_size(dst)
    if s_files != d_files or s_bytes != d_bytes:
        return False, (f"校验不一致：源 {s_files} 文件 / {human(s_bytes)}，"
                       f"目标 {d_files} 文件 / {human(d_bytes)}")
    return True, f"校验通过：{s_files} 文件 / {human(s_bytes)}"


# --------------------------------------------------------------------------
# migrate / restore / cleanup
# --------------------------------------------------------------------------
def migrate(src, dst, entry_id, name="", *, yes=False, processes=None,
            manifest: "Manifest") -> List[str]:
    """迁移一个目录。

    ``manifest`` 是**必填**的：省略时若回退到默认账本，一次手误就会往用户的
    真实账本里写记录。必填让这类调用在第一时间报 TypeError。
    """
    src, dst = Path(str(src)).resolve(), Path(str(dst)).resolve()
    log: List[str] = []

    problems = check_migration(src, dst, processes=processes)
    if problems:
        raise MigrationError("拒绝迁移：\n  - " + "\n  - ".join(problems))

    size, files = dir_size(src)
    log.append(f"源   {src}")
    log.append(f"目标 {dst}")
    log.append(f"体积 {human(size)} / {files} 文件")
    log.append(f"影子 {src.name}{SHADOW_SUFFIX}<时间戳>（原目录改名保留，不删除）")

    # Nested junctions are excluded by robocopy /XJ. They survive a rename-based
    # restore (they come back with the shadow) but not a copy-back restore.
    nested = scan_junctions(src, max_depth=0)
    if nested:
        log.append("")
        log.append(f"⚠ 源目录内含 {len(nested)} 个 junction，它们不会被复制到目标：")
        for item in nested[:5]:
            log.append(f"    {item['path']}  ->  {item['target']}")
        if len(nested) > 5:
            log.append(f"    …（共 {len(nested)} 个）")
        log.append("    改名回退时它们随原目录一起回来；从目标盘搬回时不会恢复。")

    if not yes:
        log.append("")
        log.append("[DRY-RUN] 未做任何修改。加 --yes 将执行：")
        log.append("  1) robocopy 复制到目标")
        log.append("  2) 双向校验文件数与字节数")
        log.append("  3) 把原目录改名为影子目录（O(1)，不占额外空间）")
        log.append("  4) 在原路径建立 junction")
        log.append("  5) 写入账本")
        log.append("")
        log.append(f"还原：cachemover junction restore --id {entry_id}")
        return log

    code = _robocopy(src, dst)
    if code >= 8:
        raise MigrationError(f"robocopy 复制失败（exit {code}）")
    log.append(f"[1/5] 已复制到 {dst}（robocopy exit={code}）")

    ok, message = verify_copy(src, dst)
    log.append(f"[2/5] {message}")
    if not ok:
        raise MigrationError(message + "（源目录未改动，可安全重试）")

    shadow = _shadow_path(src)
    os.rename(src, shadow)
    log.append(f"[3/5] 原目录已改名为影子目录 {shadow.name}")

    try:
        junction.create_junction(src, dst)
    except junction.JunctionRefused as exc:
        os.rename(shadow, src)                    # roll back immediately
        raise MigrationError(f"建立 junction 失败，已回滚原目录：{exc}") from exc
    log.append(f"[4/5] junction 已建立 {src} -> {dst}")

    entry = MigrationEntry(
        id=entry_id, name=name or src.name,
        original_path=str(src), target_path=str(dst),
        shadow_path=str(shadow),
        migrated_at=datetime.now().isoformat(timespec="seconds"),
        files=files, bytes=size, state="active",
        processes=sorted(set(processes or [])),
    )
    man = manifest
    man.upsert(entry)
    saved = man.save()
    log.append(f"[5/5] 已记账 {saved}")

    log.append("")
    log.append("确认程序一切正常后，释放 C 盘空间：")
    log.append(f"  cachemover junction cleanup --id {entry_id}")
    return log


def restore(entry: MigrationEntry, *, yes=False,
            manifest: "Manifest") -> List[str]:
    src, dst = Path(entry.original_path), Path(entry.target_path)
    shadow = Path(entry.shadow_path) if entry.shadow_path else None
    log: List[str] = []

    shadow_ok = bool(shadow and shadow.exists())
    log.append("还原方式：" + ("改名回退（瞬时，数据从未离开 C 盘）"
                              if shadow_ok else "从目标盘搬回（影子目录已清理）"))

    if not yes:
        log.append("")
        log.append("[DRY-RUN] 将执行：")
        log.append(f"  1) cmd /c rmdir \"{src}\"        # 只删链接，绝不递归")
        if shadow_ok:
            log.append(f"  2) rename \"{shadow}\" -> \"{src}\"")
        else:
            log.append(f"  2) robocopy \"{dst}\" -> \"{src}\" 并双向校验")
        log.append("加 --yes 执行。")
        return log

    if junction.is_junction(src):
        junction.remove_junction(src)
        log.append(f"[1] 已用 rmdir 移除链接（目标数据未动）: {src}")
    elif src.exists():
        raise MigrationError(f"原路径存在但不是 junction，为避免覆盖已中止: {src}")

    if shadow_ok:
        os.rename(shadow, src)
        log.append(f"[2] 影子目录已改名回 {src}（数据一直都在 C 盘）")
        if dst.exists():
            log.append(f"[!] 目标副本仍保留在 {dst}，确认后请自行清理"
                       f"（它已不在本工具的管理范围内）")
    else:
        code = _robocopy(dst, src)
        if code >= 8:
            raise MigrationError(f"robocopy 回搬失败（exit {code}）")
        ok, message = verify_copy(dst, src)
        log.append(f"[2] {message}")
        if not ok:
            raise MigrationError(message + "（未删除目标副本，可人工处理）")
        log.append(f"[3] 目标副本仍保留在 {dst}（确认后可手动清理）")

    entry.state = "restored"
    entry.restored_at = datetime.now().isoformat(timespec="seconds")
    man = manifest
    man.upsert(entry)
    man.save()
    log.append("已更新账本：state=restored")
    return log


def cleanup(entry: MigrationEntry, *, yes=False,
            manifest: "Manifest") -> List[str]:
    """Delete the shadow copy — the only step that actually frees C: space."""
    log: List[str] = []
    if not entry.shadow_path:
        log.append(f"{entry.id}: 账本里没有影子目录，无需清理。")
        return log

    shadow = Path(entry.shadow_path)
    if not shadow.exists():
        log.append(f"{entry.id}: 影子目录已不存在: {shadow}")
        return log

    expected_prefix = Path(entry.original_path).name + SHADOW_SUFFIX
    if not shadow.name.startswith(expected_prefix):
        raise MigrationError(f"影子目录名不符合约定，拒绝删除: {shadow}")

    if junction.is_junction(entry.original_path):
        pass
    elif Path(entry.original_path).exists():
        raise MigrationError(
            "原路径不是 junction（可能已被还原），拒绝删除影子目录以免误删数据")

    size, files = dir_size(shadow)
    log.append(f"将删除影子目录 {shadow}")
    log.append(f"  释放 {human(size)} / {files} 文件")
    log.append("  ⚠ 此后还原将改为「从目标盘搬回」，不再是瞬时操作")
    if not yes:
        log.append("[DRY-RUN] 加 --yes 执行。")
        return log

    remove_tree(shadow)
    entry.shadow_path = None
    man = manifest
    man.upsert(entry)
    man.save()
    log.append("已删除影子目录并更新账本。")
    return log


def rebase(entry: MigrationEntry, *, yes=False,
           manifest: "Manifest") -> List[str]:
    """Refresh the recorded size to what is on the target right now.

    An app that keeps running keeps growing its cache, so ``status`` would
    forever report drift although nothing is wrong. Rebase accepts the current
    state as the new baseline (dry-run by default).
    """
    log: List[str] = []
    if entry.state != "active":
        raise MigrationError(
            f"{entry.id} 状态是 {entry.state}，只有 active 条目需要 rebase")

    report = health(entry)
    cur_size, cur_files = report["target_bytes"], report["target_files"]
    log.append(f"{entry.id}: 当前 {human(cur_size)} / {cur_files} 文件，"
               f"记账 {human(entry.bytes)} / {entry.files} 文件")
    if not yes:
        log.append("[DRY-RUN] 会把记账基线刷新为当前值。加 --yes 执行。")
        return log

    entry.bytes = cur_size
    entry.files = cur_files
    man = manifest
    man.upsert(entry)
    man.save()
    log.append(f"已刷新记账基线：{human(cur_size)} / {cur_files} 文件")
    return log


# --------------------------------------------------------------------------
# inspection
# --------------------------------------------------------------------------
def scan_junctions(root, max_depth: int = 0) -> List[dict]:
    """Find every junction at or under *root*. Never descends into a link.

    ``max_depth`` of 0 means unlimited; a small value keeps ``junction scan``
    over a whole user profile from turning into a full-disk walk.
    """
    root = Path(str(root))
    found: List[dict] = []
    stack = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    path = Path(entry.path)
                    if junction.is_junction(path):
                        target = None
                        try:
                            target = os.readlink(path)
                        except OSError:
                            pass
                        found.append({"path": str(path),
                                      "target": strip_object_prefix(target)
                                      if target else None})
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if max_depth and depth + 1 > max_depth:
                            continue
                        stack.append((path, depth + 1))
        except OSError:
            continue
    return sorted(found, key=lambda d: str(d["path"]).lower())


def health(entry: MigrationEntry) -> dict:
    src = Path(entry.original_path)
    dst = Path(entry.target_path)
    shadow = Path(entry.shadow_path) if entry.shadow_path else None

    is_link = junction.is_junction(src)
    link_target = None
    if is_link:
        try:
            link_target = os.readlink(src)
        except OSError:
            pass

    if entry.state == "restored":
        state = "restored"
    elif not is_link and not src.exists():
        state = "broken"                  # link gone and nothing at the path
    elif is_link and not dst.exists():
        state = "broken-target"           # link points nowhere
    elif is_link and link_target and \
            normalize_link_target(link_target) != normalize_link_target(str(dst)):
        state = "wrong-target"
    else:
        state = "active"

    # For an active migration the data lives at the target; for a restored one
    # it lives back at the original path — compare against the right side.
    if state == "restored":
        size, files = dir_size(src) if src.exists() else (0, 0)
    else:
        size, files = dir_size(dst) if dst.exists() else (0, 0)
    return {
        "id": entry.id,
        "name": entry.name,
        "original_path": str(src),
        "target_path": str(dst),
        "is_junction": is_link,
        "link_target": link_target,
        "state": state,
        "target_bytes": size,
        "target_files": files,
        "recorded_bytes": entry.bytes,
        "recorded_files": entry.files,
        "matches_record": (size == entry.bytes and files == entry.files),
        "shadow_path": str(shadow) if shadow else None,
        "shadow_exists": bool(shadow and shadow.exists()),
        "migrated_at": entry.migrated_at,
    }