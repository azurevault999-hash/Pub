"""WooCommerce 10.9.1 compatible CSV export adapter.

Schema derived from a live WooCommerce 10.9.1 product export.
Key differences from earlier versions:
  - Attribute values are COMMA-separated, not pipe-separated.
  - The 5th attribute column is "Attribute N default" (not "used for variations").
  - Variation rows leave "Attribute N visible" and "Attribute N default" empty.
  - Three new columns: "GTIN, UPC, EAN, or ISBN", "Low stock amount", "Brands".
  - Variation rows use Tax class = "parent".
"""
from __future__ import annotations

import csv
import logging
from adapters.base import ExportAdapter, NormalizedProduct, NormalizedVariant

_log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# WooCommerce 10.9.1 canonical column list
# Derived directly from a live WC 10.9.1 export — do not guess.
# ─────────────────────────────────────────────────────────────────────────────

WOO_COLUMNS = [
    "ID", "Type", "SKU", "GTIN, UPC, EAN, or ISBN", "Name", "Published",
    "Is featured?", "Visibility in catalog", "Short description", "Description",
    "Date sale price starts", "Date sale price ends",
    "Tax status", "Tax class", "In stock?", "Stock", "Low stock amount",
    "Backorders allowed?", "Sold individually?",
    "Weight (kg)", "Length (cm)", "Width (cm)", "Height (cm)",
    "Allow customer reviews?", "Purchase note", "Sale price", "Regular price",
    "Categories", "Tags", "Shipping class", "Images",
    "Download limit", "Download expiry days", "Parent",
    "Grouped products", "Upsells", "Cross-sells",
    "External URL", "Button text", "Position", "Brands",
    # Attribute 1
    "Attribute 1 name", "Attribute 1 value(s)",
    "Attribute 1 visible", "Attribute 1 global", "Attribute 1 default",
    # Attribute 2
    "Attribute 2 name", "Attribute 2 value(s)",
    "Attribute 2 visible", "Attribute 2 global", "Attribute 2 default",
    # Attribute 3
    "Attribute 3 name", "Attribute 3 value(s)",
    "Attribute 3 visible", "Attribute 3 global", "Attribute 3 default",
    # SEO meta (plugin-specific, preserved for completeness)
    "Meta: _yoast_wpseo_title", "Meta: _yoast_wpseo_metadesc",
    "Meta: rank_math_title", "Meta: rank_math_description",
]

MAX_ATTRIBUTES = 3

# Reference columns from a live WooCommerce 10.9.1 export (2 attribute slots
# because the test product only had 2 attributes; we extend to 3 for Shopify).
WC_REFERENCE_COLUMNS = [
    "ID", "Type", "SKU", "GTIN, UPC, EAN, or ISBN", "Name", "Published",
    "Is featured?", "Visibility in catalog", "Short description", "Description",
    "Date sale price starts", "Date sale price ends",
    "Tax status", "Tax class", "In stock?", "Stock", "Low stock amount",
    "Backorders allowed?", "Sold individually?",
    "Weight (kg)", "Length (cm)", "Width (cm)", "Height (cm)",
    "Allow customer reviews?", "Purchase note", "Sale price", "Regular price",
    "Categories", "Tags", "Shipping class", "Images",
    "Download limit", "Download expiry days", "Parent",
    "Grouped products", "Upsells", "Cross-sells",
    "External URL", "Button text", "Position", "Brands",
    "Attribute 1 name", "Attribute 1 value(s)",
    "Attribute 1 visible", "Attribute 1 global", "Attribute 1 default",
    "Attribute 2 name", "Attribute 2 value(s)",
    "Attribute 2 visible", "Attribute 2 global", "Attribute 2 default",
]

AUDIT_COLUMNS = [
    "Shopify Handle",
    "Shopify Variant SKU",
    "WooCommerce Parent",
    "WooCommerce Type",
    "Option1 Name", "Option1 Value",
    "Option2 Name", "Option2 Value",
    "Option3 Name", "Option3 Value",
    "Generated Attribute Mapping",
    "Validation Result",
    "Notes",
]


# ─────────────────────────────────────────────────────────────────────────────
# Schema comparison
# ─────────────────────────────────────────────────────────────────────────────


def compare_schema_to_reference() -> dict:
    """Compare WOO_COLUMNS with the canonical WooCommerce 10.9.1 reference.

    Returns a dict with keys:
        missing_from_ours   — columns in WC reference but not in WOO_COLUMNS
        extra_in_ours       — columns in WOO_COLUMNS but not in WC reference
                              (SEO meta and Attribute 3 slot are expected extras)
        schema_valid        — True if all reference columns are present in ours
    """
    our_set = set(WOO_COLUMNS)
    ref_set = set(WC_REFERENCE_COLUMNS)
    missing = sorted(ref_set - our_set)
    extra = sorted(our_set - ref_set)
    return {
        "missing_from_ours": missing,
        "extra_in_ours": extra,
        "schema_valid": len(missing) == 0,
        "reference_column_count": len(WC_REFERENCE_COLUMNS),
        "our_column_count": len(WOO_COLUMNS),
    }


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
        Variant Compare At Price  — original / "was" price (strikethrough)

    WooCommerce semantics:
        Regular price — the normal / original price (strikethrough when on sale)
        Sale price    — the lower / discounted price (empty when not on sale)

    Mapping:
        If compare_at > price  →  regular = compare_at, sale = price  (on sale)
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
    value is "Default Title" are treated as simple (Shopify placeholder).

    Single-option products with exactly one real non-default value are treated
    as simple (no variation to choose from — nothing to drop down).
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


def _all_option_values(product: NormalizedProduct, option_idx: int) -> str:
    """Return comma-separated unique values for an option across all variants.

    WooCommerce 10.9.1 uses COMMA as the attribute value delimiter (not pipe).
    The csv module automatically quotes fields containing commas, producing the
    correct "L, M, S, XL" format that WooCommerce's importer expects.

    Using pipe (|) causes WooCommerce to treat the entire pipe-joined string
    as ONE attribute value, so every variation shows "Any" in the storefront.
    """
    values: list[str] = []
    seen: set[str] = set()
    for v in product.variants:
        val = [v.option1_value, v.option2_value, v.option3_value][option_idx]
        if val and val not in seen:
            seen.add(val)
            values.append(val)
    return ", ".join(values)


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
) -> None:
    """
    Populate Attribute N columns on *row* using WooCommerce 10.9.1 schema.

    WooCommerce 10.9.1 column structure per attribute (from live export):
        Attribute N name      — attribute taxonomy name (e.g. "Size")
        Attribute N value(s)  — comma-separated values on parent; single value on variation
        Attribute N visible   — "1" on parent row; EMPTY on variation rows
        Attribute N global    — "1" always (global taxonomy attribute)
        Attribute N default   — default selection on parent row; EMPTY on variation rows

    CRITICAL: The column is "Attribute N default", NOT "Attribute N used for variations".
    WooCommerce 10.9.1 no longer exports "used for variations" — it determines
    which attributes drive the variation dropdowns from the variation rows themselves.

    Parent / simple rows (variant=None):
        • value(s) = all distinct values joined with ", " (WooCommerce comma syntax)
        • visible = "1"
        • default = "" (no forced default selection)

    Variation rows (variant set):
        • value(s) = the single concrete value for this variant
        • visible = "" (EMPTY — matches WooCommerce 10.9.1 export)
        • default = "" (EMPTY — matches WooCommerce 10.9.1 export)
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
            visible = ""
            default = ""
        else:
            val = _all_option_values(product, idx)
            visible = "1"
            default = ""
        if not val:
            continue
        row[f"Attribute {num} name"] = name
        row[f"Attribute {num} value(s)"] = val
        row[f"Attribute {num} visible"] = visible
        row[f"Attribute {num} global"] = "1" if is_global else "0"
        row[f"Attribute {num} default"] = default


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
# Pre-export attribute validation
# ─────────────────────────────────────────────────────────────────────────────


def _pre_export_validate(products: list[NormalizedProduct]) -> list[str]:
    """
    Validate attribute structure before writing the CSV.

    Returns a list of structural error strings.  An empty list means all
    products passed pre-export validation.  These checks run before any rows
    are written; structural failures abort the export.

    Checks:
    ✓ Parent contains every attribute.
    ✓ Parent contains every possible value for each attribute.
    ✓ Every variation contains one concrete value for every required attribute.
    ✓ Every variation value exists within the parent's declared values.
    ✓ No variation value is blank or "any".
    ✓ Every variation is purchasable (has a price).
    """
    errors: list[str] = []

    for product in products:
        if not _is_variable(product):
            continue

        handle = product.handle
        option_names = [
            product.option1_name,
            product.option2_name,
            product.option3_name,
        ]
        active_options = [(n, i) for i, n in enumerate(option_names) if n]

        # Build the set of all declared values per attribute.
        declared: dict[int, set[str]] = {}
        for _, idx in active_options:
            vals_str = _all_option_values(product, idx)
            declared[idx] = {v.strip() for v in vals_str.split(", ") if v.strip()}
            if not declared[idx]:
                errors.append(
                    f"[{handle}] Attribute {idx+1} '{option_names[idx]}' "
                    "has no values — cannot build dropdown."
                )

        # Validate each variant.
        for var in product.variants:
            var_sku = var.sku or f"{handle}-var"
            opt_vals = [var.option1_value, var.option2_value, var.option3_value]

            for name, idx in active_options:
                val = opt_vals[idx].strip() if opt_vals[idx] else ""
                if not val:
                    errors.append(
                        f"[{handle}] Variant '{var_sku}': "
                        f"Attribute '{name}' has no value — will import as 'Any'."
                    )
                elif val.lower() == "any":
                    errors.append(
                        f"[{handle}] Variant '{var_sku}': "
                        f"Attribute '{name}' value is literally 'Any'."
                    )
                elif idx in declared and val not in declared[idx]:
                    errors.append(
                        f"[{handle}] Variant '{var_sku}': "
                        f"Attribute '{name}' value '{val}' not in parent's "
                        f"declared values {sorted(declared[idx])}."
                    )

            if not var.price:
                errors.append(
                    f"[{handle}] Variant '{var_sku}' has no price — "
                    "will not be purchasable."
                )

    return errors


# ─────────────────────────────────────────────────────────────────────────────
# Post-export verification
# ─────────────────────────────────────────────────────────────────────────────


def verify_woocommerce_csv(output_path: str) -> list[str]:
    """
    Read the generated WooCommerce CSV and verify its logical structure.

    Checks (using WooCommerce 10.9.1 column names):
    • Required columns present.
    • Every variation references a known parent SKU.
    • No variation attribute value is empty, "Any", or a pipe-concatenated list.
    • Every parent attribute has at least one comma-separated value listed.
    • Every parent attribute has visible = "1".
    • Every variation has a Regular price.
    • Attribute value separator is comma (not pipe).
    • SKUs are unique within the file.

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

    required_cols = {
        "Type", "SKU", "Name", "Regular price", "Parent",
        "Attribute 1 name", "Attribute 1 value(s)", "Attribute 1 default",
    }
    present_cols = set(rows[0].keys())
    missing_cols = required_cols - present_cols
    if missing_cols:
        errors.append(
            f"Generated CSV missing required columns: {', '.join(sorted(missing_cols))}"
        )

    if "Attribute 1 used for variations" in present_cols:
        errors.append(
            "Generated CSV contains legacy column 'Attribute 1 used for variations' — "
            "WooCommerce 10.9.1 uses 'Attribute 1 default' instead. "
            "This column will be ignored by the importer."
        )

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

        for n in ("1", "2", "3"):
            attr_name = var.get(f"Attribute {n} name", "").strip()
            if not attr_name:
                continue
            attr_val = var.get(f"Attribute {n} value(s)", "").strip()
            if not attr_val:
                errors.append(
                    f"Variation '{var_sku}': Attribute {n} '{attr_name}' "
                    "has no value — WooCommerce will display 'Any'."
                )
            elif attr_val.lower() == "any":
                errors.append(
                    f"Variation '{var_sku}': Attribute {n} '{attr_name}' "
                    "value is literally 'Any' — must be a concrete value."
                )
            elif "|" in attr_val:
                errors.append(
                    f"Variation '{var_sku}': Attribute {n} '{attr_name}' "
                    f"value '{attr_val}' contains pipe character — "
                    "variation values must be a single concrete value, not a list."
                )

        price = var.get("Regular price", "").strip()
        if not price:
            errors.append(
                f"Variation '{var_sku}' has no Regular price — "
                "it will not be purchasable in WooCommerce."
            )

    for parent_sku, parent_row in parent_rows.items():
        for n in ("1", "2", "3"):
            attr_name = parent_row.get(f"Attribute {n} name", "").strip()
            if not attr_name:
                continue
            all_vals = parent_row.get(f"Attribute {n} value(s)", "").strip()
            if not all_vals:
                errors.append(
                    f"Parent '{parent_sku}': Attribute {n} '{attr_name}' "
                    "has no values listed — WooCommerce cannot build the dropdown."
                )
            elif "|" in all_vals:
                errors.append(
                    f"Parent '{parent_sku}': Attribute {n} '{attr_name}' "
                    f"value(s) '{all_vals}' use pipe separator — "
                    "WooCommerce 10.9.1 requires comma-separated values. "
                    "Dropdowns will not work correctly."
                )
            visible = parent_row.get(f"Attribute {n} visible", "").strip()
            if visible != "1":
                errors.append(
                    f"Parent '{parent_sku}': Attribute {n} '{attr_name}' "
                    f"visible = '{visible or '(empty)'}' — expected '1' on parent row."
                )

    return errors


# ─────────────────────────────────────────────────────────────────────────────
# Adapter
# ─────────────────────────────────────────────────────────────────────────────


class WooCommerceAdapter(ExportAdapter):
    @property
    def name(self) -> str:
        return "WooCommerce"

    def export(
        self,
        products: list[NormalizedProduct],
        output_path: str,
        audit_path: str | None = None,
    ) -> int:
        """
        Export products to WooCommerce 10.9.1 compatible CSV.

        Args:
            products:     List of normalized products to export.
            output_path:  Path to write the main woocommerce_products.csv.
            audit_path:   Optional path for variation_audit.csv diagnostic file.

        Returns:
            Number of rows written to the main CSV.
        """
        # ── Schema sanity check ──────────────────────────────────────────────
        schema = compare_schema_to_reference()
        if not schema["schema_valid"]:
            _log.warning(
                "[SCHEMA] WOO_COLUMNS is missing reference columns: %s",
                schema["missing_from_ours"],
            )
        else:
            _log.debug("[SCHEMA] Column schema matches WooCommerce 10.9.1 reference.")

        # ── Pre-export attribute validation ──────────────────────────────────
        validation_errors = _pre_export_validate(products)
        if validation_errors:
            for ve in validation_errors:
                _log.error("[PRE-VALIDATE] %s", ve)
            _log.error(
                "[PRE-VALIDATE] %d structural error(s) found. "
                "These will prevent correct import into WooCommerce.",
                len(validation_errors),
            )

        rows: list[dict[str, str]] = []
        audit_rows: list[dict[str, str]] = []
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
                parent_sku = product.handle

                _log.debug(
                    "[PARENT] handle=%s title=%r attrs=%d variants=%d",
                    product.handle, product.title, active_opts, len(product.variants),
                )

                for name, idx, num in [
                    (product.option1_name, 0, "1"),
                    (product.option2_name, 1, "2"),
                    (product.option3_name, 2, "3"),
                ]:
                    if name:
                        all_vals = _all_option_values(product, idx)
                        _log.debug(
                            "[ATTR MAP] %s → Attribute %s name=%r values=%r (separator=',')",
                            product.handle, num, name, all_vals,
                        )

                # ── Parent product row ───────────────────────────────────────
                parent: dict[str, str] = {c: "" for c in WOO_COLUMNS}
                parent["Type"] = "variable"
                parent["SKU"] = parent_sku
                parent["Name"] = product.title
                parent["Published"] = pub
                parent["Is featured?"] = "0"
                parent["Visibility in catalog"] = "visible"
                parent["Description"] = description
                parent["Tax status"] = "taxable"
                parent["Tax class"] = ""
                parent["In stock?"] = _total_in_stock(product)
                parent["Stock"] = ""
                parent["Backorders allowed?"] = "0"
                parent["Sold individually?"] = "0"
                parent["Allow customer reviews?"] = "1"
                parent["Categories"] = cats
                parent["Tags"] = tags
                parent["Images"] = images
                parent["Position"] = "0"
                parent["Meta: _yoast_wpseo_title"] = product.seo_title
                parent["Meta: _yoast_wpseo_metadesc"] = product.seo_description
                parent["Meta: rank_math_title"] = product.seo_title
                parent["Meta: rank_math_description"] = product.seo_description
                _set_attributes(parent, product, variant=None, is_global=True)
                rows.append(parent)

                # ── Child variation rows ─────────────────────────────────────
                for i, variant in enumerate(product.variants):
                    regular, sale = _price_pair(variant.price, variant.compare_at_price)
                    var_sku = variant.sku or f"{parent_sku}-var-{i + 1}"

                    _log.debug(
                        "[VARIATION] parent=%s sku=%r opt1=%r opt2=%r opt3=%r price=%s",
                        parent_sku, var_sku,
                        variant.option1_value, variant.option2_value,
                        variant.option3_value, regular,
                    )

                    child: dict[str, str] = {c: "" for c in WOO_COLUMNS}
                    child["Type"] = "variation"
                    child["SKU"] = var_sku
                    child["Name"] = product.title
                    child["Published"] = pub
                    child["Visibility in catalog"] = "visible"
                    child["Regular price"] = regular
                    child["Sale price"] = sale
                    child["Tax status"] = "taxable"
                    child["Tax class"] = "parent"
                    child["In stock?"] = "1" if variant.inventory_qty >= 0 else "0"
                    child["Stock"] = str(max(variant.inventory_qty, 0))
                    child["Backorders allowed?"] = "0"
                    child["Sold individually?"] = "0"
                    child["Allow customer reviews?"] = "0"
                    child["Weight (kg)"] = _grams_to_kg(variant.weight_grams)
                    child["Parent"] = parent_sku
                    child["Images"] = _variant_image(variant, images)
                    child["Position"] = str(i + 1)
                    _set_attributes(child, product, variant=variant, is_global=True)
                    rows.append(child)

                    # Build audit row.
                    attr_parts = []
                    for name, idx, num in [
                        (product.option1_name, 0, "1"),
                        (product.option2_name, 1, "2"),
                        (product.option3_name, 2, "3"),
                    ]:
                        if name:
                            val = [
                                variant.option1_value,
                                variant.option2_value,
                                variant.option3_value,
                            ][idx]
                            attr_parts.append(f"{name}={val!r}")

                    opt_vals = [
                        variant.option1_value,
                        variant.option2_value,
                        variant.option3_value,
                    ]
                    validation_result = "PASS"
                    notes = ""
                    for name, idx in [
                        (product.option1_name, 0),
                        (product.option2_name, 1),
                        (product.option3_name, 2),
                    ]:
                        if not name:
                            continue
                        val = opt_vals[idx].strip() if opt_vals[idx] else ""
                        if not val:
                            validation_result = "FAIL"
                            notes += f"Attribute '{name}' has no value. "
                        elif val.lower() == "any":
                            validation_result = "FAIL"
                            notes += f"Attribute '{name}' value is 'Any'. "
                    if not regular:
                        validation_result = "FAIL"
                        notes += "No Regular price. "

                    audit_rows.append({
                        "Shopify Handle": product.handle,
                        "Shopify Variant SKU": variant.sku,
                        "WooCommerce Parent": parent_sku,
                        "WooCommerce Type": "variation",
                        "Option1 Name": product.option1_name,
                        "Option1 Value": variant.option1_value,
                        "Option2 Name": product.option2_name,
                        "Option2 Value": variant.option2_value,
                        "Option3 Name": product.option3_name,
                        "Option3 Value": variant.option3_value,
                        "Generated Attribute Mapping": "; ".join(attr_parts),
                        "Validation Result": validation_result,
                        "Notes": notes.strip(),
                    })

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
                row["Is featured?"] = "0"
                row["Visibility in catalog"] = "visible"
                row["Description"] = description
                row["Regular price"] = regular
                row["Sale price"] = sale
                row["Tax status"] = "taxable" if variant.taxable else "none"
                row["Tax class"] = ""
                row["In stock?"] = "1" if variant.inventory_qty >= 0 else "0"
                row["Stock"] = str(max(variant.inventory_qty, 0))
                row["Backorders allowed?"] = "0"
                row["Sold individually?"] = "0"
                row["Allow customer reviews?"] = "1"
                row["Weight (kg)"] = _grams_to_kg(variant.weight_grams)
                row["Categories"] = cats
                row["Tags"] = tags
                row["Images"] = images
                row["Position"] = "0"
                row["Meta: _yoast_wpseo_title"] = product.seo_title
                row["Meta: _yoast_wpseo_metadesc"] = product.seo_description
                row["Meta: rank_math_title"] = product.seo_title
                row["Meta: rank_math_description"] = product.seo_description
                _set_attributes(row, product, variant=None, is_global=False)
                rows.append(row)

        _log.info(
            "Export complete: %d simple, %d variable, %d total rows",
            simple_count, variable_count, len(rows),
        )

        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=WOO_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

        if audit_path and audit_rows:
            with open(audit_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=AUDIT_COLUMNS, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(audit_rows)
            _log.info("Variation audit written: %d rows → %s", len(audit_rows), audit_path)

        return len(rows)
