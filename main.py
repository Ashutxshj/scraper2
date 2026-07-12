"""Orchestrator: pick category -> source Google Maps places with NO website ->
STRICT VALIDATION GATE -> classify Goldenrod / New Bark -> Projects/leads_master.xlsx.

Leads land in the ONE master workbook shared by every repo (master_registry.py).
There is no output/ folder and no per-run report: businesses already in the
master are skipped by upsert(), so re-running never duplicates a lead.

Lead tiers (every lead has no website by construction):
  * Goldenrod — rating >= 4.5 with 500+ reviews.
  * New Bark  — every other no-website business.

These leads are phone-only: Google Maps listings rarely expose an email, and
there is no site to scrape one from. /scraper3 finds the ones reachable by
Instagram DM instead.

Usage:
  python main.py                 # full run (Apify / Places API / seed_places.csv)
  python main.py --mock          # built-in demo targets, no API keys needed
  python main.py --limit 25      # cap number of sourced targets
  python main.py --no-email      # build the report but skip Resend delivery
  python main.py --category 3    # preselect a business category (skips the menu)

At startup a numbered menu of BUSINESS_CATEGORIES is shown — enter a number to
source only that category (e.g. 1 = dentist), or press Enter / 0 for all.
"""

import argparse
import os
import sys

import config
import master_registry
from delivery import send_master
from target_sourcer import source_targets


def pick_category(preselected: int | None) -> str | None:
    """Numbered category menu. Returns the chosen category, or None for all."""
    categories = config.BUSINESS_CATEGORIES
    if preselected is not None:
        if preselected == 0:
            print("[main] --category 0 -> ALL categories")
            return None
        if 1 <= preselected <= len(categories):
            print(f"[main] --category {preselected} -> '{categories[preselected - 1]}'")
            return categories[preselected - 1]
        print(f"[main] --category {preselected} out of range — using ALL categories")
        return None

    print("\nWhich business category should this run target?")
    for i, cat in enumerate(categories, 1):
        print(f"  {i:2d}. {cat}")
    print("   0. all categories")
    while True:
        try:
            raw = input("Enter a number [0]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[main] no selection — using ALL categories")
            return None
        if raw in ("", "0"):
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(categories):
            choice = categories[int(raw) - 1]
            print(f"[main] targeting category: {choice}")
            return choice
        print(f"Invalid choice '{raw}' — enter 0-{len(categories)}")


def classify(target: dict) -> str:
    """Goldenrod iff rating >= 4.5 AND 500+ reviews; everything else is New Bark."""
    rating = target.get("rating")
    reviews = target.get("reviews") or 0
    if (rating is not None
            and rating >= config.GOLDENROD_MIN_RATING
            and reviews >= config.GOLDENROD_MIN_REVIEWS):
        return config.LEAD_TYPE_GOLDENROD
    return config.LEAD_TYPE_NEW_BARK


def _master_keys(target: dict) -> set[str]:
    """Identity keys for a sourcer target, in master-column terms."""
    return master_registry.identity_keys({
        "Business Name": target.get("business_name", ""),
        "Phone Number": target.get("phone", ""),
        "Email Address": target.get("email", ""),
        "Instagram": "",
    })


def run(mock: bool, limit: int, no_email: bool, category: str | None = None) -> int:
    # --- Stage 1: source no-website places from Google Maps ---
    targets = source_targets(mock=mock, category=category)

    # Businesses already in the master are dropped BEFORE --limit so the cap
    # fills with fresh leads. Mock runs skip it so smoke tests stay green.
    if not mock:
        known = master_registry.load_keys()
        if known:
            before = len(targets)
            targets = [t for t in targets if not (_master_keys(t) & known)]
            if before - len(targets):
                print(f"[main] {before - len(targets)} businesses already in the "
                      "master file — skipped")

    if limit > 0:
        targets = targets[:limit]
    if not targets:
        print("[main] no targets sourced — nothing to do")
        return 1

    rows: list[dict] = []
    stats = {"sourced": len(targets), "no_contact": 0,
             config.LEAD_TYPE_GOLDENROD: 0, config.LEAD_TYPE_NEW_BARK: 0}

    for i, target in enumerate(targets, 1):
        name = target["business_name"]
        phone, email = target.get("phone") or "", target.get("email") or ""

        # --- Stage 2: STRICT VALIDATION GATE ---
        # Rule: if email IS NULL and phone IS NULL, discard the row entirely.
        if not email and not phone:
            print(f"[main] ({i}/{len(targets)}) {name}: no email AND no phone — discarded")
            stats["no_contact"] += 1
            continue

        # --- Stage 3: tier classification ---
        lead_type = classify(target)
        stats[lead_type] += 1
        rating = target.get("rating")
        print(f"[main] ({i}/{len(targets)}) {name}: {lead_type} "
              f"(rating={rating if rating is not None else 'n/a'}, "
              f"reviews={target.get('reviews') or 0}, phone={phone or '-'})")

        reviews = target.get("reviews") or 0
        rows.append({
            "Business Name": name,
            "Category": target.get("category") or "",
            "Lead Type": lead_type,
            "Has_Website": False,
            "Phone Number": phone,
            "Email Address": email,
            "Instagram": "",
            "Rating": rating if rating is not None else "",
            "Reviews": reviews,
            master_registry.BULLETS_COLUMN: master_registry.no_website_bullets(
                target.get("category"), rating, reviews),
        })

    # Goldenrod first, then by review count within each tier.
    rows.sort(key=lambda r: (r["Lead Type"] != config.LEAD_TYPE_GOLDENROD,
                             -(r["Reviews"] or 0)))

    # --- Stage 4: append to the ONE master workbook ---
    # A --mock run must never pollute the real master with fictional businesses.
    # Overriding MASTER_FILE (a scratch path) is the explicit opt-in used by tests.
    if mock and not os.getenv("MASTER_FILE"):
        print("[main] mock run — not touching the real master file")
        added = 0
    else:
        added = master_registry.upsert(rows)

    goldenrod = stats[config.LEAD_TYPE_GOLDENROD]
    new_bark = stats[config.LEAD_TYPE_NEW_BARK]
    print(
        f"\n[main] done: sourced={stats['sourced']} no_contact={stats['no_contact']} "
        f"kept={len(rows)} added={added} (Goldenrod={goldenrod}, New Bark={new_bark})"
    )
    print(f"[main] master -> {master_registry.MASTER_FILE}")
    if len(rows) - added:
        print(f"[main] {len(rows) - added} were already in the master file")

    # --- Stage 5: delivery (wa1.txt theory) ---
    if no_email:
        print("[main] --no-email set — skipping delivery")
    elif not added:
        print("[main] 0 new leads — skipping delivery")
    else:
        send_master(added, goldenrod=goldenrod, new_bark=new_bark)

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Delhi NCR no-website business leads pipeline")
    parser.add_argument("--mock", action="store_true", help="use built-in demo targets")
    parser.add_argument("--limit", type=int, default=0, help="cap sourced targets")
    parser.add_argument("--no-email", action="store_true", help="skip Resend delivery")
    parser.add_argument("--category", type=int, default=None,
                        help="business category number (1-based, see startup menu); "
                             "omit for the interactive menu, 0 for all")
    args = parser.parse_args()
    chosen = pick_category(args.category)
    sys.exit(run(mock=args.mock, limit=args.limit, no_email=args.no_email,
                 category=chosen))
