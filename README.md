# Delhi NCR No-Website Business Leads Pipeline

Searches Google Maps for Delhi NCR businesses and keeps **only the ones with no
website at all** — the perfect prospects for a website/digital-presence pitch.
For each lead it returns the **phone number, email (when the listing exposes
one), Google review rating, and review count**, applies a **strict validation
gate** (no email AND no phone → row discarded), and classifies every lead into
one of two tiers:

| Tier | Rule | Styling |
|------|------|---------|
| **Goldenrod** | rating ≥ 4.5 **and** 500+ reviews (and no website) | golden-yellow row background in the XLSX |
| **New Bark** | every other no-website business | plain |

Output is a CSV **plus a styled `.xlsx`** (Goldenrod rows highlighted, sorted to
the top), both emailed via **Resend** following the report-generator delivery
pattern documented in `wa1.txt` (artifact → base64 attachment → transactional
send → best-effort send log).

## Setup

```powershell
pip install -r requirements.txt
copy .env.example .env    # then fill in RESEND_API_KEY (+ APIFY_TOKEN)
```

## Run

```powershell
python main.py --mock              # smoke test, no API keys needed
python main.py --mock --no-email   # smoke test without sending
python main.py --limit 50          # real run, capped at 50 targets
python main.py                     # full run
python main.py --category 3        # preselect category #3, skipping the menu
```

Every run starts with a numbered **business-category menu** (built from
`BUSINESS_CATEGORIES` in `config.py`): enter e.g. `1` for dentist, `14` for
NGO — or `0`/Enter to sweep all categories. `--category N` preselects and
skips the prompt (useful for scheduled/non-interactive runs).

Sourcing modes (auto-selected, in priority order):

1. **`APIFY_TOKEN` set** → Apify Google Maps Scraper (recommended, **no credit
   card**; free plan gives $5/month credits). The actor is asked for
   `website: "withoutWebsite"` places only, and returns name, phone, rating,
   review count, and address directly from the Maps listing.
2. **`GOOGLE_PLACES_API_KEY` set** → Places API (New) Text Search; places with a
   `websiteUri` are dropped. Note: the Places API never exposes emails, so those
   leads carry phone numbers only. Google **requires a billing account + card**.
3. **`seed_places.csv` present** (columns
   `business_name,phone,email,rating,reviews,address,category`) → plug in any
   Maps-scraper export.
4. Otherwise → built-in mock targets.

Since these businesses have **no website to scrape**, all contact info comes
from the Google Maps listing itself. Emails are rare on Maps listings — expect
most leads to be phone-only (the strict gate keeps a row if it has *either*).

## Anti-ban protections

Every outbound request (except the single billed Apify call) routes through
`http_client.py`, which provides:

- **Retry + exponential backoff + jitter** on `429`/`5xx`/timeouts, honouring
  `Retry-After`. Tune with `MAX_RETRIES`, `BACKOFF_BASE_SECONDS`, `BACKOFF_MAX_SECONDS`.
- **Randomized inter-request delay** (`JITTER_MIN_SECONDS`..`JITTER_MAX_SECONDS`) so
  the crawl has no detectable fixed cadence.
- **Rotating proxy pool** — set `PROXY_LIST` (comma-separated) and/or drop one proxy
  per line in `proxies.txt` (`scheme://[user:pass@]host:port`). Round-robins per
  request; a proxy that fails `PROXY_MAX_FAILURES` times is dropped; when the pool
  empties it falls back to the direct connection.

To enable proxies: `copy proxies.txt.example proxies.txt` and add your endpoints.

## Outputs

All artifacts are written to the `OUTPUT_DIR` folder (default `output/`):

| File | What |
|------|------|
| `output/delhi_ncr_no_website_leads_<timestamp>.csv` | Timestamped archive of each run's validated leads (has a `Lead Type` column) |
| `output/delhi_ncr_no_website_leads_<timestamp>.xlsx` | Styled workbook — Goldenrod rows get a golden-yellow background |
| `output/delhi_ncr_no_website_leads_latest.csv` | Stable copy of the most recent run |
| `output/sends_log.jsonl` | One line per successful Resend delivery (the `report_sends` analog) |

The XLSX (single file, both tiers) is what gets emailed; the CSV is a disk
archive (and the email fallback if openpyxl isn't installed). Files are always
saved to disk even if email delivery is skipped or fails.

## Recipient note

`.env` defaults `RECIPIENT_EMAIL` to `ashutosh@06067gmail.com` exactly as
specified in the plan — but `06067gmail.com` is almost certainly a typo for
`ashutosh06067@gmail.com`. Fix it in `.env` before a real send.
