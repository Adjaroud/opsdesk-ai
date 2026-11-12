import shutil
import subprocess
from pathlib import Path

import pytest


def test_gitignore_protects_local_secrets(tmp_path):
    git = shutil.which("git")
    if not git:
        pytest.skip("git absent : contrôle des règles ignore non disponible")
    root = Path(__file__).resolve().parents[1]
    shutil.copyfile(root / ".gitignore", tmp_path / ".gitignore")
    subprocess.run([git, "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    for name in (".env", ".env.local", "secrets/key.txt"):
        check = subprocess.run([git, "-C", str(tmp_path), "check-ignore", "--no-index", name], capture_output=True)
        assert check.returncode == 0
    assert subprocess.run([git, "-C", str(tmp_path), "check-ignore", "--no-index", ".env.example"], capture_output=True).returncode == 1


def test_docker_context_excludes_secrets():
    root = Path(__file__).resolve().parents[1]
    patterns = (root / ".dockerignore").read_text().splitlines()
    assert ".env" in patterns and ".env.*" in patterns and "secrets" in patterns
