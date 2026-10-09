"""Catalog integrity: nothing relocatable without an official doc behind it."""
import pytest

from cachemover.catalog import CatalogError, load_catalog


def test_catalog_loads_and_is_not_empty():
    assert len(load_catalog()) >= 30


def test_ids_are_unique_and_sorted_by_category_then_id():
    apps = load_catalog()
    ids = [a.id for a in apps]
    assert len(ids) == len(set(ids))
    keys = [(a.category, a.id) for a in apps]
    assert keys == sorted(keys)


def test_env_var_entries_carry_official_doc_and_env_name():
    for app in load_catalog():
        if app.redirect.method == "env_var":
            assert app.official_doc, f"{app.id}: env_var 条目必须有 official_doc"
            assert app.redirect.env_name, f"{app.id}: env_var 条目必须有 env_name"


def test_config_file_entries_carry_path_and_key():
    for app in load_catalog():
        if app.redirect.method == "config_file":
            assert app.redirect.config_path, app.id
            assert app.redirect.config_key, app.id


def test_none_method_entries_are_gui_or_explicitly_flagged():
    """method=none 表示官方无机制；这类条目必须是 gui，或是明确标注的例外。"""
    for app in load_catalog():
        if app.redirect.method == "none":
            assert app.category == "gui" or app.id.startswith("vscode"), app.id


def test_every_entry_declares_windows():
    for app in load_catalog():
        assert "windows" in app.platforms, app.id


def test_every_entry_has_a_default_or_a_detection_env():
    for app in load_catalog():
        assert app.detect.env or app.detect.windows, app.id


def _write(tmp_path, body: str):
    path = tmp_path / "catalog.toml"
    path.write_text(body, encoding="utf-8")
    return tmp_path


def test_rejects_env_var_entry_without_official_doc(tmp_path):
    directory = _write(tmp_path, """
[[app]]
id = "x"
name = "X"
category = "dev"
platforms = ["windows"]
detect.windows = '%USERPROFILE%\\.x'
redirect.method = "env_var"
redirect.env_name = "X_HOME"
""")
    with pytest.raises(CatalogError):
        load_catalog(directory)


def test_rejects_config_file_entry_without_key(tmp_path):
    directory = _write(tmp_path, """
[[app]]
id = "x"
name = "X"
category = "dev"
platforms = ["windows"]
official_doc = "https://example.com"
detect.windows = '%USERPROFILE%\\.x'
redirect.method = "config_file"
redirect.config_path = '%USERPROFILE%\\.xrc'
""")
    with pytest.raises(CatalogError):
        load_catalog(directory)


def test_rejects_duplicate_ids(tmp_path):
    directory = _write(tmp_path, """
[[app]]
id = "dup"
name = "A"
category = "dev"
platforms = ["windows"]
detect.windows = '%USERPROFILE%\\.a'
redirect.method = "none"

[[app]]
id = "dup"
name = "B"
category = "dev"
platforms = ["windows"]
detect.windows = '%USERPROFILE%\\.b'
redirect.method = "none"
""")
    with pytest.raises(CatalogError):
        load_catalog(directory)


def test_rejects_unknown_method(tmp_path):
    directory = _write(tmp_path, """
[[app]]
id = "x"
name = "X"
category = "dev"
platforms = ["windows"]
detect.windows = '%USERPROFILE%\\.x'
redirect.method = "hack"
""")
    with pytest.raises(CatalogError):
        load_catalog(directory)
