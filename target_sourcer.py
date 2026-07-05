"""Stage 1 — Sourcing targets: business name + website URL for Delhi NCR.

Three modes, tried in order:
  1. Google Places API (New) Text Search, if GOOGLE_PLACES_API_KEY is set.
  2. seed_urls.csv (columns: business_name,url) — plug in any Maps-scraper export.
  3. Built-in mock list, so the pipeline is runnable end-to-end with no keys.
"""

import csv
import os
import time

import requests
import tldextract

import config
import http_client

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
APIFY_RUN_SYNC_URL = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"

MOCK_TARGETS = [
    {"business_name": "Demo Dental Clinic Delhi", "url": "https://www.clovedental.in"},
    {"business_name": "Demo Restaurant Delhi", "url": "https://www.haldirams.com"},
    {"business_name": "Demo Interiors Gurgaon", "url": "https://www.livspace.com"},
]


def registrable_domain(url: str) -> str:
    ext = tldextract.extract(url)
    return f"{ext.domain}.{ext.suffix}".lower() if ext.domain and ext.suffix else ""


def _excluded_keyword(t: dict, domain: str) -> str | None:
    """Return the blocklist keyword hit if this target SELLS tech/marketing services."""
    hay = " ".join((t.get("business_name", ""), domain, t.get("category", ""))).lower()
    return next((kw for kw in config.EXCLUDED_KEYWORDS if kw in hay), None)


def _dedupe(targets: list[dict]) -> list[dict]:
    """One target per registrable domain; drop aggregators, empty URLs, and
    tech/digital-marketing sellers (they're peers, not prospects)."""
    seen, out = set(), []
    for t in targets:
        url = (t.get("url") or "").strip()
        if not url.startswith("http"):
            continue
        domain = registrable_domain(url)
        if not domain or domain in config.AGGREGATOR_DOMAINS or domain in seen:
            continue
        kw = _excluded_keyword(t, domain)
        if kw:
            print(f"[sourcer] {domain}: tech/marketing seller (matched '{kw}') — skipped")
            continue
        seen.add(domain)
        out.append({"business_name": t.get("business_name", "").strip() or domain, "url": url})
    return out


def _places_text_search(query: str, api_key: str) -> list[dict]:
    """One Text Search (New) query, following nextPageToken pagination."""
    results, page_token = [], None
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.websiteUri,nextPageToken",
    }
    for _ in range(3):  # max 3 pages (~60 results) per query
        body = {"textQuery": query}
        if page_token:
            body["pageToken"] = page_token
        resp = http_client.post(PLACES_SEARCH_URL, json=body, headers=headers)
        if resp is None:
            print(f"[sourcer] Places API unreachable for '{query}' after retries")
            break
        if resp.status_code != 200:
            print(f"[sourcer] Places API {resp.status_code} for '{query}': {resp.text[:200]}")
            break
        data = resp.json()
        for place in data.get("places", []):
            website = place.get("websiteUri")
            if website:
                results.append({
                    "business_name": place.get("displayName", {}).get("text", ""),
                    "url": website,
                })
        page_token = data.get("nextPageToken")
        if not page_token:
            break
        time.sleep(1)  # token needs a moment to become valid
    return results


def _search_queries() -> list[str]:
    """The category × city cross-product used by every keyword-based source.

    City-major order, so a small APIFY_MAX_SEARCHES cap slices across MANY
    categories in Delhi rather than one category across cities.
    """
    return [f"{category} in {city}"
            for city in config.NCR_CITIES
            for category in config.BUSINESS_CATEGORIES]


def _source_from_places(api_key: str) -> list[dict]:
    targets = []
    for query in _search_queries():
        print(f"[sourcer] querying Places: {query}")
        targets.extend(_places_text_search(query, api_key))
        time.sleep(0.3)
    return targets


def _source_from_apify() -> list[dict]:
    """Run the Apify Google Maps actor and pull its dataset in one sync call.

    Deliberately NOT routed through http_client's retrying request(): a retry on
    timeout would re-run a *billed* actor. One direct call, long timeout, no retry;
    on any failure we log and return [] rather than risk a duplicate charged run.
    """
    queries = _search_queries()[: config.APIFY_MAX_SEARCHES]
    print(f"[sourcer] Apify mode: actor={config.APIFY_ACTOR_ID}, "
          f"{len(queries)} queries x {config.APIFY_MAX_PLACES_PER_SEARCH} places")
    url = APIFY_RUN_SYNC_URL.format(actor=config.APIFY_ACTOR_ID.replace("/", "~"))
    payload = {
        "searchStringsArray": queries,
        "maxCrawledPlacesPerSearch": config.APIFY_MAX_PLACES_PER_SEARCH,
        "language": "en",
        # Without a country lock, Maps text search returns lookalike businesses
        # from anywhere in the world (observed: US agencies in a "Delhi" run).
        "countryCode": "in",
    }
    try:
        resp = requests.post(url, params={"token": config.APIFY_TOKEN},
                             json=payload, timeout=300)
    except requests.RequestException as exc:
        print(f"[sourcer] Apify request failed: {type(exc).__name__}: {exc}")
        return []
    if resp.status_code not in (200, 201):
        print(f"[sourcer] Apify returned {resp.status_code}: {resp.text[:300]}")
        return []
    try:
        items = resp.json()
    except ValueError:
        print("[sourcer] Apify response was not JSON")
        return []

    targets, outside_ncr = [], 0
    for item in items:
        # Belt-and-braces location gate: even with countryCode=in, keep a place
        # only if its returned address/city matches a Delhi NCR city.
        place_loc = " ".join(
            str(item.get(k) or "") for k in ("city", "address", "state")
        ).lower()
        if place_loc.strip() and not any(c in place_loc for c in config.NCR_CITY_KEYWORDS):
            outside_ncr += 1
            continue
        targets.append({
            "business_name": item.get("title") or item.get("name", ""),
            "url": item.get("website") or "",
            "category": item.get("categoryName") or "",
        })
    print(f"[sourcer] Apify returned {len(items)} places "
          f"({outside_ncr} outside Delhi NCR — dropped)")
    return targets


def _source_from_seed_file(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return [{"business_name": r.get("business_name", ""), "url": r.get("url", "")} for r in rows]


def source_targets(mock: bool = False) -> list[dict]:
    """Return de-duplicated [{business_name, url}] for Delhi NCR businesses."""
    # Priority chain: Apify (card-free, preferred) -> Google Places -> seed CSV -> mock.
    if mock:
        print("[sourcer] mock mode — using built-in demo targets")
        raw = MOCK_TARGETS
    elif config.APIFY_TOKEN:
        print("[sourcer] APIFY_TOKEN set — sourcing via Apify Google Maps Scraper")
        raw = _source_from_apify()
    elif config.GOOGLE_PLACES_API_KEY:
        print("[sourcer] sourcing via Google Places API")
        raw = _source_from_places(config.GOOGLE_PLACES_API_KEY)
    elif os.path.exists(config.SEED_FILE):
        print(f"[sourcer] no API token — reading {config.SEED_FILE}")
        raw = _source_from_seed_file(config.SEED_FILE)
    else:
        print("[sourcer] no API token and no seed_urls.csv — using built-in demo targets")
        raw = MOCK_TARGETS

    targets = _dedupe(raw)
    if config.MAX_TARGETS > 0:
        targets = targets[: config.MAX_TARGETS]
    print(f"[sourcer] {len(targets)} unique target domains")
    return targets
