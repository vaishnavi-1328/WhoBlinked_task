#!/usr/bin/env bash
set -euo pipefail

SITES=(
  "https://www.poltex.com"
  "https://www.alimed.com"
  "https://www.finelineflag.com"
  "https://www.gracealley.com"
  "https://www.brownmed.com"
  "https://www.s-curve.com"
  "https://www.dynamictechnomedicals.com"
  "https://www.customcomfort.com"
  "https://www.heathrowscientific.com"
  "https://www.medicus-health.com"
  "https://www.nursemates.com"
  "https://www.marketlab.com"
  "https://www.gohcl.com"
  "https://www.packlane.com"
  "https://www.boundtree.com"
  "https://www.vitalitymedical.com"
  "https://www.clinton-ind.com"
  "https://www.farfetch.com"
  "https://www.mytheresa.com"
  "https://marketlab.com"
)

for site in "${SITES[@]}"; do
  echo "========================================"
  echo "SITE: $site"
  echo "========================================"
  python scraper.py "$site" || echo "[WARN] scraper.py exited with error for $site"
  echo ""
done

echo "All sites done."
