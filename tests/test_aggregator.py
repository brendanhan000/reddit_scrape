"""Tests for per-ticker aggregation and sorting."""

from __future__ import annotations

from wsb_dd.aggregator import Aggregator
from wsb_dd.models import RedditPost


def make_post(pid: str, score: int, created: float) -> RedditPost:
    return RedditPost(
        id=pid,
        title="title",
        author="user",
        created_utc=created,
        score=score,
        num_comments=0,
        permalink=f"/r/wallstreetbets/comments/{pid}/x/",
        selftext="",
    )


def test_metrics_and_sort_order() -> None:
    agg = Aggregator()
    agg.add_post(make_post("a", 50, 100.0), ["NVDA", "NVDA", "TSLA"])
    agg.add_post(make_post("b", 10, 200.0), ["NVDA"])

    by_ticker = {s.ticker: s for s in agg.results()}

    nvda = by_ticker["NVDA"]
    assert nvda.distinct_posts == 2
    assert nvda.total_mentions == 3
    assert nvda.score_weighted == 60  # 50 + 10
    assert nvda.first_seen == 100.0
    assert nvda.last_seen == 200.0

    tsla = by_ticker["TSLA"]
    assert tsla.distinct_posts == 1
    assert tsla.total_mentions == 1
    assert tsla.score_weighted == 50

    # Sorted by score_weighted desc -> NVDA (60) before TSLA (50).
    assert [s.ticker for s in agg.results()][0] == "NVDA"
    assert agg.posts_added == 2


def test_empty_occurrences_count_post_but_add_no_tickers() -> None:
    agg = Aggregator()
    agg.add_post(make_post("a", 5, 1.0), [])
    assert agg.results() == []
    assert agg.posts_added == 1


def test_permalinks_accumulate_across_posts() -> None:
    agg = Aggregator()
    agg.add_post(make_post("a", 5, 1.0), ["GME"])
    agg.add_post(make_post("b", 7, 2.0), ["GME"])
    (stat,) = agg.results()
    assert len(stat.permalinks) == 2
    assert all(p.startswith("https://www.reddit.com/r/wallstreetbets/") for p in stat.permalinks)


def test_tie_break_prefers_more_distinct_posts() -> None:
    agg = Aggregator()
    # Same score_weighted (20) but AAA appears in 2 posts, BBB in 1.
    agg.add_post(make_post("a", 10, 1.0), ["AAA"])
    agg.add_post(make_post("b", 10, 2.0), ["AAA"])
    agg.add_post(make_post("c", 20, 3.0), ["BBB"])
    order = [s.ticker for s in agg.results()]
    assert order.index("AAA") < order.index("BBB")
