"""Read-only check of Git publication candidates, including already tracked files.

No commit/staging, no provider network, no secret values in output. When the
project has no Git repository, use a disposable Git directory to apply .gitignore.
"""
import fnmatch
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKED = {".env", ".streamlit/secrets.toml"}
PRIVATE_PATTERNS = ("*.db*", "*.sqlite*", "*.log", "*.zip", "COMPTE_RENDU_*.md", "OPSDESK_AI_CODEX_*.md")
KEY_PATTERN = re.compile(rb"\b(?:AIza[A-Za-z0-9_-]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{30,})")


def git_output(root, git_dir=None):
    command = ["git"]
    if git_dir:
        command += ["--git-dir=" + str(git_dir), "--work-tree=" + str(root)]
    command += ["-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    result = subprocess.run(command, check=True, capture_output=True)
    return sorted(set(p for p in result.stdout.decode("utf-8").split("\0") if p))


def candidates(root):
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if result.returncode == 0 and Path(result.stdout.strip()).resolve() == root.resolve():
        return git_output(root)
    with tempfile.TemporaryDirectory(prefix=".publication-check-", dir=root) as folder:
        # Verify the cleanup target remains a child of the intended workspace.
        assert Path(folder).resolve().is_relative_to(root.resolve())
        subprocess.run(["git", "init", "--quiet", folder], check=True, capture_output=True)
        return git_output(root, Path(folder) / ".git")


def inspect_files(root, names):
    secrets = []
    if (root / ".env").is_file():
        for line in (root / ".env").read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.partition("=")
            value = value.strip().strip("\"'")
            if sep and key.strip().endswith("API_KEY") and len(value) >= 12:
                secrets.append(value.encode())
    problems = []
    for name in names:
        path = Path(name)
        private_dir = any(part in {".venv", "__pycache__", "secrets", "review_exports", ".git"} or part.startswith((".pytest", ".publication-check-")) for part in path.parts)
        private_name = (name in BLOCKED or path.name == ".env"
                        or (path.name == "secrets.toml" and ".streamlit" in path.parts)
                        or (path.name.startswith(".env.") and path.name != ".env.example")
                        or any(fnmatch.fnmatch(path.name, pattern) for pattern in PRIVATE_PATTERNS))
        if private_dir or private_name:
            problems.append((name, "fichier local/privé présent dans les candidats Git"))
            continue
        file = root / path
        if file.is_symlink() or not file.resolve().is_relative_to(root.resolve()):
            problems.append((name, "lien ou chemin extérieur à vérifier"))
        elif file.is_file():
            content = file.read_bytes()
            if KEY_PATTERN.search(content) or any(secret in content for secret in secrets):
                problems.append((name, "clé potentielle détectée ; valeur masquée"))
    return problems


def main():
    if not shutil.which("git"):
        raise SystemExit("Git requis pour vérifier les candidats à la publication.")
    names = candidates(ROOT)
    problems = inspect_files(ROOT, names)
    if problems:
        for name, reason in problems:
            print(f"À corriger : {name} — {reason}")
        raise SystemExit(1)
    print(f"OK : {len(names)} fichiers candidats Git contrôlés ; aucun fichier privé, clé locale connue ou motif de clé détecté.")
    print("Lecture seule : aucun fichier ajouté à l'index, aucun commit ni publication. Les secrets non reconnus restent à vérifier manuellement avant envoi.")


if __name__ == "__main__":
    main()
