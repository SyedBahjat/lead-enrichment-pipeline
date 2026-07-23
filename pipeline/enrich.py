#!/usr/bin/env python3
"""Enrich a gosom/google-maps-scraper CSV with intel crawled from each business website.

For every lead that has a website it fetches the homepage plus a few key pages
(impressum/about/team/contact/services) and extracts:
  - emails (incl. common [at]/(at) obfuscation), phones (tel: links)
  - social profiles: LinkedIn (company page preferred), Facebook, Instagram,
    X/Twitter, YouTube, Xing
  - services offered (page headings + service-page nav links)
  - people (owner/doctors/managing directors from impressum & team pages)
  - site title + meta description (what they say they do)

Usage:
    python3 enrich.py raw.csv -o leads          -> leads.csv + leads.json
    python3 enrich.py --selftest
"""

import argparse
import concurrent.futures
import csv
import json
import re
import sys
import urllib.parse

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
TIMEOUT = 15
MAX_SUBPAGES = 5

PAGE_KEYWORDS = [
    "impressum", "imprint", "legal-notice", "about", "ueber", "über",
    "team", "praxisteam", "unser-team", "kontakt", "contact",
    "leistungen", "services", "behandlung", "praxis",
]

SERVICE_HINTS = ["leistung", "service", "behandlung", "angebot", "therapie"]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
OBFUSCATED_RE = re.compile(
    r"([a-zA-Z0-9._%+\-]+)\s*[\[\(]\s*at\s*[\]\)]\s*([a-zA-Z0-9.\-]+)\s*"
    r"(?:[\[\(]\s*dot\s*[\]\)]\s*([a-zA-Z]{2,}))?", re.I)
EMAIL_JUNK = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
EMAIL_JUNK_DOMAINS = ("example.com", "domain.com", "email.com", "sentry.io",
                      "wixpress.com", "yourdomain")

# ponytail: naive heuristic for German/English professional names; misses some,
# upgrade to an NER model if precision matters.
PERSON_RE = re.compile(
    r"(?:(?:Prof\.\s*)?Dr\.(?:\s*med\.(?:\s*dent\.)?)?|Prof\.|Dipl\.[\w.\-]*|"
    r"Inhaber(?:in)?\s*:?|Geschäftsführer(?:in)?\s*:?|Owner\s*:?|ZA\s|ZÄ\s)"
    r"\s*((?:[A-ZÄÖÜ][a-zäöüßé\-\.]+\s+){1,3}[A-ZÄÖÜ][a-zäöüßé\-]+)")

SOCIAL_DOMAINS = {
    "linkedin": "linkedin.com",
    "facebook": "facebook.com",
    "instagram": "instagram.com",
    "twitter_x": ("twitter.com", "x.com"),
    "youtube": "youtube.com",
    "xing": "xing.com",
}


def fetch(url, session, verify=True):
    try:
        r = session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA},
                        allow_redirects=True, verify=verify)
        if r.ok and "text/html" in r.headers.get("content-type", "text/html"):
            return r.text, str(r.url)
    except requests.exceptions.SSLError:
        if verify:  # broken cert chains are common on small-business sites
            return fetch(url, session, verify=False)
    except requests.RequestException:
        pass
    return None, url


def extract_emails(html):
    found = set()
    for m in EMAIL_RE.findall(html):
        e = m.strip(".").lower()
        if not e.endswith(EMAIL_JUNK) and not any(d in e for d in EMAIL_JUNK_DOMAINS):
            found.add(e)
    for user, dom, tld in OBFUSCATED_RE.findall(html):
        dom = dom.strip(".")
        email = f"{user}@{dom}.{tld}".lower() if tld else f"{user}@{dom}".lower()
        if "." in email.split("@")[1]:
            found.add(email)
    return found


def extract_phones(soup):
    phones = set()
    for a in soup.select('a[href^="tel:"]'):
        num = urllib.parse.unquote(a["href"][4:]).strip()
        if len(re.sub(r"\D", "", num)) >= 6:
            phones.add(num)
    return phones


def extract_socials(soup, socials):
    for a in soup.find_all("a", href=True):
        href = a["href"]
        for key, doms in SOCIAL_DOMAINS.items():
            doms = (doms,) if isinstance(doms, str) else doms
            if any(d in href for d in doms):
                # prefer company pages over share/intent links
                if any(x in href for x in ("share", "intent", "sharer")):
                    continue
                cur = socials.get(key)
                if not cur or ("/company/" in href and "/company/" not in cur):
                    socials[key] = href.split("?")[0]


def extract_people(text):
    people = set()
    for m in PERSON_RE.finditer(text):
        name = re.sub(r"\s+", " ", m.group(0)).strip(" :")
        if 5 < len(name) < 80:
            people.add(name)
    return people


def extract_services(soup):
    services = []
    for h in soup.find_all(["h1", "h2", "h3"]):
        t = re.sub(r"\s+", " ", h.get_text(" ", strip=True))
        if 3 < len(t) < 90 and t not in services:
            services.append(t)
    return services


def candidate_pages(soup, base_url):
    """Internal links whose path matches interesting keywords, ranked."""
    base = urllib.parse.urlparse(base_url).netloc
    seen, ranked = set(), []
    for a in soup.find_all("a", href=True):
        full = urllib.parse.urljoin(base_url, a["href"]).split("#")[0]
        p = urllib.parse.urlparse(full)
        if p.netloc != base or full in seen:
            continue
        low = p.path.lower()
        for rank, kw in enumerate(PAGE_KEYWORDS):
            if kw in low:
                seen.add(full)
                ranked.append((rank, full))
                break
    ranked.sort()
    return [u for _, u in ranked[:MAX_SUBPAGES]]


def enrich_site(website):
    out = {"emails": set(), "phones": set(), "socials": {}, "people": set(),
           "services": [], "site_title": "", "site_description": "",
           "pages_crawled": 0, "crawl_error": ""}
    if not website:
        out["crawl_error"] = "no website"
        return out
    if not website.startswith("http"):
        website = "https://" + website

    session = requests.Session()
    html, final_url = fetch(website, session)
    if html is None:
        out["crawl_error"] = "homepage fetch failed"
        return out

    soup = BeautifulSoup(html, "html.parser")
    out["pages_crawled"] = 1
    if soup.title and soup.title.string:
        out["site_title"] = soup.title.string.strip()
    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        out["site_description"] = md["content"].strip()

    def digest(page_soup, page_html, is_key_page):
        out["emails"] |= extract_emails(page_html)
        out["phones"] |= extract_phones(page_soup)
        extract_socials(page_soup, out["socials"])
        if is_key_page:
            out["people"] |= extract_people(page_soup.get_text(" ", strip=True))
        for s in extract_services(page_soup):
            if s not in out["services"]:
                out["services"].append(s)

    digest(soup, html, False)

    for url in candidate_pages(soup, final_url):
        sub_html, _ = fetch(url, session)
        if sub_html is None:
            continue
        sub_soup = BeautifulSoup(sub_html, "html.parser")
        out["pages_crawled"] += 1
        low = url.lower()
        is_key = any(k in low for k in
                     ("impressum", "imprint", "team", "about", "ueber", "über"))
        digest(sub_soup, sub_html, is_key)

    out["services"] = out["services"][:20]
    return out


def find_website_column(fieldnames):
    for cand in ("website", "web_site", "site", "url"):
        for f in fieldnames:
            if f.lower() == cand:
                return f
    raise SystemExit(f"no website column found in: {fieldnames}")


def run(input_csv, out_base, workers):
    with open(input_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("input CSV is empty")
    web_col = find_website_column(rows[0].keys())
    print(f"{len(rows)} leads, website column: '{web_col}', "
          f"{sum(1 for r in rows if r.get(web_col))} with websites")

    def work(row):
        return row, enrich_site((row.get(web_col) or "").strip())

    enriched = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (row, extra) in enumerate(ex.map(work, rows), 1):
            merged = dict(row)
            # fold in the maps scraper's own emails column (cleans '%20' junk)
            scraper_emails = extract_emails(
                urllib.parse.unquote(row.get("emails", "") or ""))
            merged["enriched_emails"] = "; ".join(
                sorted(extra["emails"] | scraper_emails))
            merged["enriched_phones"] = "; ".join(sorted(extra["phones"]))
            for key in SOCIAL_DOMAINS:
                merged[key] = extra["socials"].get(key, "")
            merged["people"] = "; ".join(sorted(extra["people"]))
            merged["services"] = "; ".join(extra["services"])
            merged["site_title"] = extra["site_title"]
            merged["site_description"] = extra["site_description"]
            merged["pages_crawled"] = extra["pages_crawled"]
            merged["crawl_error"] = extra["crawl_error"]
            enriched.append(merged)
            print(f"  [{i}/{len(rows)}] {row.get('title', '')[:40]:40} "
                  f"emails={len(extra['emails'])} people={len(extra['people'])} "
                  f"linkedin={'y' if extra['socials'].get('linkedin') else '-'}")

    fields = list(enriched[0].keys())
    with open(out_base + ".csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(enriched)
    with open(out_base + ".json", "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=1)
    print(f"wrote {out_base}.csv and .json ({len(enriched)} leads)")


def selftest():
    html = ('Kontakt: info@praxis-mueller.de oder praxis [at] zahn-muc.de '
            '<img src="logo@2x.png"> Dr. med. dent. Anna Müller, '
            'Geschäftsführer: Hans Weber')
    emails = extract_emails(html)
    assert "info@praxis-mueller.de" in emails, emails
    assert "praxis@zahn-muc.de" in emails, emails
    assert not any(e.endswith(".png") for e in emails), emails
    people = extract_people(html)
    assert any("Anna Müller" in p for p in people), people
    assert any("Hans Weber" in p for p in people), people
    soup = BeautifulSoup('<a href="https://www.linkedin.com/company/acme?x=1">l</a>'
                         '<a href="tel:+49%2089%20123456">c</a>', "html.parser")
    socials = {}
    extract_socials(soup, socials)
    assert socials["linkedin"] == "https://www.linkedin.com/company/acme", socials
    assert "+49 89 123456" in extract_phones(soup)
    print("selftest OK")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input_csv", nargs="?")
    ap.add_argument("-o", "--out", default="leads", help="output base name")
    ap.add_argument("-w", "--workers", type=int, default=10)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        selftest()
        sys.exit(0)
    if not args.input_csv:
        ap.error("input_csv required (or --selftest)")
    run(args.input_csv, args.out, args.workers)
