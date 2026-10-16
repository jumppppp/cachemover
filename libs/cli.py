"""命令行入口：

scan    列出当前缓存位置、占用与状态
plan    把检测结果变成可审阅、可序列化的迁移计划
apply   执行计划（默认 dry-run，写入前一定先备份）
verify  重新读取环境，核对是否已指向目标目录
export  导出完整清单（--format json 供程序消费）
undo    从备份目录回滚一次 apply
junction  兜底迁移：给无官方机制的应用建立 NTFS junction
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from . import __version__, winenv
from .catalog import App, CatalogError, load_catalog
from .cli_junction import register as register_junction
from .detect import (ALREADY_MOVED, ELSEWHERE, MISSING, MOVABLE, NO_OFFICIAL_WAY,
                     RUNNING, UNSUPPORTED, detect_all)
from .plan import build_plan, execute, load_plan, plan_to_json, undo
from .sizing import human

DEFAULT_TARGET = r"R:\Caches"
DEFAULT_BACKUP_ROOT = r"%USERPROFILE%\cachemover-backups"

STATUS_ORDER = {
    MOVABLE: 0, RUNNING: 1, MISSING: 2, NO_OFFICIAL_WAY: 3,
    ELSEWHERE: 4, ALREADY_MOVED: 5, UNSUPPORTED: 6,
}


def _out(stream, text: str = "") -> None:
    print(text, file=stream)


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def _load_apps(args) -> List[App]:
    directory = Path(args.catalog) if getattr(args, "catalog", None) else None
    apps = load_catalog(directory)
    category = getattr(args, "category", None)
    if category:
        apps = [a for a in apps if a.category == category]
    return apps


def _detections(args):
    apps = _load_apps(args)
    return detect_all(apps, args.target,
                      measure=not getattr(args, "no_size", False))


# --------------------------------------------------------------------------
# scan
# --------------------------------------------------------------------------
def _junction_map() -> dict:
    """original_path(lower) -> junction entry id, for active migrations.

    ``scan`` only knows about official mechanisms; without this, directories we
    relocated with a junction still read as "no-official-way, 0 B" and there is
    no way to tell they were already handled.
    """
    try:
        from .migrate import Manifest
        manifest = Manifest.load()
    except Exception:
        return {}
    return {str(Path(e.original_path)).lower(): e.id
            for e in manifest.entries.values() if e.state == "active"}


def cmd_scan(args) -> int:
    detections = _detections(args)
    jmap = _junction_map()

    if args.drive:
        prefix = args.drive.rstrip(":").upper() + ":"
        detections = [d for d in detections if d.path.upper().startswith(prefix)]

    detections.sort(key=lambda d: (-d.size_bytes, STATUS_ORDER.get(d.status, 9),
                                   d.app.id))

    if args.json:
        payload = [{
            "id": d.app.id,
            "name": d.app.name,
            "category": d.app.category,
            "platform": d.platform,
            "path": d.path,
            "source": d.source,
            "exists": d.exists,
            "size_bytes": d.size_bytes,
            "size_human": human(d.size_bytes) if d.exists else None,
            "files": d.files,
            "status": d.status,
            "target_path": d.target_path,
            "reason": d.reason,
            "risk": d.app.risk,
            "official_doc": d.app.official_doc,
            "notes": d.app.notes,
            "junction_id": jmap.get(str(Path(d.path)).lower()),
        } for d in detections]
        _out(sys.stdout, json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not detections:
        _out(sys.stdout, "没有匹配的条目。")
        return 0

    name_w = max(len(d.app.name) for d in detections)
    name_w = max(name_w, 12)
    _out(sys.stdout, f"{'状态':<16} {'占用':>11}  {'来源':<18} 工具 / 路径")
    _out(sys.stdout, "-" * (name_w + 70))
    total = 0
    for d in detections:
        total += d.size_bytes
        size = human(d.size_bytes) if d.exists else "—"
        where = d.path or "(无)"
        jid = jmap.get(str(Path(d.path)).lower())
        if jid:
            mark = f"  ✔junction:{jid}"
        elif d.status == ALREADY_MOVED:
            mark = "  ✔"
        else:
            mark = ""
        _out(sys.stdout,
             f"{d.status:<16} {size:>11}  {d.source:<18} {d.app.name}  {where}{mark}")
        if d.status in (RUNNING, NO_OFFICIAL_WAY, ELSEWHERE) and d.reason:
            _out(sys.stdout, f"{'':<16} {'':>11}  {'':<18} └─ {d.reason}")
    _out(sys.stdout, "-" * (name_w + 70))
    _out(sys.stdout, f"合计 {human(total)}   （目标目录 {args.target}）")
    _out(sys.stdout)
    _out(sys.stdout, "下一步： cachemover plan --target " + args.target)
    return 0


# --------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------
def _build(args) -> dict:
    return build_plan(_detections(args), args.target)


def cmd_plan(args) -> int:
    plan = _build(args)
    if args.output:
        Path(args.output).write_text(plan_to_json(plan), encoding="utf-8")
        _out(sys.stdout, f"计划已写入 {args.output}")

    if args.json:
        _out(sys.stdout, plan_to_json(plan))
        return 0

    actions = plan["actions"]
    todo = [a for a in actions if a["executable"]]
    blocked = [a for a in actions if not a["executable"]]

    _out(sys.stdout, f"目标目录: {plan['target']}   条目: {len(actions)}   "
                     f"可执行: {len(todo)}   仅报告: {len(blocked)}")
    _out(sys.stdout)
    _out(sys.stdout, f"{'工具':<24} {'机制':<12} {'风险':<7} 当前 → 目标")
    _out(sys.stdout, "-" * 110)
    for a in todo:
        _out(sys.stdout, f"{a['name']:<24} {a['method']:<12} {a['risk']:<7} "
                         f"{a['from_path']} → {a['to_path']}")
        if a["notes"]:
            _out(sys.stdout, f"{'':<24} {'':<12} {'':<7} └─ {a['notes']}")
    if blocked:
        _out(sys.stdout)
        _out(sys.stdout, "不执行（原因）：")
        for a in blocked:
            _out(sys.stdout, f"  · {a['name']:<24} [{a['status']}] {a['skip_reason']}")
    _out(sys.stdout)
    _out(sys.stdout, "确认后执行： cachemover apply -p <plan.json> --apply")
    return 0


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------
def cmd_apply(args) -> int:
    if args.plan:
        plan = load_plan(args.plan)
    else:
        plan = _build(args)
        if args.output:
            Path(args.output).write_text(plan_to_json(plan), encoding="utf-8")

    log = execute(plan, apply=args.apply,
                  backup_root=args.backup_root,
                  only=args.only,
                  include_running=args.force)
    for line in log:
        _out(sys.stdout, line)
    return 0


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------
def cmd_verify(args) -> int:
    apps = _load_apps(args)
    target = args.target
    ok = bad = na = 0
    _out(sys.stdout, f"目标目录: {target}")
    _out(sys.stdout)

    for app in apps:
        rule = app.redirect
        if not rule.env_name:
            continue
        wanted = ""
        if rule.value_template:
            wanted = rule.value_template.replace("{target}", str(target))

        # verify 关心的是「持久化在哪个级别」，所以跳过 process 作用域：
        # process 级变量不跨会话，不能当作“已配置”的证据。
        value = winenv.get_env(rule.env_name, "user")
        if value:
            scope = "user"
        else:
            value = winenv.get_env(rule.env_name, "machine")
            scope = "machine" if value else "未设置"
        actual = winenv.expand(value) if value else ""
        default = winenv.expand(app.detect.default_for(args.platform) or "")

        if not actual and not (default and Path(default).is_dir()):
            na += 1
            _out(sys.stdout, f"[N/A ] {app.name:<26} {rule.env_name} = (未安装)")
            continue

        if actual and wanted and \
                Path(actual).as_posix().lower() == Path(wanted).as_posix().lower():
            ok += 1
            _out(sys.stdout, f"[OK  ] {app.name:<26} {rule.env_name} = {actual}  [{scope}]")
            continue

        bad += 1
        _out(sys.stdout, f"[MISS] {app.name:<26} {rule.env_name} = {actual or '(未设置)'}  [{scope or '默认'}]")
        if actual and not actual.upper().startswith("C:"):
            _out(sys.stdout, f"{'':<7}└─ 已不在 C 盘（{actual}），只是没统一到 {wanted}")
        elif scope == "machine":
            _out(sys.stdout, f"{'':<7}└─ {rule.env_name} 在 Machine 级，需管理员或改用用户级覆盖")
        else:
            _out(sys.stdout, f"{'':<7}└─ 目标 {wanted}")

    _out(sys.stdout)
    _out(sys.stdout, f"{ok} 项已就位，{bad} 项待处理，{na} 项未安装（不计入）。")
    return 0 if bad == 0 else 1


# --------------------------------------------------------------------------
# export / undo
# --------------------------------------------------------------------------
def cmd_export(args) -> int:
    apps = _load_apps(args)
    payload = [{
        "id": a.id, "name": a.name, "category": a.category,
        "platforms": a.platforms, "risks": a.risk,
        "official_doc": a.official_doc,
        "detect": {
            "env": a.detect.env, "windows": a.detect.windows,
            "macos": a.detect.macos, "linux": a.detect.linux,
        },
        "redirect": {
            "method": a.redirect.method, "env_name": a.redirect.env_name,
            "scope": a.redirect.scope, "value_template": a.redirect.value_template,
            "config_path": a.redirect.config_path, "config_key": a.redirect.config_key,
        },
        "processes": a.processes,
        "notes": a.notes,
    } for a in apps]

    if args.format == "json":
        _out(sys.stdout, json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _out(sys.stdout, f"{'id':<20} {'机制':<12} {'风险':<7} name")
        for item in payload:
            _out(sys.stdout, f"{item['id']:<20} {item['redirect']['method']:<12} "
                             f"{item['risks']:<7} {item['name']}")
    return 0


def cmd_undo(args) -> int:
    try:
        log = undo(args.backup)
    except (FileNotFoundError, ValueError) as exc:
        _out(sys.stderr, f"undo 失败：{exc}")
        return 2
    for line in log:
        _out(sys.stdout, line)
    return 0


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------
def _common_options() -> argparse.ArgumentParser:
    """Options every subcommand accepts, so ``cachemover plan --target X`` works.

    argparse only lets a *top-level* option appear before the subcommand, which
    would break the documented ``cachemover <cmd> --target ...`` form.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--target", default=DEFAULT_TARGET,
                        help=f"统一缓存根目录（默认 {DEFAULT_TARGET}）")
    common.add_argument("--catalog", help="catalog 目录（默认包内 data/）")
    common.add_argument("--category", choices=("dev", "gui"), help="只处理某一类")
    common.add_argument("--no-size", action="store_true", help="跳过体积统计（更快）")
    common.add_argument("--platform", default="windows", help=argparse.SUPPRESS)
    return common


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cachemover",
        description="检测开发工具缓存位置，并只按官方机制把它们重定向到统一目录。")
    parser.add_argument("--version", action="version",
                        version=f"cachemover {__version__}")

    common = _common_options()
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", parents=[common], help="列出当前缓存位置、占用与状态")
    p.add_argument("--json", action="store_true", help="JSON 输出")
    p.add_argument("--drive", help="只看某个盘，如 --drive C")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("plan", parents=[common], help="生成迁移计划（不落盘）")
    p.add_argument("-o", "--output", help="把计划写入 JSON 文件")
    p.add_argument("--json", action="store_true", help="直接输出计划 JSON")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("apply", parents=[common], help="执行计划（默认 dry-run，会先备份）")
    p.add_argument("-p", "--plan", help="计划 JSON（省略则现场生成）")
    p.add_argument("-o", "--output", help="现场生成时把计划另存一份")
    p.add_argument("--apply", action="store_true",
                   help="真正写入（省略则为 dry-run）")
    p.add_argument("--only", nargs="*", help="只处理这些 app id")
    p.add_argument("--force", action="store_true",
                   help="连正在运行的条目也一并处理")
    p.add_argument("--backup-root", default=DEFAULT_BACKUP_ROOT,
                   help=f"备份根目录（默认 {DEFAULT_BACKUP_ROOT.replace(chr(37), chr(37) * 2)}）")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("verify", parents=[common], help="核对是否已指向目标")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("export", parents=[common], help="导出完整清单")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("undo", parents=[common], help="从备份目录回滚")
    p.add_argument("--backup", required=True, help="备份目录（apply 输出的那个）")
    p.set_defaults(func=cmd_undo)

    register_junction(sub, common)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    _configure_stdout()
    args = build_parser().parse_args(argv)
    args.backup_root = winenv.expand(args.backup_root) if \
        getattr(args, "backup_root", None) else None
    try:
        return args.func(args)
    except CatalogError as exc:
        _out(sys.stderr, f"catalog 错误：{exc}")
        return 2
    except KeyboardInterrupt:      # pragma: no cover
        _out(sys.stderr, "已中断。")
        return 130


if __name__ == "__main__":         # pragma: no cover
    raise SystemExit(main())
