"""Central configuration: env loading + pipeline constants."""

import os

from dotenv import load_dotenv

load_dotenv()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default

# --- Delivery (Resend, per wa1.txt report-generator theory) ---
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "ashutosh@06067gmail.com")

# --- Sourcing ---
# Apify Google Maps Scraper (card-free, preferred). Presence of the token
# activates Apify mode ahead of Google Places.
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
APIFY_ACTOR_ID = os.getenv("APIFY_ACTOR_ID", "compass/crawler-google-places")
APIFY_MAX_PLACES_PER_SEARCH = _env_int("APIFY_MAX_PLACES_PER_SEARCH", 20)
APIFY_MAX_SEARCHES = _env_int("APIFY_MAX_SEARCHES", 20)  # bound credit burn

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
# Optional manual feed (e.g. a Maps-scraper export). Columns:
#   business_name,phone,email,rating,reviews,address,category
SEED_FILE = "seed_places.csv"

NCR_CITIES = [
    "Delhi",
    "New Delhi",
    "Noida",
    "Greater Noida",
    "Gurgaon",
    "Faridabad",
    "Ghaziabad",
]

# Target customer profile: local businesses/orgs that BUY web & digital services.
# Sellers of those services (tech / digital-marketing) are excluded — see
# EXCLUDED_KEYWORDS below.
BUSINESS_CATEGORIES = [
    "dentist",
    "medical clinic",
    "restaurant",
    "cafe",
    "salon",
    "gym",
    "law firm",
    "real estate agency",
    "coaching institute",
    "consultant",
    "chartered accountant",
    "boutique shop",
    "manufacturing company",
    "NGO",
]

# Businesses that SELL tech / digital-marketing services — peers, not prospects.
# Matched case-insensitively against business name + the Maps category label;
# any hit skips the target.
EXCLUDED_KEYWORDS = [
    "digital", "marketing", "seo", "branding", "advertis", "adagenc",
    "ad agenc", "media house",
    "social media", "software", "tech", "infotech", "it solution", "it service",
    "saas", "web design", "webdesign", "web develop", "webdev", "website",
    "app develop", "graphic design",
]

# Accepted place locations — lowercase substring match against the city/address
# the source returns. Anything that matches none of these is outside Delhi NCR.
NCR_CITY_KEYWORDS = [
    "delhi", "noida", "gurgaon", "gurugram", "faridabad", "ghaziabad",
]

# --- Lead tiers (all leads have NO website by construction) ---
# Goldenrod: highly-rated, heavily-reviewed businesses running without a site —
# the hottest prospects. Everything else lands in New Bark.
LEAD_TYPE_GOLDENROD = "Goldenrod"
LEAD_TYPE_NEW_BARK = "New Bark"
GOLDENROD_MIN_RATING = _env_float("GOLDENROD_MIN_RATING", 4.5)
GOLDENROD_MIN_REVIEWS = _env_int("GOLDENROD_MIN_REVIEWS", 500)
# Golden-yellow row background applied to Goldenrod rows in the XLSX (ARGB-less hex).
GOLDENROD_FILL_HEX = "FFDF00"

MAX_TARGETS = _env_int("MAX_TARGETS", 0)  # 0 = unlimited
REQUEST_TIMEOUT = 15
REQUEST_DELAY_SECONDS = _env_float("REQUEST_DELAY_SECONDS", 1.0)

# --- Anti-ban: retry/backoff + jitter (applies to all HTTP fetches) ---
MAX_RETRIES = _env_int("MAX_RETRIES", 3)          # attempts per request on 429/503/timeout
BACKOFF_BASE_SECONDS = _env_float("BACKOFF_BASE_SECONDS", 1.5)  # exponential base
BACKOFF_MAX_SECONDS = _env_float("BACKOFF_MAX_SECONDS", 30.0)   # cap per wait
# Randomized inter-request delay window (overrides the fixed delay when max > 0).
JITTER_MIN_SECONDS = _env_float("JITTER_MIN_SECONDS", 0.8)
JITTER_MAX_SECONDS = _env_float("JITTER_MAX_SECONDS", 2.5)

# --- Anti-ban: rotating proxies ---
# Comma-separated in PROXY_LIST, and/or one-per-line in proxies.txt.
# Each entry: scheme://[user:pass@]host:port  (http/https/socks5).
PROXY_LIST = os.getenv("PROXY_LIST", "")
PROXY_FILE = os.getenv("PROXY_FILE", "proxies.txt")
PROXY_MAX_FAILURES = _env_int("PROXY_MAX_FAILURES", 3)  # strikes before a proxy is dropped

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# --- Output ---
# Reports are archived here (timestamped) in addition to being emailed.
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
OUTPUT_BASENAME = "delhi_ncr_no_website_leads"
CSV_COLUMNS = [
    "Business Name", "Category", "Phone Number", "Email",
    "Rating", "Reviews", "Address", "Lead Type",
]
SENDS_LOG_FILE = os.path.join(OUTPUT_DIR, "sends_log.jsonl")

# Registry of every business already emailed in a past report (see
# contacted_registry.py). Lives in the project root so it survives runs;
# businesses in it are skipped by future runs and never re-emailed.
CONTACTED_FILE = os.getenv("CONTACTED_FILE", "contacted_businesses.xlsx")
