"""WooCommerce 10.9.1 compatible CSV export adapter."""
from __future__ import annotations

import csv
from adapters.base import ExportAdapter, NormalizedProduct, NormalizedVariant

WOO_COLUMNS = [
    "ID", "Type", "SKU", "Name", "Published", "Is featured?",
    "Visibility in catalog", "Short description", "Description",
    "Date sale price starts", "Date sale price ends",
    "Tax status", "Tax class", "In stock?", "Stock",
    "Backorders allowed?", "Sold individually?",
    "Weight (kg)", "Length (cm)", "Width (cm)", "Height (cm)",
    "Allow customer reviews?", "Purchase note", "Sale price", "Regular price",
    "Categories", "Tags", "Shipping class", "Images",
    "Download limit", "Download expiry days", "Parent",
    "Grouped products", "Upsells", "Cross-sells",
    "External URL", "Button text", "Position",
    "Attribute 1 name", "Attribute 1 value(s)", "Attribute 1 visible", "Attribute 1 global",
    "Attribute 2 name", "Attribute 2 value(s)", "Attribute 2 visible", "Attribute 2 global",
    "Attribute 3 name", "Attribute 3 value(s)", "Attribute 3 visible", "Attribute 3 global",
    "Meta: _yoast_wpseo_title", "Meta: _yoast_wpseo_metadesc",
    "Meta: rank_math_title", "Meta: rank_math_description",
]

MAX_ATTRIBUTES = 3


# ─────────────────── Price helpers ───────────────────


def _price(val: str) -> str:
    """Normalise a price string to two decimal places."""
    val = val.strip()
    if not val:
        return ""
    try:
        return f"{float(val):.2f}"
    except ValueError:
        return val


def _price_pair(price: str, compare_at_price: str) -> tuple[str, str]:
    """
    Map Shopify price fields to WooCommerce (regular_price, sale_price).

    Shopify semantics:
        Variant Price         — current selling price
        Variant Compare At Price — original / "was" price (shown as strikethrough)

    WooCommerce semantics:
        Regular price — the normal / original price (shown with strikethrough when on sale)
        Sale price    — the lower / discounted price (empty when not on sale)

    Mapping:
        If compare_at > price  →  regular = compare_at, sale = price  (product is on sale)
        Otherwise              →  regular = price, sale = ""           (no sale)
    """
    p = _price(price)
    c = _price(compare_at_price)
    if not p:
        return ("", "")
    if c:
        try:
            if float(c) > float(p):
                return (c, p)
        except ValueError:
            pass
    return (p, "")


# ─────────────────── Other helpers ───────────────────


def _grams_to_kg(grams: float) -> str:
    if grams <= 0:
        return ""
    return f"{grams / 1000:.4f}".rstrip("0").rstrip(".")


def _published(published: bool, status: str) -> str:
    if not published or status.lower() in ("draft", "archived"):
        return "0"
    return "1"


def _is_variable(product: NormalizedProduct) -> bool:
    """
    A product is variable if it has a meaningful option dimension with more
    than one distinct value, or if it has multiple option dimensions.

    Single-option products where the only value is "Default Title" are treated
    as simple (Shopify's placeholder for products with no real options).
    """
    if not product.option1_name:
        return False
    if product.option2_name or product.option3_name:
        return True
    real_values = {
        v.option1_value for v in product.variants
        if v.option1_value and v.option1_value.lower() != "default title"
    }
    return len(real_values) > 1


def _build_categories(product_type: str) -> str:
    """Convert Shopify product type to WooCommerce category path."""
    if not product_type:
        return ""
    parts = [p.strip() for p in product_type.split(">") if p.strip()]
    return " > ".join(parts) if parts else product_type


def _build_image_list(product: NormalizedProduct) -> str:
    """Comma-separated image URLs: first = featured, rest = gallery."""
    urls = [src for src, _, _ in product.images if src]
    return ", ".join(urls)


def _featured_image(product: NormalizedProduct) -> str:
    """Return the first image URL, or empty string."""
    for src, _, _ in product.images:
        if src:
            return src
    return ""


def _all_option_values(product: NormalizedProduct, option_idx: int) -> str:
    """Return pipe-separated unique values for an option across all variants."""
    values: list[str] = []
    seen: set[str] = set()
    for v in product.variants:
        val = [v.option1_value, v.option2_value, v.option3_value][option_idx]
        if val and val not in seen:
            seen.add(val)
            values.append(val)
    return " | ".join(values)


def _set_attributes(
    row: dict[str, str],
    product: NormalizedProduct,
    variant: NormalizedVariant | None = None,
    is_global: bool = True,
) -> None:
    """
    Populate Attribute N columns on *row*.

    For parent/simple rows: all values joined with " | " (WooCommerce set syntax).
    For variation rows: single value per attribute.
    is_global controls the "Attribute N global" flag.
    """
    options = [
        (product.option1_name, 0, "1"),
        (product.option2_name, 1, "2"),
        (product.option3_name, 2, "3"),
    ]
    for name, idx, num in options:
        if not name:
            continue
        if variant is not None:
            val = [variant.option1_value, variant.option2_value, variant.option3_value][idx]
        else:
            val = _all_option_values(product, idx)
        if not val:
            continue
        row[f"Attribute {num} name"] = name
        row[f"Attribute {num} value(s)"] = val
        row[f"Attribute {num} visible"] = "1"
        row[f"Attribute {num} global"] = "1" if is_global else "0"


def _variant_image(variant: NormalizedVariant, product_images: str) -> str:
    """
    Resolve the image for a variation row.

    Priority:
    1. Variant-specific image (Variant Image column)
    2. First product image (fallback)
    """
    if variant.image_src:
        return variant.image_src
    if product_images:
        # product_images is a comma-separated list; take the first entry safely
        return product_images.split(",")[0].strip()
    return ""


def _total_in_stock(product: NormalizedProduct) -> str:
    """Return "1" if any variant has stock > 0, else "0"."""
    for v in product.variants:
        if v.inventory_qty > 0:
            return "1"
    return "0"


class WooCommerceAdapter(ExportAdapter):
    @property
    def name(self) -> str:
        return "WooCommerce"

    def export(self, products: list[NormalizedProduct], output_path: str) -> int:
        rows: list[dict[str, str]] = []

        for product in products:
            variable = _is_variable(product)
            pub = _published(product.published, product.status)
            cats = _build_categories(product.product_type)
            tags = ", ".join(product.tags)
            images = _build_image_list(product)
            description = product.body_html

            if variable:
                # ── Parent product row ──────────────────────────────────────
                # The parent SKU is the product handle — unique per product and
                # distinct from any variant SKU, preventing WooCommerce from
                # confusing the parent row with the first child row.
                parent_sku = product.handle

                parent: dict[str, str] = {c: "" for c in WOO_COLUMNS}
                parent["Type"] = "variable"
                parent["SKU"] = parent_sku
                parent["Name"] = product.title
                parent["Published"] = pub
                parent["Visibility in catalog"] = "visible"
                parent["Description"] = description
                parent["Tax status"] = "taxable"
                # Variable products track stock per variation; parent stock is blank.
                parent["In stock?"] = _total_in_stock(product)
                parent["Stock"] = ""
                parent["Categories"] = cats
                parent["Tags"] = tags
                parent["Images"] = images
                parent["Meta: _yoast_wpseo_title"] = product.seo_title
                parent["Meta: _yoast_wpseo_metadesc"] = product.seo_description
                parent["Meta: rank_math_title"] = product.seo_title
                parent["Meta: rank_math_description"] = product.seo_description
                _set_attributes(parent, product, variant=None, is_global=True)
                rows.append(parent)

                # ── Child variation rows ────────────────────────────────────
                for i, variant in enumerate(product.variants):
                    regular, sale = _price_pair(variant.price, variant.compare_at_price)
                    child: dict[str, str] = {c: "" for c in WOO_COLUMNS}
                    child["Type"] = "variation"
                    child["SKU"] = variant.sku or f"{parent_sku}-var-{i + 1}"
                    child["Name"] = product.title
                    child["Published"] = pub
                    child["Visibility in catalog"] = "visible"
                    child["Regular price"] = regular
                    child["Sale price"] = sale
                    child["Tax status"] = "taxable" if variant.taxable else "none"
                    child["In stock?"] = "1" if variant.inventory_qty >= 0 else "0"
                    child["Stock"] = str(max(variant.inventory_qty, 0))
                    child["Weight (kg)"] = _grams_to_kg(variant.weight_grams)
                    child["Parent"] = parent_sku
                    child["Images"] = _variant_image(variant, images)
                    child["Position"] = str(i)
                    _set_attributes(child, product, variant=variant, is_global=True)
                    rows.append(child)

            else:
                # ── Simple product ──────────────────────────────────────────
                variant = product.variants[0] if product.variants else NormalizedVariant(sku=product.handle)
                regular, sale = _price_pair(variant.price, variant.compare_at_price)
                row: dict[str, str] = {c: "" for c in WOO_COLUMNS}
                row["Type"] = "simple"
                row["SKU"] = variant.sku or product.handle
                row["Name"] = product.title
                row["Published"] = pub
                row["Visibility in catalog"] = "visible"
                row["Description"] = description
                row["Regular price"] = regular
                row["Sale price"] = sale
                row["Tax status"] = "taxable" if variant.taxable else "none"
                row["In stock?"] = "1" if variant.inventory_qty >= 0 else "0"
                row["Stock"] = str(max(variant.inventory_qty, 0))
                row["Weight (kg)"] = _grams_to_kg(variant.weight_grams)
                row["Categories"] = cats
                row["Tags"] = tags
                row["Images"] = images
                row["Meta: _yoast_wpseo_title"] = product.seo_title
                row["Meta: _yoast_wpseo_metadesc"] = product.seo_description
                row["Meta: rank_math_title"] = product.seo_title
                row["Meta: rank_math_description"] = product.seo_description
                # Write attributes on simple products too so option metadata is preserved.
                _set_attributes(row, product, variant=None, is_global=False)
                rows.append(row)

        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=WOO_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        return len(rows)
