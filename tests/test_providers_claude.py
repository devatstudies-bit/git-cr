"""Tests for the Claude AI provider."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from codereview.models import Issue, Severity, FixResult
from codereview.providers.claude import (
    ClaudeProvider,
    _parse_issues,
    _safe_json,
    _build_review_prompt,
    _build_fix_prompt,
)
from codereview.config import Config


# ── _safe_json ─────────────────────────────────────────────────────────────

class TestSafeJson:
    def test_plain_json_array(self):
        result = _safe_json('[{"a": 1}]')
        assert result == [{"a": 1}]

    def test_plain_json_object(self):
        result = _safe_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_markdown_fenced_json(self):
        text = '```json\n[{"file": "a.py"}]\n```'
        result = _safe_json(text)
        assert result == [{"file": "a.py"}]

    def test_markdown_fence_no_lang(self):
        text = '```\n[{"file": "a.py"}]\n```'
        result = _safe_json(text)
        assert result == [{"file": "a.py"}]

    def test_json_embedded_in_prose(self):
        text = 'Here are the issues:\n[{"file": "a.py", "line": 1}]\nThat is all.'
        result = _safe_json(text)
        assert isinstance(result, list)
        assert result[0]["file"] == "a.py"

    def test_completely_invalid_returns_none(self):
        result = _safe_json("No JSON here at all.")
        assert result is None

    def test_empty_array(self):
        assert _safe_json("[]") == []

    def test_nested_json(self):
        result = _safe_json('{"issues": [1, 2, 3]}')
        assert result == {"issues": [1, 2, 3]}


# ── _parse_issues ──────────────────────────────────────────────────────────

class TestParseIssues:
    def test_parses_valid_issue_list(self):
        raw = json.dumps([
            {"file": "auth.py", "line": 14, "severity": "error", "rule": "sql-injection", "message": "SQL injection"},
            {"file": "utils.py", "line": 31, "severity": "warning", "rule": "zero-div", "message": "Zero division"},
        ])
        issues = _parse_issues(raw)
        assert len(issues) == 2
        assert issues[0].file == Path("auth.py")
        assert issues[0].line == 14
        assert issues[0].severity == Severity.ERROR
        assert issues[0].rule == "sql-injection"
        assert issues[1].severity == Severity.WARNING

    def test_returns_empty_for_empty_array(self):
        assert _parse_issues("[]") == []

    def test_skips_item_with_missing_file(self):
        raw = json.dumps([
            {"line": 1, "severity": "error", "message": "missing file key"},
        ])
        issues = _parse_issues(raw)
        assert issues == []

    def test_skips_item_with_invalid_severity(self):
        raw = json.dumps([
            {"file": "a.py", "line": 1, "severity": "critical", "message": "bad severity"},
        ])
        issues = _parse_issues(raw)
        assert issues == []

    def test_line_coerced_to_int(self):
        raw = json.dumps([
            {"file": "a.py", "line": "42", "severity": "error", "message": "msg"},
        ])
        issues = _parse_issues(raw)
        assert issues[0].line == 42

    def test_rule_defaults_to_empty_string(self):
        raw = json.dumps([
            {"file": "a.py", "line": 1, "severity": "info", "message": "msg"},
        ])
        issues = _parse_issues(raw)
        assert issues[0].rule == ""

    def test_returns_empty_for_non_list_json(self):
        issues = _parse_issues('{"file": "a.py"}')
        assert issues == []

    def test_returns_empty_for_invalid_json(self):
        issues = _parse_issues("not json at all")
        assert issues == []


# ── _build_review_prompt ───────────────────────────────────────────────────

class TestBuildReviewPrompt:
    def test_contains_file_path(self, sample_staged_file):
        prompt = _build_review_prompt([sample_staged_file])
        assert "src/auth.py" in prompt

    def test_contains_language(self, sample_staged_file):
        prompt = _build_review_prompt([sample_staged_file])
        assert "python" in prompt

    def test_contains_diff(self, sample_staged_file):
        prompt = _build_review_prompt([sample_staged_file])
        assert sample_staged_file.diff in prompt

    def test_contains_content(self, sample_staged_file):
        prompt = _build_review_prompt([sample_staged_file])
        assert "cursor.execute" in prompt

    def test_multiple_files_separated(self, sample_staged_file):
        from codereview.models import StagedFile
        f2 = StagedFile(Path("utils.py"), "def helper(): pass\n", "+def helper(): pass\n", "python")
        prompt = _build_review_prompt([sample_staged_file, f2])
        assert "src/auth.py" in prompt
        assert "utils.py" in prompt
        assert "---" in prompt


# ── _build_fix_prompt ──────────────────────────────────────────────────────

class TestBuildFixPrompt:
    def test_contains_file_and_line(self, error_issue):
        prompt = _build_fix_prompt(error_issue, "file content here")
        assert "src/auth.py" in prompt
        assert "14" in prompt

    def test_contains_message(self, error_issue):
        prompt = _build_fix_prompt(error_issue, "file content here")
        assert error_issue.message in prompt

    def test_contains_file_content(self, error_issue):
        content = "def login(): pass\n"
        prompt = _build_fix_prompt(error_issue, content)
        assert content in prompt


# ── ClaudeProvider ─────────────────────────────────────────────────────────

def _make_provider(api_response_text):
    """Build a ClaudeProvider with a mocked Anthropic client."""
    cfg = Config()
    cfg.claude_api_key = "sk-ant-test"
    cfg.claude_model = "claude-sonnet-4-6"

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=api_response_text)]

    with patch("codereview.providers.claude.anthropic.Anthropic") as MockAnthropic:
        instance = MockAnthropic.return_value
        instance.messages.create.return_value = mock_message
        provider = ClaudeProvider(cfg)
        provider._client = instance

    return provider, instance


class TestClaudeProviderReview:
    def test_review_returns_issues(self, sample_staged_file):
        raw = json.dumps([
            {"file": "src/auth.py", "line": 14, "severity": "error", "rule": "sql-injection", "message": "SQL injection"}
        ])
        provider, mock_client = _make_provider(raw)
        mock_client.messages.create.return_value.content = [MagicMock(text=raw)]

        issues = provider.review([sample_staged_file])
        assert len(issues) == 1
        assert issues[0].severity == Severity.ERROR

    def test_review_calls_api_once(self, sample_staged_file):
        provider, mock_client = _make_provider("[]")
        mock_client.messages.create.return_value.content = [MagicMock(text="[]")]

        provider.review([sample_staged_file])
        assert mock_client.messages.create.call_count == 1

    def test_review_returns_empty_for_clean_code(self, sample_staged_file):
        provider, mock_client = _make_provider("[]")
        mock_client.messages.create.return_value.content = [MagicMock(text="[]")]

        issues = provider.review([sample_staged_file])
        assert issues == []

    def test_review_handles_malformed_response(self, sample_staged_file):
        provider, mock_client = _make_provider("not json")
        mock_client.messages.create.return_value.content = [MagicMock(text="not json")]

        issues = provider.review([sample_staged_file])
        assert issues == []


class TestClaudeProviderSuggestFix:
    def test_returns_suggestion_string(self, error_issue, tmp_path):
        error_issue.file = tmp_path / "auth.py"
        error_issue.file.write_text("cursor.execute('SELECT * FROM users WHERE id = ' + uid)\n")

        suggestion_response = json.dumps({
            "suggestion": "- cursor.execute('SELECT * ' + uid)\n+ cursor.execute('SELECT * ', (uid,))",
            "fixed_code": "cursor.execute('SELECT * FROM users WHERE id = %s', (uid,))\n"
        })
        provider, mock_client = _make_provider(suggestion_response)
        mock_client.messages.create.return_value.content = [MagicMock(text=suggestion_response)]

        result = provider.suggest_fix(error_issue)
        assert "cursor.execute" in result

    def test_returns_raw_text_when_not_json(self, error_issue, tmp_path):
        error_issue.file = tmp_path / "auth.py"
        error_issue.file.write_text("x = 1\n")

        provider, mock_client = _make_provider("Use parameterized queries instead.")
        mock_client.messages.create.return_value.content = [MagicMock(text="Use parameterized queries instead.")]

        result = provider.suggest_fix(error_issue)
        assert "parameterized" in result


class TestClaudeProviderApplyFix:
    def test_writes_fixed_code_to_file(self, error_issue, tmp_path):
        error_issue.file = Path("auth.py")
        original_path = tmp_path / "auth.py"
        original_path.write_text("cursor.execute('SELECT * ' + uid)\n")

        fixed_code = "cursor.execute('SELECT * FROM users WHERE id = %s', (uid,))\n"
        response = json.dumps({"suggestion": "- old\n+ new", "fixed_code": fixed_code})

        provider, mock_client = _make_provider(response)
        mock_client.messages.create.return_value.content = [MagicMock(text=response)]

        result = provider.apply_fix(error_issue, str(tmp_path))
        assert result.applied is True
        assert original_path.read_text() == fixed_code

    def test_returns_files_changed(self, error_issue, tmp_path):
        error_issue.file = Path("auth.py")
        (tmp_path / "auth.py").write_text("x = 1\n")

        response = json.dumps({"suggestion": "s", "fixed_code": "x = 2\n"})
        provider, mock_client = _make_provider(response)
        mock_client.messages.create.return_value.content = [MagicMock(text=response)]

        result = provider.apply_fix(error_issue, str(tmp_path))
        assert len(result.files_changed) == 1

    def test_returns_failure_when_response_unparseable(self, error_issue, tmp_path):
        error_issue.file = Path("auth.py")
        (tmp_path / "auth.py").write_text("x = 1\n")

        provider, mock_client = _make_provider("Sorry, I cannot fix this.")
        mock_client.messages.create.return_value.content = [MagicMock(text="Sorry, I cannot fix this.")]

        result = provider.apply_fix(error_issue, str(tmp_path))
        assert result.applied is False
        assert result.error != ""

    def test_stores_suggestion_on_issue(self, error_issue, tmp_path):
        error_issue.file = Path("auth.py")
        (tmp_path / "auth.py").write_text("x = 1\n")

        response = json.dumps({"suggestion": "the diff here", "fixed_code": "x = 2\n"})
        provider, mock_client = _make_provider(response)
        mock_client.messages.create.return_value.content = [MagicMock(text=response)]

        provider.apply_fix(error_issue, str(tmp_path))
        assert error_issue.suggestion == "the diff here"
