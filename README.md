# lead-enrichment-pipeline

Google Maps scrape → website enrichment → one leads file ready for outreach.

Give it a niche and a location ("dentist in Munich, Germany") and it produces a
CSV/JSON of businesses with everything Google Maps knows about them, plus
everything their own website reveals: emails, phones, social profiles
(LinkedIn, Instagram, Facebook, X, YouTube, Xing), owner/team names, services
offered, and what the business says it does.

## Requirements

- Docker (running) — that's it. First run auto-creates the Python venv.

## Quick start

```bash
git clone git@github.com:SyedBahjat/lead-enrichment-pipeline.git
cd lead-enrichment-pipeline
./run_pipeline.sh                                  # uses queries.txt, auto run name
./run_pipeline.sh queries.txt munich_dentists 10   # explicit name + depth
```

`queries.txt` holds one Google Maps search per line. Output lands in
`pipeline/output/`:

- `<name>_raw.csv` — raw Google Maps data (36+ columns: name, address, phone,
  website, ratings, reviews, hours, coordinates, emails …)
- `<name>_leads.csv` / `.json` — final leads: raw data plus per-website
  `enriched_emails`, `enriched_phones`, `linkedin`, `facebook`, `instagram`,
  `twitter_x`, `youtube`, `xing`, `people` (owners/doctors from
  impressum/team pages), `services`, `site_title`, `site_description`,
  `crawl_error`.

## Scale to a whole country

One query per city. A top-80 German city list is included:

```bash
while read c; do echo "dentist in $c, Germany"; done < pipeline/cities_germany.txt > queries.txt
./run_pipeline.sh queries.txt germany_dentists 10
```

Depth 10 ≈ up to ~120 results per city. A full-country run takes hours; for
big runs Google may throttle you — add proxies via the scraper's `-proxies`
flag (edit `pipeline/run_pipeline.sh`) or run overnight.

Any niche works: replace "dentist" with anything Google Maps understands
("physiotherapist", "roofing company", "steuerberater" …), any country.

## How it works

**Stage 1 — Google Maps.** [gosom/google-maps-scraper](https://github.com/gosom/google-maps-scraper)
(included as a submodule, runs via its Docker image — no Go needed). The
`-email` flag makes it visit each business website for emails; `-c 8` sets
concurrency.

**Stage 2 — website enrichment.** `pipeline/enrich.py` crawls each lead's
homepage plus up to 5 key pages (impressum, team, about, kontakt,
leistungen/services) and extracts contacts, socials, people, and services. It
handles `[at]`-obfuscated emails and broken SSL certs. Re-run it alone:

```bash
pipeline/.venv/bin/python3 pipeline/enrich.py pipeline/output/<name>_raw.csv -o pipeline/output/<name>_leads
pipeline/.venv/bin/python3 pipeline/enrich.py --selftest   # sanity check
```

**Optional stage 3 — deeper person data.** For shortlisted leads, B2B
enrichment APIs (e.g. LeadMagic, DataForB2B) can take a lead's domain and
return employee counts, the company LinkedIn page, and decision-makers with
verified emails. Costs credits — run only on leads worth it.

## Legal notes

- Scraping Maps is against Google ToS (standard practice, but use proxies and
  don't hammer).
- Cold **email** in Germany effectively requires prior consent even for B2B
  (UWG §7). LinkedIn/phone outreach is the safer channel for German leads.
  Check per-country rules before emailing scraped addresses.
