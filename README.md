# wsb-dd

Scrape **r/wallstreetbets** posts flaired **DD** (Due Diligence) and extract the
US-listed stock tickers mentioned in them — validated against the real NASDAQ
Trader symbol universe, with a tunable WSB-slang blocklist.

Results are aggregated per ticker (distinct posts, raw mentions, a
score-weighted metric, first/last seen, source permalinks) and written to CSV,
or upserted into MySQL for scheduled, accumulating history.

---

## 1. Requirements

- **Python 3.9+** (developed against the 3.11+ target; verified to run on 3.9)
- A Reddit account + a "script" OAuth app (free; steps below)
- (Optional) A MySQL 8 server if you use `--mysql`

## 2. Install

```bash
git clone <your-repo-url> reddit_scrape
cd reddit_scrape

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip                        # editable install needs pip >= 21.3 (PEP 660)

pip install -r requirements.txt          # runtime only
# or, editable install with the console script + dev/test extras:
pip install -e ".[dev]"
```

## 3. Create a Reddit app & get OAuth credentials

1. Log in to Reddit, then go to **https://www.reddit.com/prefs/apps**.
2. Scroll down and click **"are you a developer? create an app..."**.
3. Fill in:
   - **name:** `wsb-dd-scraper` (anything)
   - **type:** select **script**
   - **description:** optional
   - **about url:** optional
   - **redirect uri:** `http://localhost:8080` (required by the form; unused for script apps)
4. Click **create app**.
5. Read the credentials off the app card:
   - **client_id** — the short string just under the app name / "personal use script".
   - **client_secret** — the value labelled **secret**.
6. Copy the env template and paste them in:
   ```bash
   cp .env.example .env
   # edit .env and set REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
   ```
   Reddit requires a unique, descriptive **user agent**. Use the format:
   `script:wsb-dd-scraper:0.1.0 (by /u/your_reddit_username)`

This is **read-only** access to public data — a script app using the client
credentials grant needs no password and no per-user login.

## 4. Usage

```bash
# Default: 100 newest DD posts -> ./out/dd_tickers_<timestamp>.csv
wsb-dd
# (equivalently, without the console script:)
python -m wsb_dd

# Top DD of the week, skip posts under 50 upvotes, cap at 200 posts
wsb-dd --sort top --time-filter week --min-score 50 --limit 200

# Broaden the flair match to anything containing "DD" (e.g. "Daily DD")
wsb-dd --flair-mode contains

# Also upsert into MySQL (reads MYSQL_* from .env), keeping a custom CSV path
wsb-dd --sort top --time-filter week --limit 250 --mysql --out out/weekly.csv
```

### Key CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--subreddit` | `wallstreetbets` | Subreddit to scan. |
| `--sort` | `new` | `new` \| `hot` \| `top`. |
| `--time-filter` | `week` | For `--sort top`: `day` \| `week` \| `month` \| `year` \| `all`. |
| `--limit` | `100` | Max submissions to fetch (Reddit caps listings at ~1000). |
| `--min-score` | `0` | Skip posts below this score. |
| `--flair-mode` | `exact` | `exact` (flair == "DD", case-insensitive) or `contains` ("DD" substring). |
| `--out` | `out/dd_tickers_<ts>.csv` | CSV output path. |
| `--cache-dir` | `.cache` | Where NASDAQ symbol files are cached. |
| `--universe-max-age-days` | `7` | Refresh the symbol cache if older than this. |
| `--universe-scope` | `common_etf` | `common_etf` \| `common` \| `all` (which symbols count as valid). |
| `--blocklist` | `config/slang_blocklist.txt` | Editable slang/stopword file. |
| `--allow-single-char-bare` | off | Allow bare 1-char tickers (e.g. `F`, `T`). `$F` always works. |
| `--mysql` | off | Also upsert results into MySQL. |
| `--log-level` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR`. |

## 5. How ticker extraction works

1. Pull `title` + `selftext` from each matched DD post.
2. Find two candidate patterns: `$NVDA` (dollar-prefixed) and bare ALL-CAPS
   tokens `[A-Z]{1,5}`.
3. **Validate against the real universe:** the NASDAQ Trader files
   (`nasdaqlisted.txt`, `otherlisted.txt`) are downloaded at runtime, cached
   under `--cache-dir`, and refreshed when older than `--universe-max-age-days`.
   Only candidates present in that set survive. Scope defaults to **common
   stock + ETFs** (warrants, units, rights, preferreds and test issues dropped).
4. **Slang blocklist:** bare tokens in `config/slang_blocklist.txt` (DD, CEO,
   YOLO, ...) are dropped. A `$`-prefixed mention **bypasses** the blocklist —
   `$DD` is kept as DuPont.
5. Single-char bare tokens are rejected by default (too noisy); `$F` still
   works, or pass `--allow-single-char-bare`.

### Per-ticker metrics

- **distinct_posts** — unique DD posts mentioning the ticker.
- **total_mentions** — raw occurrences across all title+selftext.
- **score_weighted** — sum of post scores across the distinct posts (the
  "post-weighted" metric the leaderboard is sorted by).
- **first_seen / last_seen** — earliest / latest post `created_utc`.
- **permalinks** — source posts.

## 6. MySQL (optional)

Create the database and (optionally) pre-apply the schema:

```bash
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS wsb_dd CHARACTER SET utf8mb4;"
mysql -u root -p wsb_dd < sql/schema.sql      # or let --mysql create tables
pip install ".[mysql]"                         # ensures PyMySQL is present
```

Set `MYSQL_*` in `.env`, then run with `--mysql`. Each run inserts a row into
`dd_runs` and a batch of rows into `dd_ticker_mentions` — **prior runs are kept**
so you can chart a ticker's momentum over time. See `sql/schema.sql` for DDL and
example queries.

## 7. Scheduling

`wsb-dd` is a single idempotent command — schedule it with cron. Example
(top-of-week DD, hourly, appending to MySQL):

```cron
0 * * * * cd /path/to/reddit_scrape && ./.venv/bin/wsb-dd \
  --sort top --time-filter week --limit 250 --min-score 25 --mysql \
  >> /path/to/reddit_scrape/out/cron.log 2>&1
```

## 8. Limitations

- Reddit listing endpoints return at most ~1000 items per sort. `--limit` above
  that won't page further back; this tool tracks **current** DD and builds
  history by running repeatedly. (Deep historical backfill would need an
  archive source like Pushshift, which is now access-restricted.)
- Ticker extraction is heuristic. The universe filter + blocklist remove most
  noise, but tune `config/slang_blocklist.txt` and `--universe-scope` for your
  needs. `$`-prefixed mentions are the high-precision signal.

## 9. Development

```bash
pip install -r requirements-dev.txt
pytest                      # runs the extractor unit tests
```

## Project layout

```
src/wsb_dd/
  cli.py            CLI entrypoint (argparse)
  config.py         env / .env loading, typed config objects
  logging_setup.py  structured (key=value) logging
  models.py         dataclasses: RedditPost, TickerStat, RunMeta
  reddit_client.py  PRAW wrapper, flair filtering, 429 backoff
  universe.py       NASDAQ Trader loader + local cache + scope filter
  extractor.py      ticker candidate matching + validation
  aggregator.py     per-ticker rollup
  storage/
    csv_writer.py   CSV output
    mysql_store.py  two-table upsert (dd_runs + dd_ticker_mentions)
config/slang_blocklist.txt
sql/schema.sql
tests/
```
