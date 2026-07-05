"""Stage 2 — SITE age verification, layered signals (in lookup order):

  1. Wayback Machine first capture — how long the *website* has existed.
  2. crt.sh earliest certificate   — when the site first went live on HTTPS;
     the only reliable public detector of a brand-new (<=7 day) launch.
  3. RDAP, then WHOIS              — domain *registration* age, fallback only
     (registration age says how old the domain is, not the site on it).

Keep a domain ONLY if its verified age is >= 365 days (established) OR
<= 7 days (brand new). Anything in between, or fully unverifiable, is
discarded.

Evidence semantics matter: an archive capture or certificate proves the site
existed AT that moment (a lower bound on age). Old evidence can prove
"established", but only a first-ever cert issued days ago — or the
registration date — can indicate "brand new".
"""

import json
import os
import random
import time
from datetime import datetime, timezone

import whois

import config
import http_client

WAYBACK_CDX_URL = "https://web.archive.org/cdx/search/cdx"
CRTSH_URL = "https://crt.sh/"
RDAP_URL = "https://rdap.org/domain/{domain}"

# domain -> {"wayback": iso|"", "crt": iso|"", "reg": iso|""} ("" = looked up, none found)
_cache: dict[str, dict] = {}
_last_lookup_ts = 0.0  # wall-clock of the last live lookup (throttling)


def _throttle() -> None:
    """Space out live lookups — Wayback/crt.sh/RDAP/WHOIS all ban fast repeats."""
    global _last_lookup_ts
    min_gap = config.WHOIS_MIN_INTERVAL_SECONDS + random.uniform(0, config.WHOIS_JITTER_SECONDS)
    elapsed = time.monotonic() - _last_lookup_ts
    if elapsed < min_gap:
        time.sleep(min_gap - elapsed)
    _last_lookup_ts = time.monotonic()


def _load_cache() -> None:
    global _cache
    if os.path.exists(config.AGE_CACHE_FILE):
        try:
            with open(config.AGE_CACHE_FILE, encoding="utf-8") as f:
                _cache = json.load(f)
        except (json.JSONDecodeError, OSError):
            _cache = {}


def _save_cache() -> None:
    try:
        with open(config.AGE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache, f, indent=1)
    except OSError:
        pass


_load_cache()


def _cached_date(domain: str, signal: str, fetch) -> datetime | None:
    """Per-signal cached lookup; only live lookups are throttled."""
    entry = _cache.setdefault(domain, {})
    if signal in entry:
        return datetime.fromisoformat(entry[signal]) if entry[signal] else None
    _throttle()
    found = fetch(domain)
    entry[signal] = found.isoformat() if found else ""
    _save_cache()
    return found


# --- Signal 1: Wayback Machine ---

def _wayback_first_capture(domain: str) -> datetime | None:
    resp = http_client.get(WAYBACK_CDX_URL, timeout=30, params={
        "url": domain,
        "matchType": "domain",   # any subdomain counts (www-only archives are common)
        "output": "json",
        "fl": "timestamp",
        "limit": "1",            # CDX default sort is oldest-first
    })
    if resp is None or resp.status_code != 200:
        print(f"[age] {domain}: Wayback lookup failed")
        return None
    try:
        rows = resp.json()
    except ValueError:
        return None
    if len(rows) < 2 or not rows[1]:
        return None
    try:
        return datetime.strptime(rows[1][0], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# --- Signal 2: Certificate Transparency (crt.sh) ---

def _crt_earliest_cert(domain: str) -> datetime | None:
    # Exact identity first; wildcard fallback catches certs issued only to
    # www./sub.domains (the apex often isn't a SAN on old certs).
    for query in (domain, f"%.{domain}"):
        resp = http_client.get(CRTSH_URL, timeout=40,
                               params={"q": query, "output": "json"})
        if resp is None or resp.status_code != 200:
            print(f"[age] {domain}: crt.sh lookup failed for '{query}'")
            continue
        try:
            certs = resp.json()
        except ValueError:
            continue
        dates = []
        for cert in certs:
            raw = cert.get("not_before")
            if not raw:
                continue
            try:
                dates.append(datetime.fromisoformat(raw))
            except ValueError:
                continue
        if dates:
            earliest = min(dates)
            return earliest if earliest.tzinfo else earliest.replace(tzinfo=timezone.utc)
    return None


# --- Signal 3 (fallback): registration date via RDAP, then WHOIS ---

def _normalize_creation_date(raw) -> datetime | None:
    """python-whois may return a datetime, a list of them, or a string."""
    if isinstance(raw, list):
        raw = next((d for d in raw if isinstance(d, datetime)), raw[0] if raw else None)
    if isinstance(raw, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                raw = datetime.strptime(raw[:19], fmt)
                break
            except ValueError:
                continue
    if not isinstance(raw, datetime):
        return None
    if raw.tzinfo is None:
        raw = raw.replace(tzinfo=timezone.utc)
    return raw


def _registration_date(domain: str) -> datetime | None:
    resp = http_client.get(RDAP_URL.format(domain=domain), timeout=20)
    if resp is not None and resp.status_code == 200:
        try:
            for event in resp.json().get("events", []):
                if event.get("eventAction") == "registration" and event.get("eventDate"):
                    iso = event["eventDate"].replace("Z", "+00:00")
                    return _normalize_creation_date(datetime.fromisoformat(iso))
        except ValueError:
            pass
    try:
        record = whois.whois(domain)
        return _normalize_creation_date(record.creation_date)
    except Exception as exc:  # WHOIS failures are expected; treat as unverifiable
        print(f"[age] WHOIS failed for {domain}: {exc}")
        return None


# --- Decision ---

def _days_old(d: datetime) -> int:
    return (datetime.now(timezone.utc) - d).days


def _years_label(age_days: int, detail: str) -> str:
    years = age_days // 365
    return f"{years} year{'s' if years != 1 else ''}+ ({detail})"


def check_site_age(domain: str) -> str | None:
    """Return a human 'Site Age' label if the domain passes the filter, else None."""
    wayback = _cached_date(domain, "wayback", _wayback_first_capture)
    if wayback and _days_old(wayback) >= config.MIN_OLD_DAYS:
        label = _years_label(_days_old(wayback), f"site archived since {wayback:%Y-%m-%d}")
        print(f"[age] {domain}: {label} — kept (established site)")
        return label

    crt = _cached_date(domain, "crt", _crt_earliest_cert)
    if crt and _days_old(crt) >= config.MIN_OLD_DAYS:
        label = _years_label(_days_old(crt), f"HTTPS since {crt:%Y-%m-%d}")
        print(f"[age] {domain}: {label} — kept (established site)")
        return label
    if (crt and 0 <= _days_old(crt) <= config.MAX_NEW_DAYS
            and (wayback is None or _days_old(wayback) <= config.MAX_NEW_DAYS)):
        age = _days_old(crt)
        label = f"{age} day{'s' if age != 1 else ''} (new launch, first cert {crt:%Y-%m-%d})"
        print(f"[age] {domain}: {label} — kept (brand-new launch)")
        return label

    # Web evidence places the site at 8-364 days old -> out of window.
    evidence_ages = [_days_old(d) for d in (wayback, crt) if d]
    if evidence_ages and max(evidence_ages) > config.MAX_NEW_DAYS:
        print(f"[age] {domain}: site ~{max(evidence_ages)} days old — outside window, discarded")
        return None

    # No usable web evidence (or all of it <=7 days, which can't distinguish a
    # truly new site from one the crawlers only just found) -> registration decides.
    reg = _cached_date(domain, "reg", _registration_date)
    if reg is None:
        print(f"[age] {domain}: age unverifiable on all signals — discarded")
        return None
    age = _days_old(reg)
    if age >= config.MIN_OLD_DAYS:
        label = _years_label(age, f"registered {reg:%Y-%m-%d}")
        print(f"[age] {domain}: {label} — kept (established registration)")
        return label
    if 0 <= age <= config.MAX_NEW_DAYS:
        label = f"{age} day{'s' if age != 1 else ''} (new registration)"
        print(f"[age] {domain}: {label} — kept (fresh registration)")
        return label
    print(f"[age] {domain}: {age} days since registration — outside window, discarded")
    return None
