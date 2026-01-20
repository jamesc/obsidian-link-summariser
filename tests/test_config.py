"""
Tests for the configuration module.
"""

from pathlib import Path

import pytest
import yaml

from summarize_links.config import (
    DEFAULT_MAX_LINKS,
    DEFAULT_MODEL,
    DEFAULT_MODEL_LIMITS,
    DEFAULT_OUT_FOLDER,
    FALLBACK_MODEL_LIMITS,
    Config,
    get_model_rate_limits,
    load_config,
    load_yaml_config,
)
from summarize_links.exceptions import ConfigError
from summarize_links.rate_limiter import ModelRateLimits


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
        config = Config(
            model_provider="google",
            vault_path=tmp_path,
            gemini_api_key="",
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",
        )
        with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
            config.validate()

    def test_validate_mock_mode_no_api_key(self, tmp_path: Path) -> None:
        """Mock mode should not require API key."""
        config = Config(model_provider="google", vault_path=tmp_path, mock_mode=True)
        # Should not raise
        config.validate()

    def test_validate_missing_vault_path(self) -> None:
        """Validation should fail without vault path."""
        config = Config(
            model_provider="google",
            gemini_api_key="test-key",
            vault_path=None,
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",
        )
        with pytest.raises(ConfigError, match="Vault path is required"):
            config.validate()

    def test_validate_nonexistent_vault(self) -> None:
        """Validation should fail if vault path doesn't exist."""
        config = Config(
            model_provider="google",
            gemini_api_key="test-key",
            vault_path=Path("/nonexistent/path/12345"),
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",
        )
        with pytest.raises(ConfigError, match="does not exist"):
            config.validate()

    def test_validate_vault_is_file(self, tmp_path: Path) -> None:
        """Validation should fail if vault path is a file, not directory."""
        # Create a file instead of directory
        file_path = tmp_path / "not_a_dir.txt"
        file_path.touch()

        config = Config(
            model_provider="google",
            gemini_api_key="test-key",
            vault_path=file_path,
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",
        )
        with pytest.raises(ConfigError, match="not a directory"):
            config.validate()

    def test_validate_invalid_max_links(self, tmp_path: Path) -> None:
        """Validation should fail with max_links < 1."""
        config = Config(
            model_provider="google",
            gemini_api_key="test-key",
            vault_path=tmp_path,
            max_links=0,
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",
        )
        with pytest.raises(ConfigError, match="max_links must be at least 1"):
            config.validate()

    def test_validate_success(self, tmp_path: Path) -> None:
        """Valid config should pass validation."""
        config = Config(
            model_provider="google",
            gemini_api_key="test-key",
            vault_path=tmp_path,
            max_links=5,
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",
        )
        # Should not raise
        config.validate()

    def test_validate_invalid_playwright_phase(self, tmp_path: Path) -> None:
        """Invalid playwright phase should fail validation."""
        config = Config(
            model_provider="google",
            gemini_api_key="test-key",
            vault_path=tmp_path,
            max_links=5,
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",
            playwright_fallback_phase="phase5",  # type: ignore
        )
        with pytest.raises(ConfigError, match="Invalid playwright_fallback_phase"):
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
        monkeypatch.setenv("MODEL_PROVIDER", "google")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

        # Create YAML config
        config_content = {"model": "gemini-1.5-pro", "out_folder": "YamlFolder"}
        config_file = tmp_path / ".summarizer-config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        # Load with CLI overrides
        config = load_config(
            vault_path=tmp_path,
            model="gemini-2.0-flash",
            out_folder="CLIFolder",
            max_links=3,
        )

        assert config.model == "gemini-2.0-flash"
        assert config.out_folder == "CLIFolder"
        assert config.max_links == 3

    def test_env_vars_override_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env vars should override YAML config."""
        monkeypatch.setenv("GEMINI_API_KEY", "env-key")
        monkeypatch.setenv("MODEL", "gemini-1.5-flash")
        monkeypatch.setenv("MODEL_PROVIDER", "google")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

        # Create YAML config
        config_content = {"summary_model": "gemini-1.5-pro"}
        config_file = tmp_path / ".summarizer-config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        config = load_config(vault_path=tmp_path)

        assert config.model == "gemini-1.5-flash"
        assert config.gemini_api_key == "env-key"

    def test_yaml_config_used_as_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """YAML config should be used when no env var or CLI arg."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("MODEL_PROVIDER", "google")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
        # Clear model env var if set
        monkeypatch.delenv("MODEL", raising=False)

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
        monkeypatch.setenv("MODEL_PROVIDER", "google")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
        monkeypatch.setenv("DEFAULT_VAULT_PATH", str(tmp_path))

        config = load_config()

        assert config.vault_path == tmp_path

    def test_mock_and_dry_run_flags(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock and dry run flags should be set correctly."""
        monkeypatch.setenv("MODEL_PROVIDER", "google")
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
        monkeypatch.setenv("MODEL_PROVIDER", "google")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

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
        monkeypatch.setenv("MODEL_PROVIDER", "google")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
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
        monkeypatch.setenv("MODEL_PROVIDER", "google")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

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
        monkeypatch.setenv("MODEL_PROVIDER", "google")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

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
        monkeypatch.setenv("MODEL_PROVIDER", "google")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

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
        monkeypatch.setenv("MODEL_PROVIDER", "google")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

        config = load_config(vault_path=tmp_path)

        assert config.daily_notes_folder == ""


class TestGetModelRateLimits:
    """Tests for get_model_rate_limits function."""

    def test_known_model_defaults(self) -> None:
        """Should return correct limits for known models."""
        limits = get_model_rate_limits("gemini-2.5-flash")

        expected = DEFAULT_MODEL_LIMITS["gemini-2.5-flash"]
        assert limits.rpm_limit == expected["rpm_limit"]
        assert limits.tpm_limit == expected["tpm_limit"]
        assert limits.daily_limit == expected["daily_limit"]

    def test_unknown_model_fallback(self) -> None:
        """Should return fallback limits for unknown models."""
        limits = get_model_rate_limits("unknown-model-xyz")

        assert limits.rpm_limit == FALLBACK_MODEL_LIMITS["rpm_limit"]
        assert limits.tpm_limit == FALLBACK_MODEL_LIMITS["tpm_limit"]
        assert limits.daily_limit == FALLBACK_MODEL_LIMITS["daily_limit"]

    def test_yaml_model_limits_override(self) -> None:
        """YAML config model limits should override defaults."""
        yaml_limits = {
            "gemini-2.5-flash": {
                "rpm_limit": 100,
                "tpm_limit": 500000,
                "daily_limit": 1000,
            }
        }

        limits = get_model_rate_limits("gemini-2.5-flash", yaml_model_limits=yaml_limits)

        assert limits.rpm_limit == 100
        assert limits.tpm_limit == 500000
        assert limits.daily_limit == 1000

    def test_yaml_model_limits_new_model(self) -> None:
        """YAML config can define limits for custom models."""
        yaml_limits = {
            "my-custom-model": {
                "rpm_limit": 50,
                "tpm_limit": 250000,
                "daily_limit": 200,
            }
        }

        limits = get_model_rate_limits("my-custom-model", yaml_model_limits=yaml_limits)

        assert limits.rpm_limit == 50
        assert limits.tpm_limit == 250000
        assert limits.daily_limit == 200

    def test_returns_model_rate_limits_instance(self) -> None:
        """Should return ModelRateLimits dataclass instance."""
        limits = get_model_rate_limits("gemini-2.5-flash")

        assert isinstance(limits, ModelRateLimits)


class TestModelLimitsConfig:
    """Tests for model_limits in YAML config."""

    def test_model_limits_from_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should load model_limits from YAML config."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("MODEL_PROVIDER", "google")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

        config_content = {
            "model_limits": {
                "gemini-2.5-flash": {
                    "rpm_limit": 20,
                    "tpm_limit": 500000,
                    "daily_limit": 1000,
                },
                "gemini-2.5-pro": {
                    "rpm_limit": 10,
                    "tpm_limit": 250000,
                    "daily_limit": 50,
                },
            }
        }
        config_file = tmp_path / ".summarizer-config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        config = load_config(vault_path=tmp_path)

        assert config.model_limits is not None
        assert config.model_limits["gemini-2.5-flash"]["rpm_limit"] == 20
        assert config.model_limits["gemini-2.5-flash"]["daily_limit"] == 1000
        assert config.model_limits["gemini-2.5-pro"]["rpm_limit"] == 10

    def test_model_limits_default_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """model_limits should be None if not in YAML config."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("MODEL_PROVIDER", "google")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

        config = load_config(vault_path=tmp_path)

        assert config.model_limits is None

    def test_model_limits_integrates_with_get_model_rate_limits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Config model_limits should work with get_model_rate_limits."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("MODEL_PROVIDER", "google")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

        config_content = {
            "model_limits": {
                "gemini-2.5-flash": {
                    "rpm_limit": 100,
                    "tpm_limit": 1000000,
                    "daily_limit": 5000,
                },
            }
        }
        config_file = tmp_path / ".summarizer-config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        config = load_config(vault_path=tmp_path)

        # Use the loaded model_limits
        limits = get_model_rate_limits("gemini-2.5-flash", yaml_model_limits=config.model_limits)

        assert limits.rpm_limit == 100
        assert limits.tpm_limit == 1000000
        assert limits.daily_limit == 5000


class TestLangfuseConfig:
    """Tests for Langfuse configuration."""

    def test_langfuse_requires_credentials(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Langfuse credentials are required (except mock mode)."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("MODEL_PROVIDER", "google")
        # No Langfuse credentials set

        # Should raise during load_config since it validates
        with pytest.raises(ConfigError, match="Langfuse credentials are required"):
            load_config(vault_path=tmp_path)

    def test_langfuse_from_env_vars(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should load Langfuse config from environment variables."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("MODEL_PROVIDER", "google")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test-public")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test-secret")
        monkeypatch.setenv("LANGFUSE_BASE_URL", "https://custom.langfuse.com")

        config = load_config(vault_path=tmp_path)

        assert config.langfuse_public_key == "pk-lf-test-public"
        assert config.langfuse_secret_key == "sk-lf-test-secret"
        assert config.langfuse_base_url == "https://custom.langfuse.com"
        # Should pass validation with credentials
        config.validate()

    def test_langfuse_from_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should load Langfuse config from YAML."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("MODEL_PROVIDER", "google")

        config_content = {
            "langfuse": {
                "public_key": "pk-lf-yaml-public",
                "secret_key": "sk-lf-yaml-secret",
                "base_url": "https://yaml.langfuse.com",
            }
        }
        config_file = tmp_path / ".summarizer-config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        config = load_config(vault_path=tmp_path)

        assert config.langfuse_public_key == "pk-lf-yaml-public"
        assert config.langfuse_secret_key == "sk-lf-yaml-secret"
        assert config.langfuse_base_url == "https://yaml.langfuse.com"
        # Should pass validation with credentials
        config.validate()

    def test_langfuse_env_overrides_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Environment variables should override YAML for Langfuse."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("MODEL_PROVIDER", "google")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-env-public")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-env-secret")

        config_content = {
            "langfuse": {
                "public_key": "pk-lf-yaml-public",
                "secret_key": "sk-lf-yaml-secret",
            }
        }
        config_file = tmp_path / ".summarizer-config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        config = load_config(vault_path=tmp_path)

        # Env should override YAML
        assert config.langfuse_public_key == "pk-lf-env-public"
        assert config.langfuse_secret_key == "sk-lf-env-secret"

    def test_langfuse_mock_mode_skips_validation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mock mode should skip Langfuse credential validation."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("MODEL_PROVIDER", "google")
        # No Langfuse credentials set

        config = load_config(vault_path=tmp_path, mock_mode=True)

        # Should pass validation in mock mode
        config.validate()

    def test_langfuse_default_base_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should use default base URL when not specified."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("MODEL_PROVIDER", "google")
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

        config = load_config(vault_path=tmp_path)

        assert config.langfuse_base_url == "https://cloud.langfuse.com"
