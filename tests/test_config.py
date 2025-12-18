"""
Tests for the configuration module.
"""

from pathlib import Path

import pytest
import yaml

from summarize_links.config import (
    DEFAULT_MAX_LINKS,
    DEFAULT_MODEL,
    DEFAULT_OUT_FOLDER,
    Config,
    load_config,
    load_yaml_config,
)
from summarize_links.exceptions import ConfigError


class TestConfig:
    """Tests for the Config dataclass."""

    def test_default_values(self) -> None:
        """Config should have sensible defaults."""
        config = Config()
        assert config.model == DEFAULT_MODEL
        assert config.out_folder == DEFAULT_OUT_FOLDER
        assert config.max_links == DEFAULT_MAX_LINKS
        assert config.mock_mode is False
        assert config.dry_run is False
        assert config.verbose is False

    def test_validate_missing_api_key(self, tmp_path: Path) -> None:
        """Validation should fail without API key (unless mock mode)."""
        config = Config(vault_path=tmp_path, gemini_api_key="")
        with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
            config.validate()

    def test_validate_mock_mode_no_api_key(self, tmp_path: Path) -> None:
        """Mock mode should not require API key."""
        config = Config(vault_path=tmp_path, mock_mode=True)
        # Should not raise
        config.validate()

    def test_validate_missing_vault_path(self) -> None:
        """Validation should fail without vault path."""
        config = Config(gemini_api_key="test-key", vault_path=None)
        with pytest.raises(ConfigError, match="Vault path is required"):
            config.validate()

    def test_validate_nonexistent_vault(self) -> None:
        """Validation should fail if vault path doesn't exist."""
        config = Config(
            gemini_api_key="test-key",
            vault_path=Path("/nonexistent/path/12345"),
        )
        with pytest.raises(ConfigError, match="does not exist"):
            config.validate()

    def test_validate_vault_is_file(self, tmp_path: Path) -> None:
        """Validation should fail if vault path is a file, not directory."""
        # Create a file instead of directory
        file_path = tmp_path / "not_a_dir.txt"
        file_path.touch()

        config = Config(gemini_api_key="test-key", vault_path=file_path)
        with pytest.raises(ConfigError, match="not a directory"):
            config.validate()

    def test_validate_invalid_max_links(self, tmp_path: Path) -> None:
        """Validation should fail with max_links < 1."""
        config = Config(
            gemini_api_key="test-key",
            vault_path=tmp_path,
            max_links=0,
        )
        with pytest.raises(ConfigError, match="max_links must be at least 1"):
            config.validate()

    def test_validate_success(self, tmp_path: Path) -> None:
        """Valid config should pass validation."""
        config = Config(
            gemini_api_key="test-key",
            vault_path=tmp_path,
            max_links=5,
        )
        # Should not raise
        config.validate()


class TestLoadYamlConfig:
    """Tests for YAML config loading."""

    def test_no_config_file(self, tmp_path: Path) -> None:
        """Should return empty dict if no config file exists."""
        result = load_yaml_config(tmp_path)
        assert result == {}

    def test_load_valid_config(self, tmp_path: Path) -> None:
        """Should load values from YAML config."""
        config_content = {
            "out_folder": "MySummaries",
            "max_links": 5,
            "model": "gemini-pro",
        }
        config_file = tmp_path / ".summarizer-config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        result = load_yaml_config(tmp_path)
        assert result["out_folder"] == "MySummaries"
        assert result["max_links"] == 5
        assert result["model"] == "gemini-pro"

    def test_empty_config_file(self, tmp_path: Path) -> None:
        """Should return empty dict for empty YAML file."""
        config_file = tmp_path / ".summarizer-config.yaml"
        config_file.touch()

        result = load_yaml_config(tmp_path)
        assert result == {}

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        """Should raise ConfigError for invalid YAML."""
        config_file = tmp_path / ".summarizer-config.yaml"
        config_file.write_text("invalid: yaml: content: [")

        with pytest.raises(ConfigError, match="Failed to parse"):
            load_yaml_config(tmp_path)


class TestLoadConfig:
    """Tests for the main config loading function."""

    def test_cli_args_override_all(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLI arguments should override env vars and YAML."""
        # Set env vars
        monkeypatch.setenv("GEMINI_API_KEY", "env-key")
        monkeypatch.setenv("GEMINI_MODEL", "env-model")

        # Create YAML config
        config_content = {"model": "yaml-model", "out_folder": "YamlFolder"}
        config_file = tmp_path / ".summarizer-config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        # Load with CLI overrides
        config = load_config(
            vault_path=tmp_path,
            model="cli-model",
            out_folder="CLIFolder",
            max_links=3,
        )

        assert config.model == "cli-model"
        assert config.out_folder == "CLIFolder"
        assert config.max_links == 3

    def test_env_vars_override_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env vars should override YAML config."""
        monkeypatch.setenv("GEMINI_API_KEY", "env-key")
        monkeypatch.setenv("GEMINI_MODEL", "env-model")

        # Create YAML config
        config_content = {"model": "yaml-model"}
        config_file = tmp_path / ".summarizer-config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        config = load_config(vault_path=tmp_path)

        assert config.model == "env-model"
        assert config.gemini_api_key == "env-key"

    def test_yaml_config_used_as_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """YAML config should be used when no env var or CLI arg."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        # Clear model env var if set
        monkeypatch.delenv("GEMINI_MODEL", raising=False)

        # Create YAML config
        config_content = {"out_folder": "YamlFolder", "max_links": 7}
        config_file = tmp_path / ".summarizer-config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        config = load_config(vault_path=tmp_path)

        assert config.out_folder == "YamlFolder"
        assert config.max_links == 7

    def test_default_vault_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should use DEFAULT_VAULT_PATH env var when no CLI arg."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("DEFAULT_VAULT_PATH", str(tmp_path))

        config = load_config()

        assert config.vault_path == tmp_path

    def test_mock_and_dry_run_flags(self, tmp_path: Path) -> None:
        """Mock and dry run flags should be set correctly."""
        config = load_config(
            vault_path=tmp_path,
            mock_mode=True,
            dry_run=True,
            verbose=True,
        )

        assert config.mock_mode is True
        assert config.dry_run is True
        assert config.verbose is True

    def test_rate_limits_from_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should load rate limits from YAML config."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        config_content = {
            "rpm_limit": 10,
            "tpm_limit": 500000,
            "daily_limit": 200,
        }
        config_file = tmp_path / ".summarizer-config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        config = load_config(vault_path=tmp_path)

        assert config.rpm_limit == 10
        assert config.tpm_limit == 500000
        assert config.daily_limit == 200

    def test_rate_limits_from_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variables should override YAML rate limits."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("GEMINI_RPM_LIMIT", "20")
        monkeypatch.setenv("GEMINI_TPM_LIMIT", "1000000")
        monkeypatch.setenv("GEMINI_DAILY_LIMIT", "500")

        config_content = {
            "rpm_limit": 10,
            "tpm_limit": 500000,
            "daily_limit": 200,
        }
        config_file = tmp_path / ".summarizer-config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        config = load_config(vault_path=tmp_path)

        # Env should override YAML
        assert config.rpm_limit == 20
        assert config.tpm_limit == 1000000
        assert config.daily_limit == 500

    def test_default_tags_from_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should load default_tags from YAML config."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        config_content = {
            "default_tags": ["reading", "web-summary"],
        }
        config_file = tmp_path / ".summarizer-config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        config = load_config(vault_path=tmp_path)

        assert config.default_tags == ["reading", "web-summary"]

    def test_default_tags_single_string(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should handle default_tags as single string."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        config_content = {
            "default_tags": "single-tag",
        }
        config_file = tmp_path / ".summarizer-config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        config = load_config(vault_path=tmp_path)

        assert config.default_tags == ["single-tag"]


class TestSetupLogging:
    """Tests for logging setup."""

    def test_setup_logging_verbose(self) -> None:
        """Verbose mode should configure logging correctly."""
        import logging

        from summarize_links.config import setup_logging

        # Clear existing handlers to allow basicConfig to work
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        setup_logging(verbose=True)

        # Check that the effective level allows DEBUG through
        # basicConfig sets level on root logger
        assert root_logger.level == logging.DEBUG

    def test_setup_logging_normal(self) -> None:
        """Normal mode should set INFO level."""
        import logging

        from summarize_links.config import setup_logging

        # Clear existing handlers to allow basicConfig to work
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        setup_logging(verbose=False)

        # The root logger should be INFO
        assert root_logger.level == logging.INFO

    def test_third_party_loggers_suppressed(self) -> None:
        """Third-party loggers should be set to WARNING."""
        import logging

        from summarize_links.config import setup_logging

        # Clear existing handlers
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        setup_logging(verbose=True)

        # urllib3 and google loggers should be WARNING
        urllib3_logger = logging.getLogger("urllib3")
        google_logger = logging.getLogger("google")

        assert urllib3_logger.level >= logging.WARNING
        assert google_logger.level >= logging.WARNING


class TestDailyNotesFolder:
    """Tests for daily_notes_folder configuration."""

    def test_daily_notes_folder_from_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should load daily_notes_folder from YAML config."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        config_content = {
            "daily_notes_folder": "Journal/Daily",
        }
        config_file = tmp_path / ".summarizer-config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        config = load_config(vault_path=tmp_path)

        assert config.daily_notes_folder == "Journal/Daily"

    def test_daily_notes_folder_default_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default daily_notes_folder should be empty string."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        config = load_config(vault_path=tmp_path)

        assert config.daily_notes_folder == ""
