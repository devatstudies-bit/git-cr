"""Tests for configuration loading, saving, and merging."""
import os
from pathlib import Path
import pytest
import toml

from codereview.config import (
    Config,
    load,
    save_global,
    save_project,
    _deep_merge,
    _dict_to_config,
    _config_to_dict,
    GLOBAL_CONFIG_PATH,
)


class TestConfigDefaults:
    def test_provider_default(self):
        assert Config().provider == "claude"

    def test_model_default(self):
        assert Config().claude_model == "claude-sonnet-4-6"

    def test_block_on_default(self):
        assert Config().block_on == ["error"]

    def test_ignore_paths_default(self):
        assert Config().ignore_paths == []

    def test_show_preview_default_none(self):
        assert Config().show_preview is None

    def test_granularity_default_none(self):
        assert Config().granularity is None

    def test_api_keys_default_empty(self):
        cfg = Config()
        assert cfg.claude_api_key == ""
        assert cfg.copilot_token == ""


class TestDeepMerge:
    def test_top_level_merge(self):
        base = {"a": 1, "b": 2}
        _deep_merge(base, {"b": 99, "c": 3})
        assert base == {"a": 1, "b": 99, "c": 3}

    def test_nested_merge(self):
        base = {"ai": {"provider": "claude"}, "fix": {"show_preview": True}}
        _deep_merge(base, {"ai": {"provider": "copilot"}})
        assert base["ai"]["provider"] == "copilot"
        assert base["fix"]["show_preview"] is True

    def test_override_replaces_non_dict(self):
        base = {"review": {"block_on": ["error"]}}
        _deep_merge(base, {"review": {"block_on": ["error", "security"]}})
        assert base["review"]["block_on"] == ["error", "security"]

    def test_empty_override(self):
        base = {"a": 1}
        _deep_merge(base, {})
        assert base == {"a": 1}


class TestDictToConfig:
    def test_reads_provider(self):
        cfg = _dict_to_config({"ai": {"provider": "copilot"}})
        assert cfg.provider == "copilot"

    def test_reads_claude_model(self):
        cfg = _dict_to_config({"claude": {"model": "claude-opus-4-8"}})
        assert cfg.claude_model == "claude-opus-4-8"

    def test_reads_block_on(self):
        cfg = _dict_to_config({"review": {"block_on": ["error", "security"]}})
        assert cfg.block_on == ["error", "security"]

    def test_reads_ignore_paths(self):
        cfg = _dict_to_config({"review": {"ignore_paths": ["tests/", "docs/"]}})
        assert cfg.ignore_paths == ["tests/", "docs/"]

    def test_reads_show_preview(self):
        cfg = _dict_to_config({"fix": {"show_preview": False}})
        assert cfg.show_preview is False

    def test_reads_granularity(self):
        cfg = _dict_to_config({"fix": {"granularity": "all"}})
        assert cfg.granularity == "all"

    def test_missing_keys_use_defaults(self):
        cfg = _dict_to_config({})
        assert cfg.provider == "claude"
        assert cfg.block_on == ["error"]

    def test_env_var_overrides_empty_api_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env-test")
        cfg = _dict_to_config({})
        assert cfg.claude_api_key == "sk-env-test"

    def test_copilot_token_from_github_token(self, monkeypatch):
        monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        cfg = _dict_to_config({})
        assert cfg.copilot_token == "ghp_test"

    def test_copilot_token_prefers_copilot_token_env(self, monkeypatch):
        monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "ghp_copilot")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_github")
        cfg = _dict_to_config({})
        assert cfg.copilot_token == "ghp_copilot"


class TestConfigToDict:
    def test_provider_in_ai_section(self):
        cfg = Config()
        cfg.provider = "copilot"
        d = _config_to_dict(cfg)
        assert d["ai"]["provider"] == "copilot"

    def test_model_in_claude_section(self):
        cfg = Config()
        cfg.claude_model = "claude-haiku-4-5-20251001"
        d = _config_to_dict(cfg)
        assert d["claude"]["model"] == "claude-haiku-4-5-20251001"

    def test_block_on_in_review_section(self):
        cfg = Config()
        cfg.block_on = ["error", "security"]
        d = _config_to_dict(cfg)
        assert d["review"]["block_on"] == ["error", "security"]

    def test_none_values_omitted_by_toml(self):
        cfg = Config()  # show_preview=None, granularity=None
        d = _config_to_dict(cfg)
        dumped = toml.dumps(d)
        assert "show_preview" not in dumped
        assert "granularity" not in dumped

    def test_false_value_written_by_toml(self):
        cfg = Config()
        cfg.show_preview = False
        d = _config_to_dict(cfg)
        dumped = toml.dumps(d)
        assert "show_preview = false" in dumped


class TestSaveAndLoad:
    def test_global_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("codereview.config.GLOBAL_CONFIG_PATH", tmp_path / "config.toml")
        from codereview import config as cfg_module
        monkeypatch.setattr(cfg_module, "GLOBAL_CONFIG_PATH", tmp_path / "config.toml")

        cfg = Config()
        cfg.provider = "copilot"
        cfg.show_preview = False
        cfg.granularity = "all"
        cfg.block_on = ["error", "security"]
        save_global(cfg)

        loaded = load()
        assert loaded.provider == "copilot"
        assert loaded.show_preview is False
        assert loaded.granularity == "all"
        assert loaded.block_on == ["error", "security"]

    def test_project_overrides_global(self, tmp_path, monkeypatch):
        global_path = tmp_path / "global" / "config.toml"
        global_path.parent.mkdir()
        monkeypatch.setattr("codereview.config.GLOBAL_CONFIG_PATH", global_path)
        from codereview import config as cfg_module
        monkeypatch.setattr(cfg_module, "GLOBAL_CONFIG_PATH", global_path)

        # Global: claude
        global_cfg = Config()
        global_cfg.provider = "claude"
        save_global(global_cfg)

        # Project: copilot
        project_root = tmp_path / "project"
        project_root.mkdir()
        project_cfg = Config()
        project_cfg.provider = "copilot"
        save_project(project_cfg, project_root)

        loaded = load(project_root)
        assert loaded.provider == "copilot"

    def test_load_with_no_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("codereview.config.GLOBAL_CONFIG_PATH", tmp_path / "nonexistent.toml")
        from codereview import config as cfg_module
        monkeypatch.setattr(cfg_module, "GLOBAL_CONFIG_PATH", tmp_path / "nonexistent.toml")
        cfg = load()
        assert cfg.provider == "claude"

    def test_save_project_creates_file(self, tmp_path):
        cfg = Config()
        cfg.provider = "copilot"
        save_project(cfg, tmp_path)
        assert (tmp_path / ".cr.toml").exists()
        content = toml.load(tmp_path / ".cr.toml")
        assert content["ai"]["provider"] == "copilot"
