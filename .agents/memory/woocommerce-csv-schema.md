---
name: WooCommerce 10.9.1 CSV product schema
description: Canonical attribute column structure and value separator required by WooCommerce 10.9.1 native Product CSV Importer
---

## Rule
WooCommerce 10.9.1 uses comma-separated attribute values (`", "`) — NOT pipe (`" | "`). Using pipe causes every variation to display "Any" because WooCommerce splits on comma only.

WooCommerce 10.9.1 column differences from older versions:
- Column is `"Attribute N default"` (NOT `"Attribute N used for variations"`)
- Three new columns: `"GTIN, UPC, EAN, or ISBN"`, `"Low stock amount"`, `"Brands"`
- Variation rows: `Attribute N visible = ""` and `Attribute N default = ""` (EMPTY, not "0"/"1")
- Parent rows: `Attribute N visible = "1"`, `Attribute N global = "1"`, `Attribute N default = ""`
- Variation rows: `Tax class = "parent"`, `Allow customer reviews? = "0"`, `Backorders allowed? = "0"`
- Parent rows: `Tax class = ""`, `Allow customer reviews? = "1"`, `Regular price = ""`

**Why:** Verified against a live WooCommerce 10.9.1 product export (`wc-product-export-28-6-2026-*.csv`). The importer infers "used for variations" from variation row structure — that explicit column is no longer needed.

**How to apply:** Any time WooCommerce CSV export schema needs updating, start from the canonical reference and verify against a real WC export, not documentation alone.
