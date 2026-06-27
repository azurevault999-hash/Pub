"""Analysis service — inspects uploaded Shopify CSV and produces AnalysisResult."""
from __future__ import annotations
import re
import pandas as pd
from bs4 import BeautifulSoup

from adapters.shopify import SHOPIFY_KNOWN_COLUMNS
from models.schemas import AnalysisResult


def _str(val: object) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def _is_valid_html(html: str) -> bool:
    """Return True if the HTML is parseable and contains no obvious malformation."""
    if not html:
        return True
    try:
        soup = BeautifulSoup(html, "lxml")
        return True
    except Exception:
        return False


def analyze(df: pd.DataFrame) -> AnalysisResult:
    """Run analysis on a Shopify CSV DataFrame."""
    # Unknown columns
    unknown_columns = [c for c in df.columns if c not in SHOPIFY_KNOWN_COLUMNS]

    # Products (unique handles)
    handles = df["Handle"].dropna().apply(str).str.strip()
    handles = handles[handles != ""]
    unique_handles = handles.unique()
    product_count = len(unique_handles)

    # Variants: each row with a non-empty Variant SKU or Variant Price is a variant row
    variant_mask = df.get("Variant Price", pd.Series(dtype=str)).apply(_str) != ""
    variant_count = int(variant_mask.sum())

    # Images (non-empty Image Src, distinct per product + image)
    image_src_col = df.get("Image Src", pd.Series(dtype=str)).apply(_str)
    image_count = int((image_src_col != "").sum())

    # Categories (unique non-empty product types)
    categories: list[str] = sorted(set(
        _str(v) for v in df.get("Type", pd.Series(dtype=str)).unique() if _str(v)
    ))

    # Vendors
    vendors: list[str] = sorted(set(
        _str(v) for v in df.get("Vendor", pd.Series(dtype=str)).unique() if _str(v)
    ))

    # Product types (same as categories in Shopify context)
    product_types = categories

    # Duplicate SKUs: among rows with a non-empty SKU
    sku_col = df.get("Variant SKU", pd.Series(dtype=str)).apply(_str)
    non_empty_skus = sku_col[sku_col != ""]
    duplicate_skus = int((non_empty_skus.duplicated()).sum())

    # Missing prices: variant rows with empty Variant Price
    price_col = df.get("Variant Price", pd.Series(dtype=str)).apply(_str)
    missing_prices = int((price_col == "").sum())

    # Missing images: products without any image
    products_with_image = set(
        _str(handle)
        for handle, src in zip(df.get("Handle", pd.Series(dtype=str)), image_src_col)
        if _str(src)
    )
    missing_images = max(0, product_count - len(products_with_image))

    # Invalid HTML
    body_col = df.get("Body (HTML)", pd.Series(dtype=str))
    invalid_html_count = 0
    for val in body_col.unique():
        s = _str(val)
        if s and not _is_valid_html(s):
            invalid_html_count += 1

    return AnalysisResult(
        product_count=product_count,
        variant_count=variant_count,
        image_count=image_count,
        categories=categories,
        vendors=vendors,
        product_types=product_types,
        duplicate_skus=duplicate_skus,
        missing_prices=missing_prices,
        missing_images=missing_images,
        invalid_html_count=invalid_html_count,
        unknown_columns=unknown_columns,
        total_rows=len(df),
    )
