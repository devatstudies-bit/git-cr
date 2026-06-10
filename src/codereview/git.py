from __future__ import annotations
import subprocess
from pathlib import Path
from .models import StagedFile

LANGUAGE_MAP = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".jsx": "javascript", ".go": "go",
    ".java": "java", ".rb": "ruby", ".rs": "rust", ".cs": "csharp",
    ".cpp": "cpp", ".c": "c", ".php": "php", ".swift": "swift",
    ".kt": "kotlin", ".sh": "bash", ".yml": "yaml", ".yaml": "yaml",
    ".json": "json", ".html": "html", ".css": "css",
}


def repo_root() -> Path | None:
    result = _run(["git", "rev-parse", "--show-toplevel"])
    return Path(result.strip()) if result else None


def staged_files(root: Path, ignore_paths: list[str] | None = None) -> list[StagedFile]:
    names = _run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"])
    if not names:
        return []

    files: list[StagedFile] = []
    for name in names.splitlines():
        path = Path(name)

        if ignore_paths and _is_ignored(path, ignore_paths):
            continue

        suffix = path.suffix.lower()
        language = LANGUAGE_MAP.get(suffix, "text")

        content = _run(["git", "show", f":{name}"])
        diff = _run(["git", "diff", "--cached", "--", name])

        files.append(StagedFile(
            path=path,
            content=content,
            diff=diff,
            language=language,
        ))

    return files


def restage(path: Path) -> None:
    # Use POSIX separators — git accepts forward slashes on all platforms
    _run(["git", "add", path.as_posix()])


def _is_ignored(path: Path, patterns: list[str]) -> bool:
    # Compare using POSIX paths so forward-slash patterns work on Windows too
    posix = path.as_posix()
    for pattern in patterns:
        pattern = pattern.rstrip("/")
        if posix.startswith(pattern) or path.match(pattern):
            return True
    return False


def _run(cmd: list[str]) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError:
        return ""
