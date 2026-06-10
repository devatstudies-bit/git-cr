from __future__ import annotations
import json
import os
import subprocess
from pathlib import Path

from .base import AIProvider
from ..models import Issue, FixResult, StagedFile, Severity

_REVIEW_PROMPT_TMPL = """Review the following staged code changes for real issues only.

Return ONLY a JSON array — no markdown, no explanation, no other text.
Each element must have exactly these fields:
  file     : string  — relative file path
  line     : integer — line number where the issue occurs
  severity : string  — one of: "error", "warning", "info"
  rule     : string  — short rule name, e.g. "null-check", "sql-injection"
  message  : string  — clear, actionable description of the issue

Focus on: bugs, security vulnerabilities, null/index errors, bad error handling.
Ignore: style, formatting, naming conventions.
Return [] if there are no real issues.

---

{file_sections}"""

_FIX_PROMPT_TMPL = """Fix the following code issue in {file}. Apply the fix directly to the file.

Issue (line {line}): {message}

After fixing, confirm with a one-line JSON: {{"fixed": true, "summary": "<what you changed>"}}"""

_SUGGEST_PROMPT_TMPL = """For the following code issue, show ONLY the fix as a unified diff or short code snippet.
No other text.

File: {file}, line {line}
Issue: {message}"""


class CopilotProvider(AIProvider):

    def __init__(self, config) -> None:
        self._token = config.copilot_token
        self._env = {**os.environ, "COPILOT_GITHUB_TOKEN": self._token}

    # ── review ─────────────────────────────────────────────────────────────

    def review(self, files: list[StagedFile]) -> list[Issue]:
        file_sections = _build_file_sections(files)
        prompt = _REVIEW_PROMPT_TMPL.format(file_sections=file_sections)
        raw = self._run(prompt)
        return _parse_issues(raw)

    # ── suggest fix ────────────────────────────────────────────────────────

    def suggest_fix(self, issue: Issue) -> str:
        prompt = _SUGGEST_PROMPT_TMPL.format(
            file=issue.file, line=issue.line, message=issue.message
        )
        return self._run(prompt).strip()

    # ── apply fix ──────────────────────────────────────────────────────────

    def apply_fix(self, issue: Issue, repo_root: str) -> FixResult:
        prompt = _FIX_PROMPT_TMPL.format(
            file=issue.file, line=issue.line, message=issue.message
        )
        raw = self._run(prompt, allow_tools=True, cwd=repo_root)

        # Check for confirmation JSON in output
        confirmed = _extract_fix_confirmation(raw)
        if confirmed:
            changed = _detect_changed_files(repo_root, [str(issue.file)])
            return FixResult(issue=issue, applied=True, files_changed=changed)

        return FixResult(issue=issue, applied=False, error="Copilot did not confirm fix was applied.")

    # ── subprocess runner ──────────────────────────────────────────────────

    def _run(self, prompt: str, allow_tools: bool = False, cwd: str | None = None) -> str:
        cmd = ["copilot", "-p", prompt, "--output-format=json"]
        if allow_tools:
            cmd += ["--allow-tool=shell", "--allow-tool=write_file", "--allow-tool=read_file"]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=self._env,
                cwd=cwd,
                timeout=120,
            )
            return _extract_text_from_jsonl(result.stdout) or result.stderr
        except subprocess.TimeoutExpired:
            return ""
        except FileNotFoundError:
            raise RuntimeError("Copilot CLI not found. Install with: npm install -g @github/copilot")


# ── JSONL output parser ────────────────────────────────────────────────────

def _extract_text_from_jsonl(jsonl: str) -> str:
    """Parse Copilot CLI JSONL stream and collect all assistant text content."""
    text_parts: list[str] = []
    for line in jsonl.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Event shapes vary by Copilot CLI version; handle both known forms
        event_type = event.get("type", "")

        if event_type == "assistant" or event_type == "message":
            content = event.get("content", "")
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))

        elif event_type == "text_delta":
            text_parts.append(event.get("delta", ""))

        elif event_type == "result" or event_type == "final":
            result = event.get("result", "") or event.get("text", "")
            if result:
                text_parts.append(result)

    return "".join(text_parts).strip()


def _extract_fix_confirmation(raw: str) -> bool:
    """Return True if Copilot confirmed the fix was applied."""
    if not raw:
        return False
    # Look for {"fixed": true, ...} confirmation
    for start in range(len(raw)):
        if raw[start] == "{":
            for end in range(len(raw), start, -1):
                try:
                    obj = json.loads(raw[start:end])
                    if obj.get("fixed") is True:
                        return True
                except json.JSONDecodeError:
                    continue
    # Fallback: check for natural language confirmation
    lower = raw.lower()
    return any(phrase in lower for phrase in ["fix applied", "fixed the", "i've fixed", "has been fixed"])


def _detect_changed_files(repo_root: str, expected: list[str]) -> list[Path]:
    """Return list of files that git sees as modified after a fix."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True, text=True, cwd=repo_root,
        )
        changed = {p.strip() for p in result.stdout.splitlines() if p.strip()}
        return [Path(p) for p in expected if p in changed]
    except Exception:
        return [Path(p) for p in expected]


# ── shared helpers ─────────────────────────────────────────────────────────

def _build_file_sections(files: list[StagedFile]) -> str:
    parts = []
    for f in files:
        parts.append(
            f"### File: {f.path} (language: {f.language})\n\n"
            f"#### Diff:\n```\n{f.diff}\n```\n\n"
            f"#### Full content:\n```{f.language}\n{f.content}\n```"
        )
    return "\n\n---\n\n".join(parts)


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
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            start = text.find(start_char)
            end = text.rfind(end_char)
            if start != -1 and end != -1:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    continue
    return None
