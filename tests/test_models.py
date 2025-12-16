"""Tests for data models and tag utilities."""

import pytest

from summarize_links.models import (
    CONTENT_TYPES,
    PageMetadata,
    SummaryResult,
    UrlWithContext,
    merge_tags,
    normalize_tag,
)


class TestUrlWithContext:
    """Tests for UrlWithContext dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating a UrlWithContext with all fields."""
        url_ctx = UrlWithContext(
            url="https://example.com",
            tags=["ai", "ml"],
            context_text="Check out this #ai #ml article",
        )
        assert url_ctx.url == "https://example.com"
        assert url_ctx.tags == ["ai", "ml"]
        assert "ai" in url_ctx.context_text

    def test_defaults(self) -> None:
        """Test that defaults are applied correctly."""
        url_ctx = UrlWithContext(url="https://example.com")
        assert url_ctx.tags == []
        assert url_ctx.context_text == ""


class TestPageMetadata:
    """Tests for PageMetadata dataclass."""

    def test_required_fields(self) -> None:
        """Test creating PageMetadata with required fields only."""
        meta = PageMetadata(
            title="Test Article",
            domain="example.com",
            content="Article content here",
        )
        assert meta.title == "Test Article"
        assert meta.domain == "example.com"
        assert meta.author is None
        assert meta.article_tags == []

    def test_all_fields(self) -> None:
        """Test creating PageMetadata with all fields."""
        meta = PageMetadata(
            title="Test Article",
            domain="example.com",
            content="Content",
            author="John Smith",
            description="A test article",
            published_date="2025-12-15",
            site_name="Example Site",
            article_tags=["python", "testing"],
        )
        assert meta.author == "John Smith"
        assert meta.published_date == "2025-12-15"
        assert meta.article_tags == ["python", "testing"]


class TestSummaryResult:
    """Tests for SummaryResult dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating a SummaryResult."""
        result = SummaryResult(
            content="## Summary\nThis is a summary.",
            suggested_tags=["ai", "ml"],
            content_type="article",
        )
        assert "Summary" in result.content
        assert result.suggested_tags == ["ai", "ml"]
        assert result.content_type == "article"

    def test_defaults(self) -> None:
        """Test default values."""
        result = SummaryResult(content="Summary text")
        assert result.suggested_tags == []
        assert result.content_type == "article"

    def test_content_types_constant(self) -> None:
        """Test that CONTENT_TYPES contains expected values."""
        assert "article" in CONTENT_TYPES
        assert "tutorial" in CONTENT_TYPES
        assert "documentation" in CONTENT_TYPES
        assert "video" in CONTENT_TYPES


class TestNormalizeTag:
    """Tests for normalize_tag function."""

    def test_removes_hash_prefix(self) -> None:
        """Test that # prefix is removed."""
        assert normalize_tag("#python") == "python"
        assert normalize_tag("##double") == "double"

    def test_lowercase(self) -> None:
        """Test conversion to lowercase."""
        assert normalize_tag("Python") == "python"
        assert normalize_tag("UPPERCASE") == "uppercase"
        assert normalize_tag("MixedCase") == "mixedcase"

    def test_spaces_to_hyphens(self) -> None:
        """Test that spaces become hyphens."""
        assert normalize_tag("machine learning") == "machine-learning"
        assert normalize_tag("deep  learning") == "deep-learning"

    def test_underscores_to_hyphens(self) -> None:
        """Test that underscores become hyphens."""
        assert normalize_tag("machine_learning") == "machine-learning"

    def test_removes_special_chars(self) -> None:
        """Test removal of special characters."""
        assert normalize_tag("c++") == "c"
        assert normalize_tag("node.js") == "nodejs"
        assert normalize_tag("tag@name") == "tagname"

    def test_collapses_multiple_hyphens(self) -> None:
        """Test that multiple hyphens are collapsed."""
        assert normalize_tag("a--b---c") == "a-b-c"
        assert normalize_tag("hello - world") == "hello-world"

    def test_strips_edge_hyphens(self) -> None:
        """Test that leading/trailing hyphens are removed."""
        assert normalize_tag("-python-") == "python"
        assert normalize_tag("--test--") == "test"

    def test_empty_result(self) -> None:
        """Test that invalid tags become empty strings."""
        assert normalize_tag("###") == ""
        assert normalize_tag("---") == ""
        assert normalize_tag("@#$") == ""


class TestMergeTags:
    """Tests for merge_tags function."""

    def test_basic_merge(self) -> None:
        """Test basic merging of tags from different sources."""
        result = merge_tags(
            user_tags=["ai", "ml"],
            article_tags=["python", "data"],
            ai_tags=["deep-learning"],
        )
        assert result == ["ai", "ml", "python", "data", "deep-learning"]

    def test_deduplication(self) -> None:
        """Test that duplicate tags are removed."""
        result = merge_tags(
            user_tags=["ai", "ml"],
            article_tags=["AI", "python"],  # AI should dedupe
            ai_tags=["ml", "data"],  # ml should dedupe
        )
        assert result == ["ai", "ml", "python", "data"]

    def test_user_tags_priority(self) -> None:
        """Test that user tags take priority (appear first)."""
        result = merge_tags(
            user_tags=["important"],
            article_tags=["article-tag"],
            ai_tags=["ai-tag"],
        )
        assert result[0] == "important"

    def test_default_tags_first(self) -> None:
        """Test that default tags appear first."""
        result = merge_tags(
            user_tags=["user-tag"],
            article_tags=[],
            ai_tags=[],
            default_tags=["summarized"],
        )
        assert result[0] == "summarized"
        assert result[1] == "user-tag"

    def test_max_tags_limit(self) -> None:
        """Test that max_tags limit is respected."""
        result = merge_tags(
            user_tags=["a", "b", "c"],
            article_tags=["d", "e", "f"],
            ai_tags=["g", "h", "i"],
            max_tags=5,
        )
        assert len(result) == 5
        assert result == ["a", "b", "c", "d", "e"]

    def test_normalization_during_merge(self) -> None:
        """Test that tags are normalized during merge."""
        result = merge_tags(
            user_tags=["#Python", "Machine Learning"],
            article_tags=["DATA_SCIENCE"],
            ai_tags=[],
        )
        assert result == ["python", "machine-learning", "data-science"]

    def test_empty_sources(self) -> None:
        """Test handling of empty tag sources."""
        result = merge_tags(
            user_tags=[],
            article_tags=[],
            ai_tags=[],
        )
        assert result == []

    def test_filters_empty_normalized_tags(self) -> None:
        """Test that tags that normalize to empty are filtered out."""
        result = merge_tags(
            user_tags=["valid", "###", "---"],
            article_tags=["@#$", "good"],
            ai_tags=[],
        )
        assert result == ["valid", "good"]
