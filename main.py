"""Orchestrator: source -> site-age filter (Wayback/crt.sh/RDAP/WHOIS) ->
scrape contacts -> STRICT VALIDATION GATE -> delhi_ncr_leads.csv -> Resend.

Usage:
  python main.py                 # full run (Apify / Places API / seed_urls.csv)
  python main.py --mock          # built-in demo targets, no API keys needed
  python main.py --limit 25      # cap number of sourced targets
  python main.py --no-email      # build the CSV but skip Resend delivery
  python main.py --fresh         # ALSO sweep newly-registered NCR domains (<=7d)
"""

import argparse
import csv
import os
import shutil
import sys
from datetime import datetime

import config
from contact_scraper import scrape_contacts
from delivery import send_csv
from domain_filter import check_site_age
from fresh_domains import source_fresh_domains
from target_sourcer import registrable_domain, source_targets


def run(mock: bool, limit: int, no_email: bool, fresh: bool = False) -> int:
    # --- Stage 1: source targets ---
    targets = source_targets(mock=mock)

    # --- Stage 1b (opt-in): brand-new NCR registrations, found directly ---
    if fresh:
        have = {registrable_domain(t["url"]) for t in targets}
        targets += [t for t in source_fresh_domains()
                    if registrable_domain(t["url"]) not in have]

    if limit > 0:
        targets = targets[:limit]
    if not targets:
        print("[main] no targets sourced — nothing to do")
        return 1

    rows: list[dict] = []
    stats = {"sourced": len(targets), "age_rejected": 0, "no_contact": 0, "kept": 0}

    for i, target in enumerate(targets, 1):
        url = target["url"]
        domain = registrable_domain(url)
        print(f"\n[main] ({i}/{len(targets)}) {target['business_name']} — {domain}")

        # --- Stage 2: site age gate (skipped for fresh-sweep targets, whose
        # age is known by construction from the dated NRD list) ---
        age_label = target.get("age_label") or check_site_age(domain)
        if age_label is None:
            stats["age_rejected"] += 1
            continue

        # --- Stage 3: contact extraction ---
        contacts = scrape_contacts(url)

        # --- Stage 4: STRICT VALIDATION GATE ---
        # Rule: if email IS NULL and phone IS NULL, discard the row entirely.
        if not contacts["email"] and not contacts["phone"]:
            print(f"[main] {domain}: no email AND no phone — row discarded")
            stats["no_contact"] += 1
            continue

        stats["kept"] += 1
        print(f"[main] {domain}: KEPT (email={contacts['email']}, phone={contacts['phone']})")
        rows.append({
            "Business Name": target["business_name"],
            "URL": url,
            "Email": contacts["email"] or "",
            "Phone Number": contacts["phone"] or "",
            "Site Age": age_label,
        })

    # --- Stage 4b: write CSV to the archive folder (only validated rows here) ---
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = os.path.join(config.OUTPUT_DIR, f"{config.OUTPUT_CSV_BASENAME}_{stamp}.csv")
    latest_path = os.path.join(config.OUTPUT_DIR, f"{config.OUTPUT_CSV_BASENAME}_latest.csv")

    with open(archive_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=config.CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    shutil.copyfile(archive_path, latest_path)  # stable path for quick access

    print(
        f"\n[main] done: sourced={stats['sourced']} "
        f"age_rejected={stats['age_rejected']} no_contact={stats['no_contact']} "
        f"kept={stats['kept']}"
    )
    print(f"[main] CSV archived -> {archive_path}")
    print(f"[main] latest copy  -> {latest_path}")

    # --- Stage 5: delivery (wa1.txt theory) ---
    if no_email:
        print("[main] --no-email set — skipping delivery")
    elif not rows:
        print("[main] 0 validated leads — skipping delivery")
    else:
        send_csv(archive_path, len(rows))

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delhi NCR business leads pipeline")
    parser.add_argument("--mock", action="store_true", help="use built-in demo targets")
    parser.add_argument("--limit", type=int, default=0, help="cap sourced targets")
    parser.add_argument("--no-email", action="store_true", help="skip Resend delivery")
    parser.add_argument("--fresh", action="store_true",
                        help="also sweep newly-registered NCR domains (<=7 days old)")
    args = parser.parse_args()
    sys.exit(run(mock=args.mock, limit=args.limit, no_email=args.no_email,
                 fresh=args.fresh))
