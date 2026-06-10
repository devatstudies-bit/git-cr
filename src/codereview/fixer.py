from __future__ import annotations
from pathlib import Path

from rich.prompt import Prompt, Confirm
from rich.console import Console

from .models import Issue, Severity
from .reporter import (
    console,
    print_issue,
    print_suggestion,
    print_fixed,
    print_skipped,
    print_could_not_fix,
    print_all_suggestions,
)
from . import git


def run_fix_session(issues: list[Issue], config, ai, repo_root: str) -> None:
    if not issues:
        return

    errors   = [i for i in issues if i.severity.value in config.block_on]
    warnings = [i for i in issues if i.severity.value not in config.block_on]

    # Warnings only → no fix session needed, just list them
    if not errors:
        console.print("\n  [yellow]Warnings (not blocking commit):[/]")
        for i, issue in enumerate(warnings, 1):
            print_issue(issue, i, len(warnings))
        console.print()
        return

    console.print()

    # ── Step 1: granularity ─────────────────────────────────────────────
    granularity = config.granularity
    if granularity is None:
        console.print("  [bold]How do you want to fix?[/]")
        console.print("    [bold cyan][1][/]  Fix one by one")
        console.print("    [bold cyan][2][/]  Fix all at once")
        choice = _prompt_choice("  Choose", ["1", "2"], default="1")
        granularity = "one_by_one" if choice == "1" else "all"

    # ── Step 2: preview preference ──────────────────────────────────────
    show_preview = config.show_preview
    if show_preview is None:
        show_preview = Confirm.ask("  Show fix suggestions before applying?", default=True)

    console.print()

    if granularity == "one_by_one":
        _fix_one_by_one(errors, ai, repo_root, show_preview)
    else:
        _fix_all(errors, ai, repo_root, show_preview)

    # Always list warnings at the end (non-blocking)
    if warnings:
        console.print("  [yellow]Warnings (not blocking):[/]")
        for i, issue in enumerate(warnings, 1):
            print_issue(issue, i, len(warnings))
        console.print()


# ── one-by-one flow ────────────────────────────────────────────────────────

def _fix_one_by_one(issues: list[Issue], ai, repo_root: str, show_preview: bool) -> None:
    total = len(issues)
    for idx, issue in enumerate(issues, 1):
        print_issue(issue, idx, total)

        if show_preview:
            options  = ["v", "a", "s", "q"]
            hint     = "[[bold cyan]V[/]]iew suggestion  [[bold cyan]A[/]]pply fix  [[bold cyan]S[/]]kip  [[bold cyan]Q[/]]uit"
        else:
            options  = ["a", "s", "q"]
            hint     = "[[bold cyan]A[/]]pply fix  [[bold cyan]S[/]]kip  [[bold cyan]Q[/]]uit"

        while True:
            console.print(f"\n  {hint}")
            key = _prompt_choice("  >", options)

            if key == "v":
                console.print("  [dim]Fetching suggestion…[/]")
                suggestion = ai.suggest_fix(issue)
                issue.suggestion = suggestion
                print_suggestion(suggestion)
                # After viewing, offer A/S/Q
                console.print(f"\n  [[bold cyan]A[/]]pply this fix  [[bold cyan]S[/]]kip  [[bold cyan]Q[/]]uit")
                key = _prompt_choice("  >", ["a", "s", "q"])

            if key == "a":
                console.print("  [dim]Applying fix…[/]")
                result = ai.apply_fix(issue, repo_root)
                if result.applied:
                    for f in result.files_changed:
                        git.restage(f, cwd=Path(repo_root))
                    print_fixed(str(issue.file))
                    issue._fixed = True  # type: ignore[attr-defined]
                else:
                    print_could_not_fix(str(issue.file), result.error)
                break

            elif key == "s":
                print_skipped(str(issue.file))
                break

            elif key == "q":
                console.print("  [dim]Aborting fix session. Commit will be blocked.[/]")
                return


# ── fix-all flow ───────────────────────────────────────────────────────────

def _fix_all(issues: list[Issue], ai, repo_root: str, show_preview: bool) -> None:
    if show_preview:
        console.print("  [dim]Fetching suggestions for all issues…[/]")
        for issue in issues:
            issue.suggestion = ai.suggest_fix(issue)
        print_all_suggestions(issues)
        console.print()

        console.print("  [[bold cyan]A[/]]pply all  [[bold cyan]P[/]]ick which to apply  [[bold cyan]Q[/]]uit")
        key = _prompt_choice("  >", ["a", "p", "q"])

        if key == "q":
            console.print("  [dim]Aborting. Commit will be blocked.[/]")
            return

        if key == "p":
            issues = _pick_subset(issues)
            if not issues:
                return
    else:
        console.print(f"  [dim]Fixing {len(issues)} issue{'s' if len(issues) != 1 else ''} automatically…[/]\n")

    _apply_batch(issues, ai, repo_root)


def _apply_batch(issues: list[Issue], ai, repo_root: str) -> None:
    for issue in issues:
        console.print(f"  [dim]Fixing {issue.file}:{issue.line}…[/]")
        result = ai.apply_fix(issue, repo_root)
        if result.applied:
            for f in result.files_changed:
                git.restage(f, cwd=Path(repo_root))
            print_fixed(str(issue.file))
            issue._fixed = True  # type: ignore[attr-defined]
        else:
            print_could_not_fix(str(issue.file), result.error)
    console.print()


def _pick_subset(issues: list[Issue]) -> list[Issue]:
    selected: list[Issue] = []
    for i, issue in enumerate(issues, 1):
        answer = Confirm.ask(f"  Apply fix {i} ({issue.file}:{issue.line})?", default=True)
        if answer:
            selected.append(issue)
    return selected


# ── input helper ──────────────────────────────────────────────────────────

def _prompt_choice(prompt: str, valid: list[str], default: str | None = None) -> str:
    while True:
        raw = Prompt.ask(prompt, default=default or "").strip().lower()
        if raw in valid:
            return raw
        console.print(f"  [dim]Please enter one of: {', '.join(v.upper() for v in valid)}[/]")
