# CLAUDE.md — `domains-service2`

Orientation for AI sessions. Read this first; you shouldn't need to re-explore the tree.

## What this is

**Delhi NCR Business Leads Pipeline** — a self-contained **Python CLI batch script**. It
runs once and exits: **no server, no database, no Docker**. It sources Delhi NCR business
websites → WHOIS-filters by domain age → scrapes email/phone → writes a CSV → emails it
via Resend. All build phases **P0–P7 are complete** (`ROADMAP.md` §3); no feature work
remains, only operational setup.

## How to run

```powershell
pip install -r requirements.txt          # one-time
copy .env.example .env                    # then fill RESEND_API_KEY (+ a sourcing key)

python main.py --mock --no-email          # zero-config smoke test (no keys, no email)
python main.py --mock                     # mock targets, actually sends the email
python main.py --limit 50                 # real run, capped at 50 targets
python main.py                            # full real run
python main.py --fresh                    # + sweep newly-registered NCR domains (<=7d)
```

Python 3.10+ (uses `X | None` syntax). Optional JS-rendering fallback: `pip install
playwright && playwright install chromium`, then set `USE_PLAYWRIGHT=1`.

## Architecture (flat modules, orchestrated by `main.py`)

| File | Role |
|------|------|
| `main.py` | Orchestrator + CLI flags (`--mock`, `--limit N`, `--no-email`) + strict validation gate + CSV writer |
| `config.py` | Env loading, constants (cities/categories/crawl paths), regexes |
| `target_sourcer.py` | Source targets — precedence: **Apify → Google Places → `seed_urls.csv` → built-in mock**; drops tech/digital-marketing sellers (`EXCLUDED_KEYWORDS`) and non-NCR places (`NCR_CITY_KEYWORDS` + Apify `countryCode=in`) |
| `domain_filter.py` | `check_site_age()` — layered age gate (**Wayback first-capture → crt.sh earliest cert → RDAP/WHOIS fallback**): keep if **≥365d OR ≤7d**, else discard; unverifiable = discard |
| `fresh_domains.py` | `source_fresh_domains()` (opt-in `--fresh`) — WhoisDS newly-registered-domain feed → NCR-keyword filter → liveness check; targets are ≤7d by construction (gTLDs only, no `.in`) |
| `contact_scraper.py` | `scrape_contacts()` — email + Indian-phone extraction; optional Playwright fallback |
| `http_client.py` | Shared HTTP layer: retry/backoff/jitter, rotating proxy pool, WHOIS throttling |
| `delivery.py` | `send_csv()` — Resend CSV emailer (base64 attach) + `sends_log.jsonl` |

**Pipeline flow:** source (+ optional fresh-domain sweep) → ICP + NCR-location filter →
site-age gate → scrape contacts → **strict gate** (drop any row with no email AND no
phone) → write CSV → email.

**ICP note:** target categories (`BUSINESS_CATEGORIES`) are local service businesses —
dentists, clinics, restaurants, salons, gyms, law firms, real estate, coaching,
consultants, shops, manufacturers, NGOs. Businesses that *sell* tech or digital-marketing
services are never leads; they're filtered by keyword blocklist.

## Key env vars (full surface in `.env.example`)

- `RESEND_API_KEY` — required to email.
- One sourcing provider: `APIFY_TOKEN` (recommended, no card) **or** `GOOGLE_PLACES_API_KEY`
  **or** a `seed_urls.csv` (`business_name,url`). None set → built-in mock targets.
- `RECIPIENT_EMAIL`, `RESEND_FROM_EMAIL`, `USE_PLAYWRIGHT`.
- ~20 anti-ban knobs (`MAX_RETRIES`, `BACKOFF_*`, `JITTER_*`, `PROXY_*`, `WHOIS_*`) — see
  `.env.example` rather than listing here.

## Outputs (in `OUTPUT_DIR`, default `output/`)

`delhi_ncr_leads_<timestamp>.csv` (emailed) · `delhi_ncr_leads_latest.csv` (stable copy) ·
`sends_log.jsonl` (one line per successful send) · `age_cache.json` (repo root, per-signal
site-age cache; the old `whois_cache.json` is defunct).
CSVs always save to disk even if email is skipped/fails.

## Known caveat / next steps

- **`RECIPIENT_EMAIL`** in `.env` — double-check the digits before any real send
  (past versions have had typos in this address).
- No feature phases remain. Remaining work is operational: `.env` is filled (Resend +
  Apify), run `--mock` first, then a small `--limit 50` real run.

## Deeper docs

`README.md` (setup/run/outputs) · `ROADMAP.md` (system map + per-module plan) ·
`plan.md` (original spec) · `wa1.txt` (the Resend "report-generator" delivery theory this mirrors).
