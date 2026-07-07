"""Stage 1 — Sourcing targets: Delhi NCR businesses with NO website.

Every source returns Google-Maps-shaped place records; anything that lists a
website is dropped on the spot — a business already online is not our lead.
Contact info (phone, sometimes email), the star rating, and the review count
come straight from the Maps listing since there is no site to scrape.

Target dict shape (used by every mode):
  {business_name, phone, email, rating (float|None), reviews (int),
   address, category, place_id}

Four modes, tried in order:
  1. Apify Google Maps Scraper, if APIFY_TOKEN is set (card-free, preferred).
  2. Google Places API (New) Text Search, if GOOGLE_PLACES_API_KEY is set.
  3. seed_places.csv (business_name,phone,email,rating,reviews,address,category)
     — plug in any Maps-scraper export.
  4. Built-in mock list, so the pipeline is runnable end-to-end with no keys.
"""

import csv
import os
import time

import requests

import config
import http_client

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
APIFY_RUN_SYNC_URL = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"

MOCK_TARGETS = [
    {"business_name": "Sharma Dental Care", "phone": "+91 98110 12345",
     "email": "", "rating": 4.8, "reviews": 812,
     "address": "Karol Bagh, New Delhi", "category": "Dentist", "place_id": "mock1"},
    {"business_name": "Gupta Sweets & Caterers", "phone": "+91 98990 55555",
     "email": "guptasweets@gmail.com", "rating": 4.6, "reviews": 1450,
     "address": "Sector 18, Noida", "category": "Restaurant", "place_id": "mock2"},
    {"business_name": "Style Studio Salon", "phone": "+91 99530 22222",
     "email": "", "rating": 4.2, "reviews": 87,
     "address": "DLF Phase 3, Gurgaon", "category": "Beauty salon", "place_id": "mock3"},
    {"business_name": "Iron Core Gym", "phone": "",
     "email": "ironcorefbd@gmail.com", "rating": 4.9, "reviews": 133,
     "address": "Sector 15, Faridabad", "category": "Gym", "place_id": "mock4"},
]


def _to_int(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_rating(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _excluded_keyword(t: dict) -> str | None:
    """Return the blocklist keyword hit if this target SELLS tech/marketing services."""
    hay = " ".join((t.get("business_name", ""), t.get("category", ""))).lower()
    return next((kw for kw in config.EXCLUDED_KEYWORDS if kw in hay), None)


def _dedupe(targets: list[dict]) -> list[dict]:
    """One target per place (place_id, else name+address); drop nameless entries
    and tech/digital-marketing sellers (they're peers, not prospects)."""
    seen, out = set(), []
    for t in targets:
        name = (t.get("business_name") or "").strip()
        if not name:
            continue
        key = t.get("place_id") or f"{name.lower()}|{(t.get('address') or '').lower()}"
        if key in seen:
            continue
        kw = _excluded_keyword(t)
        if kw:
            print(f"[sourcer] {name}: tech/marketing seller (matched '{kw}') — skipped")
            continue
        seen.add(key)
        t["business_name"] = name
        out.append(t)
    return out


def _in_ncr(location_text: str) -> bool:
    loc = location_text.lower()
    return not loc.strip() or any(c in loc for c in config.NCR_CITY_KEYWORDS)


def _places_text_search(query: str, api_key: str) -> list[dict]:
    """One Text Search (New) query, following nextPageToken pagination.
    Keeps ONLY places with no websiteUri."""
    results, page_token = [], None
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.websiteUri,places.rating,"
            "places.userRatingCount,places.nationalPhoneNumber,"
            "places.internationalPhoneNumber,places.formattedAddress,"
            "places.primaryTypeDisplayName,nextPageToken"
        ),
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
            if place.get("websiteUri"):
                continue  # has a website — not our lead
            address = place.get("formattedAddress", "")
            if not _in_ncr(address):
                continue
            results.append({
                "business_name": place.get("displayName", {}).get("text", ""),
                "phone": place.get("nationalPhoneNumber")
                         or place.get("internationalPhoneNumber") or "",
                "email": "",  # Places API does not expose emails
                "rating": _to_rating(place.get("rating")),
                "reviews": _to_int(place.get("userRatingCount")),
                "address": address,
                "category": place.get("primaryTypeDisplayName", {}).get("text", ""),
                "place_id": place.get("id", ""),
            })
        page_token = data.get("nextPageToken")
        if not page_token:
            break
        time.sleep(1)  # token needs a moment to become valid
    return results


def _search_queries(category: str | None = None) -> list[str]:
    """The category × city cross-product used by every keyword-based source.

    A picked `category` (from the startup menu) narrows the sweep to just
    that category. City-major order, so a small APIFY_MAX_SEARCHES cap slices
    across MANY categories in Delhi rather than one category across cities.
    """
    categories = [category] if category else config.BUSINESS_CATEGORIES
    return [f"{cat} in {city}"
            for city in config.NCR_CITIES
            for cat in categories]


def _source_from_places(api_key: str, category: str | None) -> list[dict]:
    targets = []
    for query in _search_queries(category):
        print(f"[sourcer] querying Places: {query}")
        targets.extend(_places_text_search(query, api_key))
        time.sleep(0.3)
    return targets


def _source_from_apify(category: str | None) -> list[dict]:
    """Run the Apify Google Maps actor and pull its dataset in one sync call.

    Deliberately NOT routed through http_client's retrying request(): a retry on
    timeout would re-run a *billed* actor. One direct call, long timeout, no retry;
    on any failure we log and return [] rather than risk a duplicate charged run.
    """
    queries = _search_queries(category)[: config.APIFY_MAX_SEARCHES]
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
        # Actor-side filter: only crawl places with no website. Saves credits;
        # the client-side website check below still applies as belt-and-braces.
        "website": "withoutWebsite",
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

    targets, has_website, outside_ncr = [], 0, 0
    for item in items:
        if item.get("website"):
            has_website += 1
            continue  # already online — not our lead
        # Belt-and-braces location gate: even with countryCode=in, keep a place
        # only if its returned address/city matches a Delhi NCR city.
        place_loc = " ".join(
            str(item.get(k) or "") for k in ("city", "address", "state")
        )
        if not _in_ncr(place_loc):
            outside_ncr += 1
            continue
        emails = item.get("emails")
        targets.append({
            "business_name": item.get("title") or item.get("name", ""),
            "phone": item.get("phone") or item.get("phoneUnformatted") or "",
            "email": (emails[0] if isinstance(emails, list) and emails
                      else item.get("email") or ""),
            "rating": _to_rating(item.get("totalScore")),
            "reviews": _to_int(item.get("reviewsCount")),
            "address": item.get("address") or "",
            "category": item.get("categoryName") or "",
            "place_id": item.get("placeId") or "",
        })
    print(f"[sourcer] Apify returned {len(items)} places "
          f"({has_website} with a website, {outside_ncr} outside Delhi NCR — dropped)")
    return targets


def _source_from_seed_file(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return [{
        "business_name": r.get("business_name", ""),
        "phone": r.get("phone", ""),
        "email": r.get("email", ""),
        "rating": _to_rating(r.get("rating")),
        "reviews": _to_int(r.get("reviews")),
        "address": r.get("address", ""),
        "category": r.get("category", ""),
        "place_id": r.get("place_id", ""),
    } for r in rows]


def source_targets(mock: bool = False, category: str | None = None) -> list[dict]:
    """Return de-duplicated no-website place records for Delhi NCR businesses.

    `category` (one of config.BUSINESS_CATEGORIES, picked at the startup menu)
    narrows keyword-based sources to that category; None sweeps all of them.
    Seed-file and mock modes have no category dimension and ignore it.
    """
    if category:
        print(f"[sourcer] category filter: {category}")
    # Priority chain: Apify (card-free, preferred) -> Google Places -> seed CSV -> mock.
    if mock:
        print("[sourcer] mock mode — using built-in demo targets")
        raw = MOCK_TARGETS
    elif config.APIFY_TOKEN:
        print("[sourcer] APIFY_TOKEN set — sourcing via Apify Google Maps Scraper")
        raw = _source_from_apify(category)
    elif config.GOOGLE_PLACES_API_KEY:
        print("[sourcer] sourcing via Google Places API")
        raw = _source_from_places(config.GOOGLE_PLACES_API_KEY, category)
    elif os.path.exists(config.SEED_FILE):
        print(f"[sourcer] no API token — reading {config.SEED_FILE}")
        raw = _source_from_seed_file(config.SEED_FILE)
    else:
        print("[sourcer] no API token and no seed_places.csv — using built-in demo targets")
        raw = MOCK_TARGETS

    targets = _dedupe(raw)
    if config.MAX_TARGETS > 0:
        targets = targets[: config.MAX_TARGETS]
    print(f"[sourcer] {len(targets)} unique no-website places")
    return targets
