"""Configuration management for X Collector.

Loads configuration from ~/.openclaw/x-collector.yaml with the following structure:

```yaml
x:
  bearer_token: "your_x_bearer_token"

rate_limit:
  safe_delay: 0.7           # Seconds between requests (normal)
  slow_delay: 2.0           # Seconds when approaching limit
  safe_threshold: 10        # Slow down when remaining < this
  critical_threshold: 2     # Wait for reset when remaining < this

collection:
  max_results_per_page: 100 # Max tweets per API request (max 100)
  timeout: 30               # HTTP request timeout in seconds
  user_agent: "XCollector/0.1.0"

output:
  format: "json"            # json, jsonl, or markdown
  include_referenced: true  # Include referenced tweets (quotes, replies)
```
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import yaml


DEFAULT_CONFIG_PATH = Path.home() / ".openclaw" / "x-collector.yaml"


class ConfigError(Exception):
    """Configuration error."""
    pass


@dataclass
class RateLimitConfig:
    """Rate limiting configuration."""
    safe_delay: float = 0.7
    slow_delay: float = 2.0
    safe_threshold: int = 10
    critical_threshold: int = 2


@dataclass
class CollectionConfig:
    """Collection behavior configuration."""
    max_results_per_page: int = 100
    timeout: int = 30
    user_agent: str = "XCollector/0.1.0"


@dataclass
class OutputConfig:
    """Output format configuration."""
    format: str = "json"  # json, jsonl, markdown
    include_referenced: bool = True


@dataclass
class XConfig:
    """X Collector configuration.

    Attributes:
        bearer_token: X/Twitter API v2 Bearer Token
        rate_limit: Rate limiting settings
        collection: Collection behavior settings
        output: Output format settings
        config_path: Path to the loaded config file
    """
    bearer_token: str = ""
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    collection: CollectionConfig = field(default_factory=CollectionConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    config_path: Optional[Path] = None

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "XConfig":
        """Load configuration from YAML file.

        Priority:
        1. Explicit config_path parameter
        2. X_COLLECTOR_CONFIG environment variable
        3. ~/.openclaw/x-collector.yaml (default)

        Environment variables can override config file values:
        - X_BEARER_TOKEN: Override bearer_token

        Args:
            config_path: Optional path to config file

        Returns:
            XConfig instance

        Raises:
            ConfigError: If config file is missing or invalid
        """
        # Determine config path
        if config_path is None:
            env_path = os.environ.get("X_COLLECTOR_CONFIG")
            if env_path:
                config_path = Path(env_path)
            else:
                config_path = DEFAULT_CONFIG_PATH

        # Load from file if exists
        config_data = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config_data = yaml.safe_load(f) or {}
            except yaml.YAMLError as e:
                raise ConfigError(f"Invalid YAML in {config_path}: {e}")

        # Parse sections
        x_data = config_data.get("x", {})
        rate_limit_data = config_data.get("rate_limit", {})
        collection_data = config_data.get("collection", {})
        output_data = config_data.get("output", {})

        # Build config objects
        rate_limit = RateLimitConfig(
            safe_delay=rate_limit_data.get("safe_delay", 0.7),
            slow_delay=rate_limit_data.get("slow_delay", 2.0),
            safe_threshold=rate_limit_data.get("safe_threshold", 10),
            critical_threshold=rate_limit_data.get("critical_threshold", 2),
        )

        collection = CollectionConfig(
            max_results_per_page=min(collection_data.get("max_results_per_page", 100), 100),
            timeout=collection_data.get("timeout", 30),
            user_agent=collection_data.get("user_agent", "XCollector/0.1.0"),
        )

        output = OutputConfig(
            format=output_data.get("format", "json"),
            include_referenced=output_data.get("include_referenced", True),
        )

        # Get bearer token (env var takes precedence)
        bearer_token = os.environ.get("X_BEARER_TOKEN") or x_data.get("bearer_token", "")

        return cls(
            bearer_token=bearer_token,
            rate_limit=rate_limit,
            collection=collection,
            output=output,
            config_path=config_path,
        )

    @classmethod
    def create_default(cls, config_path: Optional[Path] = None) -> Path:
        """Create a default config file with placeholder values.

        Args:
            config_path: Where to create the config file

        Returns:
            Path to created config file
        """
        if config_path is None:
            config_path = DEFAULT_CONFIG_PATH

        config_path.parent.mkdir(parents=True, exist_ok=True)

        default_content = """\
# X Collector Configuration
# Documentation: https://github.com/coinsummer/x-collector

x:
  # Required: Your X/Twitter API v2 Bearer Token
  # Get one at: https://developer.twitter.com/en/portal/dashboard
  bearer_token: "YOUR_BEARER_TOKEN_HERE"

rate_limit:
  # Seconds between requests in normal mode
  safe_delay: 0.7
  # Seconds between requests when approaching rate limit
  slow_delay: 2.0
  # Slow down when remaining requests < this value
  safe_threshold: 10
  # Wait for rate limit reset when remaining < this value
  critical_threshold: 2

collection:
  # Max tweets per API request (X API max is 100)
  max_results_per_page: 100
  # HTTP request timeout in seconds
  timeout: 30
  # User agent for API requests
  user_agent: "XCollector/0.1.0"

output:
  # Output format: json, jsonl, or markdown
  format: "json"
  # Include referenced tweets (quotes, replies)
  include_referenced: true
"""

        with open(config_path, "w", encoding="utf-8") as f:
            f.write(default_content)

        return config_path

    def validate(self) -> list[str]:
        """Validate configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if not self.bearer_token:
            errors.append("bearer_token is required")
        elif not self.bearer_token.startswith("AAAA"):
            errors.append("bearer_token appears invalid (should start with 'AAAA')")

        if self.rate_limit.safe_delay < 0:
            errors.append("rate_limit.safe_delay must be >= 0")

        if self.rate_limit.slow_delay < self.rate_limit.safe_delay:
            errors.append("rate_limit.slow_delay should be >= safe_delay")

        if self.collection.max_results_per_page < 1 or self.collection.max_results_per_page > 100:
            errors.append("collection.max_results_per_page must be between 1 and 100")

        if self.output.format not in ("json", "jsonl", "markdown"):
            errors.append(f"output.format must be json, jsonl, or markdown (got: {self.output.format})")

        return errors

    @property
    def is_valid(self) -> bool:
        """Check if configuration is valid."""
        return len(self.validate()) == 0

    def __repr__(self) -> str:
        """String representation (hides sensitive data)."""
        token_display = f"{self.bearer_token[:8]}..." if self.bearer_token else "<not set>"
        return (
            f"XConfig("
            f"bearer_token='{token_display}', "
            f"config_path={self.config_path})"
        )
