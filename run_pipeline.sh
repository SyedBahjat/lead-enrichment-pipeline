#!/usr/bin/env bash
# Run from repo root — delegates to pipeline/run_pipeline.sh
exec "$(cd "$(dirname "$0")" && pwd)/pipeline/run_pipeline.sh" "$@"
