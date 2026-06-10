"""Tests for the CLI commands: install, uninstall, review, config."""
import subprocess
import stat
import platform
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from click.testing import CliRunner

from codereview.cli import main, HOOK_MARKER
from codereview.config import Config


@pytest.fixture
def runner():
    return CliRunner()


# ── cr --version ───────────────────────────────────────────────────────────

class TestVersion:
    def test_version_output(self, runner):
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output


# ── cr install ─────────────────────────────────────────────────────────────

class TestInstall:
    def test_creates_hook_file(self, tmp_git_repo, runner):
        result = runner.invoke(main, ["install"], catch_exceptions=False,
                               env={"HOME": str(tmp_git_repo)})
        # Run from within repo context
        import os
        original = os.getcwd()
        os.chdir(tmp_git_repo)
        try:
            result = runner.invoke(main, ["install"], catch_exceptions=False)
            hook = tmp_git_repo / ".git" / "hooks" / "pre-commit"
            assert hook.exists()
            assert HOOK_MARKER in hook.read_text()
            assert "cr review --staged" in hook.read_text()
        finally:
            os.chdir(original)

    def test_hook_is_executable_on_unix(self, tmp_git_repo, runner):
        if platform.system() == "Windows":
            pytest.skip("chmod not applicable on Windows")
        import os
        os.chdir(tmp_git_repo)
        try:
            runner.invoke(main, ["install"], catch_exceptions=False)
            hook = tmp_git_repo / ".git" / "hooks" / "pre-commit"
            mode = hook.stat().st_mode
            assert mode & stat.S_IEXEC
        finally:
            import os as _os
            _os.chdir(Path(__file__).parent.parent)

    def test_fails_outside_git_repo(self, tmp_path, runner):
        import os
        original = os.getcwd()
        os.chdir(tmp_path)
        try:
            result = runner.invoke(main, ["install"])
            assert result.exit_code != 0
            assert "Not inside a git repository" in result.output
        finally:
            os.chdir(original)

    def test_appends_to_existing_hook(self, tmp_git_repo, runner):
        import os
        hook_path = tmp_git_repo / ".git" / "hooks" / "pre-commit"
        hook_path.write_text("#!/usr/bin/env bash\nexisting_tool\n")
        hook_path.chmod(0o755)

        os.chdir(tmp_git_repo)
        try:
            result = runner.invoke(main, ["install"], input="y\n")
            content = hook_path.read_text()
            assert "existing_tool" in content
            assert HOOK_MARKER in content
        finally:
            os.chdir(Path(__file__).parent.parent)

    def test_aborts_append_when_user_says_no(self, tmp_git_repo, runner):
        import os
        hook_path = tmp_git_repo / ".git" / "hooks" / "pre-commit"
        hook_path.write_text("#!/usr/bin/env bash\nexisting_tool\n")
        hook_path.chmod(0o755)

        os.chdir(tmp_git_repo)
        try:
            runner.invoke(main, ["install"], input="n\n")
            content = hook_path.read_text()
            assert HOOK_MARKER not in content
        finally:
            os.chdir(Path(__file__).parent.parent)


# ── cr uninstall ───────────────────────────────────────────────────────────

class TestUninstall:
    def test_removes_hook_we_installed(self, tmp_git_repo, runner):
        import os
        hook_path = tmp_git_repo / ".git" / "hooks" / "pre-commit"
        hook_path.write_text(
            f"#!/usr/bin/env bash\n{HOOK_MARKER}\nset -e\ncr review --staged\n"
        )

        os.chdir(tmp_git_repo)
        try:
            result = runner.invoke(main, ["uninstall"])
            assert not hook_path.exists()
            assert "removed" in result.output.lower()
        finally:
            os.chdir(Path(__file__).parent.parent)

    def test_removes_only_our_lines_from_shared_hook(self, tmp_git_repo, runner):
        import os
        hook_path = tmp_git_repo / ".git" / "hooks" / "pre-commit"
        hook_path.write_text(
            f"#!/usr/bin/env bash\nexisting_tool\n{HOOK_MARKER}\ncr review --staged\n"
        )

        os.chdir(tmp_git_repo)
        try:
            runner.invoke(main, ["uninstall"])
            content = hook_path.read_text()
            assert "existing_tool" in content
            assert HOOK_MARKER not in content
        finally:
            os.chdir(Path(__file__).parent.parent)

    def test_warns_when_hook_not_ours(self, tmp_git_repo, runner):
        import os
        hook_path = tmp_git_repo / ".git" / "hooks" / "pre-commit"
        hook_path.write_text("#!/usr/bin/env bash\nsome_other_tool\n")

        os.chdir(tmp_git_repo)
        try:
            result = runner.invoke(main, ["uninstall"])
            assert "not installed by CodeReviewer" in result.output
        finally:
            os.chdir(Path(__file__).parent.parent)

    def test_handles_no_hook_gracefully(self, tmp_git_repo, runner):
        import os
        os.chdir(tmp_git_repo)
        try:
            result = runner.invoke(main, ["uninstall"])
            assert result.exit_code == 0
            assert "No pre-commit hook" in result.output
        finally:
            os.chdir(Path(__file__).parent.parent)

    def test_fails_outside_git_repo(self, tmp_path, runner):
        import os
        os.chdir(tmp_path)
        try:
            result = runner.invoke(main, ["uninstall"])
            assert result.exit_code != 0
        finally:
            os.chdir(Path(__file__).parent.parent)


# ── cr review ──────────────────────────────────────────────────────────────

class TestReview:
    def _run_review(self, runner, tmp_git_repo, mock_provider_cls, issues=None, env=None):
        """Helper: stage a file and invoke cr review --staged with a mock provider."""
        import os
        (tmp_git_repo / "auth.py").write_text("def login(): pass\n")
        subprocess.run(["git", "add", "auth.py"], cwd=tmp_git_repo, capture_output=True)

        default_env = {
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "HOME": str(tmp_git_repo),
        }
        if env:
            default_env.update(env)

        os.chdir(tmp_git_repo)
        try:
            with patch("codereview.cli._load_provider", return_value=mock_provider_cls):
                result = runner.invoke(main, ["review", "--staged"], env=default_env)
            return result
        finally:
            os.chdir(Path(__file__).parent.parent)

    def test_exits_0_when_no_staged_files(self, tmp_git_repo_with_commit, runner):
        import os
        os.chdir(tmp_git_repo_with_commit)
        try:
            with patch("codereview.cli._load_provider", return_value=MagicMock()):
                result = runner.invoke(main, ["review", "--staged"],
                                       env={"ANTHROPIC_API_KEY": "sk-test"})
            assert result.exit_code == 0
            assert "No reviewable files" in result.output
        finally:
            os.chdir(Path(__file__).parent.parent)

    def test_exits_0_when_no_issues_found(self, tmp_git_repo_with_commit, runner):
        import os
        (tmp_git_repo_with_commit / "clean.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "clean.py"], cwd=tmp_git_repo_with_commit, capture_output=True)

        mock_ai = MagicMock()
        mock_ai.review.return_value = []

        os.chdir(tmp_git_repo_with_commit)
        try:
            with patch("codereview.cli._load_provider", return_value=mock_ai):
                result = runner.invoke(main, ["review", "--staged"],
                                       env={"ANTHROPIC_API_KEY": "sk-test"})
            assert result.exit_code == 0
        finally:
            os.chdir(Path(__file__).parent.parent)

    def test_exits_1_when_unfixed_errors_remain(self, tmp_git_repo_with_commit, runner, error_issue):
        import os
        (tmp_git_repo_with_commit / "bad.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "bad.py"], cwd=tmp_git_repo_with_commit, capture_output=True)

        mock_ai = MagicMock()
        mock_ai.review.return_value = [error_issue]

        os.chdir(tmp_git_repo_with_commit)
        try:
            with patch("codereview.cli._load_provider", return_value=mock_ai), \
                 patch("codereview.fixer.run_fix_session"):
                result = runner.invoke(main, ["review", "--staged"],
                                       env={"ANTHROPIC_API_KEY": "sk-test"})
            assert result.exit_code == 1
        finally:
            os.chdir(Path(__file__).parent.parent)

    def test_exits_0_when_errors_are_fixed(self, tmp_git_repo_with_commit, runner, error_issue):
        import os
        (tmp_git_repo_with_commit / "bad.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "bad.py"], cwd=tmp_git_repo_with_commit, capture_output=True)

        mock_ai = MagicMock()
        mock_ai.review.return_value = [error_issue]

        def mark_fixed(issues, config, ai, root):
            for i in issues:
                i._fixed = True

        os.chdir(tmp_git_repo_with_commit)
        try:
            with patch("codereview.cli._load_provider", return_value=mock_ai), \
                 patch("codereview.fixer.run_fix_session", side_effect=mark_fixed):
                result = runner.invoke(main, ["review", "--staged"],
                                       env={"ANTHROPIC_API_KEY": "sk-test"})
            assert result.exit_code == 0
        finally:
            os.chdir(Path(__file__).parent.parent)

    def test_missing_api_key_exits_with_error(self, tmp_git_repo_with_commit, runner):
        import os
        (tmp_git_repo_with_commit / "a.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "a.py"], cwd=tmp_git_repo_with_commit, capture_output=True)

        os.chdir(tmp_git_repo_with_commit)
        try:
            result = runner.invoke(main, ["review", "--staged"],
                                   env={"ANTHROPIC_API_KEY": ""})
            assert result.exit_code != 0
            assert "ANTHROPIC_API_KEY" in result.output
        finally:
            os.chdir(Path(__file__).parent.parent)


# ── cr config ──────────────────────────────────────────────────────────────

class TestConfig:
    def test_show_prints_table(self, tmp_path, runner, monkeypatch):
        monkeypatch.setattr("codereview.config.GLOBAL_CONFIG_PATH", tmp_path / "config.toml")
        import codereview.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "GLOBAL_CONFIG_PATH", tmp_path / "config.toml")

        result = runner.invoke(main, ["config", "--show"])
        assert result.exit_code == 0
        assert "ai.provider" in result.output
        assert "claude" in result.output

    def test_set_provider(self, tmp_path, runner, monkeypatch):
        import os
        monkeypatch.setattr("codereview.config.GLOBAL_CONFIG_PATH", tmp_path / "config.toml")
        import codereview.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "GLOBAL_CONFIG_PATH", tmp_path / "config.toml")

        result = runner.invoke(main, ["config", "ai.provider=copilot"])
        assert result.exit_code == 0
        assert "copilot" in result.output

        loaded = cfg_mod.load()
        assert loaded.provider == "copilot"

    def test_set_show_preview_false(self, tmp_path, runner, monkeypatch):
        import codereview.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "GLOBAL_CONFIG_PATH", tmp_path / "config.toml")

        runner.invoke(main, ["config", "fix.show_preview=false"])
        loaded = cfg_mod.load()
        assert loaded.show_preview is False

    def test_set_granularity(self, tmp_path, runner, monkeypatch):
        import codereview.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "GLOBAL_CONFIG_PATH", tmp_path / "config.toml")

        runner.invoke(main, ["config", "fix.granularity=all"])
        loaded = cfg_mod.load()
        assert loaded.granularity == "all"

    def test_set_block_on_multiple(self, tmp_path, runner, monkeypatch):
        import codereview.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "GLOBAL_CONFIG_PATH", tmp_path / "config.toml")

        runner.invoke(main, ["config", "review.block_on=error,security"])
        loaded = cfg_mod.load()
        assert "error" in loaded.block_on
        assert "security" in loaded.block_on

    def test_unknown_key_shows_error(self, tmp_path, runner, monkeypatch):
        import codereview.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "GLOBAL_CONFIG_PATH", tmp_path / "config.toml")

        result = runner.invoke(main, ["config", "nonexistent.key=value"])
        assert "Unknown config key" in result.output

    def test_invalid_format_shows_error(self, tmp_path, runner, monkeypatch):
        import codereview.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "GLOBAL_CONFIG_PATH", tmp_path / "config.toml")

        result = runner.invoke(main, ["config", "ai.provider"])
        assert "KEY=VALUE" in result.output

    def test_project_flag_writes_to_project(self, tmp_git_repo, runner, monkeypatch):
        import os
        import codereview.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "GLOBAL_CONFIG_PATH", tmp_git_repo / "global.toml")

        os.chdir(tmp_git_repo)
        try:
            runner.invoke(main, ["config", "ai.provider=copilot", "--project"])
            project_cfg = tmp_git_repo / ".cr.toml"
            assert project_cfg.exists()
            import toml
            data = toml.load(project_cfg)
            assert data["ai"]["provider"] == "copilot"
        finally:
            os.chdir(Path(__file__).parent.parent)
