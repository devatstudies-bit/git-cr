from __future__ import annotations
import os
import toml
from dataclasses import dataclass, field
from pathlib import Path


GLOBAL_CONFIG_PATH = Path.home() / ".cr" / "config.toml"
PROJECT_CONFIG_NAME = ".cr.toml"


@dataclass
class Config:
    provider: str = "claude"

    # Claude settings
    claude_model: str = "claude-sonnet-4-6"
    claude_api_key: str = ""

    # Copilot settings
    copilot_token: str = ""

    # Review settings
    block_on: list[str] = field(default_factory=lambda: ["error"])
    ignore_paths: list[str] = field(default_factory=list)

    # Fix settings
    show_preview: bool | None = None   # None = ask each session
    granularity: str | None = None     # None = ask each session  ("one_by_one" | "all")


def load(repo_root: Path | None = None) -> Config:
    """Merge global config with project-level .cr.toml (project wins)."""
    merged: dict = {}

    if GLOBAL_CONFIG_PATH.exists():
        _deep_merge(merged, toml.load(GLOBAL_CONFIG_PATH))

    if repo_root:
        project_cfg = repo_root / PROJECT_CONFIG_NAME
        if project_cfg.exists():
            _deep_merge(merged, toml.load(project_cfg))

    return _dict_to_config(merged)


def save_global(cfg: Config) -> None:
    GLOBAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    GLOBAL_CONFIG_PATH.write_text(toml.dumps(_config_to_dict(cfg)))


def save_project(cfg: Config, repo_root: Path) -> None:
    (repo_root / PROJECT_CONFIG_NAME).write_text(toml.dumps(_config_to_dict(cfg)))


# ── helpers ────────────────────────────────────────────────────────────────

# Maps TOML section.key path to Config field name
_TOML_TO_FIELD: dict[str, str] = {
    ("ai",     "provider"):      "provider",
    ("claude", "model"):         "claude_model",
    ("copilot","token"):         "copilot_token",
    ("review", "block_on"):      "block_on",
    ("review", "ignore_paths"):  "ignore_paths",
    ("fix",    "show_preview"):  "show_preview",
    ("fix",    "granularity"):   "granularity",
}

def _deep_merge(base: dict, override: dict) -> None:
    """Merge override into base in-place, merging nested dicts rather than replacing them."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _dict_to_config(nested: dict) -> Config:
    """Convert nested TOML dict to Config, using the explicit mapping."""
    cfg = Config()
    for (section, key), field in _TOML_TO_FIELD.items():
        value = nested.get(section, {}).get(key)
        if value is not None:
            setattr(cfg, field, value)
    cfg.claude_api_key = cfg.claude_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    cfg.copilot_token  = cfg.copilot_token  or os.environ.get("COPILOT_GITHUB_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
    return cfg


def _config_to_dict(cfg: Config) -> dict:
    return {
        "ai": {"provider": cfg.provider},
        "claude": {"model": cfg.claude_model},
        "copilot": {},
        "review": {
            "block_on": cfg.block_on,
            "ignore_paths": cfg.ignore_paths,
        },
        "fix": {
            "show_preview": cfg.show_preview,
            "granularity": cfg.granularity,
        },
    }
