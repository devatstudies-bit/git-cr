from __future__ import annotations
import json
from pathlib import Path

import anthropic

from .base import AIProvider
from ..models import Issue, FixResult, StagedFile, Severity

_REVIEW_SYSTEM = """You are an expert code reviewer. Analyze the provided staged files and diffs for real issues only.

Return ONLY a JSON array — no markdown, no explanation, no other text.
Each element must have exactly these fields:
  file     : string  — relative file path
  line     : integer — line number where the issue occurs
  severity : string  — one of: "error", "warning", "info"
  rule     : string  — short rule name, e.g. "null-check", "sql-injection"
  message  : string  — clear, actionable description of the issue

Focus on: bugs, security vulnerabilities, null/index errors, bad error handling, code smells.
Ignore: style preferences, formatting, naming conventions (unless truly harmful).
Return [] if there are no real issues."""

_FIX_SYSTEM = """You are an expert software engineer. You will be given a code issue and the current file content.
Return ONLY a JSON object with two fields:
  suggestion : string — a unified diff or clear code snippet showing the fix
  fixed_code : string — the COMPLETE updated file content with the fix applied

No markdown, no explanation, no other text."""


class ClaudeProvider(AIProvider):

    def __init__(self, config) -> None:
        self._client = anthropic.Anthropic(api_key=config.claude_api_key)
        self._model = config.claude_model

    # ── review ─────────────────────────────────────────────────────────────

    def review(self, files: list[StagedFile]) -> list[Issue]:
        user_content = _build_review_prompt(files)
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=_REVIEW_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = response.content[0].text.strip()
        return _parse_issues(raw)

    # ── suggest fix ────────────────────────────────────────────────────────

    def suggest_fix(self, issue: Issue) -> str:
        file_content = _read_file(issue.file)
        response = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=_FIX_SYSTEM,
            messages=[{"role": "user", "content": _build_fix_prompt(issue, file_content)}],
        )
        raw = response.content[0].text.strip()
        data = _safe_json(raw)
        return data.get("suggestion", raw) if data else raw

    # ── apply fix ──────────────────────────────────────────────────────────

    def apply_fix(self, issue: Issue, repo_root: str) -> FixResult:
        file_path = Path(repo_root) / issue.file
        file_content = file_path.read_text(encoding="utf-8") if file_path.exists() else ""

        response = self._client.messages.create(
            model=self._model,
            max_tokens=8192,
            system=_FIX_SYSTEM,
            messages=[{"role": "user", "content": _build_fix_prompt(issue, file_content)}],
        )
        raw = response.content[0].text.strip()
        data = _safe_json(raw)

        if not data or "fixed_code" not in data:
            return FixResult(issue=issue, applied=False, error="Could not parse fix from AI response.")

        file_path.write_text(data["fixed_code"], encoding="utf-8")
        issue.suggestion = data.get("suggestion", "")
        return FixResult(issue=issue, applied=True, files_changed=[file_path])


# ── helpers ────────────────────────────────────────────────────────────────

def _build_review_prompt(files: list[StagedFile]) -> str:
    parts = []
    for f in files:
        parts.append(
            f"### File: {f.path} (language: {f.language})\n\n"
            f"#### Diff:\n```\n{f.diff}\n```\n\n"
            f"#### Full content:\n```{f.language}\n{f.content}\n```"
        )
    return "\n\n---\n\n".join(parts)


def _build_fix_prompt(issue: Issue, file_content: str) -> str:
    return (
        f"File: {issue.file}\n"
        f"Line: {issue.line}\n"
        f"Severity: {issue.severity.value}\n"
        f"Issue: {issue.message}\n\n"
        f"Current file content:\n```\n{file_content}\n```"
    )


def _parse_issues(raw: str) -> list[Issue]:
    data = _safe_json(raw)
    if not isinstance(data, list):
        return []
    issues: list[Issue] = []
    for item in data:
        try:
            issues.append(Issue(
                file=Path(item["file"]),
                line=int(item.get("line", 0)),
                severity=Severity(item.get("severity", "warning")),
                rule=item.get("rule", ""),
                message=item.get("message", ""),
            ))
        except (KeyError, ValueError):
            continue
    return issues


def _safe_json(text: str) -> dict | list | None:
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find a JSON array or object within the text
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            start = text.find(start_char)
            end = text.rfind(end_char)
            if start != -1 and end != -1:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    continue
    return None


def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
