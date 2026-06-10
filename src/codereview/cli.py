from __future__ import annotations
import sys
import stat
import shutil
import platform
from pathlib import Path

import click
from rich.console import Console

from . import __version__
from . import git, config as cfg_module
from .reporter import console, print_banner, print_commit_blocked, print_commit_allowed

HOOK_MARKER = "# Installed by CodeReviewer"


@click.group()
@click.version_option(__version__, prog_name="cr")
def main():
    """CodeReviewer — AI-powered code review on every commit."""


# ── cr install ─────────────────────────────────────────────────────────────

@main.command()
@click.option("--global", "global_", is_flag=True, help="Install to ~/.cr/ instead of the current repo.")
def install(global_: bool):
    """Install the pre-commit hook into the current git repo."""
    root = git.repo_root()
    if not root:
        console.print("[red]Not inside a git repository.[/]")
        sys.exit(1)

    hook_path = root / ".git" / "hooks" / "pre-commit"

    if hook_path.exists() and HOOK_MARKER not in hook_path.read_text():
        console.print(
            f"[yellow]⚠[/]  A pre-commit hook already exists at [cyan]{hook_path}[/]\n"
            "     Append CodeReviewer to it? [Y/n] ",
            end="",
        )
        answer = input().strip().lower()
        if answer not in ("", "y", "yes"):
            console.print("[dim]Aborted.[/]")
            return
        with hook_path.open("a") as f:
            f.write(f"\n{HOOK_MARKER}\ncr review --staged\n")
    else:
        template = Path(__file__).parent.parent.parent / "templates" / "pre-commit"
        if not template.exists():
            # fallback: write inline
            hook_path.write_text(f"#!/usr/bin/env bash\n{HOOK_MARKER}\nset -e\ncr review --staged\n")
        else:
            shutil.copy(template, hook_path)

    if platform.system() != "Windows":
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    console.print(f"[green]✔[/]  Pre-commit hook installed at [cyan]{hook_path}[/]")
    console.print("     CodeReviewer will now run automatically on [bold]git commit[/].")


# ── cr uninstall ───────────────────────────────────────────────────────────

@main.command()
def uninstall():
    """Remove the CodeReviewer pre-commit hook."""
    root = git.repo_root()
    if not root:
        console.print("[red]Not inside a git repository.[/]")
        sys.exit(1)

    hook_path = root / ".git" / "hooks" / "pre-commit"
    if not hook_path.exists():
        console.print("[dim]No pre-commit hook found.[/]")
        return

    content = hook_path.read_text()
    if HOOK_MARKER not in content:
        console.print("[yellow]⚠[/]  Hook was not installed by CodeReviewer. Not touching it.")
        return

    # If we own the whole file, delete it outright
    lines = content.splitlines()
    non_shebang = [l for l in lines if l.strip() and not l.startswith("#!")]
    cr_lines = [l for l in non_shebang if HOOK_MARKER in l or l.strip().startswith("cr review") or l.strip() == "set -e"]
    if len(cr_lines) == len(non_shebang):
        hook_path.unlink()
        console.print(f"[green]✔[/]  Pre-commit hook removed: [cyan]{hook_path}[/]")
        return

    # Partial removal — we were appended to an existing hook
    cleaned: list[str] = []
    skip_next = False
    for line in content.splitlines(keepends=True):
        if HOOK_MARKER in line:
            skip_next = True
            continue
        if skip_next and line.strip().startswith("cr review"):
            skip_next = False
            continue
        skip_next = False
        cleaned.append(line)

    hook_path.write_text("".join(cleaned))
    console.print(f"[green]✔[/]  CodeReviewer removed from existing hook at [cyan]{hook_path}[/]")


# ── cr review ──────────────────────────────────────────────────────────────

@main.command()
@click.option("--staged", is_flag=True, default=False, help="Review only staged files (used by pre-commit hook).")
@click.option("--provider", default=None, help="Override AI provider: claude or copilot.")
def review(staged: bool, provider: str | None):
    """Run a code review. Called automatically by the pre-commit hook."""
    root = git.repo_root()
    if not root:
        console.print("[red]Not inside a git repository.[/]")
        sys.exit(1)

    config = cfg_module.load(root)
    active_provider = provider or config.provider

    files = git.staged_files(root, config.ignore_paths) if staged else git.staged_files(root, config.ignore_paths)

    if not files:
        console.print("[dim]No reviewable files staged. Commit proceeding.[/]")
        sys.exit(0)

    ai = _load_provider(active_provider, config)
    if ai is None:
        sys.exit(1)

    console.print(f"\n[cyan]CodeReviewer[/] reviewing [bold]{len(files)}[/] file{'s' if len(files) != 1 else ''} via [bold]{active_provider}[/]...\n")

    issues = ai.review(files)

    errors   = [i for i in issues if i.severity.value in config.block_on]
    warnings = [i for i in issues if i.severity.value not in config.block_on]

    print_banner(len(issues), len(errors), len(warnings))

    if not issues:
        sys.exit(0)

    # Delegate to the interactive fixer (Phase 3+)
    from .fixer import run_fix_session
    run_fix_session(issues, config, ai, root)

    # Re-evaluate after fixes
    remaining_errors = [i for i in issues if i.severity.value in config.block_on and not getattr(i, "_fixed", False)]

    if remaining_errors:
        print_commit_blocked(remaining_errors)
        sys.exit(1)
    else:
        print_commit_allowed(len(warnings))
        sys.exit(0)


# ── helpers ────────────────────────────────────────────────────────────────

# ── cr config ─────────────────────────────────────────────────────────────

@main.command()
@click.argument("key_value", metavar="KEY=VALUE", required=False)
@click.option("--project", is_flag=True, help="Write to project .cr.toml instead of global ~/.cr/config.toml.")
@click.option("--show", is_flag=True, help="Print current effective config.")
def config(key_value: str | None, project: bool, show: bool):
    """Get or set CodeReviewer configuration.

    \b
    Examples:
      cr config --show
      cr config ai.provider=copilot
      cr config fix.show_preview=false --project
      cr config review.block_on=error,security
    """
    root = git.repo_root()
    current = cfg_module.load(root)

    if show or key_value is None:
        _print_config(current)
        return

    if "=" not in key_value:
        console.print(f"[red]Invalid format. Use KEY=VALUE, e.g. ai.provider=copilot[/]")
        return

    dot_key, value = key_value.split("=", 1)
    dot_key = dot_key.strip()
    value = value.strip()

    # Map dot-notation to Config field names
    KEY_MAP = {
        "ai.provider":          "provider",
        "claude.model":         "claude_model",
        "fix.show_preview":     "show_preview",
        "fix.granularity":      "granularity",
        "review.block_on":      "block_on",
        "review.ignore_paths":  "ignore_paths",
    }
    key = KEY_MAP.get(dot_key)
    if not key:
        console.print(f"[red]Unknown config key: {dot_key}[/]")
        console.print("  Valid keys: " + ", ".join(KEY_MAP.keys()))
        return

    # Type coercion
    existing = getattr(current, key)
    if isinstance(existing, bool) or key in ("show_preview",):
        coerced = value.lower() in ("true", "yes", "1")
    elif isinstance(existing, list) or "," in value:
        coerced = [v.strip() for v in value.split(",")]
    else:
        coerced = value

    setattr(current, key, coerced)

    if project and root:
        cfg_module.save_project(current, root)
        console.print(f"[green]✔[/]  Saved [bold]{key_value}[/] to [cyan]{root / '.cr.toml'}[/]")
    else:
        cfg_module.save_global(current)
        console.print(f"[green]✔[/]  Saved [bold]{key_value}[/] to [cyan]{cfg_module.GLOBAL_CONFIG_PATH}[/]")


def _print_config(cfg) -> None:
    from rich.table import Table
    from rich import box as rbox
    table = Table(box=rbox.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    rows = [
        ("ai.provider",        cfg.provider),
        ("claude.model",       cfg.claude_model),
        ("review.block_on",    ", ".join(cfg.block_on)),
        ("review.ignore_paths",", ".join(cfg.ignore_paths) or "(none)"),
        ("fix.show_preview",   str(cfg.show_preview) if cfg.show_preview is not None else "(ask each session)"),
        ("fix.granularity",    cfg.granularity or "(ask each session)"),
    ]
    for k, v in rows:
        table.add_row(k, v)
    console.print(table)


# ── helpers ────────────────────────────────────────────────────────────────

def _load_provider(name: str, config):
    if name == "claude":
        if not config.claude_api_key:
            console.print("[red]ANTHROPIC_API_KEY is not set. Run: export ANTHROPIC_API_KEY=your_key[/]")
            return None
        from .providers.claude import ClaudeProvider
        return ClaudeProvider(config)

    if name == "copilot":
        if not shutil.which("copilot"):
            console.print("[red]Copilot CLI not found. Install with: npm install -g @github/copilot[/]")
            return None
        if not config.copilot_token:
            console.print("[red]COPILOT_GITHUB_TOKEN or GITHUB_TOKEN is not set.[/]")
            return None
        from .providers.copilot import CopilotProvider
        return CopilotProvider(config)

    console.print(f"[red]Unknown provider: {name}. Choose 'claude' or 'copilot'.[/]")
    return None
