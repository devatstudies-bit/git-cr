"""Shared fixtures for all test modules."""
import subprocess
from pathlib import Path
import pytest

from codereview.models import Issue, StagedFile, FixResult, Severity
from codereview.config import Config


# ── git repo fixture ────────────────────────────────────────────────────────

@pytest.fixture
def tmp_git_repo(tmp_path):
    """Create a temporary git repository with a default user configured."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
    return tmp_path


@pytest.fixture
def tmp_git_repo_with_commit(tmp_git_repo):
    """Git repo with one existing commit (needed for some git operations)."""
    (tmp_git_repo / "README.md").write_text("# Test repo\n")
    subprocess.run(["git", "add", "."], cwd=tmp_git_repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_git_repo, capture_output=True)
    return tmp_git_repo


# ── model fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def error_issue():
    return Issue(
        file=Path("src/auth.py"),
        line=14,
        severity=Severity.ERROR,
        rule="sql-injection",
        message="SQL injection via string concatenation",
    )


@pytest.fixture
def warning_issue():
    return Issue(
        file=Path("src/utils.py"),
        line=31,
        severity=Severity.WARNING,
        rule="zero-division",
        message="Missing zero check before division",
    )


@pytest.fixture
def info_issue():
    return Issue(
        file=Path("src/models.py"),
        line=5,
        severity=Severity.INFO,
        rule="magic-number",
        message="Magic number 42 should be a named constant",
    )


@pytest.fixture
def sample_issues(error_issue, warning_issue, info_issue):
    return [error_issue, warning_issue, info_issue]


@pytest.fixture
def sample_staged_file():
    return StagedFile(
        path=Path("src/auth.py"),
        content='def get_user(uid):\n    cursor.execute("SELECT * FROM users WHERE id = \'" + uid + "\'")\n    return cursor.fetchone()\n',
        diff='@@ -1,3 +1,3 @@\n def get_user(uid):\n-    pass\n+    cursor.execute("SELECT * FROM users WHERE id = \'" + uid + "\'")\n',
        language="python",
    )


# ── config fixture ──────────────────────────────────────────────────────────

@pytest.fixture
def default_config():
    return Config()


@pytest.fixture
def claude_config():
    cfg = Config()
    cfg.provider = "claude"
    cfg.claude_api_key = "sk-ant-test"
    cfg.block_on = ["error"]
    cfg.show_preview = True
    cfg.granularity = "one_by_one"
    return cfg


@pytest.fixture
def copilot_config():
    cfg = Config()
    cfg.provider = "copilot"
    cfg.copilot_token = "ghp_test"
    cfg.block_on = ["error"]
    cfg.show_preview = False
    cfg.granularity = "all"
    return cfg


# ── mock AI provider ────────────────────────────────────────────────────────

class MockAIProvider:
    """Controllable mock that satisfies the AIProvider interface."""

    def __init__(self, issues=None, suggestion="- old\n+ new", apply_success=True):
        self._issues = issues or []
        self._suggestion = suggestion
        self._apply_success = apply_success
        self.review_called = False
        self.suggest_fix_calls = []
        self.apply_fix_calls = []

    def review(self, files):
        self.review_called = True
        return self._issues

    def suggest_fix(self, issue):
        self.suggest_fix_calls.append(issue)
        return self._suggestion

    def apply_fix(self, issue, repo_root):
        self.apply_fix_calls.append((issue, repo_root))
        if self._apply_success:
            return FixResult(issue=issue, applied=True, files_changed=[issue.file])
        return FixResult(issue=issue, applied=False, error="Mock failure")


@pytest.fixture
def mock_ai(error_issue):
    return MockAIProvider(issues=[error_issue])


@pytest.fixture
def mock_ai_no_issues():
    return MockAIProvider(issues=[])


@pytest.fixture
def mock_ai_fail():
    return MockAIProvider(apply_success=False)
