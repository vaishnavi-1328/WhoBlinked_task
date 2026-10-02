# Task: read a website's full product catalogue

## Problem

Given the address of any online store or manufacturer's website, return every product it
offers, with its price, variants and stock, exactly as a shopper would see them today.

Websites publish their catalogues in very different ways, and many actively resist
automated reading. This is a research and engineering task: find out the different ways
sites structure and expose their products, and the possible ways to read each of them,
then build a reader that handles that variety.

## Input

A website address, e.g. `https://www.heathrowscientific.com`.

## Output

One JSON document per site:

```ts
type CatalogueRead = {
  site: string;                 // the site that was read
  readAt: string;               // ISO timestamp
  complete: boolean;            // true only if every product on the site was read
  incompleteReason?: string;    // why not, e.g. "blocked", "stopped early"
  products: Product[];
};

type Product = {
  url: string;                  // the product's page
  id: string;                   // the site's own product id
  name: string;
  brand: string | null;
  sku: string | null;
  price: number | null;         // what a shopper pays now (sale price if on sale)
  listPrice: number | null;     // the regular / struck-through price, if shown
  currency: string | null;      // e.g. "USD"
  availability: "in_stock" | "out_of_stock" | "unknown";
  image: string | null;
  variants: Variant[];          // sizes, colours, pack sizes…; empty if none
};

type Variant = {
  sku: string | null;
  options: Record<string, string>;   // e.g. { size: "M", colour: "Navy" }
  price: number | null;
  listPrice: number | null;
  availability: "in_stock" | "out_of_stock" | "unknown";
};
```

Example:

```json
{
  "url": "https://www.example-store.com/products/scrub-top",
  "id": "scrub-top",
  "name": "Scrub Top",
  "brand": "Example",
  "sku": "ST-1001",
  "price": 24.99,
  "listPrice": 29.99,
  "currency": "USD",
  "availability": "in_stock",
  "image": "https://www.example-store.com/images/scrub-top.jpg",
  "variants": [
    { "sku": "ST-1001-S", "options": { "size": "S" }, "price": 24.99, "listPrice": 29.99, "availability": "in_stock" },
    { "sku": "ST-1001-XL", "options": { "size": "XL" }, "price": 27.99, "listPrice": 32.99, "availability": "out_of_stock" }
  ]
}
```

A value the site does not state is `null` or `"unknown"`, never guessed. A site that
refuses to be read is reported as incomplete, not as a site with no products.

## Sites

A spread of real sites, from easy to hard:

- https://www.poltex.com
- https://www.alimed.com
- https://www.finelineflag.com
- https://www.gracealley.com
- https://www.brownmed.com
- https://www.s-curve.com
- https://www.dynamictechnomedicals.com
- https://www.customcomfort.com
- https://www.heathrowscientific.com
- https://www.medicus-health.com
- https://www.nursemates.com
- https://www.marketlab.com
- https://www.gohcl.com
- https://www.packlane.com
- https://www.boundtree.com
- https://www.vitalitymedical.com
- https://www.clinton-ind.com
- https://www.farfetch.com
- https://www.mytheresa.com
