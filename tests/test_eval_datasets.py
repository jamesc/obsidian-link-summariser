"""Tests for evaluation dataset management."""

from pathlib import Path

import pytest
import yaml

from summarize_links.eval_datasets import EvalDataset, EvalExample, create_sample_dataset
from summarize_links.exceptions import ConfigError


class TestEvalExample:
    """Tests for EvalExample dataclass."""

    def test_minimal_example(self) -> None:
        """Test creating an example with only required field."""
        example = EvalExample(url="https://example.com")

        assert example.url == "https://example.com"
        assert example.title is None
        assert example.expected_tags == []
        assert example.expected_content_type is None
        assert example.reference_summary is None
        assert example.notes is None

    def test_full_example(self) -> None:
        """Test creating an example with all fields."""
        example = EvalExample(
            url="https://example.com/article",
            title="Example Article",
            expected_tags=["tag1", "tag2"],
            expected_content_type="article",
            reference_summary="This is a summary.",
            notes="Test notes",
        )

        assert example.url == "https://example.com/article"
        assert example.title == "Example Article"
        assert example.expected_tags == ["tag1", "tag2"]
        assert example.expected_content_type == "article"
        assert example.reference_summary == "This is a summary."
        assert example.notes == "Test notes"

    def test_to_dict_minimal(self) -> None:
        """Test converting minimal example to dict."""
        example = EvalExample(url="https://example.com")
        result = example.to_dict()

        assert result == {"url": "https://example.com"}

    def test_to_dict_full(self) -> None:
        """Test converting full example to dict."""
        example = EvalExample(
            url="https://example.com",
            title="Title",
            expected_tags=["tag1"],
            expected_content_type="article",
            reference_summary="Summary",
            notes="Notes",
        )
        result = example.to_dict()

        assert result["url"] == "https://example.com"
        assert result["title"] == "Title"
        assert result["expected_tags"] == ["tag1"]
        assert result["expected_content_type"] == "article"
        assert result["reference_summary"] == "Summary"
        assert result["notes"] == "Notes"


class TestEvalDataset:
    """Tests for EvalDataset class."""

    def test_dataset_creation(self) -> None:
        """Test creating a dataset."""
        examples = [
            EvalExample(url="https://example1.com"),
            EvalExample(url="https://example2.com"),
        ]
        dataset = EvalDataset(
            name="Test Dataset",
            description="A test dataset",
            examples=examples,
        )

        assert dataset.name == "Test Dataset"
        assert dataset.description == "A test dataset"
        assert len(dataset) == 2
        assert dataset.examples[0].url == "https://example1.com"

    def test_dataset_iteration(self) -> None:
        """Test iterating over dataset."""
        examples = [
            EvalExample(url="https://example1.com"),
            EvalExample(url="https://example2.com"),
        ]
        dataset = EvalDataset(name="Test", description="", examples=examples)

        urls = [ex.url for ex in dataset]
        assert urls == ["https://example1.com", "https://example2.com"]

    def test_from_yaml(self, tmp_path: Path) -> None:
        """Test loading dataset from YAML file."""
        yaml_content = """
name: "Test Dataset"
description: "Test description"
examples:
  - url: "https://example.com/1"
    title: "Example 1"
    expected_tags:
      - tag1
      - tag2
    expected_content_type: "article"
  - url: "https://example.com/2"
    notes: "Second example"
"""
        yaml_file = tmp_path / "test_dataset.yaml"
        yaml_file.write_text(yaml_content)

        dataset = EvalDataset.from_yaml(yaml_file)

        assert dataset.name == "Test Dataset"
        assert dataset.description == "Test description"
        assert len(dataset) == 2
        assert dataset.examples[0].url == "https://example.com/1"
        assert dataset.examples[0].title == "Example 1"
        assert dataset.examples[0].expected_tags == ["tag1", "tag2"]
        assert dataset.examples[0].expected_content_type == "article"
        assert dataset.examples[1].url == "https://example.com/2"
        assert dataset.examples[1].notes == "Second example"

    def test_from_yaml_minimal(self, tmp_path: Path) -> None:
        """Test loading minimal valid YAML."""
        yaml_content = """
examples:
  - url: "https://example.com"
"""
        yaml_file = tmp_path / "minimal.yaml"
        yaml_file.write_text(yaml_content)

        dataset = EvalDataset.from_yaml(yaml_file)

        assert dataset.name == "Untitled Dataset"
        assert dataset.description == ""
        assert len(dataset) == 1
        assert dataset.examples[0].url == "https://example.com"

    def test_from_yaml_missing_examples_key(self, tmp_path: Path) -> None:
        """Test error when 'examples' key is missing."""
        yaml_content = """
name: "Bad Dataset"
description: "No examples key"
"""
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text(yaml_content)

        with pytest.raises(ConfigError, match="missing 'examples' key"):
            EvalDataset.from_yaml(yaml_file)

    def test_from_yaml_examples_not_list(self, tmp_path: Path) -> None:
        """Test error when 'examples' is not a list."""
        yaml_content = """
examples: "not a list"
"""
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text(yaml_content)

        with pytest.raises(ConfigError, match="must be a list"):
            EvalDataset.from_yaml(yaml_file)

    def test_from_yaml_example_missing_url(self, tmp_path: Path) -> None:
        """Test error when example is missing 'url' key."""
        yaml_content = """
examples:
  - title: "No URL"
"""
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text(yaml_content)

        with pytest.raises(ConfigError, match="missing 'url' key"):
            EvalDataset.from_yaml(yaml_file)

    def test_from_yaml_example_not_dict(self, tmp_path: Path) -> None:
        """Test error when example is not a dictionary."""
        yaml_content = """
examples:
  - "just a string"
"""
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text(yaml_content)

        with pytest.raises(ConfigError, match="must be a dictionary"):
            EvalDataset.from_yaml(yaml_file)

    def test_from_yaml_file_not_found(self, tmp_path: Path) -> None:
        """Test error when file doesn't exist."""
        yaml_file = tmp_path / "nonexistent.yaml"

        with pytest.raises(ConfigError, match="Failed to read"):
            EvalDataset.from_yaml(yaml_file)

    def test_from_yaml_invalid_yaml(self, tmp_path: Path) -> None:
        """Test error when file contains invalid YAML."""
        yaml_file = tmp_path / "invalid.yaml"
        yaml_file.write_text("{ invalid: yaml: content")

        with pytest.raises(ConfigError, match="Failed to parse YAML"):
            EvalDataset.from_yaml(yaml_file)

    def test_to_yaml(self, tmp_path: Path) -> None:
        """Test saving dataset to YAML file."""
        dataset = EvalDataset(
            name="Save Test",
            description="Testing save functionality",
            examples=[
                EvalExample(
                    url="https://example.com",
                    title="Example",
                    expected_tags=["tag1", "tag2"],
                ),
            ],
        )

        yaml_file = tmp_path / "output.yaml"
        dataset.to_yaml(yaml_file)

        # Verify file was created
        assert yaml_file.exists()

        # Load and verify content
        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        assert data["name"] == "Save Test"
        assert data["description"] == "Testing save functionality"
        assert len(data["examples"]) == 1
        assert data["examples"][0]["url"] == "https://example.com"
        assert data["examples"][0]["title"] == "Example"
        assert data["examples"][0]["expected_tags"] == ["tag1", "tag2"]

    def test_to_yaml_creates_parent_directory(self, tmp_path: Path) -> None:
        """Test that to_yaml creates parent directories."""
        dataset = EvalDataset(
            name="Test",
            description="",
            examples=[EvalExample(url="https://example.com")],
        )

        yaml_file = tmp_path / "nested" / "path" / "output.yaml"
        dataset.to_yaml(yaml_file)

        assert yaml_file.exists()

    def test_roundtrip(self, tmp_path: Path) -> None:
        """Test saving and loading dataset preserves data."""
        original = EvalDataset(
            name="Roundtrip Test",
            description="Testing roundtrip",
            examples=[
                EvalExample(
                    url="https://example.com/1",
                    title="Title 1",
                    expected_tags=["tag1", "tag2"],
                    expected_content_type="article",
                    notes="Notes 1",
                ),
                EvalExample(
                    url="https://example.com/2",
                    expected_content_type="tutorial",
                ),
            ],
        )

        yaml_file = tmp_path / "roundtrip.yaml"
        original.to_yaml(yaml_file)
        loaded = EvalDataset.from_yaml(yaml_file)

        assert loaded.name == original.name
        assert loaded.description == original.description
        assert len(loaded) == len(original)

        for orig_ex, load_ex in zip(original.examples, loaded.examples, strict=True):
            assert load_ex.url == orig_ex.url
            assert load_ex.title == orig_ex.title
            assert load_ex.expected_tags == orig_ex.expected_tags
            assert load_ex.expected_content_type == orig_ex.expected_content_type
            assert load_ex.notes == orig_ex.notes


class TestCreateSampleDataset:
    """Tests for create_sample_dataset function."""

    def test_creates_valid_dataset(self) -> None:
        """Test that sample dataset is valid."""
        dataset = create_sample_dataset()

        assert dataset.name == "Sample Evaluation Dataset"
        assert len(dataset) > 0
        assert all(ex.url for ex in dataset)

    def test_sample_has_expected_tags(self) -> None:
        """Test that sample examples have expected tags."""
        dataset = create_sample_dataset()

        # At least one example should have expected tags
        examples_with_tags = [ex for ex in dataset if ex.expected_tags]
        assert len(examples_with_tags) > 0

    def test_sample_has_content_types(self) -> None:
        """Test that sample examples have content types."""
        dataset = create_sample_dataset()

        # At least one example should have expected content type
        examples_with_type = [ex for ex in dataset if ex.expected_content_type]
        assert len(examples_with_type) > 0

    def test_sample_can_be_saved(self, tmp_path: Path) -> None:
        """Test that sample dataset can be saved to YAML."""
        dataset = create_sample_dataset()
        yaml_file = tmp_path / "sample.yaml"

        dataset.to_yaml(yaml_file)

        assert yaml_file.exists()
        # Verify it can be loaded back
        loaded = EvalDataset.from_yaml(yaml_file)
        assert len(loaded) == len(dataset)
