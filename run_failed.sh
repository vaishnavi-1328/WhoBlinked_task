#!/usr/bin/env bash
set -euo pipefail

SITES=(
  "https://www.boundtree.com"
  "https://www.dynamictechnomedicals.com"
  "https://www.s-curve.com"
  "https://www.gohcl.com"
  "https://www.marketlab.com"
  "https://www.farfetch.com"
  "https://www.mytheresa.com"
)

for site in "${SITES[@]}"; do
  echo "========================================"
  echo "SITE: $site"
  echo "========================================"
  /opt/anaconda3/bin/python scraper.py "$site" || echo "[WARN] error for $site"
  echo ""
done

echo "All failed sites re-run done."
