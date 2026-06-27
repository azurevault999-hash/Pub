"""
Validation engine for Shopify CSV data.

Severity levels
───────────────
error   — Blocks conversion.  Genuine structural failures only.
warning — Conversion continues but output may be imperfect.
info    — Purely informational; does not affect conversion quality.
pass    — Check ran and found no issues.
"""
from __future__ import annotations

import pandas as pd

from models.schemas import ValidationIssue, ValidationResult
from services.utils import _str, _is_url, _has_malformed_html
from adapters.shopify import SHOPIFY_KNOWN_COLUMNS


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _issue(
    level: str,
    check: str,
    message: str,
    count: int = 0,
    details: list[str] | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        level=level,  # type: ignore[arg-type]
        check=check,
        message=message,
        count=count,
        details=(details or [])[:20],
    )


def _pass(check: str, message: str) -> ValidationIssue:
    return _issue("pass", check, message)


def _info(check: str, message: str, count: int = 0, details: list[str] | None = None) -> ValidationIssue:
    return _issue("info", check, message, count, details)


def _warn(check: str, message: str, count: int = 0, details: list[str] | None = None) -> ValidationIssue:
    return _issue("warning", check, message, count, details)


def _error(check: str, message: str, count: int = 0, details: list[str] | None = None) -> ValidationIssue:
    return _issue("error", check, message, count, details)


# ─────────────────────────────────────────────────────────────────────────────
# Main validation function
# ─────────────────────────────────────────────────────────────────────────────

def validate(df: pd.DataFrame) -> ValidationResult:  # noqa: C901
    issues: list[ValidationIssue] = []

    # Pre-compute column series (avoid repeated attribute access)
    handles = df.get("Handle", pd.Series(dtype=str)).apply(_str)
    titles = df.get("Title", pd.Series(dtype=str)).apply(_str)
    skus = df.get("Variant SKU", pd.Series(dtype=str)).apply(_str)
    prices = df.get("Variant Price", pd.Series(dtype=str)).apply(_str)
    image_srcs = df.get("Image Src", pd.Series(dtype=str)).apply(_str)
    variant_images = df.get("Variant Image", pd.Series(dtype=str)).apply(_str)
    opt1_names = df.get("Option1 Name", pd.Series(dtype=str)).apply(_str)
    opt1_vals = df.get("Option1 Value", pd.Series(dtype=str)).apply(_str)
    opt2_vals = df.get("Option2 Value", pd.Series(dtype=str)).apply(_str)
    opt3_vals = df.get("Option3 Value", pd.Series(dtype=str)).apply(_str)
    bodies = df.get("Body (HTML)", pd.Series(dtype=str)).apply(_str)
    vendors = df.get("Vendor", pd.Series(dtype=str)).apply(_str)
    tags_col = df.get("Tags", pd.Series(dtype=str)).apply(_str)
    seo_titles = df.get("SEO Title", pd.Series(dtype=str)).apply(_str)
    seo_descs = df.get("SEO Description", pd.Series(dtype=str)).apply(_str)
    barcodes = df.get("Variant Barcode", pd.Series(dtype=str)).apply(_str)
    weights = df.get("Variant Grams", pd.Series(dtype=str)).apply(_str)

    # Identify variant rows (rows that carry actual variant data, not image-only rows)
    is_variant_row = prices.ne("") | opt1_vals.ne("") | opt2_vals.ne("") | opt3_vals.ne("")

    # Pre-compute per-handle group data in a single pass
    unique_handles: set[str] = set()
    handle_to_first_title: dict[str, str] = {}
    handle_to_images: dict[str, set[str]] = {}
    handle_to_variant_images: dict[str, set[str]] = {}
    handle_to_dup_image_details: list[str] = []
    handle_to_dup_variation_details: list[str] = []
    handle_to_malformed_html: list[str] = []
    handle_to_no_tags: list[str] = []
    handle_to_no_vendor: list[str] = []
    handle_to_no_seo: list[str] = []

    for handle_val, group in df.groupby("Handle", sort=False):
        h = _str(handle_val)
        if not h:
            continue
        unique_handles.add(h)
        first = group.iloc[0]

        # Title (first occurrence)
        handle_to_first_title[h] = _str(first.get("Title", ""))

        # Image Src collection (de-duplicated per handle)
        srcs_in_group = group.get("Image Src", pd.Series(dtype=str)).apply(_str)
        nonempty_srcs = srcs_in_group[srcs_in_group != ""]
        handle_to_images[h] = set(nonempty_srcs.tolist())

        # Duplicate images within the same product
        dup_srcs = nonempty_srcs[nonempty_srcs.duplicated()].tolist()
        if dup_srcs:
            handle_to_dup_image_details.append(f"{h}: {', '.join(dict.fromkeys(dup_srcs))}")

        # Variant Image column (for variant image coverage check)
        vi_in_group = group.get("Variant Image", pd.Series(dtype=str)).apply(_str)
        handle_to_variant_images[h] = set(vi_in_group[vi_in_group != ""].tolist())

        # Duplicate variation combinations
        if len(group) > 1:
            combos = (
                group.get("Option1 Value", pd.Series(dtype=str)).apply(_str) + "|" +
                group.get("Option2 Value", pd.Series(dtype=str)).apply(_str) + "|" +
                group.get("Option3 Value", pd.Series(dtype=str)).apply(_str)
            )
            non_empty_combos = combos[combos != "||"]
            if non_empty_combos.duplicated().any():
                handle_to_dup_variation_details.append(h)

        # Malformed HTML (first row body only)
        body = _str(first.get("Body (HTML)", ""))
        if body and _has_malformed_html(body):
            handle_to_malformed_html.append(h)

        # Missing metadata (per-product, from first row)
        tags_val = _str(first.get("Tags", ""))
        if not tags_val:
            handle_to_no_tags.append(h)

        vendor_val = _str(first.get("Vendor", ""))
        if not vendor_val:
            handle_to_no_vendor.append(h)

        seo_t = _str(first.get("SEO Title", ""))
        seo_d = _str(first.get("SEO Description", ""))
        if not seo_t and not seo_d:
            handle_to_no_seo.append(h)

    # ─── 1. Required columns ───────────────────────────────────────────────
    # Handle and Title are structurally required; missing them means we cannot
    # build any output.  Variant Price is optional (some export formats omit it).
    truly_required = {"Handle", "Title"}
    missing_required = truly_required - set(df.columns)
    if missing_required:
        issues.append(_error(
            "Required Columns",
            f"Missing required columns: {', '.join(sorted(missing_required))}. "
            "Cannot proceed without Handle and Title.",
            count=len(missing_required),
            details=sorted(missing_required),
        ))
    else:
        issues.append(_pass("Required Columns", "Handle and Title columns are present."))

    # ─── 2. Empty handles ──────────────────────────────────────────────────
    empty_handle_count = int((handles == "").sum())
    if empty_handle_count:
        issues.append(_error(
            "Empty Handles",
            f"{empty_handle_count} row(s) have no Handle value. "
            "Rows without a Handle cannot be associated with any product.",
            count=empty_handle_count,
        ))
    else:
        issues.append(_pass("Empty Handles", "Every row has a Handle value."))

    # ─── 3. Empty product titles ───────────────────────────────────────────
    no_title = [h for h, t in handle_to_first_title.items() if not t]
    if no_title:
        issues.append(_error(
            "Missing Title",
            f"{len(no_title)} product(s) have no Title. "
            "WooCommerce requires a product Name.",
            count=len(no_title),
            details=no_title,
        ))
    else:
        issues.append(_pass("Missing Title", "All products have a Title."))

    # ─── 4. Duplicate SKUs ────────────────────────────────────────────────
    # WARNING (not ERROR): WooCommerce requires unique SKUs for a clean import,
    # but the conversion itself can proceed; the importer will reject duplicates.
    non_empty_skus = skus[skus != ""]
    dup_sku_vals = list(dict.fromkeys(non_empty_skus[non_empty_skus.duplicated()].tolist()))
    if dup_sku_vals:
        issues.append(_warn(
            "Duplicate SKUs",
            f"{len(dup_sku_vals)} SKU(s) appear more than once. "
            "WooCommerce requires unique SKUs; duplicate rows will be rejected on import.",
            count=len(dup_sku_vals),
            details=dup_sku_vals,
        ))
    else:
        issues.append(_pass("Duplicate SKUs", "No duplicate SKUs found."))

    # ─── 5. Duplicate images within a product ─────────────────────────────
    if handle_to_dup_image_details:
        issues.append(_warn(
            "Duplicate Image URLs",
            f"{len(handle_to_dup_image_details)} product(s) have duplicate Image Src URLs. "
            "Duplicates will be omitted in the WooCommerce gallery.",
            count=len(handle_to_dup_image_details),
            details=handle_to_dup_image_details,
        ))
    else:
        issues.append(_pass("Duplicate Image URLs", "No duplicate image URLs within any product."))

    # ─── 6. Missing prices on variant rows ────────────────────────────────
    # Only flag rows that are genuine variant rows (have option/price data).
    # Image-only rows legitimately have no Variant Price.
    variant_prices = prices[is_variant_row]
    missing_price_count = int((variant_prices == "").sum())
    if missing_price_count:
        missing_price_handles = list(dict.fromkeys(
            handles[is_variant_row & prices.eq("")].tolist()
        ))[:20]
        issues.append(_warn(
            "Missing Variant Price",
            f"{missing_price_count} variant row(s) have no Variant Price. "
            "WooCommerce requires a Regular price for all products and variations.",
            count=missing_price_count,
            details=missing_price_handles,
        ))
    else:
        issues.append(_pass("Missing Variant Price", "All variant rows have a Variant Price."))

    # ─── 7. Negative prices ───────────────────────────────────────────────
    negative_details: list[str] = []
    for i, p in enumerate(prices):
        if p:
            try:
                if float(p) < 0:
                    negative_details.append(f"Row {i + 2}: {p}")
            except ValueError:
                pass
    if negative_details:
        issues.append(_error(
            "Negative Prices",
            f"{len(negative_details)} row(s) have negative prices. "
            "Negative prices are not valid in WooCommerce.",
            count=len(negative_details),
            details=negative_details,
        ))
    else:
        issues.append(_pass("Negative Prices", "No negative prices detected."))

    # ─── 8. Missing option values ─────────────────────────────────────────
    missing_opt: list[str] = []
    for i, (name, val, h) in enumerate(zip(opt1_names, opt1_vals, handles)):
        if name and not val:
            missing_opt.append(f"Row {i + 2} ({h}): Option1 Name={name!r} has no value")
    if missing_opt:
        issues.append(_warn(
            "Missing Option Values",
            f"{len(missing_opt)} row(s) have an Option1 Name but no Option1 Value.",
            count=len(missing_opt),
            details=missing_opt,
        ))
    else:
        issues.append(_pass("Missing Option Values", "All Option Names have corresponding values."))

    # ─── 9. Duplicate variation combinations ──────────────────────────────
    if handle_to_dup_variation_details:
        issues.append(_warn(
            "Duplicate Variations",
            f"{len(handle_to_dup_variation_details)} product(s) have duplicate attribute "
            "combinations. WooCommerce will reject variation duplicates on import.",
            count=len(handle_to_dup_variation_details),
            details=handle_to_dup_variation_details,
        ))
    else:
        issues.append(_pass("Duplicate Variations", "No duplicate attribute combinations found."))

    # ─── 10. Missing product images ───────────────────────────────────────
    no_image_handles = sorted(
        h for h in unique_handles if not handle_to_images.get(h)
    )
    if no_image_handles:
        issues.append(_warn(
            "Missing Product Images",
            f"{len(no_image_handles)} product(s) have no Image Src. "
            "WooCommerce products without images may display poorly.",
            count=len(no_image_handles),
            details=no_image_handles,
        ))
    else:
        issues.append(_pass("Missing Product Images", "All products have at least one image."))

    # ─── 11. Broken image URLs ────────────────────────────────────────────
    broken_urls = [src for src in image_srcs[image_srcs != ""].unique() if not _is_url(src)]
    if broken_urls:
        issues.append(_warn(
            "Invalid Image URLs",
            f"{len(broken_urls)} image URL(s) are not valid HTTP(S) URLs "
            "and will not load in WooCommerce.",
            count=len(broken_urls),
            details=broken_urls,
        ))
    else:
        issues.append(_pass("Invalid Image URLs", "All image URLs are valid HTTP(S) URLs."))

    # ─── 12. Variant Image coverage ───────────────────────────────────────
    # Rule (per spec):
    #   Variant Image blank + Image Src exists  → INFO (product images used as fallback)
    #   Both Variant Image and Image Src blank  → ERROR (no image for that variation)
    no_var_image_handles: list[str] = []
    no_image_at_all_handles: list[str] = []
    for h in unique_handles:
        has_variant_img = bool(handle_to_variant_images.get(h))
        has_product_img = bool(handle_to_images.get(h))
        if not has_variant_img and not has_product_img:
            no_image_at_all_handles.append(h)
        elif not has_variant_img and has_product_img:
            no_var_image_handles.append(h)

    if no_image_at_all_handles:
        issues.append(_error(
            "Variant Image — No Images at All",
            f"{len(no_image_at_all_handles)} product(s) have neither a Variant Image nor "
            "an Image Src. WooCommerce variations require at least one image.",
            count=len(no_image_at_all_handles),
            details=sorted(no_image_at_all_handles),
        ))
    elif no_var_image_handles:
        issues.append(_info(
            "Variant Image — Using Product Images",
            f"{len(no_var_image_handles)} product(s) have no Variant Image; "
            "the product's Image Src list will be used instead.",
            count=len(no_var_image_handles),
            details=sorted(no_var_image_handles),
        ))
    else:
        issues.append(_pass(
            "Variant Image Coverage",
            "All products have Variant Image or Image Src coverage.",
        ))

    # ─── 13. Malformed HTML ───────────────────────────────────────────────
    if handle_to_malformed_html:
        issues.append(_warn(
            "Malformed HTML",
            f"{len(handle_to_malformed_html)} product(s) have potentially malformed "
            "HTML in their description. Review before importing.",
            count=len(handle_to_malformed_html),
            details=handle_to_malformed_html,
        ))
    else:
        issues.append(_pass("Malformed HTML", "All product descriptions appear to have valid HTML."))

    # ─── 14. Unknown columns (INFO) ───────────────────────────────────────
    unknown_cols = [c for c in df.columns if c not in SHOPIFY_KNOWN_COLUMNS]
    if unknown_cols:
        issues.append(_info(
            "Unknown Columns",
            f"{len(unknown_cols)} column(s) are not standard Shopify export columns "
            "and will be ignored during conversion.",
            count=len(unknown_cols),
            details=unknown_cols,
        ))
    else:
        issues.append(_pass("Unknown Columns", "All columns are recognised Shopify export columns."))

    # ─── 15. Multi-row handles (INFO) ─────────────────────────────────────
    nonempty_handles = handles[handles != ""]
    multi_row_count = len(nonempty_handles) - len(nonempty_handles.drop_duplicates(keep="first"))
    if multi_row_count:
        issues.append(_info(
            "Multi-row Products",
            f"{multi_row_count} additional row(s) belong to multi-row products "
            "(products with variants or multiple images). This is normal Shopify format.",
            count=multi_row_count,
        ))
    else:
        issues.append(_pass("Multi-row Products", "Each product handle appears exactly once."))

    # ─── 16. Missing tags (INFO) ──────────────────────────────────────────
    if handle_to_no_tags:
        issues.append(_info(
            "Missing Tags",
            f"{len(handle_to_no_tags)} product(s) have no Tags. "
            "Tags are optional but help with WooCommerce discoverability.",
            count=len(handle_to_no_tags),
            details=handle_to_no_tags[:20],
        ))
    else:
        issues.append(_pass("Missing Tags", "All products have at least one tag."))

    # ─── 17. Missing vendor (INFO) ────────────────────────────────────────
    if handle_to_no_vendor:
        issues.append(_info(
            "Missing Vendor",
            f"{len(handle_to_no_vendor)} product(s) have no Vendor. "
            "Vendor is not exported to WooCommerce natively.",
            count=len(handle_to_no_vendor),
        ))
    else:
        issues.append(_pass("Missing Vendor", "All products have a Vendor."))

    # ─── 18. Missing SEO fields (INFO) ────────────────────────────────────
    if handle_to_no_seo:
        issues.append(_info(
            "Missing SEO Fields",
            f"{len(handle_to_no_seo)} product(s) have neither SEO Title nor SEO Description. "
            "SEO meta will be empty in WooCommerce (Yoast/Rank Math).",
            count=len(handle_to_no_seo),
            details=handle_to_no_seo[:20],
        ))
    else:
        issues.append(_pass("Missing SEO Fields", "All products have SEO Title or SEO Description."))

    # ─── Counts & result ──────────────────────────────────────────────────
    pass_count = sum(1 for i in issues if i.level == "pass")
    info_count = sum(1 for i in issues if i.level == "info")
    warning_count = sum(1 for i in issues if i.level == "warning")
    error_count = sum(1 for i in issues if i.level == "error")

    # Only genuine structural ERRORs block conversion (not warnings).
    can_convert = error_count == 0

    return ValidationResult(
        issues=issues,
        pass_count=pass_count,
        info_count=info_count,
        warning_count=warning_count,
        error_count=error_count,
        can_convert=can_convert,
    )
