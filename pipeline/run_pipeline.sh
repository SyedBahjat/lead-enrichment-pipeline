#!/usr/bin/env bash
# One-command lead pipeline: Google Maps scrape -> website enrichment.
# Usage: ./run_pipeline.sh [queries.txt] [run-name] [depth]
#   queries.txt: one search per line, e.g. "dentist in Munich, Germany"
#                (default: queries.txt next to this script or in repo root)
#   run-name:    output file prefix (default: run_<timestamp>)
#   depth:       scroll depth per query, ~12 results each (default 10)
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
QUERIES=${1:-}
NAME=${2:-run_$(date +%Y%m%d_%H%M)}
DEPTH=${3:-10}

# default queries file: cwd, script dir, or repo root
if [[ -z "$QUERIES" ]]; then
  for cand in queries.txt "$DIR/queries.txt" "$DIR/../queries.txt"; do
    [[ -f "$cand" ]] && QUERIES="$cand" && break
  done
fi
if [[ -z "${QUERIES:-}" || ! -f "$QUERIES" ]]; then
  echo "ERROR: queries file not found: '${QUERIES:-queries.txt}'"
  echo "Create one, e.g.:  echo \"dentist in Munich, Germany\" > queries.txt"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker is not running. Start Docker Desktop and retry."
  exit 1
fi

# bootstrap python env on first run (fresh clones)
PY="$DIR/.venv/bin/python3"
if [[ ! -x "$PY" ]]; then
  echo "== First run: setting up Python environment =="
  python3 -m venv "$DIR/.venv"
  "$DIR/.venv/bin/pip" install -q requests beautifulsoup4
fi

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
