#!/usr/bin/env bash
# One-command lead pipeline: Google Maps scrape -> website enrichment.
# Usage: ./run_pipeline.sh <queries.txt> <run-name> [depth]
#   queries.txt: one search per line, e.g. "dentist in Munich, Germany"
#   depth: scroll depth per query (default 10 ≈ up to ~120 results/query)
set -euo pipefail

QUERIES=${1:?usage: run_pipeline.sh queries.txt run-name [depth]}
NAME=${2:?usage: run_pipeline.sh queries.txt run-name [depth]}
DEPTH=${3:-10}
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$DIR/.venv/bin/python3"

mkdir -p "$DIR/output"
cp "$QUERIES" "$DIR/output/${NAME}_queries.txt"

echo "== Stage 1: scraping Google Maps ($(wc -l < "$QUERIES" | tr -d ' ') queries, depth $DEPTH) =="
docker run --rm -v "$DIR/output:/work" gosom/google-maps-scraper:latest \
  -input "/work/${NAME}_queries.txt" \
  -results "/work/${NAME}_raw.csv" \
  -email -depth "$DEPTH" -c 8 -exit-on-inactivity 3m

echo "== Stage 2: enriching from business websites =="
"$PY" "$DIR/enrich.py" "$DIR/output/${NAME}_raw.csv" -o "$DIR/output/${NAME}_leads"

echo "== Done: $DIR/output/${NAME}_leads.csv =="
