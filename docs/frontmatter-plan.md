# Obsidian Frontmatter Enhancement - Implementation Plan

## Overview

Enhance summary notes with rich, useful frontmatter for better discoverability and linking in Obsidian.

## Target Frontmatter Structure

```yaml
---
source: https://example.com/article
title: "Article Title Here"
author: "John Smith"
type: article
date: 2025-12-15
status: success
from: "[[2025-12-15]]"
tags:
  - ai              # from user's daily note
  - machine-learning # from article meta/content
  - transformers    # from Gemini suggestion
---
```

## Essential Fields

| Field | Source | Required |
|-------|--------|----------|
| `source` | URL being summarized | Yes |
| `title` | HTML `<title>` or og:title | Yes |
| `author` | HTML meta or schema.org | Yes (if available) |
| `type` | Gemini classification | Yes |
| `date` | Processing date | Yes |
| `status` | success/error | Yes |
| `from` | Source daily note | Yes (if from daily note) |
| `tags` | Merged from 3 sources | Yes |

## Tag Sources (Priority Order)

| Priority | Source | Example | Description |
|----------|--------|---------|-------------|
| 1 (Highest) | User tags | `#ai #interesting` next to URL | User intent from daily note |
| 2 | Article tags | `<meta name="keywords">` | Author's categorization |
| 3 | Gemini suggestions | AI-inferred topics | Fill gaps intelligently |

Tags are merged, deduplicated, and normalized (lowercase, hyphenated).

## Data Models

### UrlWithContext
```python
@dataclass
class UrlWithContext:
    url: str
    tags: list[str]      # hashtags from daily note line
    context_text: str    # surrounding text for reference
```

### PageMetadata
```python
@dataclass
class PageMetadata:
    title: str
    author: str | None
    description: str | None
    published_date: str | None
    domain: str
    article_tags: list[str]  # from HTML meta tags
    content: str
```

### SummaryResult
```python
@dataclass
class SummaryResult:
    content: str              # markdown summary
    suggested_tags: list[str] # from Gemini
    content_type: str         # article, tutorial, docs, news, video, tool, other
```

## Implementation Phases

### Phase 1: Data Models (`models.py`)
- [ ] Create `UrlWithContext` dataclass
- [ ] Create `PageMetadata` dataclass
- [ ] Create `SummaryResult` dataclass

### Phase 2: URL + Tag Extraction (`notes.py`)
- [ ] New `extract_urls_with_context()` function
- [ ] Parse `#hashtags` from URL's line in daily note
- [ ] Return structured `UrlWithContext` objects
- [ ] Unit tests for tag extraction

### Phase 3: HTML Metadata Extraction (`extract.py`)
- [ ] Extract `<meta name="keywords">`
- [ ] Extract `<meta property="article:tag">`
- [ ] Extract `<meta name="author">` / `article:author`
- [ ] Extract hashtags from article content
- [ ] Return `PageMetadata` object
- [ ] Unit tests for metadata extraction

### Phase 4: Gemini Structured Output (`gemini_client.py`)
- [ ] Update prompt to request JSON response
- [ ] Parse `summary`, `suggested_tags`, `content_type`
- [ ] Handle fallback for malformed responses
- [ ] Update `MockGeminiClient` for testing
- [ ] Unit tests for JSON parsing

### Phase 5: Frontmatter Builder (`notes.py`)
- [ ] New `build_frontmatter()` function
- [ ] Tag merging with deduplication
- [ ] Tag normalization (lowercase, hyphenate)
- [ ] Proper YAML escaping for strings
- [ ] Unit tests for frontmatter building

### Phase 6: Integration (`cli.py`)
- [ ] Update pipeline to pass metadata through
- [ ] Wire `UrlWithContext` → extraction → Gemini → frontmatter
- [ ] Integration tests

### Phase 7: Configuration (`config.py`)
- [ ] `default_tags: list[str]` - always-add tags
- [ ] `max_tags: int` - limit total (default: 10)

## Example Flow

**Input (daily note line):**
```markdown
- [Attention Is All You Need](https://arxiv.org/abs/1706.03762) #ai #papers
```

**HTML metadata:**
```
author: "Vaswani et al."
keywords: ["transformers", "attention", "neural networks"]
```

**Gemini response:**
```json
{
  "summary": "## Overview\n...",
  "suggested_tags": ["deep-learning", "nlp", "architecture"],
  "content_type": "article"
}
```

**Output frontmatter:**
```yaml
---
source: https://arxiv.org/abs/1706.03762
title: "Attention Is All You Need"
author: "Vaswani et al."
type: article
date: 2025-12-15
status: success
from: "[[2025-12-15]]"
tags:
  - ai
  - papers
  - transformers
  - attention
  - deep-learning
  - nlp
---
```

## Estimated Timeline

| Phase | Task | Est. Time |
|-------|------|-----------|
| 1 | Data models | 20 min |
| 2 | URL+tag extraction | 50 min |
| 3 | HTML metadata extraction | 65 min |
| 4 | Gemini structured output | 60 min |
| 5 | Frontmatter builder | 55 min |
| 6 | CLI integration | 30 min |
| 7 | Configuration | 10 min |
| **Total** | | **~5 hours** |
