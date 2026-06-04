"""Unit tests for the ticker extractor (the core, tricky part)."""

from __future__ import annotations

from wsb_dd.extractor import ExtractorConfig, TickerExtractor, load_blocklist


# --- Required behaviors ----------------------------------------------------


def test_plain_slang_dd_and_ceo_are_rejected(extractor: TickerExtractor) -> None:
    found = extractor.extract_unique("Here is my DD on the CEO's master plan.")
    assert "DD" not in found
    assert "CEO" not in found


def test_dollar_prefixed_dd_is_accepted(extractor: TickerExtractor) -> None:
    # "$DD" means DuPont -> bypasses the slang blocklist.
    assert "DD" in extractor.extract_unique("I'm loading up on $DD calls.")


def test_real_tickers_in_prose_are_caught(extractor: TickerExtractor) -> None:
    found = extractor.extract_unique("I think NVDA and TSLA both rip tomorrow, maybe AMD too.")
    assert {"NVDA", "TSLA", "AMD"} <= found


# --- Dollar form details ---------------------------------------------------


def test_dollar_form_bypasses_blocklist_for_multiple_tokens(extractor: TickerExtractor) -> None:
    found = extractor.extract_unique("Watching $GO $AI $ALL closely")
    assert {"GO", "AI", "ALL"} <= found


def test_dollar_form_is_case_insensitive(extractor: TickerExtractor) -> None:
    assert "NVDA" in extractor.extract_unique("long $nvda here")


def test_dollar_bypass_can_be_disabled(universe: set[str], blocklist: set[str]) -> None:
    strict = TickerExtractor(
        universe, blocklist, ExtractorConfig(dollar_bypasses_blocklist=False)
    )
    assert "DD" not in strict.extract_unique("$DD")


# --- Bare token rules ------------------------------------------------------


def test_single_char_bare_token_rejected_by_default(extractor: TickerExtractor) -> None:
    assert "F" not in extractor.extract_unique("I would buy F right now")


def test_single_char_dollar_token_accepted(extractor: TickerExtractor) -> None:
    assert "F" in extractor.extract_unique("I would buy $F right now")


def test_single_char_bare_allowed_when_configured(universe: set[str], blocklist: set[str]) -> None:
    permissive = TickerExtractor(
        universe, blocklist, ExtractorConfig(allow_single_char_bare=True)
    )
    found = permissive.extract_unique("buy F and T")
    assert {"F", "T"} <= found


def test_lowercase_words_are_not_tickers(extractor: TickerExtractor) -> None:
    assert extractor.extract_unique("nvda tsla amd are lowercase") == set()


def test_substrings_inside_words_are_not_matched(extractor: TickerExtractor) -> None:
    found = extractor.extract_unique("BANANAS XNVDAX TSLAA blah")
    assert "NVDA" not in found
    assert "TSLA" not in found


def test_possessives_and_punctuation_are_handled(extractor: TickerExtractor) -> None:
    found = extractor.extract_unique("NVDA's run, TSLA. AMD! GME?")
    assert {"NVDA", "TSLA", "AMD", "GME"} <= found


def test_unknown_symbols_not_in_universe_are_dropped(extractor: TickerExtractor) -> None:
    assert extractor.extract_unique("$ZZZZZ and FOOBA are fake") == set()


# --- Counting --------------------------------------------------------------


def test_extract_counts_every_occurrence(extractor: TickerExtractor) -> None:
    occurrences = extractor.extract("NVDA NVDA $NVDA")
    assert occurrences.count("NVDA") == 3
    assert len(occurrences) == 3


def test_extract_combines_title_and_body_via_caller(extractor: TickerExtractor) -> None:
    # The extractor scans whatever text it's given; here we mimic title+body.
    text = "DD: why I love $TSLA\n\nNVDA is also great but the CEO worries me."
    found = extractor.extract_unique(text)
    assert {"TSLA", "NVDA"} <= found
    assert "DD" not in found
    assert "CEO" not in found


def test_empty_text_returns_empty(extractor: TickerExtractor) -> None:
    assert extractor.extract("") == []
    assert extractor.extract_unique("") == set()


# --- Blocklist file loader -------------------------------------------------


def test_load_blocklist_ignores_comments_and_blanks(tmp_path) -> None:
    path = tmp_path / "block.txt"
    path.write_text("# header comment\nDD\n\n  CEO  \nyolo  # inline\n", encoding="utf-8")
    tokens = load_blocklist(path)
    assert tokens == {"DD", "CEO", "YOLO"}
