# CLAUDE.md — `scraper2` (no-website leads variant)

Orientation for AI sessions. Read this first; you shouldn't need to re-explore the tree.

## What this is

**Delhi NCR No-Website Business Leads Pipeline** — a self-contained **Python CLI
batch script** (forked from `/scraper`, then inverted). It runs once and exits:
**no server, no database, no Docker**. It searches Google Maps for Delhi NCR
businesses (one category picked at a startup menu, or all) → keeps **only places
with NO website** → takes phone/email/rating/review-count **straight from the
Maps listing** (there is no site to scrape) → applies the strict contact gate →
classifies each lead into a tier → writes a CSV **and a styled XLSX** → emails
both via Resend.

**Lead tiers** (every lead has no website by construction):
- **Goldenrod** — rating ≥ `GOLDENROD_MIN_RATING` (4.5) AND reviews ≥
  `GOLDENROD_MIN_REVIEWS` (500). Golden-yellow row fill (`GOLDENROD_FILL_HEX`)
  in the XLSX; sorted to the top.
- **New Bark** — every other no-website business.

## How to run

```powershell
pip install -r requirements.txt          # one-time (includes openpyxl for XLSX)
copy .env.example .env                    # then fill RESEND_API_KEY (+ a sourcing key)

python main.py --mock --no-email          # zero-config smoke test (no keys, no email)
python main.py --mock                     # mock targets, actually sends the email
python main.py --limit 50                 # real run, capped at 50 targets
python main.py                            # full real run
python main.py --category 3               # preselect category #3 (skips the menu)
```

Every run opens with a numbered **category menu** (from `BUSINESS_CATEGORIES`); enter a
number for one category, `0`/Enter for all. `--category N` (0 = all) skips the prompt —
use it for non-interactive/scheduled runs (EOF on stdin also falls back to all).
Python 3.10+ (uses `X | None` syntax).

## Architecture (flat modules, orchestrated by `main.py`)

| File | Role |
|------|------|
| `main.py` | Orchestrator + category menu (`pick_category()`) + CLI flags (`--mock`, `--limit N`, `--no-email`, `--category N`) + strict validation gate + `classify()` tier logic + CSV writer + `write_xlsx()` (openpyxl, gold fill on Goldenrod rows) |
| `config.py` | Env loading, constants (cities/categories/tier thresholds), output columns |
| `target_sourcer.py` | Source no-website places — precedence: **Apify → Google Places → `seed_places.csv` → built-in mock**. Apify actor is passed `website: "withoutWebsite"`; every mode also drops any place carrying a website client-side. Target dicts: `{business_name, phone, email, rating, reviews, address, category, place_id}`. Drops tech/digital-marketing sellers (`EXCLUDED_KEYWORDS`) and non-NCR places (`NCR_CITY_KEYWORDS` + Apify `countryCode=in`); dedup by `place_id` |
| `http_client.py` | Shared HTTP layer: retry/backoff/jitter, rotating proxy pool (used by the Places API path) |
| `delivery.py` | `send_report()` — Resend emailer, attaches the one XLSX report (base64) + `sends_log.jsonl` |

**Pipeline flow:** pick category → source no-website Maps places → ICP +
NCR-location filter → **strict gate** (drop any row with no email AND no phone —
note: Maps listings rarely expose emails, so most leads are phone-only) →
classify Goldenrod / New Bark → sort (Goldenrod first, reviews desc) → write
CSV + styled XLSX → email the XLSX.

Removed relative to `/scraper`: `sitemap_filter.py`, `contact_scraper.py`,
`fresh_domains.py` (and `--fresh`) — all only make sense for businesses that
*have* websites.

**ICP note:** target categories (`BUSINESS_CATEGORIES`) are local service businesses —
dentists, clinics, restaurants, salons, gyms, law firms, real estate, coaching,
consultants, shops, manufacturers, NGOs. Businesses that *sell* tech or digital-marketing
services are never leads; they're filtered by keyword blocklist.

## Key env vars (full surface in `.env.example`)

- `RESEND_API_KEY` — required to email.
- One sourcing provider: `APIFY_TOKEN` (recommended, no card) **or** `GOOGLE_PLACES_API_KEY`
  **or** a `seed_places.csv` (`business_name,phone,email,rating,reviews,address,category`).
  None set → built-in mock targets.
- `GOLDENROD_MIN_RATING` / `GOLDENROD_MIN_REVIEWS` — tier thresholds (default 4.5 / 500).
- `RECIPIENT_EMAIL`, `RESEND_FROM_EMAIL`.
- Anti-ban knobs (`MAX_RETRIES`, `BACKOFF_*`, `JITTER_*`, `PROXY_*`) — see `.env.example`.

## Outputs (in `OUTPUT_DIR`, default `output/`)

`delhi_ncr_no_website_leads_<timestamp>.xlsx` (the ONE emailed file — all leads,
both tiers, gold-highlighted Goldenrod rows on top) · same-stamp `.csv` (disk
archive; email fallback if openpyxl missing) · `delhi_ncr_no_website_leads_latest.csv`
(stable copy) · `sends_log.jsonl` (one line per successful send). Files always
save to disk even if email is skipped/fails.

## Known caveat / next steps

- **`RECIPIENT_EMAIL`** in `.env` — double-check the digits before any real send
  (past versions have had typos in this address).
- Emails are rare on Google Maps listings; expect most leads to be phone-only.

## Deeper docs

`README.md` (setup/run/outputs) · `plan.md` (original spec, pre-fork) ·
`wa1.txt` (the Resend "report-generator" delivery theory this mirrors).
`ROADMAP.md` describes the ORIGINAL with-website pipeline and predates this fork.
