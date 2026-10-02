"""
URL discovery + product extraction pipeline.

Step 1: Firecrawl map()  → all URLs on the site (fast, JS-aware)
Step 2: Sitemap probing  → broad search across many known sitemap paths
Step 2b: SAP Commerce    → crawl /c/ category pages if sitemap is empty
Step 3: Filter URLs      → keep likely product/offering pages
         If URL-pattern filter yields nothing, scan ALL discovered URLs
Step 4: Fetch each page  → plain httpx → Playwright fallback if blocked
Step 4b: Stealth render  → human-like Playwright for bot/CF/CAPTCHA sites
Step 5: Classify + extract product data from HTML
"""
from __future__ import annotations
import asyncio
import os
import re
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import httpx

from .client import CatalogueClient
from .extractors.html import extract_product, is_product_page
from .models import Product, DiscoveryStatus
from .utils import looks_like_product_url

MAX_URLS    = 5_000
CONCURRENCY = 8

# Every sitemap path we will probe — covers all known platforms + custom sites
SITEMAP_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap.php",
    "/sitemap/sitemap.xml",
    "/sitemap/index.xml",
    "/xmlsitemap.php",           # BigCommerce
    "/xmlsitemap.php?type=products&page=1",  # BigCommerce product feed
    "/sitemap/",
    "/wp-sitemap.xml",           # WordPress 5.5+
    "/page-sitemap.xml",
    "/product-sitemap.xml",
    "/products-sitemap.xml",
    "/catalog/sitemaps/catalog.xml",  # Magento
    "/media/sitemap/sitemap.xml",
]


# ── Main entry point ──────────────────────────────────────────────────────

async def discover_and_extract(
    base: str,
    client: CatalogueClient,
) -> tuple[list[Product], bool, str | None, DiscoveryStatus]:
    """Returns (products, complete, incomplete_reason, discovery_status)."""

    # _discover_urls returns (urls, already_product_urls)
    # already_product_urls is non-empty when sitemap/API gave explicit product URLs
    all_urls, product_urls = await _discover_urls(base, client)

    if not all_urls and not product_urls:
        return [], False, "no URLs discovered — site may be fully blocked or has no accessible sitemap", "no_sitemap"

    if product_urls:
        # Explicit product URLs from sitemap/API — use directly, no filtering needed
        candidates = product_urls
        print(f"  [crawl] {len(candidates)} product URLs from sitemap/API (direct)", flush=True)
    else:
        print(f"  [crawl] {len(all_urls)} total URLs discovered", flush=True)
        pattern_matches = [u for u in all_urls if looks_like_product_url(u)]
        if len(pattern_matches) >= 5:
            candidates = pattern_matches
            print(f"  [crawl] {len(candidates)} pages matched URL patterns", flush=True)
        else:
            print("  [crawl] slug-style URLs — scanning ALL pages via HTML content", flush=True)
            candidates = all_urls

    # Deduplicate candidate URLs before fetching (SAP/category crawl may repeat)
    seen_urls: set[str] = set()
    unique_candidates: list[str] = []
    for u in candidates:
        if u not in seen_urls:
            seen_urls.add(u)
            unique_candidates.append(u)
    if len(unique_candidates) < len(candidates):
        print(f"  [crawl] deduped to {len(unique_candidates)} unique URLs", flush=True)

    print(f"  [crawl] scanning {len(unique_candidates)} pages ...", flush=True)
    products = await _extract_from_pages(unique_candidates, client)

    if products:
        return products, True, None, "complete"
    return [], False, "URLs discovered but no product pages detected", "extractor_failure"


# ── Homepage pre-flight probe ─────────────────────────────────────────────

async def _probe_homepage(base: str, client: CatalogueClient) -> str:
    """Quick check of homepage to classify access status before full crawl.
    Returns: 'ok' | 'blocked' | 'bot_wall'
    """
    r = await client.get(base + "/")
    if r is None or r.status_code in (403, 401, 503):
        return "blocked"
    if r.status_code == 200:
        if any(m in r.text for m in _CHALLENGE_MARKERS):
            return "bot_wall"
    # 202 with sgcaptcha = a variant of bot_wall
    if r.status_code == 202 and "sgcaptcha" in r.text:
        return "bot_wall"
    return "ok"


# ── URL discovery ─────────────────────────────────────────────────────────

async def _discover_urls(base: str, client: CatalogueClient) -> tuple[list[str], list[str]]:
    """Returns (all_urls, product_urls). product_urls is non-empty when the
    sitemap or REST API gave explicit product URLs."""
    api_key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if api_key:
        urls = await _firecrawl_map(base, api_key)
        if urls:
            return urls[:MAX_URLS], []

    # Try REST API product endpoints first (marketlab, WooCommerce)
    rest_urls, api_name = await _rest_api_urls(base, client)
    if rest_urls:
        print(f"  [rest-api] {len(rest_urls)} product URLs via {api_name}", flush=True)
        return [], rest_urls

    all_urls, product_urls = await _sitemap_urls(base)

    # If sitemap yielded nothing, try SAP Commerce category crawl
    if not all_urls and not product_urls:
        product_urls = await _sap_commerce_urls(base, client)
        if product_urls:
            print(f"  [sap] {len(product_urls)} product URLs via category crawl", flush=True)

    # If still nothing, stealth discover + nav-graph expansion
    if not all_urls and not product_urls:
        seed_urls = await _stealth_discover(base, client)
        if seed_urls and len(seed_urls) < 20:
            # Too few seeds — expand 1 level via nav-graph
            seed_urls = await _nav_graph_urls(base, seed_urls, client)
        all_urls = seed_urls

    return all_urls, product_urls


async def _firecrawl_map(base: str, api_key: str) -> list[str]:
    try:
        from firecrawl import FirecrawlApp
        print(f"  [firecrawl] mapping {base} ...", flush=True)
        app = FirecrawlApp(api_key=api_key)
        result = app.map(base, limit=MAX_URLS)

        if hasattr(result, "links") and result.links:
            urls = result.links
        elif isinstance(result, dict):
            urls = result.get("links") or result.get("urls") or []
        elif isinstance(result, list):
            urls = result
        else:
            urls = []

        urls = [u for u in urls if isinstance(u, str)]
        print(f"  [firecrawl] {len(urls)} URLs found", flush=True)
        return urls
    except Exception as e:
        print(f"  [firecrawl] unavailable ({e}) — falling back to sitemap", flush=True)
        return []


async def _sitemap_urls(base: str) -> tuple[list[str], list[str]]:
    """Returns (all_urls, product_urls). product_urls populated when a dedicated
    products sitemap feed exists (e.g. BigCommerce xmlsitemap.php?type=products)."""
    print(f"  [sitemap] probing {base} ...", flush=True)
    base = base.rstrip("/")

    entry_points: list[str] = []

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15,
                                     headers={"User-Agent": "Mozilla/5.0"}) as http:
            r = await http.get(f"{base}/robots.txt")
            if r.status_code == 200:
                for line in r.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        sm = line.split(":", 1)[1].strip()
                        if sm not in entry_points:
                            entry_points.append(sm)
    except Exception:
        pass

    for path in SITEMAP_PATHS:
        url = base + path
        if url not in entry_points:
            entry_points.append(url)

    all_urls: list[str] = []
    product_urls: list[str] = []
    seen_sitemaps: set[str] = set()

    async def fetch_sitemap(sm_url: str):
        if sm_url in seen_sitemaps or len(all_urls) + len(product_urls) >= MAX_URLS:
            return
        seen_sitemaps.add(sm_url)
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20,
                                         headers={"User-Agent": "Mozilla/5.0"}) as http:
                r = await http.get(sm_url)
            if r.status_code != 200:
                return

            # Dedicated products feed (BigCommerce, some custom CMSes)
            if "type=products" in sm_url:
                await _fetch_typed_product_pages(base, sm_url, r, product_urls)
                return

            root = ET.fromstring(r.content)
            ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}

            # sitemapindex — check children; if one is type=products, use it directly
            children = root.findall(".//s:sitemap/s:loc", ns)
            for loc in children:
                child_url = loc.text.strip()
                await fetch_sitemap(child_url)

            # urlset — collect all page URLs
            for loc in root.findall(".//s:url/s:loc", ns):
                all_urls.append(loc.text.strip())

        except Exception:
            pass

    # Probe all entry points — seen_sitemaps prevents duplicate fetches.
    # Never break early: a general sitemap returning blog URLs must not block
    # a later product-specific sitemap (e.g. /product-sitemap.xml).
    for ep in entry_points:
        await fetch_sitemap(ep)

    print(f"  [sitemap] {len(all_urls)} general + {len(product_urls)} product URLs found", flush=True)
    return all_urls[:MAX_URLS], product_urls[:MAX_URLS]


async def _fetch_typed_product_pages(base: str, first_url: str, first_response: httpx.Response, urls: list[str]):
    """
    Handles paginated product-typed sitemaps, e.g.:
      /xmlsitemap.php?type=products&page=1  (BigCommerce)
      /product-sitemap1.xml, product-sitemap2.xml, etc.
    Collects all product URLs across all pages.
    """
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    def extract_locs(content: bytes) -> list[str]:
        try:
            root = ET.fromstring(content)
            return [loc.text.strip() for loc in root.findall(".//s:url/s:loc", ns)]
        except Exception:
            return []

    batch = extract_locs(first_response.content)
    urls.extend(batch)

    if not batch:
        return

    # Derive the base pattern for pagination
    import re
    page_match = re.search(r'[&?]page=(\d+)', first_url)
    if not page_match:
        return

    page_param_start = int(page_match.group(1))
    url_template = re.sub(r'([&?]page=)\d+', r'\g<1>{}', first_url)
    page = page_param_start + 1

    async with httpx.AsyncClient(follow_redirects=True, timeout=20,
                                 headers={"User-Agent": "Mozilla/5.0"}) as http:
        while len(urls) < MAX_URLS:
            url = url_template.format(page)
            try:
                r = await http.get(url)
                if r.status_code != 200:
                    break
                batch = extract_locs(r.content)
                if not batch:
                    break
                urls.extend(batch)
                print(f"  [sitemap] product page {page}: +{len(batch)} URLs (total {len(urls)})", flush=True)
                page += 1
            except Exception:
                break


# ── SAP Commerce category crawl ───────────────────────────────────────────

async def _sap_commerce_urls(base: str, client: CatalogueClient) -> list[str]:
    """Discover product URLs on SAP Commerce (hybris) sites whose sitemap is empty.

    Strategy:
    1. Fetch the homepage to collect all /name/c/ID category links.
    2. For each category page, collect /path/p/SKU product links (paginating if needed).
    """
    base = base.rstrip("/")
    print(f"  [sap] probing {base} for SAP Commerce categories ...", flush=True)

    # Step 1: collect category URLs from homepage
    html = await _fetch_html(base + "/", client)
    if not html:
        return []

    cat_urls = list({
        urljoin(base, m)
        for m in re.findall(r'href="(/[^"]+/c/\d+[^"]*)"', html)
    })
    if not cat_urls:
        return []

    print(f"  [sap] {len(cat_urls)} category pages found", flush=True)

    # Step 2: for each category, paginate and collect product URLs
    product_urls: list[str] = []
    seen: set[str] = set()

    async def crawl_category(cat_url: str):
        page_num = 0
        while len(product_urls) < MAX_URLS:
            paged = cat_url + (f"?q=%3Arelevance&page={page_num}&pageSize=96" if page_num else "")
            cat_html = await _fetch_html(paged, client)
            if not cat_html:
                break
            found = [
                urljoin(base, m)
                for m in re.findall(r'href="(/[^"]+/p/[^"]+)"', cat_html)
            ]
            new = [u for u in found if u not in seen]
            if not new:
                break
            for u in new:
                seen.add(u)
                product_urls.append(u)
            page_num += 1

    sem = asyncio.Semaphore(4)

    async def bounded_crawl(cat_url: str):
        async with sem:
            await crawl_category(cat_url)

    await asyncio.gather(*[bounded_crawl(u) for u in cat_urls])
    return product_urls[:MAX_URLS]


# ── Stealth discovery fallback ─────────────────────────────────────────────

async def _rest_api_urls(base: str, client: CatalogueClient) -> tuple[list[str], str]:
    """Probe common REST API product endpoints (WooCommerce, generic /api/products).
    Returns (product_page_urls, api_name). Empty list if none found."""
    endpoints = [
        ("/wp-json/wc/v3/products?per_page=100&page={page}", "WooCommerce"),
        ("/wp-json/wc/v2/products?per_page=100&page={page}", "WooCommerce v2"),
        ("/api/products?limit=100&page={page}", "generic-api"),
        ("/api/v1/products?limit=100&page={page}", "generic-api-v1"),
        ("/api/v2/products?limit=100&page={page}", "generic-api-v2"),
    ]
    base = base.rstrip("/")
    for template, api_name in endpoints:
        urls: list[str] = []
        page = 1
        try:
            while len(urls) < MAX_URLS:
                endpoint = base + template.format(page=page)
                r = await client.get(endpoint)
                if r is None or r.status_code != 200:
                    break
                try:
                    import json as _json
                    data = _json.loads(r.text)
                except Exception:
                    break
                if not isinstance(data, list) or not data:
                    break
                for item in data:
                    if isinstance(item, dict):
                        link = item.get("permalink") or item.get("url") or item.get("link")
                        if link and isinstance(link, str):
                            urls.append(link)
                if len(data) < 100:
                    break
                page += 1
            if urls:
                return urls[:MAX_URLS], api_name
        except Exception:
            continue
    return [], ""


async def _nav_graph_urls(base: str, seed_urls: list[str], client: CatalogueClient) -> list[str]:
    """Expand seed URLs one level by fetching each and collecting internal hrefs."""
    base = base.rstrip("/")
    domain = base.split("//")[1].split("/")[0]
    seen = set(seed_urls)
    expanded = list(seed_urls)

    sem = asyncio.Semaphore(CONCURRENCY)

    async def fetch_links(url: str) -> list[str]:
        async with sem:
            r = await client.get(url)
            if r is None or r.status_code != 200:
                return []
            found = re.findall(r'href="([^"#\s]{3,300})"', r.text)
            return [
                urljoin(base, h).split("#")[0]
                for h in found
                if not h.startswith(("javascript", "mailto", "tel:", "data:"))
                and domain in urljoin(base, h)
            ]

    results = await asyncio.gather(*[fetch_links(u) for u in seed_urls])
    for links in results:
        for link in links:
            if link not in seen:
                seen.add(link)
                expanded.append(link)

    print(f"  [nav-graph] expanded to {len(expanded)} URLs", flush=True)
    return expanded[:MAX_URLS]


async def _stealth_discover(base: str, client: CatalogueClient) -> list[str]:
    """Last-resort URL discovery via stealth Playwright render of the homepage.

    Used for sites that block plain HTTP on their sitemap (Cloudflare JS
    challenge, CAPTCHA gates, bot-walls). Renders the homepage with human-like
    behaviour, then extracts all internal hrefs as seed URLs.
    """
    base = base.rstrip("/")
    print(f"  [stealth] attempting stealth render of {base} ...", flush=True)
    html = await client.render_stealth(base + "/", wait_seconds=10)
    if not html:
        return []

    domain = base.split("//")[1].split("/")[0]
    seen: set[str] = set()
    urls: list[str] = []
    for m in re.findall(r'href="([^"#\s]{3,300})"', html):
        if m.startswith(("javascript", "mailto", "tel:", "data:")):
            continue
        resolved = urljoin(base, m)
        # Strip fragment and query for dedup key, keep only same-domain
        resolved = resolved.split("#")[0]
        if domain not in resolved:
            continue
        if resolved not in seen:
            seen.add(resolved)
            urls.append(resolved)
    print(f"  [stealth] {len(urls)} URLs discovered from homepage", flush=True)
    return urls[:MAX_URLS]


# ── Per-page fetch + extract ──────────────────────────────────────────────

def _extract_embedded_product_urls(base: str, html: str) -> list[str]:
    """Extract individual product URLs embedded as JSON inside listing pages.

    Sites like Farfetch embed product data as JSON strings (e.g. "url":"/path")
    rather than plain <a href> links, so the normal href regex misses them.
    """
    domain = base.split("//")[1].split("/")[0]
    found: list[str] = []
    seen: set[str] = set()
    for m in re.findall(r'"url"\s*:\s*"(/[^"]{5,200})"', html):
        full = f"https://{domain}{m}"
        if looks_like_product_url(full) and full not in seen:
            seen.add(full)
            found.append(full)
    return found


async def _extract_from_pages(urls: list[str], client: CatalogueClient) -> list[Product]:
    sem = asyncio.Semaphore(CONCURRENCY)
    products: list[Product] = []
    lock = asyncio.Lock()
    extra_product_urls: list[str] = []
    seen_urls: set[str] = set(urls)

    async def process(url: str):
        async with sem:
            html = await _fetch_html(url, client)
            if not html:
                return
            if not is_product_page(url, html):
                # Listing page — mine it for embedded product URLs
                embedded = _extract_embedded_product_urls(url, html)
                if embedded:
                    async with lock:
                        for u in embedded:
                            if u not in seen_urls:
                                seen_urls.add(u)
                                extra_product_urls.append(u)
                return
            product = extract_product(url, html)
            if product and product.name:
                async with lock:
                    products.append(product)
                    price_str = f"${product.price}" if product.price else "price on request"
                    print(f"  [product] \"{product.name[:55]}\"  {price_str}", flush=True)

    await asyncio.gather(*[process(u) for u in urls])

    # Second pass: process any product URLs discovered inside listing pages
    if extra_product_urls:
        print(f"  [crawl] {len(extra_product_urls)} product URLs found inside listing pages", flush=True)
        await asyncio.gather(*[process(u) for u in extra_product_urls])

    return products


_CHALLENGE_MARKERS = (
    "cf-browser-verification",
    "challenge-platform",
    "window.isBotPage",
    "sgcaptcha",
    "Just a moment",
    "Enable JavaScript and cookies to continue",
    "Checking your browser",
    "DDoS protection by",
)


async def _fetch_html(url: str, client: CatalogueClient) -> str | None:
    r = await client.get(url)

    if r is not None and r.status_code == 200:
        text = r.text
        # Detect challenge/bot-wall pages served with HTTP 200
        if any(m in text for m in _CHALLENGE_MARKERS):
            print(f"  [stealth] challenge page detected at {url[:70]}", flush=True)
            return await client.render_stealth(url)
        return text

    # Hard block or timeout → try stealth Playwright
    if r is None or r.status_code in (403, 429, 503):
        status = r.status_code if r is not None else "timeout"
        print(f"  [stealth] retrying {url[:70]} (was HTTP {status})", flush=True)
        return await client.render_stealth(url)

    return None
