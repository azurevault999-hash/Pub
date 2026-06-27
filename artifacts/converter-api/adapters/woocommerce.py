"""WooCommerce 10.9.1 compatible CSV export adapter."""
from __future__ import annotations

import csv
import logging
from adapters.base import ExportAdapter, NormalizedProduct, NormalizedVariant

_log = logging.getLogger(__name__)

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
    # Attribute 1
    "Attribute 1 name", "Attribute 1 value(s)",
    "Attribute 1 visible", "Attribute 1 global", "Attribute 1 used for variations",
    # Attribute 2
    "Attribute 2 name", "Attribute 2 value(s)",
    "Attribute 2 visible", "Attribute 2 global", "Attribute 2 used for variations",
    # Attribute 3
    "Attribute 3 name", "Attribute 3 value(s)",
    "Attribute 3 visible", "Attribute 3 global", "Attribute 3 used for variations",
    # SEO meta
    "Meta: _yoast_wpseo_title", "Meta: _yoast_wpseo_metadesc",
    "Meta: rank_math_title", "Meta: rank_math_description",
]

MAX_ATTRIBUTES = 3


# ─────────────────────────────────────────────────────────────────────────────
# Price helpers
# ─────────────────────────────────────────────────────────────────────────────


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
        Variant Price             — current selling price
        Variant Compare At Price  — original / "was" price (shown as strikethrough)

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


# ─────────────────────────────────────────────────────────────────────────────
# Other helpers
# ─────────────────────────────────────────────────────────────────────────────


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

    Single-option products where the only option name is "Title" and the only
    value is "Default Title" are treated as simple (Shopify's placeholder for
    products with no real options).

    Single-option products with exactly one real non-default value are treated
    as simple (no variation to choose from — nothing to drop down).
    """
    if not product.option1_name:
        return False

    # If multiple option dimensions are defined, it is always variable.
    if product.option2_name or product.option3_name:
        return True

    # Single option dimension: collect real (non-default) values.
    real_values = {
        v.option1_value for v in product.variants
        if v.option1_value and v.option1_value.lower() != "default title"
    }
    # Zero real values → simple (only "Default Title" variant).
    # One real value  → simple (no choice to present).
    # Two+ real values → variable.
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


def _active_option_count(product: NormalizedProduct) -> int:
    """Return the number of non-empty option names defined on *product*."""
    count = 0
    for name in (product.option1_name, product.option2_name, product.option3_name):
        if name:
            count += 1
    return count


def _set_attributes(
    row: dict[str, str],
    product: NormalizedProduct,
    variant: NormalizedVariant | None = None,
    is_global: bool = True,
    used_for_variations: bool = False,
) -> None:
    """
    Populate Attribute N columns on *row*.

    Parent / simple rows (variant=None):
        • value(s) = all distinct values joined with " | " (WooCommerce set syntax)
        • used for variations = "1" when used_for_variations is True (variable parent)
        • used for variations = "0" for simple products

    Variation rows (variant set):
        • value(s) = the single value for *this* variant
        • used for variations = "0" (the flag lives on the parent, not the child)

    is_global controls the "Attribute N global" flag (global = taxonomy attribute).
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
            # Variation row: write the single value for this specific variant.
            val = [variant.option1_value, variant.option2_value, variant.option3_value][idx]
        else:
            # Parent / simple row: write all possible values.
            val = _all_option_values(product, idx)
        if not val:
            continue
        row[f"Attribute {num} name"] = name
        row[f"Attribute {num} value(s)"] = val
        row[f"Attribute {num} visible"] = "1"
        row[f"Attribute {num} global"] = "1" if is_global else "0"
        # Critical: "used for variations" = "1" on the parent row tells WooCommerce
        # which attributes power the storefront dropdowns.  Without this flag every
        # variation shows "Any" and Add to Cart is disabled.
        row[f"Attribute {num} used for variations"] = "1" if used_for_variations else "0"


def _variant_image(variant: NormalizedVariant, product_images: str) -> str:
    """
    Resolve the image for a variation row.

    Priority:
    1. Variant-specific image (Variant Image column)
    2. First product image (fallback; Variant Image is optional per spec)
    """
    if variant.image_src:
        return variant.image_src
    if product_images:
        return product_images.split(",")[0].strip()
    return ""


def _total_in_stock(product: NormalizedProduct) -> str:
    """Return "1" if any variant has stock > 0, else "0"."""
    for v in product.variants:
        if v.inventory_qty > 0:
            return "1"
    return "0"


# ─────────────────────────────────────────────────────────────────────────────
# Post-export verification
# ─────────────────────────────────────────────────────────────────────────────


def verify_woocommerce_csv(output_path: str) -> list[str]:
    """
    Read the generated WooCommerce CSV and verify its logical structure.

    Checks:
    • Every variation references a known parent SKU.
    • No variation contains "Any" or an empty string for a named attribute.
    • Every parent attribute has "used for variations" = "1".
    • Every parent attribute has at least one value listed.
    • Every variation has a Regular price.
    • Every variation SKU is unique within the file.
    • All required WooCommerce column headers are present.

    Returns a list of error strings.  An empty list means the file passed.
    """
    errors: list[str] = []

    try:
        with open(output_path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except Exception as exc:
        return [f"Cannot read generated CSV for verification: {exc}"]

    if not rows:
        return ["Generated CSV is empty — no rows were written."]

    # Required columns present?
    required_cols = {
        "Type", "SKU", "Name", "Regular price", "Parent",
        "Attribute 1 name", "Attribute 1 value(s)", "Attribute 1 used for variations",
    }
    present_cols = set(rows[0].keys())
    missing_cols = required_cols - present_cols
    if missing_cols:
        errors.append(
            f"Generated CSV missing required columns: {', '.join(sorted(missing_cols))}"
        )

    # Index parents and collect variation rows.
    parent_rows: dict[str, dict] = {}
    variation_rows: list[dict] = []
    seen_skus: set[str] = set()
    dup_skus: list[str] = []

    for row in rows:
        row_type = row.get("Type", "").strip()
        row_sku = row.get("SKU", "").strip()

        if row_sku:
            if row_sku in seen_skus:
                dup_skus.append(row_sku)
            seen_skus.add(row_sku)

        if row_type == "variable":
            parent_rows[row_sku] = row
        elif row_type == "variation":
            variation_rows.append(row)

    if dup_skus:
        errors.append(
            f"Duplicate SKUs in generated CSV: {', '.join(dict.fromkeys(dup_skus))}"
        )

    # Verify each variation row.
    for var in variation_rows:
        var_sku = var.get("SKU", "(no SKU)").strip()
        parent_ref = var.get("Parent", "").strip()

        if not parent_ref:
            errors.append(
                f"Variation '{var_sku}' has no Parent reference — "
                "WooCommerce cannot link it to a product."
            )
        elif parent_ref not in parent_rows:
            errors.append(
                f"Variation '{var_sku}' references unknown parent '{parent_ref}'."
            )

        # Every named attribute must have a concrete, non-"Any" value.
        for n in ("1", "2", "3"):
            attr_name = var.get(f"Attribute {n} name", "").strip()
            if not attr_name:
                continue
            attr_val = var.get(f"Attribute {n} value(s)", "").strip()
            if not attr_val:
                errors.append(
                    f"Variation '{var_sku}': Attribute {n} '{attr_name}' "
                    f"has no value — WooCommerce will display 'Any'."
                )
            elif attr_val.lower() == "any":
                errors.append(
                    f"Variation '{var_sku}': Attribute {n} '{attr_name}' "
                    f"value is literally 'Any' — must be a concrete value."
                )

        # Must have a price to be purchasable.
        price = var.get("Regular price", "").strip()
        if not price:
            errors.append(
                f"Variation '{var_sku}' has no Regular price — "
                "it will not be purchasable in WooCommerce."
            )

    # Verify each parent row.
    for parent_sku, parent_row in parent_rows.items():
        for n in ("1", "2", "3"):
            attr_name = parent_row.get(f"Attribute {n} name", "").strip()
            if not attr_name:
                continue
            used = parent_row.get(f"Attribute {n} used for variations", "").strip()
            if used != "1":
                errors.append(
                    f"Parent '{parent_sku}': Attribute {n} '{attr_name}' "
                    f"'used for variations' = '{used or '(empty)'}' — must be '1'. "
                    "Storefront dropdowns will be empty without this."
                )
            all_vals = parent_row.get(f"Attribute {n} value(s)", "").strip()
            if not all_vals:
                errors.append(
                    f"Parent '{parent_sku}': Attribute {n} '{attr_name}' "
                    "has no values listed — WooCommerce cannot build the dropdown."
                )

    return errors


# ─────────────────────────────────────────────────────────────────────────────
# Adapter
# ─────────────────────────────────────────────────────────────────────────────


class WooCommerceAdapter(ExportAdapter):
    @property
    def name(self) -> str:
        return "WooCommerce"

    def export(self, products: list[NormalizedProduct], output_path: str) -> int:
        rows: list[dict[str, str]] = []
        simple_count = 0
        variable_count = 0

        for product in products:
            variable = _is_variable(product)
            pub = _published(product.published, product.status)
            cats = _build_categories(product.product_type)
            tags = ", ".join(product.tags)
            images = _build_image_list(product)
            description = product.body_html
            active_opts = _active_option_count(product)

            if variable:
                variable_count += 1
                # ── Parent product row ───────────────────────────────────────
                # The parent SKU is the product handle — unique per product and
                # distinct from any variant SKU, preventing WooCommerce from
                # confusing the parent row with the first child row.
                parent_sku = product.handle

                _log.debug(
                    "[PARENT] handle=%s title=%r attrs=%d variants=%d",
                    product.handle, product.title, active_opts, len(product.variants),
                )

                # Log attribute mapping for this product.
                for name, idx, num in [
                    (product.option1_name, 0, "1"),
                    (product.option2_name, 1, "2"),
                    (product.option3_name, 2, "3"),
                ]:
                    if name:
                        all_vals = _all_option_values(product, idx)
                        _log.debug(
                            "[ATTR MAP] %s → Attribute %s name=%r values=%r",
                            product.handle, num, name, all_vals,
                        )

                parent: dict[str, str] = {c: "" for c in WOO_COLUMNS}
                parent["Type"] = "variable"
                parent["SKU"] = parent_sku
                parent["Name"] = product.title
                parent["Published"] = pub
                parent["Visibility in catalog"] = "visible"
                parent["Description"] = description
                parent["Tax status"] = "taxable"
                parent["In stock?"] = _total_in_stock(product)
                parent["Stock"] = ""
                parent["Categories"] = cats
                parent["Tags"] = tags
                parent["Images"] = images
                parent["Meta: _yoast_wpseo_title"] = product.seo_title
                parent["Meta: _yoast_wpseo_metadesc"] = product.seo_description
                parent["Meta: rank_math_title"] = product.seo_title
                parent["Meta: rank_math_description"] = product.seo_description
                # used_for_variations=True is the critical flag that enables
                # storefront dropdowns in WooCommerce.
                _set_attributes(parent, product, variant=None,
                                 is_global=True, used_for_variations=True)
                rows.append(parent)

                # ── Child variation rows ─────────────────────────────────────
                for i, variant in enumerate(product.variants):
                    regular, sale = _price_pair(variant.price, variant.compare_at_price)

                    _log.debug(
                        "[VARIATION] parent=%s sku=%r opt1=%r opt2=%r opt3=%r price=%s",
                        parent_sku, variant.sku or f"{parent_sku}-var-{i+1}",
                        variant.option1_value, variant.option2_value,
                        variant.option3_value, regular,
                    )

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
                    # Variation rows carry the single concrete value for each
                    # attribute; used_for_variations is a parent-level concept.
                    _set_attributes(child, product, variant=variant,
                                     is_global=True, used_for_variations=False)
                    rows.append(child)

            else:
                # ── Simple product ───────────────────────────────────────────
                simple_count += 1
                variant = (
                    product.variants[0] if product.variants
                    else NormalizedVariant(sku=product.handle)
                )
                regular, sale = _price_pair(variant.price, variant.compare_at_price)

                _log.debug(
                    "[SIMPLE] handle=%s title=%r sku=%r price=%s",
                    product.handle, product.title, variant.sku or product.handle, regular,
                )

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
                # Write attributes on simple products so option metadata is
                # preserved; used_for_variations=False (no dropdown needed).
                _set_attributes(row, product, variant=None,
                                 is_global=False, used_for_variations=False)
                rows.append(row)

        _log.info(
            "Export complete: %d simple, %d variable, %d total rows",
            simple_count, variable_count, len(rows),
        )

        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=WOO_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        return len(rows)
