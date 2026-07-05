# Web Scraper Project Plan: Delhi NCR Business Leads

## 1. Project Objective
Build an automated web scraping pipeline to extract contact information (Email, Phone) from businesses located in the **Delhi NCR region**. The extracted data must be saved in a CSV format and must strictly filter domains based on their registration age (either >= 1 year old OR <= 1 week old) and the presence of valid contact info.

## 2. The 3-Step Pipeline Architecture

### Step 1: Sourcing Targets (The "Delhi NCR" Filter)
* **Method:** Instead of crawling the open web, use the Google Places API or a Google Maps scraper.
* **Action:** Search for local business categories across Delhi, Noida, Gurgaon, etc. Extract their website URLs to build a highly targeted seed list.

### Step 2: Domain Age Verification (The "1 Year or 1 Week" Filter)
* **Method:** Use WHOIS database lookups (`python-whois`). *Do not rely on sitemaps or robots.txt for creation dates.*
* **Action:** Look up the domain's `Creation Date`. Filter the list to keep ONLY domains that were registered > 365 days ago OR < 7 days ago.

### Step 3: Contact Info Extraction (The Email/Phone Crawler)
* **Method:** Custom web crawler using Python (BeautifulSoup and/or Playwright).
* **Action:** * Crawl the Homepage and common sub-pages (`/contact`, `/about`, `/reach-us`).
    * Extract emails via Regex and HTML `mailto:` tags.
    * Extract Indian Phone numbers (e.g., +91 prefixes, standard 10-digit mobile, 011/0120/0124 landline codes) via Regex and HTML `tel:` tags.

## 3. Strict Validation Gate (Data Quality)
* Before saving to the dataset, the scraper must verify if the target yielded any contact data.
* **Rule:** If `email IS NULL` AND `phone IS NULL`, discard the row entirely.
* **Rule:** Only write rows to the final CSV if at least one contact method was successfully scraped.

## 4. Proposed Tech Stack
* **Language:** Python
* **Scraping & Parsing:** `Playwright` (for JavaScript-heavy modern sites) and `BeautifulSoup`.
* **Domain Data:** `python-whois`
* **Data Export:** Python `csv` module or `pandas`.

---

## 🤖 Instructions for the LLM Developer Agent:
Please act as a Senior Python Data Engineer. Read the project plan above and generate the corresponding Python code. I need a modular, well-documented solution split into the following components:

1.  `target_sourcer.py`: A module (or placeholder logic) to query Google Maps/Places API to fetch business URLs in Delhi NCR.
2.  `domain_filter.py`: A module using `python-whois` that takes a URL, calculates its age from the creation date, and returns the age category if it meets the criteria (>= 1 year or <= 1 week).
3.  `contact_scraper.py`: A module using `Playwright` and `BeautifulSoup` that navigates to a URL, checks the homepage and `/contact` page, and uses Regex to extract emails and Indian phone numbers.
4.  `main.py`: The orchestrator script that runs the pipeline. It must include the **Strict Validation Gate** logic (discarding domains with no contact info) and output the final validated data to `delhi_ncr_leads.csv` with the columns: `Business Name`, `URL`, `Email`, `Phone Number`, and `Domain Age`.
