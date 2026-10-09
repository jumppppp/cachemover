"""Junction guard rails: every path that could destroy data must say no."""
import pytest

from devcache.junction import JunctionRefused, guards_ok, is_junction


def test_refused_without_allow_destructive(tmp_path):
    with pytest.raises(JunctionRefused):
        guards_ok(interactive=True, allow_destructive=False, backup_dir=tmp_path)


def test_refused_in_non_interactive_runs(tmp_path):
    """Pipes and CI must never trigger a junction relocation."""
    with pytest.raises(JunctionRefused):
        guards_ok(interactive=False, allow_destructive=True, backup_dir=tmp_path)


def test_refused_without_an_existing_backup_directory(tmp_path):
    with pytest.raises(JunctionRefused):
        guards_ok(interactive=True, allow_destructive=True,
                  backup_dir=tmp_path / "missing")


def test_allowed_only_when_every_precondition_holds(tmp_path):
    guards_ok(interactive=True, allow_destructive=True, backup_dir=tmp_path)


def test_plain_directory_is_not_a_junction(tmp_path):
    assert is_junction(tmp_path) is False


def test_missing_path_is_not_a_junction(tmp_path):
    assert is_junction(tmp_path / "nope") is False
