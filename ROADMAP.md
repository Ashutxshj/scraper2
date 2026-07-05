# Delhi NCR Business Leads Scraper — Map, Roadmap & Build Plan

## 1. System Map (how everything connects)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            PIPELINE (main.py)                           │
│                                                                         │
│  Stage 1: SOURCE            Stage 2: FILTER          Stage 3: EXTRACT   │
│  target_sourcer.py          domain_filter.py         contact_scraper.py │
│  ┌───────────────────┐      ┌──────────────────┐     ┌───────────────┐  │
│  │ Google Places API │      │ WHOIS lookup     │     │ requests+BS4  │  │
│  │ Text Search (New) │ URLs │ (python-whois)   │ OK  │ (+ Playwright │  │
│  │ per category ×    ├─────►│ creation_date →  ├────►│  fallback for │  │
│  │ Delhi/Noida/Ggn/  │      │ age category:    │     │  JS-heavy     │  │
│  │ Faridabad/Ghzbd   │      │  ≥365d  OR ≤7d   │     │  sites)       │  │
│  │ (or seed CSV /    │      │  else DISCARD    │     │ /, /contact,  │  │
│  │  mock mode)       │      │  unknown DISCARD │     │ /about, ...   │  │
│  └───────────────────┘      └──────────────────┘     └──────┬────────┘  │
│                                                             │           │
│                              Stage 4: VALIDATION GATE       ▼           │
│                              ┌────────────────────────────────────┐     │
│                              │ email IS NULL AND phone IS NULL    │     │
│                              │        → DISCARD ROW               │     │
│                              └───────────────┬────────────────────┘     │
│                                              ▼                          │
│                              delhi_ncr_leads.csv                        │
│                 (Business Name, URL, Email, Phone Number, Domain Age)   │
└──────────────────────────────────────┬──────────────────────────────────┘
                                       │  Stage 5: DELIVERY (delivery.py)
                                       │  — the wa1.txt "report-generator" theory —
                                       ▼
                    build artifact → base64 attach → Resend send → log send
                    ┌──────────────────────────────────────────────┐
                    │ Resend API                                   │
                    │  subject: "Your Delhi NCR leads CSV is here" │
                    │  text: subject repeated (no marketing body)  │
                    │  attachment: delhi_ncr_leads.csv (base64)    │
                    │  to: RECIPIENT_EMAIL (.env)                  │
                    └───────────────────┬──────────────────────────┘
                                        ▼
                    sends_log.jsonl  (best-effort, non-fatal — the
                    local stand-in for report-generator's Mongo
                    `report_sends` collection)
```

## 2. The Delivery Theory (from wa1.txt, applied here)

`wa1.txt` documents the **report-generator** microservice pattern:
*build artifact → attach as base64 → one transactional Resend send → best-effort log of the delivered send.* Key traits we replicate:

| report-generator (wa1.txt)                  | this project (delivery.py)                  |
|---------------------------------------------|---------------------------------------------|
| buildHtml → PDF buffer                       | pipeline → CSV file bytes                    |
| Resend send, base64 PDF attachment           | Resend send, base64 CSV attachment           |
| No HTML body — subject repeated as `text`    | Same: plain text = subject line              |
| Subject varies by payload ("for N mailboxes")| Subject includes lead count ("N leads")      |
| `saveReportSend` → Mongo, best-effort        | `log_send` → sends_log.jsonl, best-effort    |
| Errors logged, never crash the caller        | Delivery failure never destroys the CSV      |
| From: reports@… (env `RESEND_FROM_EMAIL`)    | From: env `RESEND_FROM_EMAIL`                |

## 3. Roadmap (build order)

| Phase | Deliverable | Status |
|-------|-------------|--------|
| P0 | Planning docs (this file), project scaffold, `.env.example`, `requirements.txt` | ✅ |
| P1 | `config.py` — env loading, constants (cities, categories, crawl paths, regexes) | ✅ |
| P2 | `target_sourcer.py` — Places API Text Search (New) + seed-CSV + mock fallback | ✅ |
| P3 | `domain_filter.py` — WHOIS age category (≥1 yr / ≤1 wk), cache, strict discard on unknown | ✅ |
| P4 | `contact_scraper.py` — requests+BS4 crawler, email/Indian-phone regex, mailto/tel, optional Playwright fallback | ✅ |
| P5 | `main.py` — orchestrator + strict validation gate + CSV writer | ✅ |
| P6 | `delivery.py` — Resend CSV emailer per wa1.txt theory + JSONL send log | ✅ |
| P7 | Smoke test end-to-end in mock mode (no API keys needed) | ✅ |

## 4. Detailed Plan per Module

### P2 — `target_sourcer.py`
- **Real mode**: POSTs to `https://places.googleapis.com/v1/places:searchText` with
  `X-Goog-Api-Key` + field mask `places.displayName,places.websiteUri`. Queries are the
  cross-product of `BUSINESS_CATEGORIES × NCR_CITIES`. Paginates via `nextPageToken`.
- **Seed mode**: if `seed_urls.csv` exists (columns: `business_name,url`), use it — lets you
  plug in any Maps-scraper export.
- **Mock mode**: neither key nor seed file → small built-in demo list so the pipeline is
  runnable immediately.
- De-dupes by registrable domain; skips aggregator domains (justdial, indiamart, facebook…).

### P3 — `domain_filter.py`
- `python-whois` lookup → `creation_date` (handles list/scalar/naive/aware datetimes).
- Age ≥ 365 days → `"X years"` / age ≤ 7 days → `"X days (new)"` → **keep**, with the label
  written to the CSV's `Domain Age` column. Anything between, or WHOIS failure/missing
  date → **discard** (per plan: never trust sitemaps/robots for dates; unverifiable = out).
- In-memory + on-disk cache (`whois_cache.json`) so re-runs don't hammer WHOIS servers.

### P4 — `contact_scraper.py`
- Fetch homepage + `/contact`, `/contact-us`, `/about`, `/about-us`, `/reach-us` (first N
  that exist), also harvest any nav links whose text/href looks contact-ish.
- Emails: `mailto:` hrefs + regex over visible text/HTML; junk filter (image names,
  example.com, sentry/wix internals, obfuscated duplicates); de-obfuscate `name [at] site [dot] com`.
- Phones: `tel:` hrefs + Indian-format regex — `+91` prefixed, bare 10-digit mobiles
  (starting 6–9), and NCR landlines (`011`, `0120`, `0124`, `0129`, `0130` codes).
  Normalised to `+91XXXXXXXXXX`.
- Politeness: shared session, custom UA, 15 s timeout, configurable delay between requests.
- Optional Playwright fallback (`USE_PLAYWRIGHT=1`) only when static fetch found nothing.

### P5 — `main.py` (orchestrator)
1. Source targets → 2. WHOIS filter → 3. scrape contacts → 4. **Strict Validation Gate**
   (`if not email and not phone: discard`) → 5. write `delhi_ncr_leads.csv` → 6. deliver.
- Progress logging per stage with kept/discarded counts (mirrors the `[generate]`
  breadcrumb style from wa1.txt).
- `--limit N`, `--no-email`, `--mock` CLI flags for safe partial runs.

### P6 — `delivery.py`
- Exactly the wa1.txt send shape: `resend.Emails.send({from, to, subject, text,
  attachments:[{filename, content: base64}]})`; then best-effort append to
  `sends_log.jsonl` (`{to, filename, leadCount, sentAt}`) — the Mongo-`report_sends`
  analog. Delivery errors are logged, never fatal; the CSV always survives on disk.

## 5. Config surface (`.env`)

| Var | Required | Purpose |
|-----|----------|---------|
| `RESEND_API_KEY` | for email | Resend transactional send |
| `RESEND_FROM_EMAIL` | no (default `onboarding@resend.dev`) | From address |
| `RECIPIENT_EMAIL` | no (default `ashutosh@06067gmail.com`) | CSV recipient — **verify: likely `ashutosh06067@gmail.com`** |
| `GOOGLE_PLACES_API_KEY` | for real sourcing | Places Text Search (New) |
| `USE_PLAYWRIGHT` | no (default 0) | JS-rendering fallback in scraper |
| `REQUEST_DELAY_SECONDS` | no (default 1.0) | Politeness delay |
| `MAX_TARGETS` | no (default 0 = all) | Cap sourced targets |

## 6. Data-quality rules (hard gates)

1. Domain age must be **verifiably** ≥ 365 days OR ≤ 7 days — unknown/unverifiable is a discard.
2. A row is written **only if** at least one of Email / Phone was extracted.
3. One row per domain (best email + best phone), de-duplicated.
4. Aggregator/marketplace domains are never treated as the business's own site.
