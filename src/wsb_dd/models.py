"""Core data models shared across the pipeline.

These dataclasses are the contract between modules: the reddit client emits
``RedditPost``, the aggregator emits ``TickerStat``, and ``RunMeta`` carries
per-execution metadata into storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

REDDIT_BASE_URL = "https://www.reddit.com"

#: selftext sentinels Reddit uses for removed/deleted bodies.
_EMPTY_BODY_SENTINELS = frozenset({"[removed]", "[deleted]", ""})


@dataclass(frozen=True)
class RedditPost:
    """A single DD submission, normalized from a PRAW ``Submission``."""

    id: str
    title: str
    author: str  # "[deleted]" when the author account is gone
    created_utc: float  # epoch seconds, UTC
    score: int
    num_comments: int
    permalink: str  # relative, e.g. "/r/wallstreetbets/comments/abc/title/"
    selftext: str
    flair: str | None = None

    @property
    def full_permalink(self) -> str:
        """Absolute URL to the post."""
        return f"{REDDIT_BASE_URL}{self.permalink}"

    @property
    def body(self) -> str:
        """Selftext, normalized to '' for removed/deleted/empty posts."""
        return "" if self.selftext.strip().lower() in _EMPTY_BODY_SENTINELS else self.selftext

    @property
    def search_text(self) -> str:
        """Combined title + body that the extractor scans."""
        return f"{self.title}\n{self.body}"


@dataclass
class TickerStat:
    """Aggregated metrics for one ticker across a run."""

    ticker: str
    distinct_posts: int
    total_mentions: int
    score_weighted: int  # sum of post scores across the distinct posts
    first_seen: float  # epoch seconds, UTC (earliest post created_utc)
    last_seen: float  # epoch seconds, UTC (latest post created_utc)
    permalinks: list[str] = field(default_factory=list)


@dataclass
class RunMeta:
    """Metadata describing a single execution of the scraper."""

    run_uuid: str
    started_at: datetime  # UTC
    subreddit: str
    sort: str
    time_filter: str | None
    post_limit: int | None
    min_score: int
    flair_mode: str
    posts_scanned: int = 0
    posts_matched: int = 0
    universe_size: int | None = None
    finished_at: datetime | None = None  # UTC, set on success
