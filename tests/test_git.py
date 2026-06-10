"""Tests for git operations: staged file collection, ignore rules, restage."""
import subprocess
from pathlib import Path
import pytest

from codereview.git import repo_root, staged_files, restage, _is_ignored, LANGUAGE_MAP


class TestRepoRoot:
    def test_returns_path_inside_git_repo(self, tmp_git_repo):
        import os
        original = os.getcwd()
        os.chdir(tmp_git_repo)
        try:
            root = repo_root()
            assert root is not None
            assert root.exists()
        finally:
            os.chdir(original)

    def test_returns_none_outside_git_repo(self, tmp_path):
        import os
        original = os.getcwd()
        os.chdir(tmp_path)
        try:
            root = repo_root()
            assert root is None
        finally:
            os.chdir(original)


class TestLanguageMap:
    def test_python(self):
        assert LANGUAGE_MAP[".py"] == "python"

    def test_typescript(self):
        assert LANGUAGE_MAP[".ts"] == "typescript"
        assert LANGUAGE_MAP[".tsx"] == "typescript"

    def test_javascript(self):
        assert LANGUAGE_MAP[".js"] == "javascript"
        assert LANGUAGE_MAP[".jsx"] == "javascript"

    def test_go(self):
        assert LANGUAGE_MAP[".go"] == "go"

    def test_rust(self):
        assert LANGUAGE_MAP[".rs"] == "rust"

    def test_shell(self):
        assert LANGUAGE_MAP[".sh"] == "bash"


class TestIsIgnored:
    def test_prefix_match(self):
        assert _is_ignored(Path("tests/fixtures/data.json"), ["tests/fixtures/"])

    def test_prefix_no_match(self):
        assert not _is_ignored(Path("src/auth.py"), ["tests/fixtures/"])

    def test_glob_extension(self):
        assert _is_ignored(Path("config.generated.ts"), ["*.generated.ts"])

    def test_glob_no_match(self):
        assert not _is_ignored(Path("src/auth.py"), ["*.generated.ts"])

    def test_multiple_patterns_first_matches(self):
        assert _is_ignored(Path("vendor/lib.py"), ["vendor/", "docs/"])

    def test_multiple_patterns_second_matches(self):
        assert _is_ignored(Path("docs/api.md"), ["vendor/", "docs/"])

    def test_multiple_patterns_none_match(self):
        assert not _is_ignored(Path("src/main.py"), ["vendor/", "docs/"])

    def test_empty_patterns(self):
        assert not _is_ignored(Path("src/auth.py"), [])

    def test_posix_paths_work_regardless_of_separator(self):
        # Path("src/auth.py") uses forward slash on all platforms via as_posix()
        assert _is_ignored(Path("src/auth.py"), ["src/"])
        assert not _is_ignored(Path("lib/auth.py"), ["src/"])

    def test_pattern_with_trailing_slash_stripped(self):
        # "tests/" and "tests" should both match "tests/foo.py"
        assert _is_ignored(Path("tests/foo.py"), ["tests/"])
        assert _is_ignored(Path("tests/foo.py"), ["tests"])


class TestStagedFiles:
    def test_empty_when_nothing_staged(self, tmp_git_repo_with_commit):
        files = staged_files(tmp_git_repo_with_commit)
        assert files == []

    def test_returns_staged_python_file(self, tmp_git_repo_with_commit):
        repo = tmp_git_repo_with_commit
        auth = repo / "auth.py"
        auth.write_text("def login(): pass\n")
        subprocess.run(["git", "add", "auth.py"], cwd=repo, capture_output=True)

        files = staged_files(repo)
        assert len(files) == 1
        assert files[0].path == Path("auth.py")
        assert files[0].language == "python"
        assert "login" in files[0].content

    def test_detects_language_from_extension(self, tmp_git_repo_with_commit):
        repo = tmp_git_repo_with_commit
        (repo / "index.ts").write_text("const x: number = 1;\n")
        subprocess.run(["git", "add", "index.ts"], cwd=repo, capture_output=True)

        files = staged_files(repo)
        assert files[0].language == "typescript"

    def test_unknown_extension_uses_text(self, tmp_git_repo_with_commit):
        repo = tmp_git_repo_with_commit
        (repo / "config.xyz").write_text("key=value\n")
        subprocess.run(["git", "add", "config.xyz"], cwd=repo, capture_output=True)

        files = staged_files(repo)
        assert files[0].language == "text"

    def test_diff_is_populated(self, tmp_git_repo_with_commit):
        repo = tmp_git_repo_with_commit
        (repo / "utils.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "utils.py"], cwd=repo, capture_output=True)

        files = staged_files(repo)
        assert files[0].diff != ""

    def test_ignores_paths_matching_pattern(self, tmp_git_repo_with_commit):
        repo = tmp_git_repo_with_commit
        (repo / "auth.py").write_text("def login(): pass\n")
        (repo / "fixture.py").write_text("FIXTURE = True\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)

        files = staged_files(repo, ignore_paths=["fixture.py"])
        paths = [f.path for f in files]
        assert Path("fixture.py") not in paths
        assert Path("auth.py") in paths

    def test_multiple_files_returned(self, tmp_git_repo_with_commit):
        repo = tmp_git_repo_with_commit
        (repo / "a.py").write_text("x = 1\n")
        (repo / "b.go").write_text("package main\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)

        files = staged_files(repo)
        langs = {f.language for f in files}
        assert "python" in langs
        assert "go" in langs


class TestRestage:
    def test_restage_calls_git_add(self, mocker):
        mock_run = mocker.patch("codereview.git._run")
        restage(Path("src/auth.py"))
        mock_run.assert_called_once_with(["git", "add", "src/auth.py"], cwd=None)

    def test_restage_passes_cwd(self, tmp_path, mocker):
        mock_run = mocker.patch("codereview.git._run")
        restage(Path("src/auth.py"), cwd=tmp_path)
        mock_run.assert_called_once_with(["git", "add", "src/auth.py"], cwd=tmp_path)

    def test_restage_uses_posix_path(self, mocker):
        mock_run = mocker.patch("codereview.git._run")
        restage(Path("src/sub/file.py"))
        args = mock_run.call_args[0][0]
        assert "/" in args[2]
        assert "\\" not in args[2]
