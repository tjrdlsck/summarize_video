"""Regression tests for cleanup helpers."""

from pathlib import Path

from app.application.cleanup import remove_temp_files


def test_remove_temp_files_deletes_existing_paths(tmp_path: Path):
    file_a = tmp_path / "a.tmp"
    file_b = tmp_path / "b.tmp"
    file_a.write_text("a", encoding="utf-8")
    file_b.write_text("b", encoding="utf-8")

    remove_temp_files([str(file_a), str(file_b)])

    assert not file_a.exists()
    assert not file_b.exists()


def test_remove_temp_files_ignores_missing_paths(tmp_path: Path):
    missing_file = tmp_path / "missing.tmp"

    remove_temp_files([str(missing_file)])

    assert not missing_file.exists()
