from __future__ import annotations
import hashlib
import re
from urllib.parse import urlparse

PRICE_RE = re.compile(r"[\$£€¥₹]?\s*([\d,]+\.?\d*)")

AVAILABILITY_MAP = {
    "http://schema.org/instock": "in_stock",
    "https://schema.org/instock": "in_stock",
    "instock": "in_stock",
    "in stock": "in_stock",
    "in_stock": "in_stock",
    "http://schema.org/outofstock": "out_of_stock",
    "https://schema.org/outofstock": "out_of_stock",
    "outofstock": "out_of_stock",
    "out of stock": "out_of_stock",
    "out_of_stock": "out_of_stock",
    "http://schema.org/limitedavailability": "in_stock",
    "https://schema.org/limitedavailability": "in_stock",
    "limitedavailability": "in_stock",
    "preorder": "out_of_stock",
    "http://schema.org/preorder": "out_of_stock",
    "https://schema.org/preorder": "out_of_stock",
    "discontinue": "out_of_stock",
    "soldout": "out_of_stock",
    "sold out": "out_of_stock",
}

# URL path fragments that suggest a product/offering page on ANY kind of site
PRODUCT_URL_SIGNALS = {
    "/product", "/products", "/shop", "/item", "/items",
    "/catalog", "/catalogue", "/p/", "/goods", "/pd/",
    "/store", "/buy", "/listing", "/detail", "/offering",
    "/equipment", "/machine", "/device", "/solution", "/model",
    "/collection", "/collections", "/service", "/part",
    "/inventory", "/line", "/range", "/series", "/variant",
}

# Paths to always skip — definitely not product pages
SKIP_URL_FRAGMENTS = {
    "/blog", "/news", "/about", "/contact", "/faq",
    "/cart", "/checkout", "/account", "/login", "/register",
    "/search", "/wishlist", "/compare", "/sitemap", "/tag/",
    "/author", "/policy", "/privacy", "/shipping", "/returns",
    "/help", "/support", "/terms", "/legal", "/cookie",
    "/press", "/career", "/job", "/team", "/partner",
    "/event", "/webinar", "/newsletter", "/forum", "/community",
}

SKIP_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg",
    ".css", ".js", ".ico", ".zip", ".gz", ".mp4", ".mp3", ".webp",
}

CURRENCY_SYMBOL_MAP = {"$": "USD", "£": "GBP", "€": "EUR", "¥": "JPY", "₹": "INR"}


def parse_price(raw) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if raw >= 0 else None
    s = str(raw).strip().replace(",", "")
    m = PRICE_RE.search(s)
    if m:
        try:
            v = float(m.group(1))
            return v if v >= 0 else None
        except ValueError:
            return None
    return None


def normalise_availability(raw) -> str:
    if raw is None:
        return "unknown"
    key = str(raw).strip().lower()
    return AVAILABILITY_MAP.get(key, "unknown")


def extract_domain(url: str) -> str:
    return urlparse(url).netloc.lstrip("www.")


def make_id(platform_id: str | None, url: str) -> str:
    if platform_id and str(platform_id).strip():
        return str(platform_id).strip()
    return hashlib.md5(url.encode()).hexdigest()[:16]


def looks_like_product_url(url: str) -> bool:
    """
    Broad heuristic: does this URL look like it could be a product,
    equipment, service, or offering page on ANY kind of website?
    """
    parsed = urlparse(url)
    path = parsed.path.lower()

    # skip known file extensions
    suffix = "." + path.rsplit(".", 1)[-1] if "." in path.split("/")[-1] else ""
    if suffix in SKIP_EXTENSIONS:
        return False

    # skip known non-product sections
    if any(path.startswith(s) or s in path for s in SKIP_URL_FRAGMENTS):
        return False

    # positive match on known product path patterns
    if any(s in path for s in PRODUCT_URL_SIGNALS):
        return True

    return False
