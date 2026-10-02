#!/usr/bin/env python3
"""
Product catalogue scraper — works on any website.

Usage:
    python scraper.py <url>
    python scraper.py <url> --max-pages 500 --delay 1.0
    FIRECRAWL_API_KEY=fc-xxx python scraper.py <url>

Output:
    <domain>_catalogue.json  in the current directory
    Live progress printed to terminal
"""
from __future__ import annotations
import argparse
import asyncio
import dataclasses
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from lib.client import CatalogueClient
from lib.crawler import discover_and_extract, MAX_URLS
from lib.models import CatalogueRead


def _normalise(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _domain(url: str) -> str:
    return urlparse(url).netloc.lstrip("www.")


def _to_dict(obj) -> object:
    if dataclasses.is_dataclass(obj):
        return {k: _to_dict(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_dict(i) for i in obj]
    return obj


async def _run(base: str, delay: float, max_pages: int) -> CatalogueRead:
    client = CatalogueClient(delay=delay)
    try:
        print(f"\n[scraper] {base}", flush=True)
        print(f"[scraper] delay={delay}s  max_pages={max_pages}\n", flush=True)

        products, complete, reason, _discovery_status = await discover_and_extract(base, client)

        result = CatalogueRead(
            site=base,
            readAt=datetime.now(timezone.utc).isoformat(),
            complete=complete,
            products=products,
            incompleteReason=reason,
        )
        return result
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(
        description="Extract full product catalogue from any website."
    )
    parser.add_argument("url", help="Website URL, e.g. https://www.example.com")
    parser.add_argument(
        "--delay", type=float, default=0.5,
        help="Seconds between requests per domain (default: 0.5)"
    )
    parser.add_argument(
        "--max-pages", type=int, default=MAX_URLS,
        help=f"Max pages to scan (default: {MAX_URLS})"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output file path (default: <domain>_catalogue.json)"
    )
    args = parser.parse_args()

    base = _normalise(args.url)
    result = asyncio.run(_run(base, args.delay, args.max_pages))

    # Determine output path
    out_path = args.output or f"{_domain(base)}_catalogue.json"

    data = _to_dict(result)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # Terminal summary
    n = len(result.products)
    status = "complete" if result.complete else f"incomplete — {result.incompleteReason}"
    print(f"\n[scraper] done: {n} product(s) found  [{status}]")
    print(f"[scraper] output → {out_path}")

    if n > 0:
        print(f"\n--- first 3 products ---")
        for p in result.products[:3]:
            price_str = f"${p.price}" if p.price else "price on request"
            print(f"  • {p.name}  |  {price_str}  |  {p.availability}")
            if p.sku:
                print(f"    SKU: {p.sku}")
            if p.specs:
                for k, v in list(p.specs.items())[:3]:
                    print(f"    {k}: {v}")


if __name__ == "__main__":
    main()
