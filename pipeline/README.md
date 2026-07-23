# Lead Pipeline

Google Maps scrape → website enrichment → one leads file ready for outreach.

## Requirements

Docker Desktop running. Python venv is already set up in `.venv/`.

## Quick start

From the repo root (a sample `queries.txt` is included):

```bash
./run_pipeline.sh                                  # uses queries.txt, auto run name
./run_pipeline.sh queries.txt munich_dentists 10   # explicit name + depth
```

First run auto-creates the Python venv. Only requirement: Docker running.

Output lands in `output/`:

- `<name>_raw.csv` — raw Google Maps data (36+ columns: name, address, phone,
  website, ratings, reviews, hours, coordinates, emails …)
- `<name>_leads.csv` / `.json` — final leads, raw data plus per-website:
  `enriched_emails`, `enriched_phones`, `linkedin`, `facebook`, `instagram`,
  `twitter_x`, `youtube`, `xing`, `people` (owners/doctors from
  impressum/team pages), `services`, `site_title`, `site_description`,
  `crawl_error`.

## Scale to a whole country

One query per city. For Germany a top-80 city list is included:

```bash
while read c; do echo "dentist in $c, Germany"; done < cities_germany.txt > queries.txt
./run_pipeline.sh queries.txt germany_dentists 10
```

Depth 10 ≈ up to ~120 results per city. A full-country run takes hours; for
big runs Google may throttle you — add proxies via the scraper's `-proxies`
flag (edit `run_pipeline.sh`) or run overnight.

Any niche works: replace "dentist" with anything Google Maps understands
("physiotherapist", "roofing company", "steuerberater" …), any country.

## Stage details

**Stage 1** — [gosom/google-maps-scraper](https://github.com/gosom/google-maps-scraper)
(cloned in `../google-maps-scraper`, runs via its Docker image). `-email` makes
it visit each business website for emails; `-c 8` = concurrency.

**Stage 2** — `enrich.py` crawls each lead's homepage + up to 5 key pages
(impressum, team, about, kontakt, leistungen/services) and extracts contacts,
socials, people and services. Re-run it alone anytime:

```bash
.venv/bin/python3 enrich.py output/<name>_raw.csv -o output/<name>_leads
.venv/bin/python3 enrich.py --selftest   # sanity check
```

## Optional stage 3 — deeper person data

For leads where the website has no LinkedIn/owner info, the LeadMagic and
DataForB2B connectors (already hooked up in Claude) can take a lead's domain
and return employee counts, the company LinkedIn page, and decision-makers
with verified emails (`enrich_company`, `find_decision_makers`). Costs
credits, so run it only on shortlisted leads — just ask Claude with the
leads CSV.

## Legal notes

- Scraping Maps is against Google ToS (standard practice, but use proxies and
  don't hammer).
- Cold **email** in Germany effectively requires prior consent even for B2B
  (UWG §7). LinkedIn/phone outreach is the safer channel for German leads.
  Check per-country rules before emailing scraped addresses.
