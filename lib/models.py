from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

DiscoveryStatus = Literal[
    "complete",          # all products found
    "partial",           # some found, some pages blocked mid-crawl
    "blocked",           # hard 403 / Akamai / CF — nothing accessible
    "bot_wall",          # challenge page served as 200, no real content
    "no_sitemap",        # sitemap empty/missing, all fallbacks exhausted
    "extractor_failure", # URLs found but zero product pages detected
]


@dataclass
class Variant:
    sku: str | None
    options: dict[str, str]          # e.g. {"size": "M", "colour": "Blue"}
    price: float | None
    listPrice: float | None
    availability: Literal["in_stock", "out_of_stock", "unknown"]


@dataclass
class Product:
    url: str
    id: str
    name: str
    brand: str | None
    sku: str | None
    price: float | None              # null if quote-only / no price shown
    listPrice: float | None
    currency: str | None
    availability: Literal["in_stock", "out_of_stock", "unknown"]
    image: str | None
    description: str | None          # product description or summary
    specs: dict[str, str]            # technical specs / attributes table
    variants: list[Variant] = field(default_factory=list)


@dataclass
class CatalogueRead:
    site: str
    readAt: str
    complete: bool
    products: list[Product] = field(default_factory=list)
    incompleteReason: str | None = None
    discoveryStatus: DiscoveryStatus = "complete"
