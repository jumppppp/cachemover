"""Plan/apply behaviour: dry-run by default, backup before write, undo restores."""
import json

import pytest

from cachemover.catalog import load_catalog
from cachemover.detect import Detection, MOVABLE, NO_OFFICIAL_WAY, RUNNING
from cachemover.plan import (build_plan, execute, load_plan, plan_to_json, undo,
                           _write_ini)


def _detection(app_id, status=MOVABLE, target_path=None, path=r"C:\fake\cache"):
    app = next(a for a in load_catalog() if a.id == app_id)
    return Detection(
        app=app, platform="windows", path=path, source="default",
        exists=True, size_bytes=0, files=0, status=status,
        target_path=target_path if target_path is not None else f"R:\\Caches\\{app_id}",
    )


def _silence_registry(monkeypatch, calls):
    monkeypatch.setattr("cachemover.plan.winenv.set_user_env",
                        lambda name, value: calls.append((name, value)))
    monkeypatch.setattr("cachemover.plan.winenv.broadcast_change", lambda *a, **k: None)
    monkeypatch.setattr("cachemover.plan.winenv.export_registry", lambda dest: [])
    monkeypatch.setattr("cachemover.plan.winenv.get_user_env_raw", lambda name: (None, None))


def test_dry_run_is_the_default_and_writes_nothing(tmp_path, monkeypatch):
    calls = []
    _silence_registry(monkeypatch, calls)
    plan = build_plan([_detection("pip", target_path=r"R:\Caches\pip")], r"R:\Caches")

    log = "\n".join(execute(plan, apply=False, backup_root=tmp_path))

    assert "[DRY-RUN]" in log
    assert calls == []
    assert list(tmp_path.iterdir()) == []          # 连备份目录都不该建


def test_apply_writes_env_and_creates_backup(tmp_path, monkeypatch):
    calls = []
    _silence_registry(monkeypatch, calls)
    plan = build_plan([_detection("pip", target_path=r"R:\Caches\pip")], r"R:\Caches")

    execute(plan, apply=True, backup_root=tmp_path)

    assert ("PIP_CACHE_DIR", r"R:\Caches\pip") in calls
    backups = list(tmp_path.iterdir())
    assert len(backups) == 1
    assert (backups[0] / "plan.json").is_file()
    assert (backups[0] / "env-before.json").is_file()


def test_method_none_is_never_executable():
    plan = build_plan([_detection("synthcut", status=NO_OFFICIAL_WAY)], r"R:\Caches")
    action = plan["actions"][0]
    assert action["executable"] is False
    assert action["skip_reason"]


def test_running_entries_are_skipped_unless_forced(tmp_path, monkeypatch):
    calls = []
    _silence_registry(monkeypatch, calls)
    plan = build_plan(
        [_detection("pip", status=RUNNING, target_path=r"R:\Caches\pip")], r"R:\Caches")

    execute(plan, apply=True, backup_root=tmp_path)
    assert calls == []

    execute(plan, apply=True, backup_root=tmp_path, include_running=True)
    assert calls == [("PIP_CACHE_DIR", r"R:\Caches\pip")]


def test_only_filters_by_app_id(tmp_path, monkeypatch):
    calls = []
    _silence_registry(monkeypatch, calls)
    plan = build_plan([
        _detection("pip", target_path=r"R:\Caches\pip"),
        _detection("uv", target_path=r"R:\Caches\uv"),
    ], r"R:\Caches")

    execute(plan, apply=True, backup_root=tmp_path, only=["uv"])
    assert calls == [("UV_CACHE_DIR", r"R:\Caches\uv")]


def test_plan_round_trips_through_json(tmp_path):
    plan = build_plan([_detection("pip", target_path=r"R:\Caches\pip")], r"R:\Caches")
    path = tmp_path / "plan.json"
    path.write_text(plan_to_json(plan), encoding="utf-8")
    assert load_plan(path)["target"] == r"R:\Caches"


def test_unknown_plan_version_is_rejected(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"version": 999}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_plan(path)


def test_ini_writer_preserves_comments_and_other_lines(tmp_path):
    npmrc = tmp_path / ".npmrc"
    npmrc.write_text("# keep me\nregistry=https://registry.npmjs.org/\n",
                     encoding="utf-8")

    _write_ini(npmrc, "cache-dir", r"R:\Caches\pnpm-cache", [])

    text = npmrc.read_text(encoding="utf-8")
    assert "# keep me" in text
    assert "registry=https://registry.npmjs.org/" in text
    assert r"cache-dir=R:\Caches\pnpm-cache" in text
    assert (tmp_path / ".npmrc.bak").is_file()


def test_ini_writer_replaces_existing_key(tmp_path):
    npmrc = tmp_path / ".npmrc"
    npmrc.write_text("cache-dir=C:\\old\n", encoding="utf-8")

    _write_ini(npmrc, "cache-dir", r"R:\Caches\pnpm-cache", [])

    text = npmrc.read_text(encoding="utf-8")
    assert r"R:\Caches\pnpm-cache" in text
    assert "C:\\old" not in text


def test_undo_restores_snapshot_and_deletes_new_vars(tmp_path, monkeypatch):
    restored, removed = [], []
    monkeypatch.setattr("cachemover.plan.winenv.set_user_env",
                        lambda n, v: restored.append((n, v)))
    monkeypatch.setattr("cachemover.plan.winenv.delete_user_env",
                        lambda n: (removed.append(n), True)[1])
    monkeypatch.setattr("cachemover.plan.winenv.broadcast_change", lambda *a, **k: None)

    (tmp_path / "env-before.json").write_text(json.dumps({
        "PIP_CACHE_DIR": {"value": r"C:\old\pip", "type": 2},
        "WAS_NOT_SET": {"value": None, "type": None},
    }), encoding="utf-8")

    log = undo(tmp_path)

    assert ("PIP_CACHE_DIR", r"C:\old\pip") in restored
    assert "WAS_NOT_SET" in removed
    assert log


def test_undo_without_snapshot_or_regs_is_an_error(tmp_path):
    from cachemover.plan import undo as undo_fn
    with pytest.raises(FileNotFoundError):
        undo_fn(tmp_path)
