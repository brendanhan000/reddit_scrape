"""Per-ticker aggregation across DD posts."""

from __future__ import annotations

from collections import Counter
from typing import Sequence

from .models import RedditPost, TickerStat


class Aggregator:
    """Accumulates per-ticker metrics as posts are added.

    Metrics tracked per ticker:
      * distinct_posts  - unique posts mentioning it
      * total_mentions  - raw occurrences across all title+selftext
      * score_weighted  - sum of post scores across the distinct posts
      * first/last seen - min/max post created_utc
      * permalinks      - source posts
    """

    def __init__(self) -> None:
        self._distinct_posts: Counter[str] = Counter()
        self._total_mentions: Counter[str] = Counter()
        self._score_weighted: Counter[str] = Counter()
        self._first_seen: dict[str, float] = {}
        self._last_seen: dict[str, float] = {}
        self._permalinks: dict[str, list[str]] = {}
        self._posts_added = 0

    @property
    def posts_added(self) -> int:
        return self._posts_added

    def add_post(self, post: RedditPost, occurrences: Sequence[str]) -> None:
        """Fold one post's ticker occurrences into the running totals."""
        self._posts_added += 1
        if not occurrences:
            return

        per_post = Counter(symbol.upper() for symbol in occurrences)
        for ticker, count in per_post.items():
            self._total_mentions[ticker] += count
            self._distinct_posts[ticker] += 1
            self._score_weighted[ticker] += post.score
            self._permalinks.setdefault(ticker, []).append(post.full_permalink)

            created = post.created_utc
            if ticker not in self._first_seen or created < self._first_seen[ticker]:
                self._first_seen[ticker] = created
            if ticker not in self._last_seen or created > self._last_seen[ticker]:
                self._last_seen[ticker] = created

    def results(self) -> list[TickerStat]:
        """Return stats sorted by score_weighted desc (the 'post-weighted' metric).

        Ties broken by distinct_posts, then total_mentions (desc), then ticker (asc).
        """
        stats = [
            TickerStat(
                ticker=ticker,
                distinct_posts=self._distinct_posts[ticker],
                total_mentions=self._total_mentions[ticker],
                score_weighted=self._score_weighted[ticker],
                first_seen=self._first_seen[ticker],
                last_seen=self._last_seen[ticker],
                permalinks=list(self._permalinks[ticker]),
            )
            for ticker in self._distinct_posts
        ]
        # Stable two-pass sort: ticker asc first, then the numeric keys desc.
        stats.sort(key=lambda s: s.ticker)
        stats.sort(
            key=lambda s: (s.score_weighted, s.distinct_posts, s.total_mentions),
            reverse=True,
        )
        return stats
