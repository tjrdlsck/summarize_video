import os
from pathlib import Path

def test_convention_file_exists_and_contains_os_spec():
    convention_path = Path("CONVENTION.md")
    assert convention_path.exists(), "CONVENTION.md file must exist."
    
    content = convention_path.read_text(encoding="utf-8")
    assert "Development & Target Environment" in content
    assert "Directory Structure & Architectural Blueprint" in content
    assert "Linux" in content

def test_archived_docs_directory_and_ignore():
    archive_path = Path("docs/archive")
    assert archive_path.exists() and archive_path.is_dir(), "docs/archive directory must exist."
    
    ignore_path = Path(".ignore")
    assert ignore_path.exists(), ".ignore file must exist."
    ignore_content = ignore_path.read_text(encoding="utf-8")
    assert "docs/archive/" in ignore_content
