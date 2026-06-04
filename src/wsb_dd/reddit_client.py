"""PRAW-based Reddit client: fetch DD-flaired submissions with backoff.

PRAW itself honors Reddit's rate limits (and sleeps up to ``ratelimit_seconds``
on 429s when configured). On top of that we add explicit exponential backoff and
a resumable retry that rebuilds the listing and de-dupes by submission id, so a
transient 5xx/network blip mid-listing doesn't abort the run.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Iterator

from .config import RedditCredentials
from .models import RedditPost

log = logging.getLogger("wsb_dd.reddit")

VALID_SORTS = ("new", "hot", "top")


@dataclass
class FetchResult:
    """Posts that matched, plus how many submissions were scanned."""

    posts: list[RedditPost] = field(default_factory=list)
    scanned: int = 0


def flair_matches(flair: str | None, mode: str) -> bool:
    """True if ``flair`` is a DD flair under ``mode`` ('exact' or 'contains')."""
    if not flair:
        return False
    normalized = flair.strip().lower()
    if mode == "contains":
        return "dd" in normalized
    return normalized == "dd"


def _author_name(submission: object) -> str:
    author = getattr(submission, "author", None)
    if author is None:  # deleted/suspended account
        return "[deleted]"
    return getattr(author, "name", "[deleted]")


def submission_to_post(submission: object) -> RedditPost:
    """Normalize a PRAW ``Submission`` into a :class:`RedditPost`."""
    return RedditPost(
        id=str(submission.id),
        title=submission.title or "",
        author=_author_name(submission),
        created_utc=float(submission.created_utc),
        score=int(submission.score),
        num_comments=int(submission.num_comments),
        permalink=str(submission.permalink),
        selftext=submission.selftext or "",
        flair=submission.link_flair_text,
    )


class RedditClient:
    """Thin wrapper around a read-only PRAW client."""

    def __init__(
        self,
        credentials: RedditCredentials,
        *,
        ratelimit_seconds: int = 300,
        max_retries: int = 5,
        backoff_base: float = 2.0,
        max_backoff: float = 60.0,
    ) -> None:
        import praw  # lazy: only needed when actually hitting Reddit

        self._reddit = praw.Reddit(
            client_id=credentials.client_id,
            client_secret=credentials.client_secret,
            user_agent=credentials.user_agent,
            ratelimit_seconds=ratelimit_seconds,
            check_for_updates=False,
        )
        self._reddit.read_only = True
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.max_backoff = max_backoff

    def _make_listing(self, subreddit: str, sort: str, time_filter: str, limit: int):
        sub = self._reddit.subreddit(subreddit)
        if sort == "new":
            return sub.new(limit=limit)
        if sort == "hot":
            return sub.hot(limit=limit)
        return sub.top(time_filter=time_filter, limit=limit)

    def _sleep_for(self, exc: Exception, attempt: int) -> float:
        retry_after = getattr(getattr(exc, "response", None), "headers", {})
        if isinstance(retry_after, dict):
            header = retry_after.get("Retry-After") or retry_after.get("retry-after")
            if header:
                try:
                    return min(float(header), self.max_backoff)
                except (TypeError, ValueError):
                    pass
        return min(self.backoff_base ** attempt, self.max_backoff)

    def _iter_submissions(
        self, subreddit: str, sort: str, time_filter: str, limit: int
    ) -> Iterator[object]:
        """Yield submissions, retrying transient errors with backoff + de-dupe."""
        import prawcore

        seen: set[str] = set()
        attempt = 0
        while True:
            listing = self._make_listing(subreddit, sort, time_filter, limit)
            try:
                for submission in listing:
                    sid = str(submission.id)
                    if sid in seen:
                        continue
                    seen.add(sid)
                    yield submission
                return
            except prawcore.PrawcoreException as exc:
                attempt += 1
                if attempt > self.max_retries:
                    log.error(
                        "reddit_giving_up",
                        extra={"attempts": attempt, "error": repr(exc)},
                    )
                    raise
                sleep_s = self._sleep_for(exc, attempt)
                log.warning(
                    "reddit_retry",
                    extra={"attempt": attempt, "sleep_s": round(sleep_s, 1), "error": repr(exc)},
                )
                time.sleep(sleep_s)

    def fetch_dd_posts(
        self,
        *,
        subreddit: str,
        sort: str,
        time_filter: str,
        limit: int,
        min_score: int,
        flair_mode: str,
    ) -> FetchResult:
        """Fetch DD-flaired posts, applying flair + min-score filters."""
        sort = sort.lower()
        if sort not in VALID_SORTS:
            raise ValueError(f"sort must be one of {VALID_SORTS}, got {sort!r}")

        result = FetchResult()
        for submission in self._iter_submissions(subreddit, sort, time_filter, limit):
            result.scanned += 1
            try:
                if not flair_matches(submission.link_flair_text, flair_mode):
                    continue
                if int(submission.score) < min_score:
                    log.debug(
                        "skip_low_score",
                        extra={"id": str(submission.id), "score": int(submission.score)},
                    )
                    continue
                post = submission_to_post(submission)
            except Exception as exc:  # one bad submission shouldn't kill the run
                log.warning(
                    "skip_bad_submission",
                    extra={"id": getattr(submission, "id", "?"), "error": repr(exc)},
                )
                continue
            result.posts.append(post)

        log.info(
            "fetch_complete",
            extra={
                "scanned": result.scanned,
                "matched": len(result.posts),
                "sort": sort,
            },
        )
        return result
