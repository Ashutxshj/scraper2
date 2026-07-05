"""Stage 3 — Contact extraction: crawl homepage + contact-ish pages, pull
emails (regex + mailto:) and Indian phone numbers (regex + tel:).

Static-first (requests + BeautifulSoup). If USE_PLAYWRIGHT=1 and the static
pass found nothing, the homepage is re-rendered with headless Chromium.
"""

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import config
import http_client

_CONTACT_LINK_HINT = re.compile(r"contact|reach|about|get.?in.?touch", re.IGNORECASE)


def _fetch(url: str) -> str | None:
    """Fetch via the shared client (rotating proxies + backoff/jitter)."""
    resp = http_client.get(url, allow_redirects=True)
    if resp is not None and resp.status_code == 200 and \
            "text/html" in resp.headers.get("Content-Type", "html"):
        return resp.text
    return None


def _clean_emails(candidates: set[str]) -> list[str]:
    out = set()
    for email in candidates:
        e = email.strip().strip(".").lower()
        if any(junk in e for junk in config.EMAIL_JUNK_PATTERNS):
            continue
        if len(e) > 64 or e.count("@") != 1:
            continue
        out.add(e)
    # Prefer info@/contact@/sales@-style addresses first, then shortest.
    return sorted(out, key=lambda e: (not e.startswith(("info@", "contact@", "sales@", "hello@")), len(e)))


def _normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0091"):
        digits = digits[4:]
    elif digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91{digits}"
    # Landline with STD code kept as dialled form
    if 10 <= len(digits) <= 11 and raw.strip().lstrip("+").startswith(("011", "0120", "0124", "0129", "0130", "0131")):
        return f"+91{digits.lstrip('0')}"
    return None


def _extract_from_html(html: str, base_url: str) -> tuple[set[str], set[str], list[str]]:
    """Return (emails, phones, contact-ish links) found in one page."""
    soup = BeautifulSoup(html, "html.parser")
    emails: set[str] = set()
    phones: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            addr = href[7:].split("?")[0].strip()
            if addr:
                emails.add(addr)
        elif href.lower().startswith("tel:"):
            norm = _normalize_phone(href[4:])
            if norm:
                phones.add(norm)

    text = soup.get_text(" ", strip=True)
    emails.update(config.EMAIL_RE.findall(text))
    emails.update(config.EMAIL_RE.findall(html))  # catches JSON-LD / hidden markup
    for m in config.OBFUSCATED_EMAIL_RE.finditer(text):
        emails.add(f"{m.group(1)}@{m.group(2)}.{m.group(3)}")

    for m in config.PHONE_RE.finditer(text):
        norm = _normalize_phone(m.group(0))
        if norm:
            phones.add(norm)

    links = []
    base_netloc = urlparse(base_url).netloc
    for a in soup.find_all("a", href=True):
        label = f"{a['href']} {a.get_text(' ', strip=True)}"
        if _CONTACT_LINK_HINT.search(label):
            full = urljoin(base_url, a["href"])
            if urlparse(full).netloc == base_netloc:
                links.append(full.split("#")[0])
    return emails, phones, links


def _render_with_playwright(url: str) -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[scraper] USE_PLAYWRIGHT=1 but playwright not installed — skipping")
        return None
    proxy = http_client.POOL.next()
    launch_kwargs = {"headless": True}
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_kwargs)
            page = browser.new_page(user_agent=config.USER_AGENT)
            page.goto(url, wait_until="networkidle", timeout=30000)
            html = page.content()
            browser.close()
            return html
    except Exception as exc:
        print(f"[scraper] playwright render failed {url}: {exc}")
        return None


def scrape_contacts(url: str) -> dict:
    """Crawl a site and return {'email': str|None, 'phone': str|None}."""
    base = url.rstrip("/")
    queue = [base + path for path in config.CONTACT_PATHS]
    visited: set[str] = set()
    emails: set[str] = set()
    phones: set[str] = set()
    pages_fetched = 0

    while queue and pages_fetched < config.MAX_PAGES_PER_SITE:
        page_url = queue.pop(0)
        key = page_url.rstrip("/").lower()
        if key in visited:
            continue
        visited.add(key)

        html = _fetch(page_url)
        if html is None:
            continue
        pages_fetched += 1
        e, p, links = _extract_from_html(html, page_url)
        emails |= e
        phones |= p
        # Discovered contact-ish links go to the front of the queue.
        queue = [l for l in links if l.rstrip("/").lower() not in visited] + queue
        http_client.polite_sleep()

    if not emails and not phones and config.USE_PLAYWRIGHT:
        print(f"[scraper] static pass empty for {url} — trying Playwright render")
        html = _render_with_playwright(base)
        if html:
            e, p, _ = _extract_from_html(html, base)
            emails |= e
            phones |= p

    clean = _clean_emails(emails)
    return {
        "email": clean[0] if clean else None,
        "phone": sorted(phones)[0] if phones else None,
    }
