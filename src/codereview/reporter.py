from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from .models import Issue, Severity

console = Console()

SEVERITY_COLOR = {
    Severity.ERROR:   "bold red",
    Severity.WARNING: "bold yellow",
    Severity.INFO:    "bold blue",
}

SEVERITY_ICON = {
    Severity.ERROR:   "✖",
    Severity.WARNING: "⚠",
    Severity.INFO:    "ℹ",
}


def print_banner(n_issues: int, n_errors: int, n_warnings: int) -> None:
    if n_issues == 0:
        console.print(Panel("[bold green]✔  No issues found. Commit proceeding.[/]", box=box.ROUNDED))
        return

    summary = (
        f"[bold]{n_issues} issue{'s' if n_issues != 1 else ''} found[/]  "
        f"([red]{n_errors} error{'s' if n_errors != 1 else ''}[/] · "
        f"[yellow]{n_warnings} warning{'s' if n_warnings != 1 else ''}[/])"
    )
    console.print(Panel(summary, title="[bold cyan]CodeReviewer[/]", box=box.ROUNDED))


def print_issue(issue: Issue, index: int, total: int) -> None:
    color = SEVERITY_COLOR[issue.severity]
    icon = SEVERITY_ICON[issue.severity]
    console.print(
        f"\n  Issue [dim]{index}/{total}[/]  [{color}]{icon} {issue.severity.value.upper()}[/]  "
        f"[cyan]{issue.file}[/][dim]:{issue.line}[/]"
    )
    console.print(f"  {issue.message}")


def print_suggestion(suggestion: str) -> None:
    console.print(Panel(
        suggestion,
        title="[bold]Suggested fix[/]",
        border_style="dim green",
        box=box.ROUNDED,
    ))


def print_fixed(path: str) -> None:
    console.print(f"  [green]✔[/]  Fixed + re-staged: [cyan]{path}[/]")


def print_skipped(path: str) -> None:
    console.print(f"  [dim]–[/]  Skipped: [dim]{path}[/]")


def print_could_not_fix(path: str, reason: str = "") -> None:
    msg = f"  [yellow]⚠[/]  Could not fix: [cyan]{path}[/]"
    if reason:
        msg += f" — [dim]{reason}[/]"
    console.print(msg)


def print_all_suggestions(issues: list[Issue]) -> None:
    for i, issue in enumerate(issues, 1):
        color = SEVERITY_COLOR[issue.severity]
        icon = SEVERITY_ICON[issue.severity]
        header = (
            f"[{color}]{icon} {i}[/]  [bold]{issue.severity.value.upper()}[/]  "
            f"[cyan]{issue.file}[/][dim]:{issue.line}[/]\n"
            f"[dim]{issue.message}[/]"
        )
        body = issue.suggestion or "[dim italic]No suggestion available.[/]"
        console.print(Panel(f"{header}\n\n{body}", box=box.ROUNDED, border_style="dim"))


def print_commit_blocked(errors: list[Issue]) -> None:
    console.print(
        Panel(
            f"[bold red]✖  Commit blocked.[/] Fix {len(errors)} error{'s' if len(errors) != 1 else ''} above to proceed.",
            box=box.ROUNDED,
            border_style="red",
        )
    )


def print_commit_allowed(warnings: int) -> None:
    msg = "[bold green]✔  Commit proceeding.[/]"
    if warnings:
        msg += f" [dim]({warnings} warning{'s' if warnings != 1 else ''} noted)[/]"
    console.print(Panel(msg, box=box.ROUNDED))
