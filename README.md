# Delhi NCR Business Leads Pipeline

Scrapes Delhi NCR business websites for contact info (email + Indian phone),
keeps only domains that are **≥ 1 year old OR ≤ 1 week old** (WHOIS-verified),
applies a **strict validation gate** (no email AND no phone → row discarded),
writes `delhi_ncr_leads.csv`, and emails it via **Resend** following the
report-generator delivery pattern documented in `wa1.txt`
(artifact → base64 attachment → transactional send → best-effort send log).

See `ROADMAP.md` for the full system map and build plan.

## Setup

```powershell
pip install -r requirements.txt
copy .env.example .env    # then fill in RESEND_API_KEY (+ GOOGLE_PLACES_API_KEY)
```

Optional JS-rendering fallback:

```powershell
pip install playwright
playwright install chromium
# then set USE_PLAYWRIGHT=1 in .env
```

## Run

```powershell
python main.py --mock              # smoke test, no API keys needed
python main.py --mock --no-email   # smoke test without sending
python main.py --limit 50          # real run, capped at 50 targets
python main.py                     # full run
```

Sourcing modes (auto-selected, in priority order):

1. **`APIFY_TOKEN` set** → Apify Google Maps Scraper (recommended, **no credit
   card**; free plan gives $5/month credits ≈ 1.2–3k records). Returns business
   name + website directly.
2. **`GOOGLE_PLACES_API_KEY` set** → Places API (New) Text Search. Free tier is
   generous (5,000 calls/month) but Google **requires a billing account + card**.
3. **`seed_urls.csv` present** (columns `business_name,url`) → seed file — plug in
   any Maps-scraper export.
4. Otherwise → built-in mock targets.

## Anti-ban protections

Every outbound request routes through `http_client.py`, which provides:

- **Retry + exponential backoff + jitter** on `429`/`5xx`/timeouts, honouring
  `Retry-After`. Tune with `MAX_RETRIES`, `BACKOFF_BASE_SECONDS`, `BACKOFF_MAX_SECONDS`.
- **Randomized inter-request delay** (`JITTER_MIN_SECONDS`..`JITTER_MAX_SECONDS`) so
  the crawl has no detectable fixed cadence.
- **Rotating proxy pool** — set `PROXY_LIST` (comma-separated) and/or drop one proxy
  per line in `proxies.txt` (`scheme://[user:pass@]host:port`). Round-robins per
  request; a proxy that fails `PROXY_MAX_FAILURES` times is dropped; when the pool
  empties it falls back to the direct connection. Applies to page fetches, the
  Places API, and the Playwright fallback.
- **WHOIS throttling** — live WHOIS lookups are spaced by
  `WHOIS_MIN_INTERVAL_SECONDS` (+ jitter) to avoid registry IP bans; cache hits are
  never throttled.

To enable proxies: `copy proxies.txt.example proxies.txt` and add your endpoints.

## Outputs

All artifacts are written to the `OUTPUT_DIR` folder (default `output/`):

| File | What |
|------|------|
| `output/delhi_ncr_leads_<timestamp>.csv` | Timestamped archive of each run's validated leads |
| `output/delhi_ncr_leads_latest.csv` | Stable copy of the most recent run |
| `output/sends_log.jsonl` | One line per successful Resend delivery (the `report_sends` analog) |
| `whois_cache.json` | WHOIS creation-date cache so re-runs don't repeat lookups |

The timestamped CSV is what gets emailed. CSVs are always saved to disk even if
email delivery is skipped or fails.

## Recipient note

`.env` defaults `RECIPIENT_EMAIL` to `ashutosh@06067gmail.com` exactly as
specified in the plan — but `06067gmail.com` is almost certainly a typo for
`ashutosh06067@gmail.com`. Fix it in `.env` before a real send.
