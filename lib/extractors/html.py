"""
Universal product extractor — works on any website.

Strategy order (highest priority first):
  1. schema.org JSON-LD  (@type: Product)
  2. OpenGraph / meta itemprop tags
  3. HTML heuristics — covers B2B / industrial / quote-only pages
     that have NO price but DO have model numbers, spec tables, part numbers.

A page is considered a "product/offering page" if it has ANY of:
  - JSON-LD @type: Product
  - og:type = product
  - A "request a quote / contact for pricing / download datasheet" call-to-action
  - A spec table alongside a heading
  - A visible SKU / part number label
"""
from __future__ import annotations
import json
import re
from bs4 import BeautifulSoup

from ..models import Product, Variant
from ..utils import parse_price, normalise_availability, make_id, CURRENCY_SYMBOL_MAP

# Elements whose class/id suggest they hold a price
PRICE_CLASS_RE = re.compile(
    r"(price|sale[\-_]?price|current[\-_]?price|"
    r"offer[\-_]?price|special[\-_]?price|now[\-_]?price)",
    re.I,
)

# Labels that precede a SKU / part number value
SKU_LABEL_RE = re.compile(
    r"(sku|item\s*#|part\s*#|model\s*#|product\s*id|"
    r"part\s*no\.?|item\s*no\.?|cat\s*no\.?|catalog\s*no\.?|"
    r"ref\s*no\.?|reference\s*no\.?|article\s*no\.?)\s*[:\-]?\s*",
    re.I,
)

# Broad "offering" language — works for B2B, industrial, medical, etc.
OFFERED_RE = re.compile(
    r"request\s+a?\s*quote|get\s+a?\s*quote|contact\s+for\s+pric|"
    r"request\s+pricing|enquire\s+now|ask\s+for\s+price|"
    r"download\s+datasheet|request\s+a?\s*demo|get\s+a?\s*sample|"
    r"add\s+to\s+cart|buy\s+now|add\s+to\s+bag|order\s+now|"
    r"purchase\s+now|inquire\s+now|get\s+a?\s*free\s+trial|"
    r"request\s+information|learn\s+more\s+about\s+this|"
    r"contact\s+us\s+for|get\s+a?\s*price|request\s+a?\s*callback",
    re.I,
)


# ── Public API ────────────────────────────────────────────────────────────

def is_product_page(url: str, html: str) -> bool:
    """
    Returns True if this page is a single product/offering detail page.
    JSON-LD and og:type are trusted unconditionally.
    Heuristics only used when structured data is absent.
    """
    soup = BeautifulSoup(html, "lxml")

    # 1. JSON-LD with @type: Product — always trust this (most reliable signal)
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            for item in _ld_items(data):
                if "Product" in _types(item):
                    return True
        except Exception:
            pass

    # 2. og:type = product — also always trust
    if "product" in (_meta(soup, "og:type") or "").lower():
        return True

    # Below: heuristics only — check for listing-page signals first
    page_text = soup.get_text(" ", strip=True)
    h1s = soup.find_all("h1")

    # Listing pages typically have many <h2> or <h3> product titles
    # and repeated price elements — skip if it looks like a grid
    price_elements = soup.find_all(class_=PRICE_CLASS_RE)
    if len(price_elements) > 5 and len(h1s) != 1:
        return False

    # 3. SKU / part number label in visible text (strong single-product signal)
    for node in soup.find_all(string=SKU_LABEL_RE):
        if node.parent and node.parent.name not in ("script", "style"):
            return True

    # 4. Offering CTA language + single <h1>
    if len(h1s) == 1 and OFFERED_RE.search(page_text):
        return True

    # 5. Spec table + single <h1> (classic B2B product detail)
    if len(h1s) == 1 and soup.find("table"):
        return True

    return False


def extract_product(url: str, html: str) -> Product | None:
    soup = BeautifulSoup(html, "lxml")

    p = _from_jsonld(url, soup)
    if p:
        return p

    p = _from_meta(url, soup)
    if p:
        return p

    return _from_heuristics(url, soup)


# ── JSON-LD ───────────────────────────────────────────────────────────────

def _from_jsonld(url: str, soup: BeautifulSoup) -> Product | None:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        for item in _ld_items(data):
            if "Product" in _types(item):
                return _parse_ld_product(url, item)
    return None


def _parse_ld_product(url: str, d: dict) -> Product:
    name = _s(d.get("name")) or ""
    sku  = _s(d.get("sku"))
    pid  = _s(d.get("productID") or d.get("@id") or d.get("identifier"))
    desc = _s(d.get("description"))

    brand = None
    b = d.get("brand")
    if isinstance(b, dict):
        brand = _s(b.get("name"))
    elif isinstance(b, str):
        brand = b

    image = _ld_image(d.get("image"))

    specs: dict[str, str] = {}
    for prop in d.get("additionalProperty", []):
        if isinstance(prop, dict):
            k, v = _s(prop.get("name")), _s(prop.get("value"))
            if k and v:
                specs[k] = v

    price = list_price = currency = None
    availability = "unknown"
    variants: list[Variant] = []

    offers_raw = d.get("offers")
    if offers_raw:
        for offer in (offers_raw if isinstance(offers_raw, list) else [offers_raw]):
            if not isinstance(offer, dict):
                continue
            if price is None:
                price = parse_price(offer.get("price") or offer.get("lowPrice"))
            if list_price is None:
                list_price = parse_price(offer.get("highPrice"))
            if currency is None:
                currency = _s(offer.get("priceCurrency"))
            if availability == "unknown":
                availability = normalise_availability(offer.get("availability"))

    # Actively listed = available
    if availability == "unknown" and name:
        availability = "in_stock"

    return Product(
        url=url, id=make_id(pid or sku, url),
        name=name, brand=brand, sku=sku,
        price=price, listPrice=list_price, currency=currency,
        availability=availability, image=image,
        description=desc, specs=specs, variants=variants,
    )


# ── Meta tags ─────────────────────────────────────────────────────────────

def _from_meta(url: str, soup: BeautifulSoup) -> Product | None:
    og_type = _meta(soup, "og:type") or ""
    is_product_og = "product" in og_type.lower()

    name = (_meta(soup, "og:title") or _meta(soup, "twitter:title") or _h1(soup))
    if not name:
        return None

    price = parse_price(
        _meta(soup, "og:price:amount") or
        _meta(soup, "product:price:amount") or
        _itemprop(soup, "price")
    )
    currency = (
        _meta(soup, "og:price:currency") or
        _meta(soup, "product:price:currency") or
        _itemprop(soup, "priceCurrency")
    )
    image = _meta(soup, "og:image") or _meta(soup, "twitter:image")

    avail_raw = _meta(soup, "og:availability") or _itemprop(soup, "availability")
    availability = normalise_availability(avail_raw) if avail_raw else "in_stock"

    sku = _itemprop(soup, "sku")
    brand_tag = soup.find(itemprop="brand")
    brand = brand_tag.get_text(strip=True) if brand_tag else None

    desc_tag = soup.find(itemprop="description")
    description = (
        desc_tag.get_text(strip=True) if desc_tag
        else (_meta(soup, "og:description") or _meta(soup, "description"))
    )

    if not is_product_og and price is None:
        return None

    return Product(
        url=url, id=make_id(sku, url),
        name=name, brand=brand, sku=sku,
        price=price, listPrice=None, currency=currency,
        availability=availability, image=image,
        description=description, specs={}, variants=[],
    )


# ── HTML heuristics ───────────────────────────────────────────────────────

def _from_heuristics(url: str, soup: BeautifulSoup) -> Product | None:
    name = _h1(soup)
    if not name:
        return None

    page_text = soup.get_text(" ", strip=True)

    # Must have at least one offering/product signal
    if not OFFERED_RE.search(page_text) and not SKU_LABEL_RE.search(page_text):
        return None

    # Price — scan for elements whose class/id looks price-related
    price = currency = None
    for tag in soup.find_all(True):
        label = " ".join(tag.get("class", [])) + " " + tag.get("id", "")
        if PRICE_CLASS_RE.search(label):
            txt = tag.get_text(strip=True)
            p = parse_price(txt)
            if p and price is None:
                price = p
                for sym, code in CURRENCY_SYMBOL_MAP.items():
                    if sym in txt:
                        currency = code
                        break

    # SKU / part number — only look in visible text nodes, never in <script>/<style>
    sku = None
    for node in soup.find_all(string=SKU_LABEL_RE):
        # skip anything inside a script or style tag
        if node.parent and node.parent.name in ("script", "style"):
            continue
        parent = node.parent
        nxt = parent.find_next_sibling()
        raw = nxt.get_text(strip=True) if nxt else ""
        if not raw:
            raw = SKU_LABEL_RE.sub("", parent.get_text(strip=True)).strip()
        # a real SKU is short — if it's longer than 80 chars it's probably code
        if raw and len(raw) <= 80:
            sku = raw
            break

    # Availability
    low = page_text.lower()
    if "out of stock" in low or "sold out" in low or "discontinued" in low:
        availability = "out_of_stock"
    else:
        availability = "in_stock"   # actively listed = available

    # Image
    image = _product_image(soup)

    # Description — first <p> after <h1>, or meta
    description = None
    h1_tag = soup.find("h1")
    if h1_tag:
        nxt = h1_tag.find_next("p")
        if nxt:
            description = nxt.get_text(strip=True)
    if not description:
        description = _meta(soup, "description") or _meta(soup, "og:description")

    # Specs — tables and definition lists
    specs = _extract_specs(soup)

    # Brand
    brand = _find_brand(soup, page_text)

    return Product(
        url=url, id=make_id(sku, url),
        name=name, brand=brand, sku=sku,
        price=price, listPrice=None, currency=currency,
        availability=availability, image=image,
        description=description, specs=specs, variants=[],
    )


def _extract_specs(soup: BeautifulSoup) -> dict[str, str]:
    specs: dict[str, str] = {}
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) == 2:
                k = cells[0].get_text(strip=True)
                v = cells[1].get_text(strip=True)
                if k and v and len(k) < 80:
                    specs[k] = v
    for dl in soup.find_all("dl"):
        for dt, dd in zip(dl.find_all("dt"), dl.find_all("dd")):
            k = dt.get_text(strip=True)
            v = dd.get_text(strip=True)
            if k and v:
                specs[k] = v
    return specs


def _product_image(soup: BeautifulSoup) -> str | None:
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-zoom-image") or ""
        alt = img.get("alt", "").lower()
        if src and ("product" in src.lower() or "product" in alt):
            return src
    img = soup.find("img")
    return img.get("src") if img else None


def _find_brand(soup: BeautifulSoup, page_text: str) -> str | None:
    tag = (
        soup.find(itemprop="brand") or
        soup.find(class_=re.compile(r"brand", re.I)) or
        soup.find(id=re.compile(r"brand", re.I))
    )
    if tag:
        return tag.get_text(strip=True) or None
    m = re.search(r"(?:brand|manufacturer|made\s+by)\s*[:\-]?\s*([A-Za-z0-9 &\-]+)", page_text, re.I)
    return m.group(1).strip() if m else None


# ── Tiny helpers ──────────────────────────────────────────────────────────

def _ld_items(data) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "@graph" in data:
            return data["@graph"]
        return [data]
    return []


def _types(item: dict) -> list[str]:
    t = item.get("@type", "")
    return t if isinstance(t, list) else [t]


def _ld_image(raw) -> str | None:
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if isinstance(raw, dict):
        return raw.get("url") or raw.get("contentUrl")
    return raw if isinstance(raw, str) else None


def _s(v) -> str | None:
    return str(v).strip() if v else None


def _meta(soup: BeautifulSoup, prop: str) -> str | None:
    tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
    return (tag.get("content", "").strip() or None) if tag else None


def _itemprop(soup: BeautifulSoup, prop: str) -> str | None:
    tag = soup.find(itemprop=prop)
    if not tag:
        return None
    return tag.get("content") or tag.get_text(strip=True) or None


def _h1(soup: BeautifulSoup) -> str | None:
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else None
