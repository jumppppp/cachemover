"""`junction` 子命令组 —— 兜底迁移：给没有官方机制的应用用 NTFS junction。

这是本项目里**唯一会改变文件系统结构**的部分，因此它比其它命令保守得多：

* **默认 dry-run**，只有显式 --yes 才会动盘；
* **源目录只改名、不删除** —— 迁移把原目录改名为影子目录（同盘 O(1)），所以
  restore 是瞬时的，数据在确认之前从未离开原盘；
* **删链接一律用 cmd /c rmdir**，绝不递归；
* **一切记账** 在 %USERPROFILE%\\.cachemover\\manifest.json，status 与
  restore 只依据账本。

它不属于「官方机制」，所以 scan / plan 永远不会自动带上它。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from . import migrate
from .migrate import (DEFAULT_MANIFEST, Manifest, MigrationError,
                      MigrationEntry)
from .sizing import human


def _out(stream, text: str = "") -> None:
    print(text, file=stream)


def _manifest(args) -> Manifest:
    return Manifest.load(getattr(args, "manifest", None) or DEFAULT_MANIFEST)


def _entry_ids(man: Manifest, args) -> List[MigrationEntry]:
    if getattr(args, "all", False):
        # Only entries that are still migrated: re-restoring a restored entry
        # would fail on "the original path is not a junction".
        entries = [e for e in man.entries.values() if e.state == "active"]
        if not entries:
            raise MigrationError("账本里没有 active 条目（--all 只处理 active）")
        return sorted(entries, key=lambda e: e.id)
    ids = list(getattr(args, "id", None) or [])
    if not ids:
        raise MigrationError("需要 --id <条目> 或 --all")
    return [man.find(i) for i in ids]


# --------------------------------------------------------------------------
# junction scan —— 识别
# 注意：函数名不能叫 cmd_scan —— cli.py 里另有一个同名的顶层 scan 入口，
# 而本函数在多条命令注册时都是裸名字引用，重名会让 junction scan 走错分支。
# --------------------------------------------------------------------------
def cmd_junction_scan(args) -> int:
    roots = args.root or [r"%USERPROFILE%"]
    roots = [str(Path(migrate.winenv.expand(r))) for r in roots]

    found: List[dict] = []
    for root in roots:
        if not Path(root).is_dir():
            _out(sys.stderr, f"跳过不存在的根目录: {root}")
            continue
        found.extend(migrate.scan_junctions(root, max_depth=args.depth))

    known = {}
    try:
        man = _manifest(args)
        known = {str(Path(e.original_path)).lower(): e for e in man.entries.values()}
    except MigrationError:
        pass

    for item in found:
        entry = known.get(str(Path(item["path"])).lower())
        item["in_manifest"] = bool(entry)
        item["manifest_id"] = entry.id if entry else None

    if args.json:
        _out(sys.stdout, json.dumps(found, ensure_ascii=False, indent=2))
        return 0

    if not found:
        _out(sys.stdout, f"在 {', '.join(roots)} 下没有发现 junction。")
        return 0

    _out(sys.stdout, f"{'账本':<6} {'链接（C 盘原路径）':<52} 指向")
    _out(sys.stdout, "-" * 110)
    for item in found:
        tag = item["manifest_id"] or "—"
        _out(sys.stdout, f"{tag:<6} {item['path']:<52} {item['target'] or '(无法解析)'}")
    _out(sys.stdout)
    _out(sys.stdout, f"共 {len(found)} 个 junction（未记账的说明不是本工具建的，或账本被删）")
    return 0


# --------------------------------------------------------------------------
# junction list / status —— 记账与体检
# --------------------------------------------------------------------------
def cmd_list(args) -> int:
    man = _manifest(args)
    entries = sorted(man.entries.values(), key=lambda e: e.id)
    if args.json:
        _out(sys.stdout, json.dumps([asdict(e) for e in entries],
                                    ensure_ascii=False, indent=2))
        return 0
    if not entries:
        _out(sys.stdout, f"账本为空: {man.path}")
        return 0
    _out(sys.stdout, f"账本 {man.path}")
    _out(sys.stdout)
    _out(sys.stdout, f"{'id':<14} {'状态':<10} {'体积':>10}  {'原路径':<44} 目标")
    _out(sys.stdout, "-" * 130)
    for e in entries:
        _out(sys.stdout, f"{e.id:<14} {e.state:<10} {e.size_human:>10}  "
                         f"{e.original_path:<44} {e.target_path}")
        if e.shadow_path:
            shadow = Path(e.shadow_path)
            mark = "存在" if shadow.exists() else "已清理"
            _out(sys.stdout, f"{'':<14} {'':<10} {'':>10}  └─ 影子目录 [{mark}] {shadow.name}")
    return 0


def cmd_status(args) -> int:
    man = _manifest(args)
    entries = sorted(man.entries.values(), key=lambda e: e.id)
    reports = [migrate.health(e) for e in entries]

    if args.json:
        _out(sys.stdout, json.dumps(reports, ensure_ascii=False, indent=2))
        return 0

    if not reports:
        _out(sys.stdout, f"账本为空: {man.path}")
        return 0

    problems = 0
    _out(sys.stdout, f"{'id':<14} {'状态':<14} {'链接':<8} {'记账对得上':<10} 说明")
    _out(sys.stdout, "-" * 120)
    for r in reports:
        bad = r["state"] in ("broken", "broken-target", "wrong-target") or \
            (r["state"] == "active" and not r["matches_record"])
        problems += 1 if bad else 0
        note = ""
        if r["state"] == "broken":
            note = "链接不见了，程序会看到空目录 —— 用 restore 重建"
        elif r["state"] == "broken-target":
            note = "链接目标不可达（目标盘没挂上？）"
        elif r["state"] == "wrong-target":
            note = f"指向了别处: {r['link_target']}"
        elif r["state"] == "active" and not r["matches_record"]:
            drift = r["target_bytes"] - r["recorded_bytes"]
            note = (f"体积与记账不一致：现在 {human(r['target_bytes'])}/"
                    f"{r['target_files']} 文件，记账 {human(r['recorded_bytes'])}/"
                    f"{r['recorded_files']} 文件"
                    + (f"（差 {drift:+,} 字节）" if drift else ""))
        elif r["state"] == "active":
            note = "正常" + ("（影子目录仍在，可 cleanup 释放空间）"
                            if r["shadow_exists"] else "")
        elif r["state"] == "restored":
            note = "已还原"
        _out(sys.stdout, f"{r['id']:<14} {r['state']:<14} "
                         f"{'是' if r['is_junction'] else '否':<8} "
                         f"{'是' if r['matches_record'] else '否':<10} {note}")

    _out(sys.stdout)
    _out(sys.stdout, f"共 {len(reports)} 条，异常 {problems} 条。")
    return 0 if problems == 0 else 1


# --------------------------------------------------------------------------
# junction add —— 迁移
# --------------------------------------------------------------------------
def _derive_target(args, src: Path) -> str:
    if args.to:
        return migrate.winenv.expand(args.to)
    stem = args.id or src.name.lstrip(".")
    return str(Path(args.target) / "apps" / stem / src.name)


def cmd_add(args) -> int:
    src = Path(migrate.winenv.expand(args.path))
    entry_id = args.id or src.name.lstrip(".").lower()
    dst = Path(_derive_target(args, src))

    try:
        log = migrate.migrate(
            src, dst, entry_id, name=args.name or src.name,
            yes=args.yes, processes=args.process or None,
            manifest=_manifest(args))
    except MigrationError as exc:
        _out(sys.stderr, f"迁移失败：{exc}")
        return 2
    for line in log:
        _out(sys.stdout, line)
    return 0


# --------------------------------------------------------------------------
# junction restore / cleanup / rebase
# --------------------------------------------------------------------------
def cmd_restore(args) -> int:
    man = _manifest(args)
    try:
        entries = _entry_ids(man, args)
    except MigrationError as exc:
        _out(sys.stderr, str(exc))
        return 2

    rc = 0
    for entry in entries:
        _out(sys.stdout, f"=== restore {entry.id} ({entry.name}) ===")
        try:
            for line in migrate.restore(entry, yes=args.yes, manifest=man):
                _out(sys.stdout, line)
        except MigrationError as exc:
            _out(sys.stderr, f"  失败：{exc}")
            rc = 2
        _out(sys.stdout)
    return rc


def cmd_cleanup(args) -> int:
    man = _manifest(args)
    try:
        entries = _entry_ids(man, args)
    except MigrationError as exc:
        _out(sys.stderr, str(exc))
        return 2

    rc = 0
    for entry in entries:
        _out(sys.stdout, f"=== cleanup {entry.id} ({entry.name}) ===")
        try:
            for line in migrate.cleanup(entry, yes=args.yes, manifest=man):
                _out(sys.stdout, line)
        except MigrationError as exc:
            _out(sys.stderr, f"  失败：{exc}")
            rc = 2
        _out(sys.stdout)
    return rc


def cmd_rebase(args) -> int:
    man = _manifest(args)
    try:
        entries = _entry_ids(man, args)
    except MigrationError as exc:
        _out(sys.stderr, str(exc))
        return 2

    rc = 0
    for entry in entries:
        _out(sys.stdout, f"=== rebase {entry.id} ({entry.name}) ===")
        try:
            for line in migrate.rebase(entry, yes=args.yes, manifest=man):
                _out(sys.stdout, line)
        except MigrationError as exc:
            _out(sys.stderr, f"  失败：{exc}")
            rc = 2
        _out(sys.stdout)
    return rc


# --------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------
def register(sub, common) -> argparse.ArgumentParser:
    """Attach the ``junction`` command group to an existing subparsers object."""
    jp = sub.add_parser(
        "junction",
        parents=[common],
        help="兜底迁移：给无官方机制的应用建立 NTFS junction（默认 dry-run）",
        description="用 NTFS junction 把没有官方重定向机制的应用数据搬到别的盘。"
                    "默认 dry-run；迁移只改名不删除；一切记账，可一键还原。")
    jsub = jp.add_subparsers(dest="junction_command", required=True)

    p = jsub.add_parser("scan", parents=[common],
                        help="识别：列出现存 junction")
    p.add_argument("--root", action="append",
                   help="扫描根目录（可重复；默认 %%USERPROFILE%%）")
    p.add_argument("--depth", type=int, default=2,
                   help="最大递归深度（默认 2，避免全盘慢扫）")
    p.add_argument("--json", action="store_true")
    p.add_argument("--manifest",
                   help=f"账本路径（默认 {DEFAULT_MANIFEST.replace(chr(37), chr(37) * 2)}）")
    p.set_defaults(func=cmd_junction_scan)

    p = jsub.add_parser("list", parents=[common], help="列出账本里的迁移记录")
    p.add_argument("--json", action="store_true")
    p.add_argument("--manifest", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_list)

    p = jsub.add_parser("status", parents=[common],
                        help="体检：链接是否健在、目标是否可达、大小是否对得上")
    p.add_argument("--json", action="store_true")
    p.add_argument("--manifest", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_status)

    p = jsub.add_parser("add", parents=[common],
                        help="迁移一个目录（默认 dry-run，--yes 才执行）")
    p.add_argument("--path", required=True, help="要迁移的原路径（C 盘上的目录）")
    p.add_argument("--to", help="目标路径（默认 <target>\\apps\\<id>\\<目录名>）")
    p.add_argument("--id", help="条目 id（默认取目录名）")
    p.add_argument("--name", help="显示名")
    p.add_argument("--process", action="append",
                   help="迁移前必须退出的进程名（可重复）")
    p.add_argument("--yes", action="store_true", help="真正执行（否则 dry-run）")
    p.add_argument("--manifest", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_add)

    p = jsub.add_parser("restore", parents=[common],
                        help="还原（优先改名回退，瞬时）")
    p.add_argument("--id", action="append", help="要还原的条目（可重复）")
    p.add_argument("--all", action="store_true", help="还原全部 active 条目")
    p.add_argument("--yes", action="store_true", help="真正执行（否则 dry-run）")
    p.add_argument("--manifest", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_restore)

    p = jsub.add_parser("cleanup", parents=[common],
                        help="删除影子目录，释放 C 盘空间（此后还原不再瞬时）")
    p.add_argument("--id", action="append", help="要清理的条目（可重复）")
    p.add_argument("--all", action="store_true", help="清理全部")
    p.add_argument("--yes", action="store_true", help="真正执行（否则 dry-run）")
    p.add_argument("--manifest", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_cleanup)

    p = jsub.add_parser("rebase", parents=[common],
                        help="刷新记账基线（应用持续写入导致的“不一致”不再报警）")
    p.add_argument("--id", action="append", help="要刷新的条目（可重复）")
    p.add_argument("--all", action="store_true", help="刷新全部 active 条目")
    p.add_argument("--yes", action="store_true", help="真正写入（否则 dry-run）")
    p.add_argument("--manifest", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_rebase)

    return jp