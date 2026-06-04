"""Command-line entrypoint: scrape DD posts -> extract tickers -> CSV/MySQL."""

from __future__ import annotations

import argparse
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .aggregator import Aggregator
from .config import (
    ConfigError,
    load_env,
    load_mysql_config,
    load_reddit_credentials,
)
from .extractor import ExtractorConfig, TickerExtractor, load_blocklist
from .logging_setup import setup_logging
from .models import RunMeta
from .universe import UniverseLoader, UniverseScope

DEFAULT_BLOCKLIST = "config/slang_blocklist.txt"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wsb-dd",
        description="Scrape r/wallstreetbets DD posts and extract validated US tickers.",
    )
    parser.add_argument("--version", action="version", version=f"wsb-dd {__version__}")

    parser.add_argument("--subreddit", default="wallstreetbets", help="Subreddit to scan.")
    parser.add_argument("--sort", choices=("new", "hot", "top"), default="new")
    parser.add_argument(
        "--time-filter",
        choices=("day", "week", "month", "year", "all"),
        default="week",
        help="Used only with --sort top.",
    )
    parser.add_argument("--limit", type=int, default=100, help="Max submissions to fetch.")
    parser.add_argument("--min-score", type=int, default=0, help="Skip posts below this score.")
    parser.add_argument(
        "--flair-mode",
        choices=("exact", "contains"),
        default="exact",
        help="exact: flair == 'DD' (case-insensitive); contains: 'DD' substring.",
    )

    parser.add_argument("--out", default=None, help="CSV output path (default: out/dd_tickers_<ts>.csv).")
    parser.add_argument("--cache-dir", default=".cache", help="Where NASDAQ symbol files are cached.")
    parser.add_argument("--universe-max-age-days", type=int, default=7)
    parser.add_argument(
        "--universe-scope",
        choices=tuple(s.value for s in UniverseScope),
        default=UniverseScope.COMMON_ETF.value,
    )
    parser.add_argument("--blocklist", default=DEFAULT_BLOCKLIST, help="Editable slang/stopword file.")
    parser.add_argument(
        "--allow-single-char-bare",
        action="store_true",
        help="Allow bare 1-char tickers (e.g. F, T). $F always works regardless.",
    )

    parser.add_argument("--mysql", action="store_true", help="Also upsert results into MySQL.")
    parser.add_argument("--dotenv", default=None, help="Path to a .env file (default: auto-discover).")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    return parser


def _default_out_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Path("out") / f"dd_tickers_{stamp}.csv"


def run(args: argparse.Namespace, log: logging.Logger) -> int:
    load_env(args.dotenv)

    # 1. Reddit credentials (fail fast before any network work).
    credentials = load_reddit_credentials()

    # 2. Ticker universe (download/cache/refresh).
    universe = UniverseLoader(
        Path(args.cache_dir),
        max_age_days=args.universe_max_age_days,
        scope=UniverseScope(args.universe_scope),
    ).load()

    # 3. Extractor (universe + editable blocklist + balanced defaults).
    blocklist_path = Path(args.blocklist)
    if blocklist_path.exists():
        blocklist = load_blocklist(blocklist_path)
    else:
        log.warning("blocklist_missing", extra={"path": str(blocklist_path)})
        blocklist = set()
    extractor = TickerExtractor(
        universe,
        blocklist,
        ExtractorConfig(allow_single_char_bare=args.allow_single_char_bare),
    )

    # 4. Fetch DD posts.
    from .reddit_client import RedditClient  # lazy import (needs praw)

    run_meta = RunMeta(
        run_uuid=str(uuid.uuid4()),
        started_at=datetime.now(timezone.utc),
        subreddit=args.subreddit,
        sort=args.sort,
        time_filter=args.time_filter if args.sort == "top" else None,
        post_limit=args.limit,
        min_score=args.min_score,
        flair_mode=args.flair_mode,
        universe_size=len(universe),
    )

    client = RedditClient(credentials)
    fetched = client.fetch_dd_posts(
        subreddit=args.subreddit,
        sort=args.sort,
        time_filter=args.time_filter,
        limit=args.limit,
        min_score=args.min_score,
        flair_mode=args.flair_mode,
    )
    run_meta.posts_scanned = fetched.scanned
    run_meta.posts_matched = len(fetched.posts)

    # 5. Aggregate.
    aggregator = Aggregator()
    for post in fetched.posts:
        aggregator.add_post(post, extractor.extract(post.search_text))
    stats = aggregator.results()
    run_meta.finished_at = datetime.now(timezone.utc)

    if not stats:
        log.warning("no_tickers_found", extra={"matched_posts": len(fetched.posts)})

    # 6. Output: CSV (always) + MySQL (optional).
    from .storage.csv_writer import write_csv  # lazy import

    out_path = Path(args.out) if args.out else _default_out_path()
    write_csv(out_path, stats)

    if args.mysql:
        from .storage.mysql_store import MySQLStore  # lazy import (needs pymysql)

        mysql_config = load_mysql_config()
        with MySQLStore(mysql_config) as store:
            store.ensure_schema()
            store.record_run(run_meta, stats)

    for stat in stats[:10]:
        log.info(
            "ticker",
            extra={
                "symbol": stat.ticker,
                "posts": stat.distinct_posts,
                "mentions": stat.total_mentions,
                "score_weighted": stat.score_weighted,
            },
        )
    log.info(
        "done",
        extra={
            "tickers": len(stats),
            "posts_matched": run_meta.posts_matched,
            "posts_scanned": run_meta.posts_scanned,
            "out": str(out_path),
        },
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = setup_logging(args.log_level)
    try:
        return run(args, log)
    except ConfigError as exc:
        log.error("config_error", extra={"detail": str(exc)})
        return 2
    except KeyboardInterrupt:
        log.error("interrupted")
        return 130
    except Exception as exc:  # noqa: BLE001 - top-level guard, log and exit non-zero
        log.exception("fatal", extra={"error": repr(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
