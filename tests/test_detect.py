"""Detection rules: env beats default, and state transitions are exclusive."""
from cachemover.catalog import load_catalog
from cachemover.detect import (ALREADY_MOVED, MISSING, MOVABLE, NO_OFFICIAL_WAY,
                             RUNNING, classify, resolve_path, target_path)


def _app(app_id: str):
    return next(a for a in load_catalog() if a.id == app_id)


def test_env_var_wins_over_platform_default(monkeypatch):
    app = _app("pip")
    monkeypatch.setattr(
        "cachemover.winenv.get_env",
        lambda name, scope: r"R:\Custom\pip" if scope == "process" else None)
    path, source = resolve_path(app, "windows")
    assert path == r"R:\Custom\pip"
    assert source.startswith("env:PIP_CACHE_DIR")


def test_falls_back_to_platform_default(monkeypatch):
    app = _app("pip")
    monkeypatch.setattr("cachemover.winenv.get_env", lambda name, scope: None)
    path, source = resolve_path(app, "windows")
    assert source == "default"
    assert path.lower().endswith("pip\\cache")


def test_target_path_expands_template():
    assert target_path(_app("pip"), r"R:\Caches") == r"R:\Caches\pip"


def test_gui_entry_has_no_official_way():
    status, reason = classify(_app("synthcut"), r"C:\Users\x\.aive", True, False,
                              r"R:\Caches")
    assert status == NO_OFFICIAL_WAY
    assert reason


def test_missing_directory_is_reported_as_missing():
    status, _ = classify(_app("pip"), r"C:\nope", False, False, r"R:\Caches")
    assert status == MISSING


def test_already_moved_beats_running():
    status, _ = classify(_app("pip"), r"R:\Caches\pip", True, True, r"R:\Caches")
    assert status == ALREADY_MOVED


def test_running_beats_movable():
    status, reason = classify(_app("pip"), r"C:\x\pip", True, True, r"R:\Caches")
    assert status == RUNNING
    assert reason


def test_movable_when_nothing_stands_in_the_way():
    status, reason = classify(_app("pip"), r"C:\x\pip", True, False, r"R:\Caches")
    assert status == MOVABLE
    assert reason == ""


def test_gui_entry_without_value_template_has_no_target_path():
    assert target_path(_app("synthcut"), r"R:\Caches") == ""
