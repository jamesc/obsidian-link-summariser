"""Tests for evaluation metrics."""

import pytest

from summarize_links.eval import (
    ContentTypeAccuracyMetric,
    MetricResult,
    TagAccuracyMetric,
    evaluate_summary_result,
)


class TestMetricResult:
    """Tests for MetricResult dataclass."""

    def test_primary_score_f1(self) -> None:
        """Test that F1 score is primary for tag accuracy."""
        result = MetricResult(
            name="tag_accuracy",
            scores={"precision": 0.8, "recall": 0.6, "f1_score": 0.7},
        )
        assert result.primary_score == 0.7

    def test_primary_score_accuracy(self) -> None:
        """Test that accuracy is primary for content type."""
        result = MetricResult(
            name="content_type_accuracy",
            scores={"accuracy": 0.9},
        )
        assert result.primary_score == 0.9

    def test_primary_score_fallback(self) -> None:
        """Test fallback to first score when no primary identified."""
        result = MetricResult(
            name="custom_metric",
            scores={"score1": 0.5, "score2": 0.7},
        )
        # Returns first score
        assert result.primary_score == 0.5

    def test_primary_score_empty(self) -> None:
        """Test handling empty scores."""
        result = MetricResult(
            name="empty_metric",
            scores={},
        )
        assert result.primary_score == 0.0


class TestTagAccuracyMetric:
    """Tests for TagAccuracyMetric class."""

    def test_perfect_match(self) -> None:
        """Test when all tags match exactly."""
        metric = TagAccuracyMetric()
        result = metric.evaluate(
            suggested_tags=["ai", "ml", "python"],
            expected_tags=["ai", "ml", "python"],
        )

        assert result.scores["precision"] == 1.0
        assert result.scores["recall"] == 1.0
        assert result.scores["f1_score"] == 1.0

    def test_no_match(self) -> None:
        """Test when no tags match."""
        metric = TagAccuracyMetric()
        result = metric.evaluate(
            suggested_tags=["ai", "ml"],
            expected_tags=["web", "html"],
        )

        assert result.scores["precision"] == 0.0
        assert result.scores["recall"] == 0.0
        assert result.scores["f1_score"] == 0.0

    def test_partial_match(self) -> None:
        """Test partial tag overlap."""
        metric = TagAccuracyMetric()
        result = metric.evaluate(
            suggested_tags=["ai", "ml", "web"],  # 2/3 correct
            expected_tags=["ai", "ml", "python"],  # Missing python
        )

        # Precision: 2/3 (suggested that are correct)
        assert result.scores["precision"] == pytest.approx(2 / 3)
        # Recall: 2/3 (expected that were found)
        assert result.scores["recall"] == pytest.approx(2 / 3)
        # F1: harmonic mean = 2/3
        assert result.scores["f1_score"] == pytest.approx(2 / 3)

    def test_high_precision_low_recall(self) -> None:
        """Test case with high precision but low recall."""
        metric = TagAccuracyMetric()
        result = metric.evaluate(
            suggested_tags=["ai"],  # Only 1 tag, but correct
            expected_tags=["ai", "ml", "python", "deep-learning"],  # 4 expected
        )

        # Precision: 1/1 = 1.0 (all suggested are correct)
        assert result.scores["precision"] == 1.0
        # Recall: 1/4 = 0.25 (only found 1 of 4)
        assert result.scores["recall"] == pytest.approx(0.25)

    def test_low_precision_high_recall(self) -> None:
        """Test case with low precision but high recall."""
        metric = TagAccuracyMetric()
        result = metric.evaluate(
            suggested_tags=["ai", "ml", "web", "html", "css"],  # 5 tags, 2 correct
            expected_tags=["ai", "ml"],  # Only 2 expected
        )

        # Precision: 2/5 = 0.4 (only 2 of 5 suggested are correct)
        assert result.scores["precision"] == pytest.approx(0.4)
        # Recall: 2/2 = 1.0 (found all expected)
        assert result.scores["recall"] == 1.0

    def test_case_insensitive(self) -> None:
        """Test that comparison is case insensitive."""
        metric = TagAccuracyMetric()
        result = metric.evaluate(
            suggested_tags=["AI", "ML", "Python"],
            expected_tags=["ai", "ml", "python"],
        )

        assert result.scores["precision"] == 1.0
        assert result.scores["recall"] == 1.0
        assert result.scores["f1_score"] == 1.0

    def test_whitespace_handling(self) -> None:
        """Test that whitespace is stripped."""
        metric = TagAccuracyMetric()
        result = metric.evaluate(
            suggested_tags=["  ai  ", " ml", "python "],
            expected_tags=["ai", "ml", "python"],
        )

        assert result.scores["precision"] == 1.0
        assert result.scores["recall"] == 1.0

    def test_no_expected_tags(self) -> None:
        """Test behavior when no expected tags provided."""
        metric = TagAccuracyMetric()
        result = metric.evaluate(
            suggested_tags=["ai", "ml"],
            expected_tags=None,
        )

        # Precision is 1.0 (assume all correct)
        assert result.scores["precision"] == 1.0
        # Recall is 0.0 (can't compute)
        assert result.scores["recall"] == 0.0
        # F1 is 0.0 (can't compute)
        assert result.scores["f1_score"] == 0.0
        assert result.details is not None
        assert "note" in result.details

    def test_empty_expected_tags(self) -> None:
        """Test behavior when expected tags is empty list."""
        metric = TagAccuracyMetric()
        result = metric.evaluate(
            suggested_tags=["ai", "ml"],
            expected_tags=[],
        )

        # Same as None - no expected tags to compare against
        assert result.scores["precision"] == 1.0
        assert result.scores["recall"] == 0.0
        assert result.scores["f1_score"] == 0.0

    def test_empty_suggested_tags(self) -> None:
        """Test behavior when no tags are suggested."""
        metric = TagAccuracyMetric()
        result = metric.evaluate(
            suggested_tags=[],
            expected_tags=["ai", "ml"],
        )

        # Precision: 0/0 = 0.0 (no tags to evaluate)
        assert result.scores["precision"] == 0.0
        # Recall: 0/2 = 0.0 (missed all expected)
        assert result.scores["recall"] == 0.0
        assert result.scores["f1_score"] == 0.0

    def test_details_included(self) -> None:
        """Test that detailed breakdown is included."""
        metric = TagAccuracyMetric()
        result = metric.evaluate(
            suggested_tags=["ai", "ml", "web"],
            expected_tags=["ai", "python"],
        )

        assert result.details is not None
        assert "true_positives" in result.details
        assert "ai" in result.details["true_positives"]
        assert "false_positives" in result.details
        false_pos = result.details["false_positives"]
        assert "ml" in false_pos or "web" in false_pos
        assert "false_negatives" in result.details
        assert "python" in result.details["false_negatives"]


class TestContentTypeAccuracyMetric:
    """Tests for ContentTypeAccuracyMetric class."""

    def test_exact_match(self) -> None:
        """Test when content type matches exactly."""
        metric = ContentTypeAccuracyMetric()
        result = metric.evaluate(
            predicted_type="article",
            expected_type="article",
        )

        assert result.scores["accuracy"] == 1.0
        assert result.details is not None
        assert result.details["match"] is True

    def test_no_match(self) -> None:
        """Test when content type doesn't match."""
        metric = ContentTypeAccuracyMetric()
        result = metric.evaluate(
            predicted_type="article",
            expected_type="tutorial",
        )

        assert result.scores["accuracy"] == 0.0
        assert result.details is not None
        assert result.details["match"] is False

    def test_case_insensitive(self) -> None:
        """Test that comparison is case insensitive."""
        metric = ContentTypeAccuracyMetric()
        result = metric.evaluate(
            predicted_type="ARTICLE",
            expected_type="article",
        )

        assert result.scores["accuracy"] == 1.0

    def test_whitespace_handling(self) -> None:
        """Test that whitespace is stripped."""
        metric = ContentTypeAccuracyMetric()
        result = metric.evaluate(
            predicted_type="  article  ",
            expected_type="article",
        )

        assert result.scores["accuracy"] == 1.0

    def test_no_expected_type(self) -> None:
        """Test behavior when no expected type provided."""
        metric = ContentTypeAccuracyMetric()
        result = metric.evaluate(
            predicted_type="article",
            expected_type=None,
        )

        # Assume correct if no expectation
        assert result.scores["accuracy"] == 1.0
        assert result.details is not None
        assert "note" in result.details

    def test_details_included(self) -> None:
        """Test that details are included."""
        metric = ContentTypeAccuracyMetric()
        result = metric.evaluate(
            predicted_type="tutorial",
            expected_type="article",
        )

        assert result.details is not None
        assert result.details["predicted_type"] == "tutorial"
        assert result.details["expected_type"] == "article"
        assert result.details["match"] is False


class TestEvaluateSummaryResult:
    """Tests for evaluate_summary_result convenience function."""

    def test_returns_all_metrics(self) -> None:
        """Test that all metrics are returned."""
        results = evaluate_summary_result(
            summary_content="A test summary.",
            summary_tags=["ai", "ml"],
            summary_content_type="article",
            expected_tags=["ai", "ml"],
            expected_content_type="article",
        )

        assert "tag_accuracy" in results
        assert "content_type_accuracy" in results

    def test_perfect_scores(self) -> None:
        """Test with perfectly matching results."""
        results = evaluate_summary_result(
            summary_content="A test summary.",
            summary_tags=["ai", "ml", "python"],
            summary_content_type="tutorial",
            expected_tags=["ai", "ml", "python"],
            expected_content_type="tutorial",
        )

        assert results["tag_accuracy"].primary_score == 1.0
        assert results["content_type_accuracy"].primary_score == 1.0

    def test_zero_scores(self) -> None:
        """Test with completely wrong results."""
        results = evaluate_summary_result(
            summary_content="A test summary.",
            summary_tags=["web", "html"],
            summary_content_type="news",
            expected_tags=["ai", "ml"],
            expected_content_type="article",
        )

        assert results["tag_accuracy"].primary_score == 0.0
        assert results["content_type_accuracy"].primary_score == 0.0

    def test_no_expectations(self) -> None:
        """Test when no expected values provided."""
        results = evaluate_summary_result(
            summary_content="A test summary.",
            summary_tags=["ai", "ml"],
            summary_content_type="article",
        )

        # Should return results without errors
        assert "tag_accuracy" in results
        assert "content_type_accuracy" in results
        # Defaults to "assume correct" when no expectations
        assert results["content_type_accuracy"].primary_score == 1.0

    def test_with_url_logging(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that URL is logged when provided."""
        import logging

        with caplog.at_level(logging.INFO):
            evaluate_summary_result(
                summary_content="A test summary.",
                summary_tags=["ai"],
                summary_content_type="article",
                expected_tags=["ai"],
                expected_content_type="article",
                url="https://example.com/article",
            )

        assert "example.com" in caplog.text
