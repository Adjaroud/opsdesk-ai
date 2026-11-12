import shutil
import subprocess

import pytest

from scripts.check_publication import ROOT, candidates, inspect_files


def test_candidate_scan_excludes_private_outputs(tmp_path):
    if not shutil.which("git"):
        pytest.skip("git requis")
    shutil.copyfile(ROOT / ".gitignore", tmp_path / ".gitignore")
    for name in (".env", "data/demo.db", "review_exports/report.md", "output.zip", "COMPTE_RENDU_LOCAL.md", ".streamlit/secrets.toml", "main.py"):
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("example")
    names = candidates(tmp_path)
    assert set(names) == {".gitignore", "main.py"}
    assert not inspect_files(tmp_path, names)


@pytest.mark.parametrize("name", [".env", "nested/.env", "nested/.streamlit/secrets.toml"])
def test_already_tracked_private_file_is_reported(tmp_path, name):
    if not shutil.which("git"):
        pytest.skip("git requis")
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    file = tmp_path / name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("GEMINI_API_KEY=fake-local-key-value")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-f", name], check=True, capture_output=True)
    assert inspect_files(tmp_path, candidates(tmp_path))[0][0] == name


def test_known_key_accidentally_copied_to_source_is_reported_without_value(tmp_path):
    key = "synthetic-local-private-key"
    (tmp_path / ".env").write_text("GEMINI_API_KEY=" + key)
    (tmp_path / "main.py").write_text("key = '" + key + "'")
    problems = inspect_files(tmp_path, ["main.py"])
    assert problems and key not in str(problems)
