# CodeReviewer

AI-powered code reviewer that runs automatically on every `git commit`. It analyses your staged files, reports real issues with file and line references, and offers to fix them — interactively or all at once — before the commit lands.

Backed by **Claude** (Anthropic) or **GitHub Copilot CLI** as swappable AI providers. One config line to switch between them.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
  - [1. Install the Python Package](#1-install-the-python-package)
  - [2. Set Your API Key](#2-set-your-api-key)
  - [3. Hook It Into a Git Repo](#3-hook-it-into-a-git-repo)
- [Quick Start](#quick-start)
- [Supported Languages](#supported-languages)
- [What Issues It Identifies](#what-issues-it-identifies)
- [What It Fixes](#what-it-fixes)
- [Interactive Fix Session](#interactive-fix-session)
  - [Fix One by One](#fix-one-by-one)
  - [Fix All at Once](#fix-all-at-once)
  - [Preview Suggestions](#preview-suggestions)
- [CLI Reference](#cli-reference)
  - [cr install](#cr-install)
  - [cr uninstall](#cr-uninstall)
  - [cr review](#cr-review)
  - [cr config](#cr-config)
- [Configuration Reference](#configuration-reference)
  - [Global vs Project Config](#global-vs-project-config)
  - [All Config Keys](#all-config-keys)
  - [Example .cr.toml](#example-crtoml)
- [AI Providers](#ai-providers)
  - [Claude (Anthropic)](#claude-anthropic)
  - [GitHub Copilot CLI](#github-copilot-cli)
  - [Switching Providers](#switching-providers)
- [Review Scope](#review-scope)
- [Adopting as a Team Standard](#adopting-as-a-team-standard)
- [Troubleshooting](#troubleshooting)

---

## How It Works

```
git commit
    │
    └── pre-commit hook (installed by cr install)
            │
            └── cr review --staged
                    │
                    ├── Collect staged files  (git diff --cached)
                    ├── Send diff + full file content to AI provider
                    ├── Receive structured issue list
                    │       (file · line · severity · rule · message)
                    │
                    ├── [No issues]  → commit proceeds
                    │
                    └── [Issues found]
                            │
                            ├── Warnings only  → listed, commit proceeds
                            │
                            └── Errors found   → interactive fix session
                                    │
                                    ├── Fix one by one  (V/A/S/Q per issue)
                                    ├── Fix all at once (with optional preview)
                                    │
                                    ├── Fixed files are auto re-staged
                                    │
                                    ├── All errors fixed  → commit proceeds
                                    └── Errors remain     → commit blocked
```

The review sees both **the diff** (what changed) and the **full file content** (context around the change), so it catches not just bugs you introduced but pre-existing issues in any file you touched.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | Check: `python3 --version` |
| Git | 2.x+ | Must be inside a git repo to install the hook |
| **Claude provider** | — | `ANTHROPIC_API_KEY` environment variable |
| **Copilot provider** | — | Node.js 22+, `npm install -g @github/copilot`, `COPILOT_GITHUB_TOKEN` or `GITHUB_TOKEN` |

You only need one provider. Install the one you want to use.

---

## Installation

### 1. Install the Python Package

**From source (this repo):**
```bash
git clone https://github.com/your-org/code-reviewer.git
cd code-reviewer
pip install -e .
```

**Verify:**
```bash
cr --version
# cr, version 0.1.0
```

### 2. Set Your API Key

**For Claude:**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
# Add to ~/.zshrc or ~/.bashrc to persist it
```

**For GitHub Copilot CLI:**
```bash
# Install the Copilot CLI first
npm install -g @github/copilot

# Authenticate
export COPILOT_GITHUB_TOKEN=ghp_...
# or
export GITHUB_TOKEN=ghp_...
```

### 3. Hook It Into a Git Repo

Navigate to any git repository and run:

```bash
cd your-project
cr install
```

Output:
```
✔  Pre-commit hook installed at /your-project/.git/hooks/pre-commit
   CodeReviewer will now run automatically on git commit.
```

That's it. Every `git commit` in that repo now triggers a code review.

---

## Quick Start

```bash
# 1. Install package
pip install -e .

# 2. Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# 3. Install hook in your project
cd my-project
cr install

# 4. Make changes and commit as normal
git add src/auth.py
git commit -m "add user login"

# CodeReviewer runs automatically:
#
# CodeReviewer reviewing 1 file via claude...
#
# ╭─ 2 issues found (1 error · 1 warning) ─╮
# │                                          │
# ╰──────────────────────────────────────────╯
#
#   Issue 1/2  ✖ ERROR  src/auth.py:14
#   SQL injection via string concatenation in query
#
#   How do you want to fix?
#     [1]  Fix one by one
#     [2]  Fix all at once
#
#   Show fix suggestions before applying? [Y/n]:
```

---

## Supported Languages

CodeReviewer identifies the language from the file extension and passes it to the AI for language-aware analysis. The following languages are fully supported:

| Language | Extensions |
|---|---|
| Python | `.py` |
| JavaScript | `.js`, `.jsx` |
| TypeScript | `.ts`, `.tsx` |
| Go | `.go` |
| Java | `.java` |
| Ruby | `.rb` |
| Rust | `.rs` |
| C# | `.cs` |
| C++ | `.cpp` |
| C | `.c` |
| PHP | `.php` |
| Swift | `.swift` |
| Kotlin | `.kt` |
| Bash / Shell | `.sh` |
| YAML | `.yml`, `.yaml` |
| JSON | `.json` |
| HTML | `.html` |
| CSS | `.css` |

Files with unrecognised extensions are still reviewed as plain text — the AI uses content heuristics to analyse them.

---

## What Issues It Identifies

The AI focuses on **real, actionable bugs** — not style preferences or formatting. Issues are classified into three severities:

### Errors (block commit by default)

These are defects that are likely to cause incorrect behaviour or security vulnerabilities at runtime.

| Category | Examples |
|---|---|
| **SQL Injection** | String concatenation in SQL queries; unparameterised user input passed to `execute()` |
| **Null / None Dereference** | Accessing attributes or calling methods on a value that could be `None`/`null` without a prior check |
| **Index Out of Bounds** | Array or list access without length check; off-by-one in loops |
| **Unhandled Exceptions** | Calling code that raises without a try/except; swallowing exceptions silently (`except: pass`) |
| **Credential Exposure** | Hardcoded passwords, API keys, tokens, or secrets committed in source files |
| **Command Injection** | Passing unsanitised user input to `subprocess`, `os.system`, `exec`, `eval` |
| **Path Traversal** | Using user-supplied paths without normalisation or sandboxing |
| **Type Errors** | Passing the wrong type where a specific type is required; implicit type coercion bugs |
| **Division by Zero** | Missing zero-check before division operations |
| **Resource Leaks** | Files, database connections, or network sockets opened but never closed |
| **Race Conditions** | Shared state accessed from multiple threads without synchronisation |
| **Infinite Loops** | Loop conditions that can never become false given reachable inputs |
| **Logic Errors** | Off-by-one, inverted conditionals, unreachable branches |

### Warnings (noted but do not block commit)

Real issues worth fixing, but less likely to cause immediate failure.

| Category | Examples |
|---|---|
| **Missing Error Handling** | Network or I/O calls with no error handling |
| **Deprecated APIs** | Use of functions marked deprecated in the language/framework |
| **Memory Inefficiency** | Loading entire files into memory when streaming is possible |
| **Unnecessary Complexity** | Code that achieves the same result in a significantly simpler way |
| **Dead Code** | Variables assigned but never read; imports never used |
| **Magic Numbers** | Unexplained literal numbers that should be named constants |
| **Fragile String Parsing** | Manual string parsing instead of a dedicated parser |

### Info

Notes about patterns that are not bugs but worth awareness — never block a commit.

---

## What It Fixes

When you choose to apply a fix, the AI:

1. Reads the **full current content** of the affected file
2. Generates a corrected version of the entire file with the issue resolved
3. **Writes the fixed file back to disk**
4. **Re-stages it automatically** (`git add`) so the fixed version is what gets committed

Fixes are applied at the **file level** — the AI rewrites the entire file rather than applying a text patch, which avoids merge conflict issues with large diffs.

### Fix quality by issue type

| Issue Type | Fix reliability |
|---|---|
| SQL injection (add parameterisation) | High |
| Null checks | High |
| Missing try/except | High |
| Removing hardcoded secrets (replace with env var) | High |
| Division by zero (add guard) | High |
| Resource leaks (add context manager / close) | High |
| Logic errors / complex control flow | Medium — always review before accepting |
| Race conditions | Medium — requires understanding of full concurrency model |
| Architecture-level issues | Low — AI suggests but manual review is recommended |

> **Always review applied fixes before pushing.** The AI is accurate for well-defined patterns but may misunderstand complex business logic. Use `git diff --cached` after a fix to inspect what changed.

---

## Interactive Fix Session

When errors are found, CodeReviewer starts an interactive session before deciding whether to allow the commit. Two top-level choices control the session:

### Fix One by One

Each error is presented individually with four options:

```
  Issue 2/3  ✖ ERROR  src/auth.py:14
  SQL injection via string concatenation in cursor.execute()

  [V]iew suggestion  [A]pply fix  [S]kip  [Q]uit
  >
```

| Key | Action |
|---|---|
| `V` | Fetch and display the suggested fix as a diff/snippet before deciding |
| `A` | Apply the fix directly, re-stage the file, move to next issue |
| `S` | Skip this issue (it remains unfixed; if it's an error, commit is still blocked at the end) |
| `Q` | Abort the entire fix session (commit will be blocked) |

After pressing `V` to view the suggestion:

```
  ── Suggested fix ─────────────────────────────────
  - cursor.execute("SELECT * FROM users WHERE id = '" + user_id + "'")
  + cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
  ──────────────────────────────────────────────────

  [A]pply this fix  [S]kip  [Q]uit
  >
```

### Fix All at Once

All errors are processed together. With preview on, suggestions for every issue are fetched and displayed before you decide:

```
  ┌─ 1  ERROR  src/auth.py:14 ──────────────────────────────
  │  -  cursor.execute("SELECT * FROM users WHERE id = '" + user_id + "'")
  │  +  cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
  ├─ 2  ERROR  src/utils.py:31 ────────────────────────────
  │  -  return data['key']
  │  +  return data.get('key')
  └──────────────────────────────────────────────────────────

  [A]pply all  [P]ick which to apply  [Q]uit
  >
```

`P` (pick) lets you go through each fix individually and confirm or skip it, while still benefiting from having seen all suggestions upfront.

### Preview Suggestions

The preview preference is asked once per session (or can be permanently configured):

- **Preview ON** — the `[V]iew suggestion` option appears; or in fix-all mode, all suggestions are shown before applying
- **Preview OFF** — the `[V]` key is removed; fixes apply immediately when you press `A`

Set permanently:
```bash
cr config fix.show_preview=false   # never show previews, fix directly
cr config fix.show_preview=true    # always show previews (default)
```

---

## CLI Reference

### cr install

```
cr install [--global]
```

Installs a pre-commit git hook in the current repository's `.git/hooks/pre-commit`. After installation, every `git commit` automatically runs `cr review --staged`.

If a pre-commit hook already exists (from another tool), CodeReviewer appends itself to it rather than overwriting — it asks for confirmation first.

```bash
cr install                  # install in current git repo
cr install --global         # install to ~/.cr/ (global config only, no hook)
```

---

### cr uninstall

```
cr uninstall
```

Removes the CodeReviewer hook. If the hook was entirely installed by CodeReviewer, the file is deleted. If CodeReviewer was appended to an existing hook, only the CodeReviewer lines are removed and the rest of the hook is preserved.

---

### cr review

```
cr review [--staged] [--provider claude|copilot]
```

Runs a code review. Called automatically by the pre-commit hook but can be run manually at any time.

| Flag | Description |
|---|---|
| `--staged` | Review only staged files. Used internally by the pre-commit hook. |
| `--provider` | Override the configured AI provider for this run only. |

```bash
cr review --staged                    # review staged files (hook usage)
cr review --staged --provider copilot # use Copilot for this run only
cr review                             # review all staged files manually
```

---

### cr config

```
cr config [KEY=VALUE] [--project] [--show]
```

Get or set configuration values. Settings are stored in `~/.cr/config.toml` (global) or `.cr.toml` in the project root (project-level). Project settings override global ones.

```bash
cr config --show                          # print current effective config
cr config ai.provider=copilot             # switch to Copilot globally
cr config ai.provider=claude --project    # use Claude for this project only
cr config fix.show_preview=false          # skip preview prompts globally
cr config fix.granularity=all             # always use fix-all mode
cr config review.block_on=error,security  # block on errors and security issues
cr config review.ignore_paths=tests/,docs/
cr config claude.model=claude-opus-4-8    # use a different Claude model
```

---

## Configuration Reference

### Global vs Project Config

| File | Location | Scope |
|---|---|---|
| Global | `~/.cr/config.toml` | All repos on this machine |
| Project | `<repo-root>/.cr.toml` | This repo only; overrides global |

Commit `.cr.toml` to your repository so the whole team shares the same settings.

### All Config Keys

| Key | Type | Default | Description |
|---|---|---|---|
| `ai.provider` | string | `claude` | AI provider: `claude` or `copilot` |
| `claude.model` | string | `claude-sonnet-4-6` | Claude model ID |
| `review.block_on` | list | `["error"]` | Severity levels that block the commit |
| `review.ignore_paths` | list | `[]` | Path prefixes or glob patterns to skip |
| `fix.show_preview` | bool | *(ask)* | Whether to show fix suggestions before applying. Unset = ask each session |
| `fix.granularity` | string | *(ask)* | `one_by_one` or `all`. Unset = ask each session |

### Example .cr.toml

```toml
# Committed to repo root — shared with the whole team

[ai]
provider = "claude"

[claude]
model = "claude-sonnet-4-6"

[review]
block_on     = ["error", "security"]
ignore_paths = ["tests/fixtures/", "migrations/", "*.generated.ts"]

[fix]
show_preview = true
granularity  = "one_by_one"
```

---

## AI Providers

### Claude (Anthropic)

**How it works:**
- Uses the Anthropic Python SDK
- Review: one API call with the diff + full file content, returns a structured JSON issue list
- Fix: one API call per issue, returns the complete corrected file content
- Suggestion preview: one additional API call per issue to generate a human-readable diff

**Setup:**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
cr config ai.provider=claude
cr config claude.model=claude-sonnet-4-6   # default
```

**Available models:**

| Model ID | Speed | Quality | Best for |
|---|---|---|---|
| `claude-haiku-4-5-20251001` | Fastest | Good | Large codebases, quick checks |
| `claude-sonnet-4-6` | Fast | Excellent | **Default. Best balance** |
| `claude-opus-4-8` | Slower | Best | Complex logic, security audits |

---

### GitHub Copilot CLI

**How it works:**
- Uses the `copilot` CLI (`@github/copilot`) with the `-p` flag for non-interactive use
- `--output-format=json` returns a JSONL stream; CodeReviewer parses the assistant message events to extract the issue list and fix confirmations
- Fix: Copilot CLI edits the file directly as an agent; CodeReviewer detects changed files and re-stages them

**Setup:**
```bash
# Install Node.js 22+ first, then:
npm install -g @github/copilot

export COPILOT_GITHUB_TOKEN=ghp_...   # GitHub token with Copilot access
# or
export GITHUB_TOKEN=ghp_...

cr config ai.provider=copilot
```

**Requirements:**
- GitHub Copilot Individual, Business, or Enterprise subscription
- Node.js 22 or later
- `copilot` binary on your `PATH`

---

### Switching Providers

Switch globally:
```bash
cr config ai.provider=copilot
```

Switch for one project:
```bash
cr config ai.provider=claude --project
```

Override for a single run:
```bash
cr review --staged --provider copilot
```

Both providers expose the same interface — switching requires no changes to your workflow or project config structure.

---

## Review Scope

| Scenario | Reviewed? |
|---|---|
| Lines you changed in this commit | Yes |
| Pre-existing code in files you touched | Yes — full file content is sent |
| Files you did not touch | No — only staged files |
| Cross-file issues (e.g. broken callers after a signature change) | No |
| Hardcoded secrets anywhere in staged files | Yes |
| Generated files (e.g. `*.generated.ts`) | Configurable — add to `review.ignore_paths` |

To skip specific paths:
```bash
cr config review.ignore_paths=tests/fixtures/,vendor/,*.pb.go
```

---

## Adopting as a Team Standard

### Step 1 — Add `.cr.toml` to your repo

```toml
# .cr.toml — committed to repo root
[ai]
provider = "claude"

[review]
block_on     = ["error"]
ignore_paths = ["tests/fixtures/"]

[fix]
show_preview = true
granularity  = "one_by_one"
```

### Step 2 — Each developer installs once

```bash
# Each developer runs this once after cloning:
pip install -e path/to/code-reviewer
export ANTHROPIC_API_KEY=sk-ant-...       # in ~/.zshrc or ~/.bashrc
cr install                                 # inside the project repo
```

### Step 3 — CI gate (optional)

Add a second review gate on pull requests to catch issues that slipped through:

```yaml
# .github/workflows/review.yml
name: Code Review
on: [pull_request]

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e .
      - run: git diff origin/main...HEAD --name-only | xargs git add
      - run: cr review --staged
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

---

## Platform Compatibility

| Platform | Status | Notes |
|---|---|---|
| macOS | Full support | All features work |
| Linux | Full support | All features work |
| Windows (Git for Windows) | Full support | Install [Git for Windows](https://git-scm.com/download/win) — provides Git Bash which runs the pre-commit hook |
| Windows (pure CMD/PowerShell, no Git Bash) | Hook won't run | The pre-commit hook uses a bash shebang. Without Git Bash, `git commit` silently skips the hook. `cr review --staged` still works manually. |

> **Recommended for Windows:** Install [Git for Windows](https://git-scm.com/download/win) (the standard Git installer). It includes Git Bash and hooks work automatically.

---

## Troubleshooting

### `ANTHROPIC_API_KEY is not set`
```bash
export ANTHROPIC_API_KEY=sk-ant-...
# Make it permanent:
echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.zshrc
source ~/.zshrc
```

### `Copilot CLI not found`
```bash
npm install -g @github/copilot
# Verify:
copilot --version
```

### `Not inside a git repository`
Run `cr install` from inside a directory that has been initialised with `git init` or cloned from a remote.

### Hook not running on commit
```bash
# Check the hook exists and is executable:
ls -la .git/hooks/pre-commit
cat .git/hooks/pre-commit

# Reinstall if needed:
cr uninstall && cr install
```

### Commit blocked after applying fixes
The fix may not have resolved all errors. Run `git diff --cached` to inspect what the AI changed. If the fix introduced new problems, `git checkout -- <file>` to revert, then fix manually.

### Skipping the review for one commit
```bash
git commit --no-verify -m "your message"
```
Use sparingly. `--no-verify` bypasses all pre-commit hooks, not just CodeReviewer.

### Review takes too long
Switch to a faster model:
```bash
cr config claude.model=claude-haiku-4-5-20251001
```
Or ignore large auto-generated files:
```bash
cr config review.ignore_paths=src/generated/,*.pb.go,*.lock
```

### Config not being read
```bash
cr config --show   # shows the effective merged config
```
Project `.cr.toml` overrides global `~/.cr/config.toml`. Make sure you're running `cr` from inside the repo root.
