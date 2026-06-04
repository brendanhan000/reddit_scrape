"""Shared fixtures for the test suite."""

from __future__ import annotations

import pytest

from wsb_dd.extractor import TickerExtractor

# A small, fixed stand-in for the real NASDAQ universe. Includes real tickers,
# real-but-slangy tickers (DD, CEO, GO, AI, ALL, IT, ON, SO), and single-char
# tickers (A, F, T, U) so the single-char rule can be exercised.
UNIVERSE_SYMBOLS = {
    "NVDA", "TSLA", "AMD", "GME", "AMC", "PLTR", "SOFI", "BABA", "SPY", "QQQ",
    "INTC", "MSFT", "AAPL", "TSM", "BRK.A",
    "DD", "CEO", "GO", "AI", "ALL", "IT", "ON", "SO",
    "A", "F", "T", "U",
}

# Tokens that are valid tickers but almost always slang on WSB (bare form only).
BLOCKLIST_TOKENS = {
    "DD", "CEO", "GO", "AI", "ALL", "IT", "ON", "SO",
    "YOLO", "IMO", "ATH", "EOD", "USA", "FD",
}


@pytest.fixture
def universe() -> set[str]:
    return set(UNIVERSE_SYMBOLS)


@pytest.fixture
def blocklist() -> set[str]:
    return set(BLOCKLIST_TOKENS)


@pytest.fixture
def extractor(universe: set[str], blocklist: set[str]) -> TickerExtractor:
    return TickerExtractor(universe, blocklist)
