"""
Evaluation framework for summary quality assessment.

This module provides tools for evaluating the quality of generated summaries:
- Dataset management for storing evaluation examples
- Metrics for measuring tag accuracy and content type classification

Usage:
    from summarize_links.eval import EvalDataset, EvalExample, evaluate_summary_result
"""

from summarize_links.eval.datasets import (
    EvalDataset,
    EvalExample,
    create_sample_dataset,
)
from summarize_links.eval.metrics import (
    ContentTypeAccuracyMetric,
    MetricResult,
    TagAccuracyMetric,
    evaluate_summary_result,
)

__all__ = [
    # Datasets
    "EvalDataset",
    "EvalExample",
    "create_sample_dataset",
    # Metrics
    "MetricResult",
    "TagAccuracyMetric",
    "ContentTypeAccuracyMetric",
    "evaluate_summary_result",
]
