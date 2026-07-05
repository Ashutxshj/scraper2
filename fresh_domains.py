"""Stage 1b (opt-in via --fresh) — source BRAND-NEW businesses directly.

Week-old websites essentially never appear on Google Maps yet, so instead of
waiting for them this module reads the free WhoisDS newly-registered-domains
feed for the last FRESH_NRD_DAYS_BACK days, keeps domains whose name contains
a Delhi NCR city token (minus tech/marketing sellers), and checks that a site
actually answers. Everything sourced here is <= 7 days old BY CONSTRUCTION
(the feed is dated), so targets carry a preset `age_label` and skip the slow
age gate in main.py.

Caveat: the free feed covers gTLDs only (.com/.net/.org/…). ccTLDs like .in
publish no zone files, so brand-new .in registrations can't be found this way.
"""

import base64
import io
import zipfile
from datetime import datetime, timedelta, timezone

import requests

import config

# Free daily list; the URL path is base64("YYYY-MM-DD.zip").
WHOISDS_URL = "https://www.whoisds.com/whois-database/newly-registered-domains/{key}/nrd"


def _nrd_domains(day: datetime) -> list[str]:
    key = base64.b64encode(f"{day:%Y-%m-%d}.zip".encode()).decode()
    try:
        resp = requests.get(WHOISDS_URL.format(key=key), timeout=60,
                            headers={"User-Agent": config.USER_AGENT})
    except requests.RequestException as exc:
        print(f"[fresh] NRD list {day:%Y-%m-%d}: {type(exc).__name__}")
        return []
    if resp.status_code != 200:
        print(f"[fresh] NRD list {day:%Y-%m-%d}: HTTP {resp.status_code}")
        return []
    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            names = zf.namelist()
            return zf.read(names[0]).decode("utf-8", "replace").split() if names else []
    except zipfile.BadZipFile:
        print(f"[fresh] NRD list {day:%Y-%m-%d}: not a zip (feed layout changed?)")
        return []


def _is_candidate(domain: str) -> bool:
    return (any(city in domain for city in config.FRESH_DOMAIN_KEYWORDS)
            and not any(kw in domain for kw in config.EXCLUDED_KEYWORDS))


def _site_responds(domain: str) -> bool:
    """One fast attempt per scheme — deliberately NOT via http_client: most
    week-old domains serve nothing yet, and retry+backoff per dead domain
    would make the sweep crawl."""
    for scheme in ("https", "http"):
        try:
            resp = requests.get(f"{scheme}://{domain}", timeout=8,
                                headers={"User-Agent": config.USER_AGENT},
                                allow_redirects=True)
            if resp.status_code < 500:
                return True
        except requests.RequestException:
            continue
    return False


def source_fresh_domains() -> list[dict]:
    """Return live, <=7-day-old NCR-keyword domains as pipeline targets."""
    today = datetime.now(timezone.utc)
    days_back = min(config.FRESH_NRD_DAYS_BACK, config.MAX_NEW_DAYS)
    candidates: dict[str, int] = {}  # domain -> age in days
    # Start at yesterday: today's list isn't published until tomorrow.
    for age in range(1, days_back + 1):
        day = today - timedelta(days=age)
        domains = _nrd_domains(day)
        hits = [d.strip().lower() for d in domains if _is_candidate(d.strip().lower())]
        print(f"[fresh] {day:%Y-%m-%d}: {len(domains)} new domains, "
              f"{len(hits)} NCR keyword hits")
        for d in hits:
            candidates.setdefault(d, age)

    targets, checked = [], 0
    # Newest first — those are the freshest leads.
    for domain, age in sorted(candidates.items(), key=lambda kv: kv[1]):
        if len(targets) >= config.FRESH_MAX_DOMAINS:
            print(f"[fresh] cap FRESH_MAX_DOMAINS={config.FRESH_MAX_DOMAINS} reached — "
                  f"{len(candidates) - checked} candidates unchecked")
            break
        checked += 1
        if not _site_responds(domain):
            continue
        targets.append({
            "business_name": domain,
            "url": f"https://{domain}",
            "age_label": f"{age} day{'s' if age != 1 else ''} (new registration)",
        })
    print(f"[fresh] {len(targets)} live brand-new NCR domains "
          f"(of {len(candidates)} candidates)")
    return targets
