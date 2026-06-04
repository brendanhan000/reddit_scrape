"""US-listed ticker universe loader.

Downloads the NASDAQ Trader symbol directory files, caches them locally, and
parses them into a validated set of tradable symbols. Extractor candidates are
only kept if they appear in this set.

  nasdaqlisted.txt : Symbol|Security Name|Market Category|Test Issue|
                     Financial Status|Round Lot Size|ETF|NextShares
  otherlisted.txt  : ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|
                     Round Lot Size|Test Issue|NASDAQ Symbol

Both files are pipe-delimited, carry a header row, and end with a
"File Creation Time" footer line that must be skipped.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

log = logging.getLogger("wsb_dd.universe")

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

NASDAQ_LISTED_FILE = "nasdaqlisted.txt"
OTHER_LISTED_FILE = "otherlisted.txt"

# Security-name keywords that mark non-common, non-ETF instruments. ADRs
# ("American Depositary Shares") are intentionally NOT matched so they survive.
_DROP_NAME_RE = re.compile(
    r"\b(warrants?|units?|rights?|preferreds?|pfd|notes?|debentures?|bonds?|etns?)\b",
    re.IGNORECASE,
)


class UniverseScope(str, Enum):
    """Which security types count as a valid ticker."""

    COMMON_ETF = "common_etf"  # common stock + ETFs (default)
    COMMON = "common"  # operating-company common shares only (drop ETFs too)
    ALL = "all"  # every listed symbol (only test issues removed)


@dataclass(frozen=True)
class TickerUniverse:
    """An immutable set of valid uppercase symbols with ``in`` support."""

    symbols: frozenset[str]

    def __contains__(self, item: object) -> bool:
        return isinstance(item, str) and item.upper() in self.symbols

    def __len__(self) -> int:
        return len(self.symbols)


def _keep_row(name: str, is_etf: bool, scope: UniverseScope) -> bool:
    """Decide whether a (non-test) row should be kept under ``scope``."""
    if scope is UniverseScope.ALL:
        return True
    if _DROP_NAME_RE.search(name):
        return False
    if scope is UniverseScope.COMMON and is_etf:
        return False
    return True


def _parse_pipe_file(
    text: str,
    *,
    symbol_idx: int,
    name_idx: int,
    test_idx: int,
    etf_idx: int,
    scope: UniverseScope,
) -> set[str]:
    """Parse a NASDAQ Trader pipe-delimited file body into a symbol set."""
    out: set[str] = set()
    lines = text.splitlines()
    if not lines:
        return out
    max_idx = max(symbol_idx, name_idx, test_idx, etf_idx)
    for line in lines[1:]:  # skip header row
        if not line or line.startswith("File Creation Time"):
            continue
        parts = line.split("|")
        if len(parts) <= max_idx:
            continue
        symbol = parts[symbol_idx].strip().upper()
        if not symbol:
            continue
        if parts[test_idx].strip().upper() == "Y":  # test issue
            continue
        is_etf = parts[etf_idx].strip().upper() == "Y"
        if _keep_row(parts[name_idx], is_etf, scope):
            out.add(symbol)
    return out


def parse_nasdaq_listed(text: str, scope: UniverseScope) -> set[str]:
    return _parse_pipe_file(
        text, symbol_idx=0, name_idx=1, test_idx=3, etf_idx=6, scope=scope
    )


def parse_other_listed(text: str, scope: UniverseScope) -> set[str]:
    return _parse_pipe_file(
        text, symbol_idx=0, name_idx=1, test_idx=6, etf_idx=4, scope=scope
    )


class UniverseLoader:
    """Loads (and refreshes) the ticker universe from NASDAQ Trader files."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        max_age_days: int = 7,
        scope: UniverseScope = UniverseScope.COMMON_ETF,
        timeout: float = 30.0,
        session: object | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.max_age_days = max_age_days
        self.scope = scope
        self.timeout = timeout
        self._session = session  # lazily created requests.Session if None

    def load(self) -> TickerUniverse:
        """Return the validated universe, downloading/refreshing the cache as needed."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        nasdaq_text = self._read_or_download(NASDAQ_LISTED_FILE, NASDAQ_LISTED_URL)
        other_text = self._read_or_download(OTHER_LISTED_FILE, OTHER_LISTED_URL)

        symbols = parse_nasdaq_listed(nasdaq_text, self.scope)
        symbols |= parse_other_listed(other_text, self.scope)
        if not symbols:
            raise RuntimeError("Parsed an empty ticker universe; refusing to continue.")

        log.info(
            "universe_loaded",
            extra={"size": len(symbols), "scope": self.scope.value},
        )
        return TickerUniverse(frozenset(symbols))

    # -- internals -----------------------------------------------------------

    def _session_get(self, url: str) -> str:
        import requests  # lazy: keeps offline imports (and tests) dependency-free

        if self._session is None:
            self._session = requests.Session()
        resp = self._session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    def _read_or_download(self, filename: str, url: str) -> str:
        path = self.cache_dir / filename
        if self._is_fresh(path):
            log.debug("universe_cache_hit", extra={"file": filename})
            return path.read_text(encoding="utf-8", errors="replace")

        try:
            text = self._session_get(url)
        except Exception as exc:
            if path.exists():  # fall back to stale cache rather than fail
                log.warning(
                    "universe_download_failed_using_stale",
                    extra={"file": filename, "error": repr(exc)},
                )
                return path.read_text(encoding="utf-8", errors="replace")
            raise RuntimeError(f"Failed to download {url}: {exc}") from exc

        path.write_text(text, encoding="utf-8")
        log.info("universe_downloaded", extra={"file": filename, "bytes": len(text)})
        return text

    def _is_fresh(self, path: Path) -> bool:
        if not path.exists():
            return False
        age_seconds = time.time() - path.stat().st_mtime
        return age_seconds < self.max_age_days * 86400
