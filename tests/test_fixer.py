"""Tests for the interactive fix session."""
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from codereview.models import Issue, Severity, FixResult
from codereview.fixer import run_fix_session, _fix_one_by_one, _fix_all, _apply_batch, _pick_subset
from codereview.config import Config


def _cfg(granularity="one_by_one", show_preview=False, block_on=None):
    cfg = Config()
    cfg.granularity = granularity
    cfg.show_preview = show_preview
    cfg.block_on = block_on or ["error"]
    return cfg


# ── run_fix_session entry point ────────────────────────────────────────────

class TestRunFixSession:
    def test_returns_immediately_with_no_issues(self, mock_ai_no_issues, tmp_path):
        run_fix_session([], _cfg(), mock_ai_no_issues, str(tmp_path))
        assert not mock_ai_no_issues.review_called

    def test_warnings_only_does_not_start_fix_loop(self, warning_issue, mock_ai_no_issues, tmp_path):
        cfg = _cfg(block_on=["error"])
        mock_ai_no_issues._issues = [warning_issue]
        # Should print warnings but not call apply_fix
        run_fix_session([warning_issue], cfg, mock_ai_no_issues, str(tmp_path))
        assert len(mock_ai_no_issues.apply_fix_calls) == 0

    def test_routes_to_one_by_one(self, error_issue, tmp_path, mocker):
        mocker.patch("codereview.fixer._fix_one_by_one")
        from codereview import fixer
        mock_fn = mocker.patch.object(fixer, "_fix_one_by_one")

        run_fix_session([error_issue], _cfg(granularity="one_by_one"), MagicMock(), str(tmp_path))
        mock_fn.assert_called_once()

    def test_routes_to_fix_all(self, error_issue, tmp_path, mocker):
        from codereview import fixer
        mock_fn = mocker.patch.object(fixer, "_fix_all")

        run_fix_session([error_issue], _cfg(granularity="all"), MagicMock(), str(tmp_path))
        mock_fn.assert_called_once()

    def test_warnings_listed_after_error_fix(self, error_issue, warning_issue, mock_ai, tmp_path, mocker):
        mock_ai._issues = [error_issue, warning_issue]
        mocker.patch("codereview.fixer._fix_one_by_one")

        run_fix_session([error_issue, warning_issue], _cfg(), mock_ai, str(tmp_path))
        # no exception = warnings handled


# ── _fix_one_by_one ────────────────────────────────────────────────────────

class TestFixOneByOne:
    def test_apply_fix_marks_issue_fixed(self, error_issue, mock_ai, tmp_path, mocker):
        mocker.patch("codereview.fixer._prompt_choice", return_value="a")
        mocker.patch("codereview.fixer.git.restage")

        _fix_one_by_one([error_issue], mock_ai, str(tmp_path), show_preview=False)
        assert getattr(error_issue, "_fixed", False) is True

    def test_skip_does_not_fix(self, error_issue, mock_ai, tmp_path, mocker):
        mocker.patch("codereview.fixer._prompt_choice", return_value="s")

        _fix_one_by_one([error_issue], mock_ai, str(tmp_path), show_preview=False)
        assert len(mock_ai.apply_fix_calls) == 0
        assert not getattr(error_issue, "_fixed", False)

    def test_quit_aborts_remaining_issues(self, error_issue, warning_issue, mock_ai, tmp_path, mocker):
        mocker.patch("codereview.fixer._prompt_choice", return_value="q")

        issues = [error_issue, warning_issue]
        _fix_one_by_one(issues, mock_ai, str(tmp_path), show_preview=False)
        assert len(mock_ai.apply_fix_calls) == 0

    def test_view_then_apply(self, error_issue, mock_ai, tmp_path, mocker):
        # First call returns "v", second returns "a"
        mocker.patch("codereview.fixer._prompt_choice", side_effect=["v", "a"])
        mocker.patch("codereview.fixer.git.restage")

        _fix_one_by_one([error_issue], mock_ai, str(tmp_path), show_preview=True)
        assert len(mock_ai.suggest_fix_calls) == 1
        assert getattr(error_issue, "_fixed", False) is True

    def test_view_then_skip(self, error_issue, mock_ai, tmp_path, mocker):
        mocker.patch("codereview.fixer._prompt_choice", side_effect=["v", "s"])

        _fix_one_by_one([error_issue], mock_ai, str(tmp_path), show_preview=True)
        assert len(mock_ai.apply_fix_calls) == 0

    def test_failed_fix_not_marked_fixed(self, error_issue, mock_ai_fail, tmp_path, mocker):
        mocker.patch("codereview.fixer._prompt_choice", return_value="a")

        _fix_one_by_one([error_issue], mock_ai_fail, str(tmp_path), show_preview=False)
        assert not getattr(error_issue, "_fixed", False)

    def test_preview_off_hides_v_option(self, error_issue, mock_ai, tmp_path, mocker):
        calls = []
        def capture_choice(prompt, valid, default=None):
            calls.append(valid)
            return "s"
        mocker.patch("codereview.fixer._prompt_choice", side_effect=capture_choice)

        _fix_one_by_one([error_issue], mock_ai, str(tmp_path), show_preview=False)
        assert "v" not in calls[0]

    def test_preview_on_shows_v_option(self, error_issue, mock_ai, tmp_path, mocker):
        calls = []
        def capture_choice(prompt, valid, default=None):
            calls.append(valid)
            return "s"
        mocker.patch("codereview.fixer._prompt_choice", side_effect=capture_choice)

        _fix_one_by_one([error_issue], mock_ai, str(tmp_path), show_preview=True)
        assert "v" in calls[0]

    def test_restage_called_on_successful_fix(self, error_issue, mock_ai, tmp_path, mocker):
        mocker.patch("codereview.fixer._prompt_choice", return_value="a")
        mock_restage = mocker.patch("codereview.fixer.git.restage")

        _fix_one_by_one([error_issue], mock_ai, str(tmp_path), show_preview=False)
        mock_restage.assert_called_once()


# ── _fix_all ───────────────────────────────────────────────────────────────

class TestFixAll:
    def test_apply_all_no_preview(self, error_issue, mock_ai, tmp_path, mocker):
        mocker.patch("codereview.fixer.git.restage")

        _fix_all([error_issue], mock_ai, str(tmp_path), show_preview=False)
        assert len(mock_ai.apply_fix_calls) == 1

    def test_apply_all_with_preview_shows_suggestions(self, error_issue, mock_ai, tmp_path, mocker):
        mocker.patch("codereview.fixer._prompt_choice", return_value="a")
        mocker.patch("codereview.fixer.git.restage")

        _fix_all([error_issue], mock_ai, str(tmp_path), show_preview=True)
        assert len(mock_ai.suggest_fix_calls) == 1

    def test_quit_skips_all_fixes(self, error_issue, mock_ai, tmp_path, mocker):
        mocker.patch("codereview.fixer._prompt_choice", return_value="q")

        _fix_all([error_issue], mock_ai, str(tmp_path), show_preview=True)
        assert len(mock_ai.apply_fix_calls) == 0

    def test_pick_mode_calls_pick_subset(self, error_issue, mock_ai, tmp_path, mocker):
        mocker.patch("codereview.fixer._prompt_choice", return_value="p")
        mock_pick = mocker.patch("codereview.fixer._pick_subset", return_value=[])

        _fix_all([error_issue], mock_ai, str(tmp_path), show_preview=True)
        mock_pick.assert_called_once()

    def test_multiple_issues_all_fixed(self, error_issue, warning_issue, mock_ai, tmp_path, mocker):
        mock_ai._issues = [error_issue, warning_issue]
        mocker.patch("codereview.fixer.git.restage")

        issues = [error_issue, warning_issue]
        _fix_all(issues, mock_ai, str(tmp_path), show_preview=False)
        assert len(mock_ai.apply_fix_calls) == 2


# ── _apply_batch ───────────────────────────────────────────────────────────

class TestApplyBatch:
    def test_marks_issues_fixed(self, error_issue, warning_issue, mock_ai, tmp_path, mocker):
        mocker.patch("codereview.fixer.git.restage")

        issues = [error_issue, warning_issue]
        _apply_batch(issues, mock_ai, str(tmp_path))
        assert getattr(error_issue, "_fixed", False) is True
        assert getattr(warning_issue, "_fixed", False) is True

    def test_failed_fix_not_marked(self, error_issue, mock_ai_fail, tmp_path, mocker):
        _apply_batch([error_issue], mock_ai_fail, str(tmp_path))
        assert not getattr(error_issue, "_fixed", False)

    def test_calls_restage_for_each_fixed_file(self, error_issue, warning_issue, mock_ai, tmp_path, mocker):
        mock_restage = mocker.patch("codereview.fixer.git.restage")

        _apply_batch([error_issue, warning_issue], mock_ai, str(tmp_path))
        assert mock_restage.call_count == 2


# ── _pick_subset ───────────────────────────────────────────────────────────

class TestPickSubset:
    def test_returns_confirmed_issues(self, error_issue, warning_issue, mocker):
        mocker.patch("codereview.fixer.Confirm.ask", side_effect=[True, False])
        result = _pick_subset([error_issue, warning_issue])
        assert result == [error_issue]

    def test_returns_all_when_all_confirmed(self, error_issue, warning_issue, mocker):
        mocker.patch("codereview.fixer.Confirm.ask", return_value=True)
        result = _pick_subset([error_issue, warning_issue])
        assert len(result) == 2

    def test_returns_empty_when_none_confirmed(self, error_issue, mocker):
        mocker.patch("codereview.fixer.Confirm.ask", return_value=False)
        result = _pick_subset([error_issue])
        assert result == []
