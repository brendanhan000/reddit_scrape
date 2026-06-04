"""CSV output for aggregated ticker results."""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from ..models import TickerStat

log = logging.getLogger("wsb_dd.csv")

CSV_COLUMNS = [
    "ticker",
    "distinct_posts",
    "total_mentions",
    "score_weighted",
    "first_seen",
    "last_seen",
    "permalinks",
]


def _iso(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def write_csv(path: str | Path, stats: Sequence[TickerStat]) -> Path:
    """Write ``stats`` to ``path`` as CSV; returns the resolved path."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for stat in stats:
            writer.writerow(
                [
                    stat.ticker,
                    stat.distinct_posts,
                    stat.total_mentions,
                    stat.score_weighted,
                    _iso(stat.first_seen),
                    _iso(stat.last_seen),
                    " ".join(stat.permalinks),
                ]
            )
    log.info("wrote_csv", extra={"path": str(out_path), "rows": len(stats)})
    return out_path
