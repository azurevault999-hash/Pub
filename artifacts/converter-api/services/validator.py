"""Validation engine for Shopify CSV data."""
from __future__ import annotations
import re
import pandas as pd
from bs4 import BeautifulSoup

from adapters.shopify import SHOPIFY_KNOWN_COLUMNS
from models.schemas import ValidationIssue, ValidationResult


def _str(val: object) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def _is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _has_malformed_html(html: str) -> bool:
    if not html:
        return False
    try:
        BeautifulSoup(html, "lxml")
        return False
    except Exception:
        return True


def validate(df: pd.DataFrame) -> ValidationResult:
    issues: list[ValidationIssue] = []

    handles = df.get("Handle", pd.Series(dtype=str)).apply(_str)
    skus = df.get("Variant SKU", pd.Series(dtype=str)).apply(_str)
    prices = df.get("Variant Price", pd.Series(dtype=str)).apply(_str)
    image_srcs = df.get("Image Src", pd.Series(dtype=str)).apply(_str)
    bodies = df.get("Body (HTML)", pd.Series(dtype=str)).apply(_str)

    # --- PASS checks ---

    # 1. Required columns present
    required = {"Handle", "Title", "Variant Price"}
    missing_cols = required - set(df.columns)
    if not missing_cols:
        issues.append(ValidationIssue(
            level="pass", check="Required Columns Present",
            message="All required columns (Handle, Title, Variant Price) are present.",
            count=0, details=[],
        ))
    else:
        issues.append(ValidationIssue(
            level="error", check="Required Columns Present",
            message=f"Missing required columns: {', '.join(sorted(missing_cols))}",
            count=len(missing_cols), details=list(sorted(missing_cols)),
        ))

    # 2. Handles present
    empty_handle_rows = int((handles == "").sum())
    if empty_handle_rows == 0:
        issues.append(ValidationIssue(
            level="pass", check="Handles Present",
            message="All rows have a Handle value.",
            count=0, details=[],
        ))
    else:
        issues.append(ValidationIssue(
            level="error", check="Handles Present",
            message=f"{empty_handle_rows} row(s) are missing a Handle value.",
            count=empty_handle_rows, details=[],
        ))

    # --- DUPLICATE checks ---

    # 3. Duplicate SKUs
    non_empty_skus = skus[skus != ""]
    dup_skus = non_empty_skus[non_empty_skus.duplicated()].tolist()
    dup_sku_vals = list(dict.fromkeys(dup_skus))[:20]
    if not dup_sku_vals:
        issues.append(ValidationIssue(
            level="pass", check="Duplicate SKUs",
            message="No duplicate SKUs found.",
            count=0, details=[],
        ))
    else:
        issues.append(ValidationIssue(
            level="error", check="Duplicate SKUs",
            message=f"{len(dup_sku_vals)} duplicate SKU(s) detected. WooCommerce requires unique SKUs.",
            count=len(dup_sku_vals), details=dup_sku_vals,
        ))

    # 4. Duplicate handles (informational warning)
    first_occurrence_handles = handles[handles != ""].drop_duplicates(keep="first")
    all_nonempty = handles[handles != ""]
    dup_handle_count = len(all_nonempty) - len(first_occurrence_handles)
    if dup_handle_count == 0:
        issues.append(ValidationIssue(
            level="pass", check="Duplicate Handles",
            message="Each product handle appears only once (no multi-row products detected as duplicates).",
            count=0, details=[],
        ))
    else:
        issues.append(ValidationIssue(
            level="pass", check="Duplicate Handles",
            message=f"{dup_handle_count} multi-row handle(s) — normal for products with variants or multiple images.",
            count=dup_handle_count, details=[],
        ))

    # 5. Duplicate images within a product
    dup_image_details: list[str] = []
    for handle_val, group in df.groupby("Handle"):
        srcs = group.get("Image Src", pd.Series(dtype=str)).apply(_str)
        non_empty = srcs[srcs != ""]
        dups = non_empty[non_empty.duplicated()].tolist()
        if dups:
            dup_image_details.append(f"{_str(handle_val)}: {', '.join(dict.fromkeys(dups))}")
    if not dup_image_details:
        issues.append(ValidationIssue(
            level="pass", check="Duplicate Images",
            message="No duplicate image URLs found within any product.",
            count=0, details=[],
        ))
    else:
        issues.append(ValidationIssue(
            level="warning", check="Duplicate Images",
            message=f"{len(dup_image_details)} product(s) have duplicate image URLs.",
            count=len(dup_image_details), details=dup_image_details[:20],
        ))

    # --- PRICE checks ---

    # 6. Missing prices
    missing_price_rows = int((prices == "").sum())
    if missing_price_rows == 0:
        issues.append(ValidationIssue(
            level="pass", check="Missing Prices",
            message="All rows have a Variant Price.",
            count=0, details=[],
        ))
    else:
        missing_price_handles = handles[prices == ""].tolist()[:20]
        issues.append(ValidationIssue(
            level="error", check="Missing Prices",
            message=f"{missing_price_rows} row(s) have no Variant Price.",
            count=missing_price_rows, details=missing_price_handles,
        ))

    # 7. Negative prices
    negative_price_details: list[str] = []
    for i, p in enumerate(prices):
        if p:
            try:
                if float(p) < 0:
                    negative_price_details.append(f"Row {i+2}: {p}")
            except ValueError:
                pass
    if not negative_price_details:
        issues.append(ValidationIssue(
            level="pass", check="Negative Prices",
            message="No negative prices detected.",
            count=0, details=[],
        ))
    else:
        issues.append(ValidationIssue(
            level="error", check="Negative Prices",
            message=f"{len(negative_price_details)} row(s) have negative prices.",
            count=len(negative_price_details), details=negative_price_details[:20],
        ))

    # --- VARIATION checks ---

    # 8. Missing option values for variant rows
    opt1_name = df.get("Option1 Name", pd.Series(dtype=str)).apply(_str)
    opt1_val = df.get("Option1 Value", pd.Series(dtype=str)).apply(_str)
    missing_opt_details: list[str] = []
    for i, (name, val, handle_val) in enumerate(zip(opt1_name, opt1_val, handles)):
        if name and not val:
            missing_opt_details.append(f"Row {i+2} (handle: {handle_val}): Option1 Name={name!r} but no value")
    if not missing_opt_details:
        issues.append(ValidationIssue(
            level="pass", check="Missing Option Values",
            message="All option names have corresponding values.",
            count=0, details=[],
        ))
    else:
        issues.append(ValidationIssue(
            level="warning", check="Missing Option Values",
            message=f"{len(missing_opt_details)} row(s) have an option name but no option value.",
            count=len(missing_opt_details), details=missing_opt_details[:20],
        ))

    # 9. Duplicate variations within a product
    dup_variation_details: list[str] = []
    for handle_val, group in df.groupby("Handle"):
        if len(group) <= 1:
            continue
        combos = (
            group.get("Option1 Value", pd.Series(dtype=str)).apply(_str) + "|" +
            group.get("Option2 Value", pd.Series(dtype=str)).apply(_str) + "|" +
            group.get("Option3 Value", pd.Series(dtype=str)).apply(_str)
        )
        non_empty_combos = combos[combos != "||"]
        if non_empty_combos.duplicated().any():
            dup_variation_details.append(_str(handle_val))
    if not dup_variation_details:
        issues.append(ValidationIssue(
            level="pass", check="Duplicate Variations",
            message="No duplicate attribute combinations found.",
            count=0, details=[],
        ))
    else:
        issues.append(ValidationIssue(
            level="warning", check="Duplicate Variations",
            message=f"{len(dup_variation_details)} product(s) have duplicate variation combinations.",
            count=len(dup_variation_details), details=dup_variation_details[:20],
        ))

    # --- IMAGE checks ---

    # 10. Missing images (products with no image)
    unique_handles_set = set(handles[handles != ""])
    handles_with_images = set(
        _str(h) for h, src in zip(handles, image_srcs) if _str(src)
    )
    no_image_products = unique_handles_set - handles_with_images
    if not no_image_products:
        issues.append(ValidationIssue(
            level="pass", check="Missing Images",
            message="All products have at least one image.",
            count=0, details=[],
        ))
    else:
        detail_list = sorted(no_image_products)[:20]
        issues.append(ValidationIssue(
            level="warning", check="Missing Images",
            message=f"{len(no_image_products)} product(s) have no images.",
            count=len(no_image_products), details=detail_list,
        ))

    # 11. Broken image URLs
    broken_image_details: list[str] = []
    for src in image_srcs[image_srcs != ""].unique():
        if not _is_url(src):
            broken_image_details.append(src)
    if not broken_image_details:
        issues.append(ValidationIssue(
            level="pass", check="Broken Image URLs",
            message="All image URLs appear to be valid HTTP(S) URLs.",
            count=0, details=[],
        ))
    else:
        issues.append(ValidationIssue(
            level="warning", check="Broken Image URLs",
            message=f"{len(broken_image_details)} image URL(s) are not valid HTTP(S) URLs.",
            count=len(broken_image_details), details=broken_image_details[:20],
        ))

    # --- HTML checks ---

    # 12. Malformed HTML
    malformed_bodies: list[str] = []
    for handle_val, group in df.groupby("Handle"):
        body = _str(group.iloc[0].get("Body (HTML)", ""))
        if body and _has_malformed_html(body):
            malformed_bodies.append(_str(handle_val))
    if not malformed_bodies:
        issues.append(ValidationIssue(
            level="pass", check="Malformed HTML",
            message="All product descriptions have valid HTML.",
            count=0, details=[],
        ))
    else:
        issues.append(ValidationIssue(
            level="warning", check="Malformed HTML",
            message=f"{len(malformed_bodies)} product(s) have malformed HTML descriptions.",
            count=len(malformed_bodies), details=malformed_bodies[:20],
        ))

    # --- COLUMN checks ---

    # 13. Unknown columns
    unknown_cols = [c for c in df.columns if c not in SHOPIFY_KNOWN_COLUMNS]
    if not unknown_cols:
        issues.append(ValidationIssue(
            level="pass", check="Unknown Columns",
            message="All columns are recognised Shopify export columns.",
            count=0, details=[],
        ))
    else:
        issues.append(ValidationIssue(
            level="warning", check="Unknown Columns",
            message=f"{len(unknown_cols)} unknown column(s) will be ignored during conversion.",
            count=len(unknown_cols), details=unknown_cols,
        ))

    # 14. Empty products (handle with no title)
    titles = df.get("Title", pd.Series(dtype=str)).apply(_str)
    empty_product_details: list[str] = []
    for handle_val, group in df.groupby("Handle"):
        first_title = _str(group.iloc[0].get("Title", ""))
        if not first_title:
            empty_product_details.append(_str(handle_val))
    if not empty_product_details:
        issues.append(ValidationIssue(
            level="pass", check="Empty Products",
            message="All products have a title.",
            count=0, details=[],
        ))
    else:
        issues.append(ValidationIssue(
            level="error", check="Empty Products",
            message=f"{len(empty_product_details)} product(s) are missing a Title.",
            count=len(empty_product_details), details=empty_product_details[:20],
        ))

    # --- Counts ---
    pass_count = sum(1 for i in issues if i.level == "pass")
    warning_count = sum(1 for i in issues if i.level == "warning")
    error_count = sum(1 for i in issues if i.level == "error")
    can_convert = error_count == 0

    return ValidationResult(
        issues=issues,
        pass_count=pass_count,
        warning_count=warning_count,
        error_count=error_count,
        can_convert=can_convert,
    )
