"""Shopify CSV import adapter."""
from __future__ import annotations

import chardet
import pandas as pd

from adapters.base import ImportAdapter, NormalizedProduct, NormalizedVariant
from services.utils import _str, _bool, _float, _int

SHOPIFY_KNOWN_COLUMNS = {
    "Handle", "Title", "Body (HTML)", "Vendor", "Product Category", "Type",
    "Tags", "Published", "Option1 Name", "Option1 Value", "Option2 Name",
    "Option2 Value", "Option3 Name", "Option3 Value", "Variant SKU",
    "Variant Grams", "Variant Inventory Tracker", "Variant Inventory Qty",
    "Variant Inventory Policy", "Variant Fulfillment Service", "Variant Price",
    "Variant Compare At Price", "Variant Requires Shipping", "Variant Taxable",
    "Variant Barcode", "Image Src", "Image Position", "Image Alt Text",
    "Gift Card", "SEO Title", "SEO Description",
    "Google Shopping / Google Product Category", "Google Shopping / Gender",
    "Google Shopping / Age Group", "Google Shopping / MPN",
    "Google Shopping / Condition", "Google Shopping / Custom Product",
    "Google Shopping / Custom Label 0", "Google Shopping / Custom Label 1",
    "Google Shopping / Custom Label 2", "Google Shopping / Custom Label 3",
    "Google Shopping / Custom Label 4", "Variant Image", "Variant Weight Unit",
    "Variant Tax Code", "Cost per item", "Status",
    "Included / United States", "Price / United States",
    "Compare At Price / United States",
}


def _detect_encoding(filepath: str) -> str:
    with open(filepath, "rb") as f:
        raw = f.read(32768)
    result = chardet.detect(raw)
    enc = result.get("encoding") or "utf-8"
    if enc.lower() in ("utf-8-sig", "utf-8"):
        return "utf-8-sig"
    return enc


def _is_variant_row(row: pd.Series) -> bool:
    """
    Return True if *row* carries variant data (price or option values present).

    Shopify exports additional image rows for products with multiple images.
    These rows have Handle and Image Src but no Variant Price and no Option
    values.  Including them as variants creates phantom/empty variations.
    """
    price = _str(row.get("Variant Price", ""))
    opt1 = _str(row.get("Option1 Value", ""))
    opt2 = _str(row.get("Option2 Value", ""))
    opt3 = _str(row.get("Option3 Value", ""))
    return bool(price or opt1 or opt2 or opt3)


class ShopifyAdapter(ImportAdapter):
    @property
    def name(self) -> str:
        return "Shopify"

    @property
    def supported_columns(self) -> list[str]:
        return list(SHOPIFY_KNOWN_COLUMNS)

    def read(self, filepath: str) -> pd.DataFrame:
        enc = _detect_encoding(filepath)
        df = pd.read_csv(filepath, encoding=enc, keep_default_na=False, dtype=str)
        df.columns = [c.strip() for c in df.columns]
        return df

    def unknown_columns(self, df: pd.DataFrame) -> list[str]:
        return [c for c in df.columns if c not in SHOPIFY_KNOWN_COLUMNS]

    def normalize(self, df: pd.DataFrame) -> list[NormalizedProduct]:
        """Group rows by Handle and build NormalizedProduct objects."""
        products: list[NormalizedProduct] = []

        for handle, group in df.groupby("Handle", sort=False):
            handle = _str(handle)
            if not handle:
                continue

            first = group.iloc[0]

            opt1_name = _str(first.get("Option1 Name", ""))
            opt2_name = _str(first.get("Option2 Name", ""))
            opt3_name = _str(first.get("Option3 Name", ""))

            # Collect images from all rows (de-duplicated, sorted by position)
            images: list[tuple[str, int, str]] = []
            image_srcs_seen: set[str] = set()
            for _, row in group.iterrows():
                src = _str(row.get("Image Src", ""))
                if src and src not in image_srcs_seen:
                    image_srcs_seen.add(src)
                    pos = _int(row.get("Image Position", ""), 0)
                    alt = _str(row.get("Image Alt Text", ""))
                    images.append((src, pos, alt))
            images.sort(key=lambda x: x[1])

            # Build variants — skip image-only rows that carry no variant data
            variants: list[NormalizedVariant] = []
            for _, row in group.iterrows():
                if not _is_variant_row(row):
                    continue

                sku = _str(row.get("Variant SKU", ""))
                price = _str(row.get("Variant Price", ""))
                cap = _str(row.get("Variant Compare At Price", ""))
                grams = _float(row.get("Variant Grams", ""), 0.0)
                qty = _int(row.get("Variant Inventory Qty", ""), 0)
                taxable = _bool(row.get("Variant Taxable", "true"))
                barcode = _str(row.get("Variant Barcode", ""))
                variant_image = _str(row.get("Variant Image", ""))
                requires_shipping = _bool(row.get("Variant Requires Shipping", "true"))
                opt1_val = _str(row.get("Option1 Value", ""))
                opt2_val = _str(row.get("Option2 Value", ""))
                opt3_val = _str(row.get("Option3 Value", ""))

                variants.append(NormalizedVariant(
                    sku=sku,
                    option1_value=opt1_val,
                    option2_value=opt2_val,
                    option3_value=opt3_val,
                    price=price,
                    compare_at_price=cap,
                    weight_grams=grams,
                    inventory_qty=qty,
                    taxable=taxable,
                    barcode=barcode,
                    image_src=variant_image,
                    requires_shipping=requires_shipping,
                ))

            # Shopify always has at least one variant row per product.
            # If somehow all rows were image-only, skip the product.
            if not variants:
                continue

            tags_raw = _str(first.get("Tags", ""))
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

            body = _str(first.get("Body (HTML)", ""))

            # Published: Shopify Published column is "true"/"false".
            # Status column ("active"/"draft"/"archived") is separate.
            published_raw = _str(first.get("Published", "true"))
            published = published_raw.lower() not in ("false", "0", "no")
            status = _str(first.get("Status", "active")).lower() or "active"

            product = NormalizedProduct(
                handle=handle,
                title=_str(first.get("Title", "")),
                body_html=body,
                vendor=_str(first.get("Vendor", "")),
                product_type=_str(first.get("Type", "")),
                tags=tags,
                published=published,
                seo_title=_str(first.get("SEO Title", "")),
                seo_description=_str(first.get("SEO Description", "")),
                status=status,
                option1_name=opt1_name,
                option2_name=opt2_name,
                option3_name=opt3_name,
                images=images,
                variants=variants,
            )
            products.append(product)

        return products
