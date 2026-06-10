"""Tests for data models."""
from pathlib import Path
import pytest

from codereview.models import Issue, StagedFile, FixResult, Severity


class TestSeverity:
    def test_values(self):
        assert Severity.ERROR.value == "error"
        assert Severity.WARNING.value == "warning"
        assert Severity.INFO.value == "info"

    def test_from_string(self):
        assert Severity("error") == Severity.ERROR
        assert Severity("warning") == Severity.WARNING
        assert Severity("info") == Severity.INFO

    def test_invalid_value(self):
        with pytest.raises(ValueError):
            Severity("critical")

    def test_is_string_subclass(self):
        assert isinstance(Severity.ERROR, str)


class TestIssue:
    def test_basic_creation(self):
        issue = Issue(
            file=Path("src/auth.py"),
            line=14,
            severity=Severity.ERROR,
            rule="sql-injection",
            message="SQL injection vulnerability",
        )
        assert issue.file == Path("src/auth.py")
        assert issue.line == 14
        assert issue.severity == Severity.ERROR
        assert issue.rule == "sql-injection"
        assert issue.message == "SQL injection vulnerability"

    def test_suggestion_defaults_empty(self):
        issue = Issue(Path("a.py"), 1, Severity.WARNING, "rule", "msg")
        assert issue.suggestion == ""

    def test_rule_defaults_empty(self):
        issue = Issue(file=Path("a.py"), line=1, severity=Severity.INFO, message="msg")
        assert issue.rule == ""

    def test_severity_comparison(self):
        e = Issue(Path("a.py"), 1, Severity.ERROR, message="e")
        w = Issue(Path("a.py"), 2, Severity.WARNING, message="w")
        assert e.severity != w.severity
        assert e.severity.value == "error"


class TestStagedFile:
    def test_creation(self):
        f = StagedFile(
            path=Path("src/main.py"),
            content="def foo(): pass\n",
            diff="+def foo(): pass\n",
            language="python",
        )
        assert f.path == Path("src/main.py")
        assert f.language == "python"
        assert "foo" in f.content
        assert f.diff.startswith("+")

    def test_unknown_language(self):
        f = StagedFile(Path("config.xyz"), "data", "diff", "text")
        assert f.language == "text"


class TestFixResult:
    def test_success(self):
        issue = Issue(Path("a.py"), 1, Severity.ERROR, message="msg")
        result = FixResult(issue=issue, applied=True, files_changed=[Path("a.py")])
        assert result.applied is True
        assert len(result.files_changed) == 1
        assert result.error == ""

    def test_failure(self):
        issue = Issue(Path("a.py"), 1, Severity.ERROR, message="msg")
        result = FixResult(issue=issue, applied=False, error="Could not parse")
        assert result.applied is False
        assert result.files_changed == []
        assert result.error == "Could not parse"

    def test_files_changed_defaults_empty(self):
        issue = Issue(Path("a.py"), 1, Severity.ERROR, message="msg")
        result = FixResult(issue=issue, applied=True)
        assert result.files_changed == []
