"""MySQL sink: two-table, history-accumulating upsert.

  dd_runs            -> one row per execution (metadata + params)
  dd_ticker_mentions -> one row per (run_id, ticker)

Each execution gets a fresh ``run_id``, so prior runs are never overwritten.
Writes use INSERT ... ON DUPLICATE KEY UPDATE keyed on ``run_uuid`` /
(run_id, ticker) so re-running the same run is idempotent. PyMySQL is imported
lazily so non-MySQL runs need no DB driver.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Sequence

from ..config import MySQLConfig
from ..models import RunMeta, TickerStat

log = logging.getLogger("wsb_dd.mysql")

CREATE_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS dd_runs (
    run_id         BIGINT       NOT NULL AUTO_INCREMENT,
    run_uuid       CHAR(36)     NOT NULL,
    started_at     DATETIME     NOT NULL,
    finished_at    DATETIME     NULL,
    subreddit      VARCHAR(64)  NOT NULL,
    sort           VARCHAR(16)  NOT NULL,
    time_filter    VARCHAR(16)  NULL,
    post_limit     INT          NULL,
    min_score      INT          NOT NULL DEFAULT 0,
    flair_mode     VARCHAR(16)  NOT NULL DEFAULT 'exact',
    posts_scanned  INT          NOT NULL DEFAULT 0,
    posts_matched  INT          NOT NULL DEFAULT 0,
    universe_size  INT          NULL,
    PRIMARY KEY (run_id),
    UNIQUE KEY uq_run_uuid (run_uuid),
    KEY idx_started_at (started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

CREATE_MENTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS dd_ticker_mentions (
    run_id          BIGINT      NOT NULL,
    ticker          VARCHAR(8)  NOT NULL,
    distinct_posts  INT         NOT NULL,
    total_mentions  INT         NOT NULL,
    score_weighted  BIGINT      NOT NULL,
    first_seen      DATETIME    NOT NULL,
    last_seen       DATETIME    NOT NULL,
    permalinks      TEXT        NULL,
    PRIMARY KEY (run_id, ticker),
    CONSTRAINT fk_mentions_run
        FOREIGN KEY (run_id) REFERENCES dd_runs (run_id) ON DELETE CASCADE,
    KEY idx_ticker (ticker),
    KEY idx_ticker_seen (ticker, last_seen)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_INSERT_RUN = """
INSERT INTO dd_runs
    (run_uuid, started_at, finished_at, subreddit, sort, time_filter,
     post_limit, min_score, flair_mode, posts_scanned, posts_matched, universe_size)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    finished_at = VALUES(finished_at),
    posts_scanned = VALUES(posts_scanned),
    posts_matched = VALUES(posts_matched),
    universe_size = VALUES(universe_size)
"""

_INSERT_MENTION = """
INSERT INTO dd_ticker_mentions
    (run_id, ticker, distinct_posts, total_mentions, score_weighted,
     first_seen, last_seen, permalinks)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    distinct_posts = VALUES(distinct_posts),
    total_mentions = VALUES(total_mentions),
    score_weighted = VALUES(score_weighted),
    first_seen = VALUES(first_seen),
    last_seen = VALUES(last_seen),
    permalinks = VALUES(permalinks)
"""


def _epoch_to_dt(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _dt_str(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%d %H:%M:%S")


class MySQLStore:
    """Connection + idempotent two-table writer for run results."""

    def __init__(self, config: MySQLConfig) -> None:
        self.config = config
        self._conn = None

    def connect(self) -> "MySQLStore":
        import pymysql  # lazy: only needed with --mysql

        self._conn = pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            connect_timeout=self.config.connect_timeout,
            charset="utf8mb4",
            autocommit=False,
        )
        log.info("mysql_connected", extra={"host": self.config.host, "db": self.config.database})
        return self

    def __enter__(self) -> "MySQLStore":
        return self.connect()

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def ensure_schema(self) -> None:
        """Create the tables if they don't already exist."""
        assert self._conn is not None, "call connect() first"
        with self._conn.cursor() as cur:
            cur.execute(CREATE_RUNS_TABLE)
            cur.execute(CREATE_MENTIONS_TABLE)
        self._conn.commit()

    def record_run(self, run_meta: RunMeta, stats: Sequence[TickerStat]) -> int:
        """Insert the run row + its ticker rows in one transaction; return run_id."""
        assert self._conn is not None, "call connect() first"
        with self._conn.cursor() as cur:
            cur.execute(
                _INSERT_RUN,
                (
                    run_meta.run_uuid,
                    _dt_str(run_meta.started_at),
                    _dt_str(run_meta.finished_at),
                    run_meta.subreddit,
                    run_meta.sort,
                    run_meta.time_filter,
                    run_meta.post_limit,
                    run_meta.min_score,
                    run_meta.flair_mode,
                    run_meta.posts_scanned,
                    run_meta.posts_matched,
                    run_meta.universe_size,
                ),
            )
            cur.execute("SELECT run_id FROM dd_runs WHERE run_uuid = %s", (run_meta.run_uuid,))
            run_id = int(cur.fetchone()[0])

            rows = [
                (
                    run_id,
                    stat.ticker,
                    stat.distinct_posts,
                    stat.total_mentions,
                    stat.score_weighted,
                    _epoch_to_dt(stat.first_seen),
                    _epoch_to_dt(stat.last_seen),
                    " ".join(stat.permalinks),
                )
                for stat in stats
            ]
            if rows:
                cur.executemany(_INSERT_MENTION, rows)

        self._conn.commit()
        log.info("mysql_recorded", extra={"run_id": run_id, "tickers": len(stats)})
        return run_id
