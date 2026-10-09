"""Size accounting must never follow a junction into the real target."""
import os
import subprocess

import pytest

from cachemover.sizing import dir_size, human, is_reparse_path


def test_counts_bytes_and_files(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.txt").write_bytes(b"12345")
    (tmp_path / "sub" / "b.bin").write_bytes(b"123")
    assert dir_size(tmp_path) == (8, 2)


def test_missing_directory_is_zero(tmp_path):
    assert dir_size(tmp_path / "does-not-exist") == (0, 0)


def test_a_file_is_not_a_directory(tmp_path):
    target = tmp_path / "file.txt"
    target.write_bytes(b"abc")
    assert dir_size(target) == (0, 0)


@pytest.mark.parametrize("size,expected", [
    (0, "0 B"),
    (512, "512 B"),
    (1024, "1.0 KB"),
    (1024 ** 2, "1.0 MB"),
    (1024 ** 3, "1.0 GB"),
])
def test_human_formatting(size, expected):
    assert human(size) == expected


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows-only")
def test_junction_path_reports_zero_and_target_is_still_measured(tmp_path):
    real = tmp_path / "real"
    link = tmp_path / "link"
    real.mkdir()
    (real / "payload.bin").write_bytes(b"x" * 4096)

    proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(real)],
                          capture_output=True)     # 输出可能是 GBK，不解码
    if proc.returncode != 0:
        pytest.skip(f"mklink unavailable (exit {proc.returncode})")

    assert is_reparse_path(link) is True
    assert dir_size(real) == (4096, 1)
    # 已重定向的缓存不能按目标体积重复计一次
    assert dir_size(link) == (0, 0)
