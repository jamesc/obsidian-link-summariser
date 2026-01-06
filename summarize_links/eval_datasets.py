"""
Evaluation dataset management.

Supports loading/saving datasets of URLs with reference outputs
for evaluation purposes. Datasets are stored in YAML format
and can be used to systematically evaluate summarization quality.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from summarize_links.exceptions import ConfigError

__all__ = [
    "EvalExample",
    "EvalDataset",
    "create_sample_dataset",
]

logger = logging.getLogger(__name__)


@dataclass
class EvalExample:
    """
    A single evaluation example.

    Represents a URL with optional expected outputs for evaluation.
    Fields map to the JSON schema used in evaluation datasets.

    Attributes:
        url: The URL to evaluate.
        title: Optional expected page title.
        expected_tags: Optional list of expected tags for tag accuracy metrics.
        expected_content_type: Optional expected content type classification.
        reference_summary: Optional reference summary for quality comparison.
        notes: Optional notes about the example for documentation.
    """

    url: str
    title: str | None = None
    expected_tags: list[str] = field(default_factory=list)
    expected_content_type: str | None = None
    reference_summary: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        result: dict[str, Any] = {"url": self.url}

        if self.title:
            result["title"] = self.title
        if self.expected_tags:
            result["expected_tags"] = self.expected_tags
        if self.expected_content_type:
            result["expected_content_type"] = self.expected_content_type
        if self.reference_summary:
            result["reference_summary"] = self.reference_summary
        if self.notes:
            result["notes"] = self.notes

        return result


@dataclass
class EvalDataset:
    """
    Collection of evaluation examples.

    A dataset contains a name, description, and list of examples
    that can be used to evaluate summarization quality.

    Attributes:
        name: Human-readable name for the dataset.
        description: Description of the dataset's purpose.
        examples: List of evaluation examples.
    """

    name: str
    description: str
    examples: list[EvalExample]

    @classmethod
    def from_yaml(cls, path: Path) -> "EvalDataset":
        """
        Load dataset from YAML file.

        Args:
            path: Path to YAML file.

        Returns:
            Loaded EvalDataset instance.

        Raises:
            ConfigError: If file cannot be loaded or has invalid format.
        """
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data or "examples" not in data:
                raise ConfigError(f"Invalid eval dataset format: {path} (missing 'examples' key)")

            if not isinstance(data["examples"], list):
                raise ConfigError(f"Invalid eval dataset format: {path} ('examples' must be a list)")

            examples = []
            for i, ex in enumerate(data["examples"]):
                if not isinstance(ex, dict):
                    raise ConfigError(f"Invalid example at index {i}: must be a dictionary")
                if "url" not in ex:
                    raise ConfigError(f"Invalid example at index {i}: missing 'url' key")

                examples.append(
                    EvalExample(
                        url=ex["url"],
                        title=ex.get("title"),
                        expected_tags=ex.get("expected_tags", []),
                        expected_content_type=ex.get("expected_content_type"),
                        reference_summary=ex.get("reference_summary"),
                        notes=ex.get("notes"),
                    )
                )

            dataset = cls(
                name=data.get("name", "Untitled Dataset"),
                description=data.get("description", ""),
                examples=examples,
            )

            logger.info("Loaded eval dataset '%s' with %d examples from %s", dataset.name, len(examples), path)
            return dataset

        except yaml.YAMLError as e:
            raise ConfigError(f"Failed to parse YAML from {path}: {e}") from e
        except OSError as e:
            raise ConfigError(f"Failed to read eval dataset from {path}: {e}") from e

    def to_yaml(self, path: Path) -> None:
        """
        Save dataset to YAML file.

        Args:
            path: Path to save the YAML file.
        """
        data = {
            "name": self.name,
            "description": self.description,
            "examples": [ex.to_dict() for ex in self.examples],
        }

        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        logger.info("Saved eval dataset '%s' to %s", self.name, path)

    def __len__(self) -> int:
        """Return number of examples in dataset."""
        return len(self.examples)

    def __iter__(self):
        """Iterate over examples."""
        return iter(self.examples)


def create_sample_dataset() -> EvalDataset:
    """
    Create a sample evaluation dataset for documentation.

    Returns:
        Sample EvalDataset with example entries.
    """
    return EvalDataset(
        name="Sample Evaluation Dataset",
        description="Example dataset showing expected format for evaluation",
        examples=[
            EvalExample(
                url="https://ai.google.dev/gemini-api/docs/models/gemini",
                title="Gemini models documentation",
                expected_tags=["ai", "gemini", "documentation", "llm", "google"],
                expected_content_type="documentation",
                reference_summary=None,  # Optional - can be added for quality comparison
                notes="Should identify as documentation and extract relevant AI tags",
            ),
            EvalExample(
                url="https://www.anthropic.com/news/claude-3-family",
                title="Introducing Claude 3",
                expected_tags=["ai", "anthropic", "claude", "announcement"],
                expected_content_type="news",
                notes="Should be classified as news/announcement",
            ),
            EvalExample(
                url="https://github.blog/2024-01-01-example-blog-post/",
                title="Example GitHub Blog Post",
                expected_tags=["github", "blog"],
                expected_content_type="blog",
                notes="Should recognize blog post format",
            ),
        ],
    )
