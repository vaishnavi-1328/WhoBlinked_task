# whoBlinked — Product Catalogue Scraper

Given any online store or manufacturer URL, extract every product it offers — name, price, variants, stock status — and write it to a structured JSON file.

---

## Intent

Websites publish their product catalogues in many different ways. Some use structured data (JSON-LD, OpenGraph). Others render content entirely in JavaScript. Many actively block automated access with bot-detection, CAPTCHAs, or Cloudflare challenges. The goal was to build a single scraper that handles this variety without site-specific configuration.

---

## Strategy

The scraper runs a five-step pipeline for every site:

### 1. URL Discovery

Four strategies are attempted in order, stopping at the first that yields results:

| Strategy | When used |
|---|---|
| **Firecrawl map** | If `FIRECRAWL_API_KEY` is set — fastest, most complete |
| **REST API probe** | Tries WooCommerce and generic `/api/products` endpoints |
| **Sitemap crawl** | Probes `robots.txt` + 16 common sitemap paths |
| **SAP Commerce crawl** | Follows `/c/` category pages on hybris sites |
| **Stealth homepage render** | Last resort — renders homepage with Playwright and mines every internal link |

### 2. URL Filtering

Discovered URLs are filtered to product-page candidates using path-pattern matching (`/product/`, `/item/`, `/catalog/`, etc.). If fewer than 5 URLs match, all discovered URLs are scanned instead.

### 3. Page Fetching

Each candidate page is fetched using a layered rendering strategy:

```
curl_cffi  →  httpx  →  Playwright  →  camoufox (stealth Firefox)
```

The scraper escalates automatically when:
- The response is a **CSR shell** (React/Vue/Angular app that rendered nothing server-side — detected by stripping script/style blocks and checking if visible text is under 200 characters)
- The page contains a **bot-wall challenge** (Cloudflare, CAPTCHA markers)
- The server returns **403 / 429 / 503**

### 4. Page Classification

Each fetched page is checked to confirm it is a single product detail page, not a listing. Signals checked (in priority order):

1. `@type: Product` in JSON-LD
2. `og:type = product` meta tag
3. A visible SKU / part-number label (e.g. `SKU:`, `Item #:`, `Cat No.:`)
4. Offering language (`Add to Cart`, `Request a Quote`, etc.) with a single `<h1>`
5. A spec table alongside a single `<h1>`

Listing pages (many price elements, many headings) are skipped and mined for embedded product URLs instead.

### 5. Data Extraction

Three extraction strategies are tried in order:

1. **JSON-LD** — parses `application/ld+json` blocks for `@type: Product`
2. **Meta tags** — reads OpenGraph and `itemprop` attributes
3. **HTML heuristics** — scrapes the `<h1>`, price elements (by class name), SKU labels, spec tables, and CTA text for sites with no structured data

---

## Output

One JSON file per site, written to the current directory as `<domain>_catalogue.json`.

```json
{
  "site": "https://www.example.com",
  "readAt": "2026-10-02T16:00:00+00:00",
  "complete": true,
  "incompleteReason": null,
  "products": [
    {
      "url": "https://www.example.com/product/widget",
      "id": "widget-001",
      "name": "Widget",
      "brand": "Acme",
      "sku": "WDG-001",
      "price": 24.99,
      "listPrice": 29.99,
      "currency": "USD",
      "availability": "in_stock",
      "image": "https://www.example.com/images/widget.jpg",
      "description": "A very reliable widget.",
      "specs": { "Material": "Aluminum", "Weight": "200g" },
      "variants": []
    }
  ]
}
```

`complete: false` means the scraper ran but could not extract products — a blocked site, not an empty one.

---

## Project Structure

```
.
├── scraper.py          # CLI entry point
├── run_all.sh          # Batch-run all 19 target sites
├── run_failed.sh       # Re-run sites that previously failed
├── lib/
│   ├── client.py       # HTTP client — rate limiting, retries, rendering fallbacks
│   ├── crawler.py      # URL discovery + page fetching pipeline
│   ├── models.py       # CatalogueRead, Product, Variant dataclasses
│   ├── utils.py        # Price parsing, URL heuristics, availability normalization
│   └── extractors/
│       └── html.py     # Product classification and data extraction
└── README.md
```

---

## Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd whoBlinked-task
```

### 2. Install Python dependencies

Using `uv` (recommended):

```bash
pip install uv      # if you don't have uv yet
uv sync
```

Or with plain pip:

```bash
pip install -r requirements.txt
```

### 3. Install browser drivers

Required for JavaScript-rendered sites:

```bash
playwright install chromium
```

Required for bot-walled sites (Cloudflare, etc.):

```bash
pip install camoufox
python -m camoufox fetch
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in your values. The only variable is `FIRECRAWL_API_KEY` — leave it blank if you don't have one (the scraper will fall back to sitemap crawling).

---

## Usage

```bash
# Scrape a single site
python scraper.py https://www.example.com

# With options
python scraper.py https://www.example.com --delay 1.0 --max-pages 1000 --output out.json

# Run all target sites
bash run_all.sh

# Re-run previously failed sites
bash run_failed.sh
```

---

## Testing Considerations

**Start with easy sites.** Sites like `poltex.com`, `brownmed.com`, or `customcomfort.com` use standard HTML or JSON-LD and should produce complete catalogues quickly. Use these to confirm the pipeline is working before testing harder sites.

**CSR / React sites need Playwright.** Sites like `marketlab.com` return a JavaScript shell over plain HTTP. The scraper detects this and escalates to Playwright automatically, but Playwright must be installed (`playwright install chromium`). Without it, these sites will yield 0 products.

**camoufox must be installed for bot-walled sites.** Sites behind Cloudflare or aggressive bot detection (e.g. `farfetch.com`, `mytheresa.com`) require camoufox stealth rendering. Install with `pip install camoufox` and run `python -m camoufox fetch` to download the patched Firefox binary.

**Prices are often `null` on B2B and quote-only sites.** Sites like `dynamictechnomedicals.com` or `gohcl.com` do not display public prices. The scraper will still extract name, SKU, specs, and availability — `null` price is correct, not a bug.

**Variants are not yet extracted.** The `variants` field is always an empty array. Sites that sell items in multiple sizes, colours, or pack sizes will have those options on the page but the data will not appear in the output.

**Rate limiting is per-domain.** The default delay between requests is 0.5 seconds. For sensitive sites, increase with `--delay 2.0`. The scraper does not rotate IPs or proxies — repeated runs from the same IP may trigger temporary blocks on some sites.

**`complete: false` has two distinct causes.** If `products` is empty and `complete` is false, either (a) the site blocked all requests, or (b) the extractor could not identify any product pages. Check the terminal output for `[stealth]` lines — if every URL triggered stealth retries and still failed, the site is blocked. If stealth succeeded but products is still 0, the page structure is not yet handled by the extractor.

---

## Known Limitations

**No variant extraction.** Product pages that present options (size, colour, material) via JavaScript-driven selectors do not expose those variants in the output.

**Price accuracy on multi-variant pages.** When price depends on the selected variant and is loaded dynamically, the extracted price may be `null` or reflect the default variant only.

**Pagination on large catalogues.** The scraper discovers URLs from sitemaps and homepages but does not paginate listing pages. A site with 10,000 products spread across paginated category pages may yield far fewer than the full catalogue.

**Single-IP, no proxy rotation.** The scraper runs all requests from one IP. Sites with strict rate limits or IP-based bot detection can block a run midway through. The output will be partial with `complete: false`.

**JavaScript-gated content.** Even with stealth rendering, some sites require user interaction (cookie consent dialogs, login walls, age gates) before product content is visible. The scraper does not handle these.

**Firecrawl dependency is optional but impactful.** Without a Firecrawl API key, URL discovery falls back to sitemap crawling and homepage parsing. For sites with no sitemap and a heavily JavaScript-rendered homepage, this can miss large sections of the catalogue.

---

## Cost Per Execution (Production)

This section covers the **real deployed cost** — Firecrawl API key required, scraper running on a cloud server, no local machine. All product classification and extraction is rule-based; there are **zero LLM / AI model costs**.

### Services Used in Production

| Service | Role | Pricing model |
|---|---|---|
| **Firecrawl `map()`** | URL discovery — 1 call per domain | 1 credit per URL returned |
| **curl_cffi / httpx** | Page fetching — direct HTTP to target site | Free (your server's egress bandwidth) |
| **Playwright (Chromium)** | JS-rendered page fallback | Free — local browser process on server |
| **camoufox (Firefox)** | Stealth rendering for bot-walled sites | Free — local browser process on server |
| **Cloud server** | Runs the Python process + browsers | Fixed monthly fee |
| **LLM / AI models** | Not used | $0 |

---

### 1. Firecrawl Costs

`map()` costs **1 credit per URL** in the returned list — one call per domain.

| Plan | Credits/month | Price | Effective rate |
|---|---|---|---|
| Standard | 100,000 | $83/mo (annual) | $0.00083 / credit |
| Growth | 500,000 | $333/mo (annual) | $0.00067 / credit |
| PAYG top-up (Standard) | +2,000 per $5 | — | $0.0025 / credit |

Typical credit spend per domain:

| Site size | URLs discovered | Credits used | Cost (Standard rate) |
|---|---|---|---|
| Small (~200 URLs) | ~200 | 200 | ~$0.17 |
| Medium (~1,000 URLs) | ~1,000 | 1,000 | ~$0.83 |
| Large (~5,000 URLs) | ~5,000 | 5,000 | ~$4.15 |

> The Standard plan's 100,000 monthly credits cover ~100 medium-sized domains or ~20 large ones before PAYG kicks in.

---

### 2. Server / Compute Costs

The scraper spawns real browser processes (Playwright + camoufox) and runs up to 8 concurrent HTTP requests. It needs **at least 2 vCPUs and 4 GB RAM** in production to handle browser rendering without OOM errors.

**AWS EC2** (us-east-1, on-demand — prices as of October 2026):

| Instance | vCPU | RAM | On-demand/hr | Monthly (always-on) | Monthly (1-yr reserved) |
|---|---|---|---|---|---|
| t3.medium | 2 | 4 GB | $0.0418 | **~$30** | ~$18 |
| t3.large | 2 | 8 GB | $0.0832 | **~$60** | ~$36 |
| t3.xlarge | 4 | 16 GB | $0.1664 | **~$120** | ~$72 |

**Railway** (usage-based, simpler deployment):

| Plan | Included credits | Price | Compute rate |
|---|---|---|---|
| Hobby | $5/mo | $5/mo | ~$50/vCPU-month active |
| Pro | $20/mo | $20/mo | ~$50/vCPU-month active |

For a scraper that runs in bursts (not always-on), Railway Pro at $20/mo is sufficient for light workloads. For continuous or high-volume scraping, a reserved EC2 t3.large (~$36/mo) is more cost-effective.

**Recommended production instance:** `t3.large` on AWS (1-yr reserved) — **~$36/mo** — gives 2 vCPUs and 8 GB RAM, enough headroom for parallel browser rendering.

---

### 3. Bandwidth / Egress Costs

Each scraped page is typically 50–500 KB of HTML. Direct HTTP fetching (curl_cffi/httpx) pulls from the target site to your server.

| Scale | Pages fetched | Egress estimate | AWS egress cost (first 10 GB free) |
|---|---|---|---|
| 10 domains × 500 pages | ~5,000 pages | ~1–2 GB | ~$0.00–$0.18 |
| 100 domains × 500 pages | ~50,000 pages | ~10–25 GB | ~$0.90–$2.25 |

Egress is a rounding error at this scale — essentially free for typical usage.

---

### 4. Total Production Cost Per Domain

**Assumptions:** Standard Firecrawl plan ($83/mo, 100k credits), t3.large 1-yr reserved (~$36/mo), 50 domains/month processed.

```
Server cost (t3.large reserved, prorated per domain):
  $36/mo ÷ 50 domains                              →  $0.72 / domain

Firecrawl map() — medium site (~1,000 URLs):
  1,000 credits × $0.00083                          →  $0.83 / domain

Bandwidth egress (~500 pages × 200KB = 100MB):
  ~$0.009 per domain                                →  ~$0.01 / domain

LLM tokens:  None                                  →  $0.00

─────────────────────────────────────────────────────────────────────────────
Total per domain (medium site, 50 domains/mo)       ~$1.56
─────────────────────────────────────────────────────────────────────────────
```

**Range across site sizes:**

| Site size | Firecrawl | Server (prorated) | Total per domain |
|---|---|---|---|
| Small (~200 URLs) | ~$0.17 | ~$0.72 | **~$0.89** |
| Medium (~1,000 URLs) | ~$0.83 | ~$0.72 | **~$1.55** |
| Large (~5,000 URLs) | ~$4.15 | ~$0.72 | **~$4.87** |

---

### 5. Monthly Fixed Costs (Production Baseline)

Regardless of how many domains you scrape each month, you always pay:

| Cost | Amount |
|---|---|
| Firecrawl Standard plan | $83/mo |
| EC2 t3.large (1-yr reserved) | ~$36/mo |
| **Monthly baseline** | **~$119/mo** |

This baseline covers up to ~100,000 Firecrawl map credits — enough for ~100 medium-sized domains before PAYG top-ups are needed.

---

### Summary

- **Dominant cost is Firecrawl** — it scales directly with catalogue size (URLs discovered per domain).
- **Server cost is fixed** — t3.large at ~$36/mo whether you run 1 domain or 100.
- **No LLM spend** — all extraction is rule-based; zero token costs ever.
- **Break-even:** at ~50 domains/month, total cost is roughly **$1.50–$5 per domain**. At 100+ domains/month, the fixed costs amortize and per-domain cost drops to **$0.83–$4.15** (pure Firecrawl credits).
