"""Tests for the GitHub Copilot CLI provider."""
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from codereview.models import Issue, Severity
from codereview.providers.copilot import (
    CopilotProvider,
    _extract_text_from_jsonl,
    _extract_fix_confirmation,
    _detect_changed_files,
    _parse_issues,
    _safe_json,
)
from codereview.config import Config


# ── _extract_text_from_jsonl ───────────────────────────────────────────────

class TestExtractTextFromJsonl:
    def test_extracts_assistant_message(self):
        jsonl = json.dumps({"type": "assistant", "content": "Hello world"})
        assert _extract_text_from_jsonl(jsonl) == "Hello world"

    def test_extracts_message_type(self):
        jsonl = json.dumps({"type": "message", "content": "review result"})
        assert _extract_text_from_jsonl(jsonl) == "review result"

    def test_extracts_text_delta(self):
        lines = [
            json.dumps({"type": "text_delta", "delta": "Hello "}),
            json.dumps({"type": "text_delta", "delta": "world"}),
        ]
        result = _extract_text_from_jsonl("\n".join(lines))
        assert result == "Hello world"

    def test_extracts_result_type(self):
        jsonl = json.dumps({"type": "result", "result": "final output"})
        assert _extract_text_from_jsonl(jsonl) == "final output"

    def test_extracts_final_type(self):
        jsonl = json.dumps({"type": "final", "text": "done"})
        assert _extract_text_from_jsonl(jsonl) == "done"

    def test_ignores_non_text_events(self):
        lines = [
            json.dumps({"type": "tool_use", "name": "read_file"}),
            json.dumps({"type": "assistant", "content": "actual text"}),
        ]
        result = _extract_text_from_jsonl("\n".join(lines))
        assert result == "actual text"

    def test_returns_empty_for_empty_input(self):
        assert _extract_text_from_jsonl("") == ""

    def test_skips_invalid_json_lines(self):
        lines = [
            "not json",
            json.dumps({"type": "assistant", "content": "valid"}),
        ]
        result = _extract_text_from_jsonl("\n".join(lines))
        assert result == "valid"

    def test_extracts_content_list_text_blocks(self):
        jsonl = json.dumps({
            "type": "assistant",
            "content": [
                {"type": "text", "text": "part one "},
                {"type": "text", "text": "part two"},
            ]
        })
        result = _extract_text_from_jsonl(jsonl)
        assert result == "part one part two"

    def test_multiple_assistant_messages_concatenated(self):
        lines = [
            json.dumps({"type": "assistant", "content": "first "}),
            json.dumps({"type": "assistant", "content": "second"}),
        ]
        result = _extract_text_from_jsonl("\n".join(lines))
        assert result == "first second"


# ── _extract_fix_confirmation ──────────────────────────────────────────────

class TestExtractFixConfirmation:
    def test_true_from_json_fixed_true(self):
        assert _extract_fix_confirmation('{"fixed": true, "summary": "added null check"}') is True

    def test_false_from_json_fixed_false(self):
        assert _extract_fix_confirmation('{"fixed": false}') is False

    def test_true_from_natural_language_fix_applied(self):
        assert _extract_fix_confirmation("The fix applied successfully.") is True

    def test_true_from_natural_language_fixed_the(self):
        assert _extract_fix_confirmation("I've fixed the null pointer issue.") is True

    def test_true_from_natural_language_has_been_fixed(self):
        assert _extract_fix_confirmation("The bug has been fixed.") is True

    def test_false_for_empty_string(self):
        assert _extract_fix_confirmation("") is False

    def test_false_for_unrelated_text(self):
        assert _extract_fix_confirmation("Unable to determine the root cause.") is False

    def test_json_embedded_in_text(self):
        text = 'I applied the changes.\n{"fixed": true, "summary": "done"}\nAll done.'
        assert _extract_fix_confirmation(text) is True


# ── _detect_changed_files ──────────────────────────────────────────────────

class TestDetectChangedFiles:
    def test_returns_expected_file_when_in_git_diff(self, tmp_git_repo_with_commit, mocker):
        mock_result = MagicMock()
        mock_result.stdout = "src/auth.py\n"
        mocker.patch("subprocess.run", return_value=mock_result)

        changed = _detect_changed_files(str(tmp_git_repo_with_commit), ["src/auth.py"])
        assert Path("src/auth.py") in changed

    def test_returns_expected_file_even_if_git_fails(self, mocker):
        mocker.patch("subprocess.run", side_effect=Exception("git error"))
        changed = _detect_changed_files("/some/path", ["src/auth.py"])
        assert Path("src/auth.py") in changed

    def test_filters_to_only_changed_files(self, mocker):
        mock_result = MagicMock()
        mock_result.stdout = "src/auth.py\n"
        mocker.patch("subprocess.run", return_value=mock_result)

        changed = _detect_changed_files("/path", ["src/auth.py", "src/utils.py"])
        paths = [str(p) for p in changed]
        assert "src/auth.py" in paths
        assert "src/utils.py" not in paths


# ── CopilotProvider ────────────────────────────────────────────────────────

def _make_copilot_provider(stdout_output="[]"):
    cfg = Config()
    cfg.copilot_token = "ghp_test"
    provider = CopilotProvider(cfg)
    return provider


class TestCopilotProviderReview:
    def test_review_parses_jsonl_response(self, sample_staged_file, mocker):
        issues_json = json.dumps([
            {"file": "src/auth.py", "line": 14, "severity": "error", "rule": "sql-injection", "message": "SQL injection"}
        ])
        jsonl_output = json.dumps({"type": "assistant", "content": issues_json})

        mocker.patch("subprocess.run", return_value=MagicMock(
            stdout=jsonl_output, stderr="", returncode=0
        ))

        provider = _make_copilot_provider()
        issues = provider.review([sample_staged_file])
        assert len(issues) == 1
        assert issues[0].severity == Severity.ERROR

    def test_review_returns_empty_for_no_issues(self, sample_staged_file, mocker):
        jsonl_output = json.dumps({"type": "assistant", "content": "[]"})
        mocker.patch("subprocess.run", return_value=MagicMock(
            stdout=jsonl_output, stderr="", returncode=0
        ))

        provider = _make_copilot_provider()
        issues = provider.review([sample_staged_file])
        assert issues == []

    def test_review_passes_output_format_flag(self, sample_staged_file, mocker):
        mock_run = mocker.patch("subprocess.run", return_value=MagicMock(
            stdout=json.dumps({"type": "assistant", "content": "[]"}),
            stderr="", returncode=0
        ))

        provider = _make_copilot_provider()
        provider.review([sample_staged_file])

        cmd = mock_run.call_args[0][0]
        assert "--output-format=json" in cmd

    def test_review_uses_copilot_binary(self, sample_staged_file, mocker):
        mock_run = mocker.patch("subprocess.run", return_value=MagicMock(
            stdout=json.dumps({"type": "assistant", "content": "[]"}),
            stderr="", returncode=0
        ))

        provider = _make_copilot_provider()
        provider.review([sample_staged_file])

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "copilot"

    def test_review_handles_malformed_jsonl(self, sample_staged_file, mocker):
        mocker.patch("subprocess.run", return_value=MagicMock(
            stdout="not jsonl at all", stderr="", returncode=0
        ))

        provider = _make_copilot_provider()
        issues = provider.review([sample_staged_file])
        assert issues == []


class TestCopilotProviderSuggestFix:
    def test_returns_stripped_text(self, error_issue, mocker):
        jsonl_output = json.dumps({"type": "assistant", "content": "  Use parameterized queries.  "})
        mocker.patch("subprocess.run", return_value=MagicMock(
            stdout=jsonl_output, stderr="", returncode=0
        ))

        provider = _make_copilot_provider()
        result = provider.suggest_fix(error_issue)
        assert result == "Use parameterized queries."

    def test_returns_empty_on_timeout(self, error_issue, mocker):
        mocker.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("copilot", 120))

        provider = _make_copilot_provider()
        result = provider.suggest_fix(error_issue)
        assert result == ""


class TestCopilotProviderApplyFix:
    def test_returns_success_on_confirmation(self, error_issue, mocker):
        confirmation = '{"fixed": true, "summary": "added null check"}'
        jsonl_output = json.dumps({"type": "assistant", "content": confirmation})

        mock_run = mocker.patch("subprocess.run", return_value=MagicMock(
            stdout=jsonl_output, stderr="", returncode=0
        ))
        mocker.patch(
            "codereview.providers.copilot._detect_changed_files",
            return_value=[error_issue.file]
        )

        provider = _make_copilot_provider()
        result = provider.apply_fix(error_issue, "/repo")
        assert result.applied is True

    def test_returns_failure_without_confirmation(self, error_issue, mocker):
        jsonl_output = json.dumps({"type": "assistant", "content": "I looked at the code."})
        mocker.patch("subprocess.run", return_value=MagicMock(
            stdout=jsonl_output, stderr="", returncode=0
        ))

        provider = _make_copilot_provider()
        result = provider.apply_fix(error_issue, "/repo")
        assert result.applied is False
        assert result.error != ""

    def test_passes_allow_tool_flags(self, error_issue, mocker):
        mock_run = mocker.patch("subprocess.run", return_value=MagicMock(
            stdout=json.dumps({"type": "assistant", "content": '{"fixed": true}'}),
            stderr="", returncode=0
        ))
        mocker.patch(
            "codereview.providers.copilot._detect_changed_files",
            return_value=[error_issue.file]
        )

        provider = _make_copilot_provider()
        provider.apply_fix(error_issue, "/repo")

        cmd = mock_run.call_args[0][0]
        assert any("--allow-tool" in arg for arg in cmd)
