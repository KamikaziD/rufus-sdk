"""
Configuration management for Rufus CLI.

Handles loading, saving, and managing CLI configuration stored in ~/.rufus/config.yaml
"""

import os
import yaml
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict


@dataclass
class SQLiteConfig:
    """SQLite persistence configuration"""
    db_path: str = "~/.rufus/workflows.db"


@dataclass
class PostgresConfig:
    """PostgreSQL persistence configuration"""
    db_url: str = "postgresql://localhost/rufus"
    pool_min_size: int = 10
    pool_max_size: int = 50


@dataclass
class PersistenceConfig:
    """Persistence provider configuration"""
    provider: str = "memory"  # memory, sqlite, postgres
    sqlite: SQLiteConfig = None
    postgres: PostgresConfig = None

    def __post_init__(self):
        if self.sqlite is None:
            self.sqlite = SQLiteConfig()
        if self.postgres is None:
            self.postgres = PostgresConfig()


@dataclass
class ExecutionConfig:
    """Execution provider configuration"""
    provider: str = "sync"  # sync, celery, thread_pool


@dataclass
class ObservabilityConfig:
    """Observability provider configuration"""
    provider: str = "logging"  # logging, noop


@dataclass
class DefaultsConfig:
    """Default behavior configuration"""
    auto_execute: bool = False  # Don't auto-execute steps by default
    interactive: bool = True    # Prompt for HITL steps
    json_output: bool = False   # Use table output by default


@dataclass
class Config:
    """Complete Rufus CLI configuration"""
    version: str = "1.0"
    persistence: PersistenceConfig = None
    execution: ExecutionConfig = None
    observability: ObservabilityConfig = None
    defaults: DefaultsConfig = None

    def __post_init__(self):
        if self.persistence is None:
            self.persistence = PersistenceConfig()
        if self.execution is None:
            self.execution = ExecutionConfig()
        if self.observability is None:
            self.observability = ObservabilityConfig()
        if self.defaults is None:
            self.defaults = DefaultsConfig()


class ConfigManager:
    """Manages Rufus CLI configuration"""

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize config manager.

        Args:
            config_path: Optional path to config file. Defaults to ~/.rufus/config.yaml
        """
        if config_path is None:
            self.config_path = Path.home() / ".rufus" / "config.yaml"
        else:
            self.config_path = Path(config_path)

        self._config: Optional[Config] = None

    def load(self) -> Config:
        """
        Load configuration from file.

        Returns:
            Config instance with loaded or default values
        """
        if not self.config_path.exists():
            # Return default config if file doesn't exist
            self._config = Config()
            return self._config

        try:
            with open(self.config_path, "r") as f:
                data = yaml.safe_load(f) or {}

            # Parse configuration
            config = Config(
                version=data.get("version", "1.0"),
                persistence=self._parse_persistence(data.get("persistence", {})),
                execution=self._parse_execution(data.get("execution", {})),
                observability=self._parse_observability(data.get("observability", {})),
                defaults=self._parse_defaults(data.get("defaults", {}))
            )

            self._config = config
            return config

        except Exception as e:
            # If config file is corrupted, return default config
            print(f"Warning: Failed to load config from {self.config_path}: {e}")
            print("Using default configuration")
            self._config = Config()
            return self._config

    def save(self, config: Optional[Config] = None) -> None:
        """
        Save configuration to file.

        Args:
            config: Config to save. If None, saves current config.
        """
        if config is None:
            config = self._config
        if config is None:
            config = Config()

        # Ensure config directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert config to dict
        data = self._config_to_dict(config)

        # Save to file
        with open(self.config_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def get(self) -> Config:
        """
        Get current configuration (loads if not already loaded).

        Returns:
            Current Config instance
        """
        if self._config is None:
            return self.load()
        return self._config

    def set_persistence(self, provider: str, **kwargs) -> None:
        """
        Set persistence provider configuration.

        Args:
            provider: Provider name (memory, sqlite, postgres)
            **kwargs: Provider-specific configuration
        """
        config = self.get()
        config.persistence.provider = provider

        if provider == "sqlite":
            if "db_path" in kwargs:
                config.persistence.sqlite.db_path = kwargs["db_path"]
        elif provider == "postgres":
            if "db_url" in kwargs:
                config.persistence.postgres.db_url = kwargs["db_url"]
            if "pool_min_size" in kwargs:
                config.persistence.postgres.pool_min_size = kwargs["pool_min_size"]
            if "pool_max_size" in kwargs:
                config.persistence.postgres.pool_max_size = kwargs["pool_max_size"]

        self.save(config)

    def set_execution(self, provider: str) -> None:
        """
        Set execution provider configuration.

        Args:
            provider: Provider name (sync, celery, thread_pool)
        """
        config = self.get()
        config.execution.provider = provider
        self.save(config)

    def set_default(self, key: str, value: Any) -> None:
        """
        Set default behavior configuration.

        Args:
            key: Configuration key (auto_execute, interactive, json_output)
            value: Configuration value
        """
        config = self.get()
        if hasattr(config.defaults, key):
            setattr(config.defaults, key, value)
            self.save(config)
        else:
            raise ValueError(f"Unknown default configuration key: {key}")

    def reset(self) -> None:
        """Reset configuration to defaults"""
        self._config = Config()
        self.save()

    def _parse_persistence(self, data: Dict[str, Any]) -> PersistenceConfig:
        """Parse persistence configuration from dict"""
        sqlite_data = data.get("sqlite", {})
        postgres_data = data.get("postgres", {})

        return PersistenceConfig(
            provider=data.get("provider", "memory"),
            sqlite=SQLiteConfig(
                db_path=sqlite_data.get("db_path", "~/.rufus/workflows.db")
            ),
            postgres=PostgresConfig(
                db_url=postgres_data.get("db_url", "postgresql://localhost/rufus"),
                pool_min_size=postgres_data.get("pool_min_size", 10),
                pool_max_size=postgres_data.get("pool_max_size", 50)
            )
        )

    def _parse_execution(self, data: Dict[str, Any]) -> ExecutionConfig:
        """Parse execution configuration from dict"""
        return ExecutionConfig(
            provider=data.get("provider", "sync")
        )

    def _parse_observability(self, data: Dict[str, Any]) -> ObservabilityConfig:
        """Parse observability configuration from dict"""
        return ObservabilityConfig(
            provider=data.get("provider", "logging")
        )

    def _parse_defaults(self, data: Dict[str, Any]) -> DefaultsConfig:
        """Parse defaults configuration from dict"""
        return DefaultsConfig(
            auto_execute=data.get("auto_execute", False),
            interactive=data.get("interactive", True),
            json_output=data.get("json_output", False)
        )

    def _config_to_dict(self, config: Config) -> Dict[str, Any]:
        """Convert Config to dictionary for YAML serialization"""
        return {
            "version": config.version,
            "persistence": {
                "provider": config.persistence.provider,
                "sqlite": {
                    "db_path": config.persistence.sqlite.db_path
                },
                "postgres": {
                    "db_url": config.persistence.postgres.db_url,
                    "pool_min_size": config.persistence.postgres.pool_min_size,
                    "pool_max_size": config.persistence.postgres.pool_max_size
                }
            },
            "execution": {
                "provider": config.execution.provider
            },
            "observability": {
                "provider": config.observability.provider
            },
            "defaults": {
                "auto_execute": config.defaults.auto_execute,
                "interactive": config.defaults.interactive,
                "json_output": config.defaults.json_output
            }
        }


# Global config manager instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """Get global config manager instance"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def get_config() -> Config:
    """Get current configuration"""
    return get_config_manager().get()
