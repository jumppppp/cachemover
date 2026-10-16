"""计划模型：检测结果 → 可审阅、可序列化、可执行的动作。

apply 只消费计划，所以计划可以先导出、可以 diff、可以提交进仓库，由人看过
之后再执行。

安全契约：

* 不带 --apply 时 apply 就是 dry-run；
* 写任何东西之前，先把两个环境变量注册表键、计划本身，以及每个待改变量的
  改前快照（env-before.json）一起导出到 <backup_root>/<时间戳>/；
* 绝不删除任何东西 —— 真实数据的搬运由你自己用 robocopy/move 完成。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import winenv
from .detect import (ALREADY_MOVED, Detection, ELSEWHERE, MISSING, MOVABLE,
                     NO_OFFICIAL_WAY, RUNNING, UNSUPPORTED)

PLAN_VERSION = 1

#: Actions we are willing to execute by ourselves.
AUTO_METHODS = ("env_var", "config_file")


@dataclass
class Action:
    app_id: str
    name: str
    method: str
    risk: str
    from_path: str
    to_path: str
    env_name: Optional[str] = None
    env_scope: str = "user"
    config_path: Optional[str] = None
    config_key: Optional[str] = None
    config_format: Optional[str] = None
    official_doc: Optional[str] = None
    notes: str = ""
    status: str = ""
    reason: str = ""
    executable: bool = False
    skip_reason: str = ""


def build_plan(detections: Iterable[Detection], target, *,
               platform: str = "windows") -> Dict[str, Any]:
    actions: List[Action] = []
    for det in detections:
        app = det.app
        rule = app.redirect
        to_path = det.target_path or (
            str(Path(str(target)) / app.id) if rule.method == "config_file" else "")

        action = Action(
            app_id=app.id, name=app.name, method=rule.method, risk=app.risk,
            from_path=det.path, to_path=to_path,
            env_name=rule.env_name, env_scope=rule.scope,
            config_path=winenv.expand(rule.config_path) if rule.config_path else None,
            config_key=rule.config_key, config_format=rule.config_format,
            official_doc=app.official_doc, notes=app.notes,
            status=det.status, reason=det.reason,
        )

        if det.status == ALREADY_MOVED:
            action.skip_reason = "已经在目标位置"
        elif det.status in (UNSUPPORTED,):
            action.skip_reason = det.reason or "不支持当前平台"
        elif det.status == NO_OFFICIAL_WAY:
            action.skip_reason = "官方无机制，只能报告"
        elif det.status == MISSING:
            action.skip_reason = "目录不存在，无需迁移"
        elif det.status == RUNNING:
            # 有官方机制、可执行，但默认跳过；由 selected(include_running=...)
            # 决定是否真的执行（--force）。
            action.executable = True
            action.skip_reason = "有进程在运行，默认跳过（--force 可覆盖）"
        elif det.status == ELSEWHERE:
            action.skip_reason = "已在其他盘，只是没统一到目标目录"
        elif rule.method not in AUTO_METHODS:
            action.skip_reason = f"method={rule.method} 不在自动执行范围内"
        elif not to_path:
            action.skip_reason = "缺少 value_template，无法推导目标路径"
        else:
            action.executable = True

        actions.append(action)

    return {
        "version": PLAN_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "platform": platform,
        "target": str(target),
        "actions": [asdict(a) for a in actions],
    }


def plan_to_json(plan: Dict[str, Any]) -> str:
    return json.dumps(plan, ensure_ascii=False, indent=2)


def load_plan(path) -> Dict[str, Any]:
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if plan.get("version") != PLAN_VERSION:
        raise ValueError(
            f"unsupported plan version {plan.get('version')!r} "
            f"(this build understands {PLAN_VERSION})")
    return plan


def selected(plan: Dict[str, Any], *, only: Optional[Iterable[str]] = None,
             include_running: bool = False) -> List[Dict[str, Any]]:
    wanted = {o.lower() for o in only} if only else None
    out = []
    for action in plan.get("actions", []):
        if not action.get("executable"):
            continue
        if wanted is not None and action["app_id"].lower() not in wanted:
            continue
        if action.get("status") == RUNNING and not include_running:
            continue
        out.append(action)
    return out


# --------------------------------------------------------------------------
# backup / undo
# --------------------------------------------------------------------------
def make_backup_dir(backup_root) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    directory = Path(backup_root) / stamp
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def env_snapshot(actions: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Current user-scope value of every variable the plan would touch."""
    snap: Dict[str, Any] = {}
    for action in actions:
        name = action.get("env_name")
        if not name or name in snap:
            continue
        value, reg_type = winenv.get_user_env_raw(name)
        snap[name] = {"value": value, "type": reg_type}
    return snap


def _backup_file(path: Path) -> Optional[Path]:
    """Copy an existing config next to itself as ``*.bak`` before touching it."""
    if not path.is_file():
        return None
    target = path.with_suffix(path.suffix + ".bak")
    target.write_text(path.read_text(encoding="utf-8", errors="replace"),
                      encoding="utf-8")
    return target


def _write_yaml(path: Path, key: str, value: str, log: List[str]) -> None:
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        log.append(
            f"SKIP  {path.name}: 需要 PyYAML 才能安全改写（手动设置 {key}: [{value}]）")
        return

    backup = _backup_file(path)
    data = {}
    if path.is_file():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    existing = data.get(key)
    values = existing if isinstance(existing, list) else ([existing] if existing else [])
    if value not in values:
        values.insert(0, value)
    data[key] = values
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    log.append(f"OK    {path.name} -> {key}: {value}"
               + (f"  (备份 {backup.name})" if backup else "  (新建)"))


def _write_ini(path: Path, key: str, value: str, log: List[str]) -> None:
    """Minimal ``key=value`` writer for ``.npmrc``-style files.

    Only the target key is rewritten; comments and unknown lines are preserved
    verbatim, and the file is backed up first.
    """
    backup = _backup_file(path)
    lines: List[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    replaced = False
    out: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith(";"):
            out.append(line)
            continue
        head = stripped.split("=", 1)[0].strip() if "=" in stripped else None
        if head and head.lower() == key.lower():
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
    log.append(f"OK    {path.name} -> {key}={value}"
               + (f"  (备份 {backup.name})" if backup else "  (新建)"))


def _write_config_file(action: Dict[str, Any], log: List[str]) -> None:
    """Official config edit. Never guesses: unknown formats are reported, not written."""
    path = Path(action["config_path"])
    key = action["config_key"]
    value = action["to_path"]
    fmt = (action.get("config_format") or "").lower()

    if fmt == "yaml":
        _write_yaml(path, key, value, log)
    elif fmt == "ini":
        _write_ini(path, key, value, log)
    else:
        log.append(f"SKIP  {path.name}: 不支持自动改写格式 {fmt!r}，"
                   f"请手动设置 {key}={value}")


def execute(plan: Dict[str, Any], *, apply: bool = False,
            backup_root=None, only: Optional[Iterable[str]] = None,
            include_running: bool = False) -> List[str]:
    """Run the plan. Dry-run by default; ``apply=True`` writes after backing up."""
    actions = selected(plan, only=only, include_running=include_running)
    log: List[str] = []

    if not actions:
        log.append("没有可执行的条目。")
        return log

    for action in actions:
        log.append(f"{'WILL ' if not apply else 'SET  '}{action['env_name'] or action['config_key']}"
                   f"  {action['name']}  ->  {action['to_path']}")

    if not apply:
        log.append("")
        log.append("[DRY-RUN] 未做任何修改。加上 --apply 才会写入（会先自动备份）。")
        log.append("注意：本工具不搬运、不删除任何文件——请先用 robocopy/move 把数据搬到位。")
        return log

    if backup_root is None:
        raise ValueError("apply=True requires backup_root")

    backup_dir = make_backup_dir(backup_root)
    reg_files = winenv.export_registry(backup_dir)
    (backup_dir / "plan.json").write_text(plan_to_json(plan), encoding="utf-8")
    (backup_dir / "env-before.json").write_text(
        json.dumps(env_snapshot(actions), ensure_ascii=False, indent=2),
        encoding="utf-8")
    log.append("")
    log.append(f"备份目录: {backup_dir}"
               + (f"  ({len(reg_files)} 个 .reg)" if reg_files else ""))

    for action in actions:
        if action["method"] == "env_var" and action.get("env_name"):
            winenv.set_user_env(action["env_name"], action["to_path"])
            log.append(f"SET   {action['env_name']} = {action['to_path']}")
        elif action["method"] == "config_file" and action.get("config_path"):
            _write_config_file(action, log)

    winenv.broadcast_change()
    log.append("")
    log.append("已写入并广播变更；新开的终端/程序即可生效。")
    log.append(f"回滚： cachemover undo --backup {backup_dir}")
    return log


def undo(backup_dir) -> List[str]:
    """Restore the user-scope environment recorded in a backup directory."""
    directory = Path(backup_dir)
    log: List[str] = []
    snapshot_file = directory / "env-before.json"
    if not snapshot_file.is_file():
        # fall back to the raw registry dump
        regs = sorted(directory.glob("*.reg"))
        if not regs:
            raise FileNotFoundError(
                f"no env-before.json or .reg found under {directory}")
        log.extend(winenv.restore_registry(regs))
        return log

    snapshot = json.loads(snapshot_file.read_text(encoding="utf-8"))
    for name, entry in snapshot.items():
        value = entry.get("value")
        if value is None:
            if winenv.delete_user_env(name):
                log.append(f"DELETE {name}")
        else:
            winenv.set_user_env(name, value)
            log.append(f"RESTORE {name} = {value}")
    winenv.broadcast_change()
    return log
