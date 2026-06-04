"""Tests for parsing/filtering the NASDAQ Trader symbol files (offline)."""

from __future__ import annotations

from wsb_dd.universe import (
    TickerUniverse,
    UniverseScope,
    parse_nasdaq_listed,
    parse_other_listed,
)

NASDAQ_LISTED = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
TSLA|Tesla, Inc. - Common Stock|Q|N|N|100|N|N
ZTEST|Nasdaq Test Issue - Common Stock|Q|Y|N|100|N|N
QQQ|Invesco QQQ Trust, Series 1|Q|N|N|100|Y|N
ABCDW|Foo Acquisition Corp - Warrant|Q|N|N|100|N|N
File Creation Time: 0601202601:02|||||"""

OTHER_LISTED = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BRK.A|Berkshire Hathaway Inc. Class A Common Stock|N|BRK.A|N|1|N|
SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|
XYZ.U|SomeSpac Acquisition Corp - Units|N|XYZ.U|N|100|N|
BABA|Alibaba Group Holding Limited American Depositary Shares|N|BABA|N|100|N|
File Creation Time: 0601202601:02|||||"""


def test_nasdaq_common_etf_keeps_stock_and_etf_drops_test_and_warrant() -> None:
    symbols = parse_nasdaq_listed(NASDAQ_LISTED, UniverseScope.COMMON_ETF)
    assert {"AAPL", "TSLA", "QQQ"} <= symbols
    assert "ZTEST" not in symbols  # test issue
    assert "ABCDW" not in symbols  # warrant


def test_nasdaq_common_only_drops_etfs() -> None:
    symbols = parse_nasdaq_listed(NASDAQ_LISTED, UniverseScope.COMMON)
    assert {"AAPL", "TSLA"} <= symbols
    assert "QQQ" not in symbols


def test_nasdaq_all_keeps_warrant_but_still_drops_test_issue() -> None:
    symbols = parse_nasdaq_listed(NASDAQ_LISTED, UniverseScope.ALL)
    assert "ABCDW" in symbols
    assert "ZTEST" not in symbols


def test_other_listed_keeps_adr_and_class_shares_drops_units() -> None:
    symbols = parse_other_listed(OTHER_LISTED, UniverseScope.COMMON_ETF)
    assert {"BRK.A", "SPY", "BABA"} <= symbols  # ADR + class share + ETF kept
    assert "XYZ.U" not in symbols  # unit


def test_ticker_universe_membership_is_case_insensitive() -> None:
    uni = TickerUniverse(frozenset({"NVDA", "BRK.A"}))
    assert "nvda" in uni
    assert "NVDA" in uni
    assert "brk.a" in uni
    assert "TSLA" not in uni
    assert len(uni) == 2
