"""Ticker candidate extraction and validation.

Two patterns are matched in title + selftext:

  (a) $-prefixed symbols, e.g. ``$NVDA`` (case-insensitive) -> high precision;
      these BYPASS the slang blocklist and the single-char rule.
  (b) bare ALL-CAPS tokens, e.g. ``NVDA`` -> subject to the blocklist, the
      single-char rule, and (always) universe validation.

A candidate is only emitted if it appears in the provided ticker universe.
The extractor is deliberately decoupled from the universe loader: it accepts any
``Container[str]`` (a ``set`` in tests, a ``TickerUniverse`` in production).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Container, Iterable

# A symbol is 1-5 letters, with an optional ".X" share-class suffix (e.g. BRK.B).
# Dollar form accepts any case (we upper-case it); bare form must already be
# upper-case so prose words like "nvda" are not treated as tickers.
_DOLLAR_RE = re.compile(r"(?<![A-Za-z0-9.])\$([A-Za-z]{1,5}(?:\.[A-Za-z])?)\b")
_BARE_RE = re.compile(r"(?<![A-Za-z0-9.$])([A-Z]{1,5}(?:\.[A-Z])?)(?![A-Za-z0-9])")


@dataclass(frozen=True)
class ExtractorConfig:
    """Tunable knobs for the extractor (defaults = 'balanced' mode)."""

    allow_single_char_bare: bool = False  # bare 'F'/'T' rejected unless True ($F always works)
    dollar_bypasses_blocklist: bool = True


class TickerExtractor:
    """Extracts validated ticker symbols from free text."""

    def __init__(
        self,
        universe: Container[str],
        blocklist: Iterable[str],
        config: ExtractorConfig | None = None,
    ) -> None:
        self.universe = universe
        self.blocklist = frozenset(token.strip().upper() for token in blocklist if token.strip())
        self.config = config or ExtractorConfig()

    def extract(self, text: str) -> list[str]:
        """Return every accepted ticker occurrence (with repetition) in ``text``."""
        if not text:
            return []
        results: list[str] = []

        # (a) $-prefixed: bypass blocklist (configurable) and single-char rule.
        for match in _DOLLAR_RE.finditer(text):
            symbol = match.group(1).upper()
            if self.config.dollar_bypasses_blocklist or symbol not in self.blocklist:
                if symbol in self.universe:
                    results.append(symbol)

        # (b) bare upper-case tokens: full validation.
        for match in _BARE_RE.finditer(text):
            symbol = match.group(1).upper()
            base = symbol.split(".", 1)[0]
            if len(base) == 1 and not self.config.allow_single_char_bare:
                continue
            if symbol in self.blocklist:
                continue
            if symbol in self.universe:
                results.append(symbol)

        return results

    def extract_unique(self, text: str) -> set[str]:
        """Return the distinct accepted tickers in ``text``."""
        return set(self.extract(text))


def load_blocklist(path: str | Path) -> set[str]:
    """Load an upper-cased slang/stopword set from a blocklist file.

    Blank lines and ``#`` comments (full-line or trailing) are ignored.
    """
    tokens: set[str] = set()
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            tokens.add(line.upper())
    return tokens
