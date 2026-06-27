"""WooCommerce 10.9.1 compatible CSV export adapter."""
from __future__ import annotations
import csv
import re
from adapters.base import ExportAdapter, NormalizedProduct, NormalizedVariant

# WooCommerce native import CSV columns
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


def _grams_to_kg(grams: float) -> str:
    if grams <= 0:
        return ""
    return f"{grams / 1000:.4f}".rstrip("0").rstrip(".")


def _price(val: str) -> str:
    """Clean a price string — keep two decimal places if numeric."""
    val = val.strip()
    if not val:
        return ""
    try:
        return f"{float(val):.2f}"
    except ValueError:
        return val


def _published(published: bool, status: str) -> str:
    if not published or status.lower() == "draft":
        return "0"
    return "1"


def _is_variable(product: NormalizedProduct) -> bool:
    """A product is variable if it has meaningful option values (more than a single blank/default)."""
    if not product.option1_name:
        return False
    option_values = {v.option1_value for v in product.variants if v.option1_value and v.option1_value.lower() != "default title"}
    return len(option_values) > 1 or bool(product.option2_name) or bool(product.option3_name)


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
            parent_sku = product.variants[0].sku if product.variants else product.handle

            if variable:
                # --- Parent product row ---
                parent: dict[str, str] = {c: "" for c in WOO_COLUMNS}
                parent["Type"] = "variable"
                parent["SKU"] = parent_sku
                parent["Name"] = product.title
                parent["Published"] = pub
                parent["Visibility in catalog"] = "visible"
                parent["Description"] = description
                parent["Tax status"] = "taxable"
                parent["In stock?"] = "1"
                parent["Categories"] = cats
                parent["Tags"] = tags
                parent["Images"] = images
                parent["Meta: _yoast_wpseo_title"] = product.seo_title
                parent["Meta: _yoast_wpseo_metadesc"] = product.seo_description
                parent["Meta: rank_math_title"] = product.seo_title
                parent["Meta: rank_math_description"] = product.seo_description

                # Attributes on parent: all values as a set
                if product.option1_name:
                    parent["Attribute 1 name"] = product.option1_name
                    parent["Attribute 1 value(s)"] = _all_option_values(product, 0)
                    parent["Attribute 1 visible"] = "1"
                    parent["Attribute 1 global"] = "1"
                if product.option2_name:
                    parent["Attribute 2 name"] = product.option2_name
                    parent["Attribute 2 value(s)"] = _all_option_values(product, 1)
                    parent["Attribute 2 visible"] = "1"
                    parent["Attribute 2 global"] = "1"
                if product.option3_name:
                    parent["Attribute 3 name"] = product.option3_name
                    parent["Attribute 3 value(s)"] = _all_option_values(product, 2)
                    parent["Attribute 3 visible"] = "1"
                    parent["Attribute 3 global"] = "1"

                rows.append(parent)

                # --- Child variation rows ---
                for i, variant in enumerate(product.variants):
                    child: dict[str, str] = {c: "" for c in WOO_COLUMNS}
                    child["Type"] = "variation"
                    child["SKU"] = variant.sku or f"{parent_sku}-var-{i+1}"
                    child["Name"] = product.title
                    child["Published"] = pub
                    child["Visibility in catalog"] = "visible"
                    child["Regular price"] = _price(variant.price)
                    child["Sale price"] = _price(variant.compare_at_price) if variant.compare_at_price else ""
                    child["Tax status"] = "taxable" if variant.taxable else "none"
                    child["In stock?"] = "1" if variant.inventory_qty >= 0 else "0"
                    child["Stock"] = str(max(variant.inventory_qty, 0))
                    child["Weight (kg)"] = _grams_to_kg(variant.weight_grams)
                    child["Parent"] = parent_sku
                    child["Images"] = variant.image_src or (images.split(",")[0].strip() if images else "")
                    child["Position"] = str(i)

                    if product.option1_name and variant.option1_value:
                        child["Attribute 1 name"] = product.option1_name
                        child["Attribute 1 value(s)"] = variant.option1_value
                        child["Attribute 1 visible"] = "1"
                        child["Attribute 1 global"] = "1"
                    if product.option2_name and variant.option2_value:
                        child["Attribute 2 name"] = product.option2_name
                        child["Attribute 2 value(s)"] = variant.option2_value
                        child["Attribute 2 visible"] = "1"
                        child["Attribute 2 global"] = "1"
                    if product.option3_name and variant.option3_value:
                        child["Attribute 3 name"] = product.option3_name
                        child["Attribute 3 value(s)"] = variant.option3_value
                        child["Attribute 3 visible"] = "1"
                        child["Attribute 3 global"] = "1"

                    rows.append(child)

            else:
                # --- Simple product ---
                variant = product.variants[0] if product.variants else NormalizedVariant(sku=product.handle)
                row: dict[str, str] = {c: "" for c in WOO_COLUMNS}
                row["Type"] = "simple"
                row["SKU"] = variant.sku or product.handle
                row["Name"] = product.title
                row["Published"] = pub
                row["Visibility in catalog"] = "visible"
                row["Description"] = description
                row["Regular price"] = _price(variant.price)
                row["Sale price"] = _price(variant.compare_at_price) if variant.compare_at_price else ""
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
                rows.append(row)

        # Write CSV with UTF-8 BOM for Excel compatibility
        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=WOO_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        return len(rows)
