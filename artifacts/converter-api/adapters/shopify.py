"""Shopify CSV import adapter."""
from __future__ import annotations
import re
import chardet
import pandas as pd
from adapters.base import ImportAdapter, NormalizedProduct, NormalizedVariant

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
    # Normalise common variants
    if enc.lower() in ("utf-8-sig", "utf-8"):
        return "utf-8-sig"
    return enc


def _str(val: object) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def _bool(val: object) -> bool:
    s = _str(val).lower()
    return s in ("true", "yes", "1")


def _float(val: object, default: float = 0.0) -> float:
    s = _str(val)
    try:
        return float(s) if s else default
    except ValueError:
        return default


def _int(val: object, default: int = 0) -> int:
    s = _str(val)
    try:
        return int(float(s)) if s else default
    except ValueError:
        return default


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
        # Strip whitespace from column names
        df.columns = [c.strip() for c in df.columns]
        return df

    def unknown_columns(self, df: pd.DataFrame) -> list[str]:
        return [c for c in df.columns if c not in SHOPIFY_KNOWN_COLUMNS]

    def normalize(self, df: pd.DataFrame) -> list[NormalizedProduct]:
        """Group rows by Handle and build NormalizedProduct objects."""
        products: list[NormalizedProduct] = []
        seen_images: dict[str, set[str]] = {}  # handle -> set of image srcs

        for handle, group in df.groupby("Handle", sort=False):
            handle = _str(handle)
            if not handle:
                continue

            # Use first row for product-level fields
            first = group.iloc[0]
            seen_images[handle] = set()

            # Discover which option names are used
            opt1_name = _str(first.get("Option1 Name", ""))
            opt2_name = _str(first.get("Option2 Name", ""))
            opt3_name = _str(first.get("Option3 Name", ""))

            # Collect images from all rows
            images: list[tuple[str, int, str]] = []
            image_srcs_seen: set[str] = set()
            for _, row in group.iterrows():
                src = _str(row.get("Image Src", ""))
                if src and src not in image_srcs_seen:
                    image_srcs_seen.add(src)
                    pos = _int(row.get("Image Position", ""), 0)
                    alt = _str(row.get("Image Alt Text", ""))
                    images.append((src, pos, alt))

            # Sort images by position
            images.sort(key=lambda x: x[1])

            # Build variants
            variants: list[NormalizedVariant] = []
            for _, row in group.iterrows():
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

            tags_raw = _str(first.get("Tags", ""))
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

            body = _str(first.get("Body (HTML)", ""))
            published_raw = _str(first.get("Published", "true"))
            published = published_raw.lower() not in ("false", "0", "draft", "no")

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
                status=_str(first.get("Status", "active")),
                option1_name=opt1_name,
                option2_name=opt2_name,
                option3_name=opt3_name,
                images=images,
                variants=variants,
            )
            products.append(product)

        return products
