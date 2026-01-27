"""
Shared constants for the summarize-links application.

This module provides commonly used constants across the application,
including URL patterns, tracking parameters, and other configuration values.
"""

import re

__all__ = [
    # URL patterns
    "MARKDOWN_LINK_PATTERN",
    "BARE_URL_PATTERN",
    "CHAT_URL_PATTERN",
    "COMMON_TLDS",
    # URL cleaning
    "TRACKING_PARAMS",
    "NOISE_FRAGMENTS",
    "MEANINGFUL_PARAMS",
    # Hashtag patterns
    "HASHTAG_PATTERN",
]

# ----- Common TLDs -----
COMMON_TLDS = r"com|org|net|io|dev|co|edu|gov|info|app|ai|me|xyz"

# ----- URL Extraction Patterns -----

# Pattern to match Markdown links: [text](url)
MARKDOWN_LINK_PATTERN = r"\[([^\]]+)\]\((https?://[^)]+)\)"

# Pattern to match bare URLs (not inside Markdown link syntax)
# Matches http:// or https:// followed by non-whitespace, non-bracket characters
BARE_URL_PATTERN = r"(?<!\()(https?://[^\s\[\]()]+)(?!\))"

# Chat tool URL pattern (more lenient, matches bare domains)
# Used in chat interface for extracting URLs from conversational text
CHAT_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"')\]]+"  # Full URLs with protocol
    r"|(?:www\.)[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:/[^\s<>\"')\]]*)?"  # www.
    r"|[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}/[^\s<>\"')\]]*"  # Domain with path
    rf"|[a-zA-Z0-9][-a-zA-Z0-9]*\.(?:{COMMON_TLDS})",  # Bare domain
    re.IGNORECASE,
)

# ----- Hashtag Pattern -----

# Pattern to match hashtags (Obsidian-style tags)
# Matches #tag but not ## headers or # in URLs
HASHTAG_PATTERN = re.compile(r"(?<!\S)#([a-zA-Z][a-zA-Z0-9_-]*)", re.UNICODE)

# ----- URL Cleaning -----

# Query parameters to strip (tracking, analytics, etc.)
TRACKING_PARAMS = {
    # UTM tracking (Google Analytics)
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    # Social/referrer tracking
    "ref",
    "ref_src",
    "ref_url",
    "source",
    "fbclid",  # Facebook
    "gclid",  # Google Ads
    "msclkid",  # Microsoft Ads
    "twclid",  # Twitter
    "igshid",  # Instagram
    # Mobile/app tracking
    "m",  # Blogspot mobile
    # Session/paywall tokens
    "st",
    "token",
    # Misc
    "share",
    "s",  # Some sharing params
}

# URL fragments to strip (RSS noise, etc.)
NOISE_FRAGMENTS = {
    "atom-everything",
    "rss",
}

# Domains where certain params are meaningful and should be kept
MEANINGFUL_PARAMS = {
    "youtube.com": {"v", "t", "list", "index"},
    "youtu.be": {"t"},
    "github.com": {"tab", "q"},
    "twitter.com": {"s"},  # Tweet ID context
    "x.com": {"s"},
}
