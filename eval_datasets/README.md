# Evaluation Datasets

This directory contains evaluation datasets for testing summarization quality.

## Dataset Format

Evaluation datasets are YAML files with the following structure:

```yaml
name: "Dataset Name"
description: "Description of the dataset's purpose"
examples:
  - url: "https://example.com/article"
    title: "Optional title override"
    expected_tags:
      - tag1
      - tag2
    expected_content_type: "article"
    notes: "Optional notes for this example"
```

### Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | No | Human-readable dataset name |
| `description` | No | Description of the dataset |
| `examples` | Yes | List of evaluation examples |

### Example Fields

| Field | Required | Description |
|-------|----------|-------------|
| `url` | Yes | URL to summarize |
| `title` | No | Expected/override title |
| `expected_tags` | No | Expected tags for accuracy metrics |
| `expected_content_type` | No | Expected content type classification |
| `reference_summary` | No | Reference summary for comparison (future use) |
| `notes` | No | Notes for documentation |

## Usage

Run evaluation on a dataset:

```bash
# Basic evaluation
summarize-links eval eval_datasets/sample.yaml

# Save results to file
summarize-links eval eval_datasets/sample.yaml --output results.yaml

# Use a different model
summarize-links eval eval_datasets/sample.yaml --model llama3:latest
```

## Creating New Datasets

1. Create a new YAML file in this directory
2. Add examples with URLs and expected outputs
3. Run evaluation to test

You can also use the `create_sample_dataset()` function in Python:

```python
from summarize_links.eval import create_sample_dataset

dataset = create_sample_dataset()
dataset.to_yaml(Path("my_dataset.yaml"))
```

## Metrics

The evaluation framework calculates:

- **Tag Precision**: Fraction of suggested tags that are in expected tags
- **Tag Recall**: Fraction of expected tags that were suggested
- **Tag F1 Score**: Harmonic mean of precision and recall
- **Content Type Accuracy**: Whether content type classification matches
