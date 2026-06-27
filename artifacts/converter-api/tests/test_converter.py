"""Unit tests for the WooCommerce adapter and end-to-end conversion."""
from __future__ import annotations

import csv
import os
import tempfile
import textwrap

import pytest

from adapters.base import NormalizedProduct, NormalizedVariant
from adapters.woocommerce import (
    WooCommerceAdapter,
    _grams_to_kg,
    _is_variable,
    _price,
    _price_pair,
    _build_categories,
    _all_option_values,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _product(**kwargs) -> NormalizedProduct:
    defaults = dict(
        handle="test-product",
        title="Test Product",
        body_html="<p>Desc</p>",
        vendor="Acme",
        product_type="Widgets",
        tags=["tag1"],
        published=True,
        seo_title="SEO",
        seo_description="Desc",
        status="active",
        option1_name="",
        option2_name="",
        option3_name="",
        images=[("http://cdn.example.com/img.jpg", 1, "alt text")],
        variants=[],
    )
    defaults.update(kwargs)
    return NormalizedProduct(**defaults)


def _variant(**kwargs) -> NormalizedVariant:
    defaults = dict(
        sku="SKU-001",
        option1_value="",
        option2_value="",
        option3_value="",
        price="9.99",
        compare_at_price="",
        weight_grams=0.0,
        inventory_qty=10,
        taxable=True,
        barcode="",
        image_src="",
        requires_shipping=True,
    )
    defaults.update(kwargs)
    return NormalizedVariant(**defaults)


def _export(products: list[NormalizedProduct]) -> list[dict[str, str]]:
    """Export products and return parsed CSV rows."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8-sig"
    ) as f:
        path = f.name
    try:
        adapter = WooCommerceAdapter()
        adapter.export(products, path)
        with open(path, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    finally:
        os.unlink(path)


# ─────────────────────────────────────────────────────────────────────────────
# Unit helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestPricePair:
    def test_no_compare_at(self):
        regular, sale = _price_pair("19.99", "")
        assert regular == "19.99"
        assert sale == ""

    def test_compare_at_higher_means_on_sale(self):
        """compare_at > price → Regular = compare_at, Sale = price."""
        regular, sale = _price_pair("15.00", "25.00")
        assert regular == "25.00"
        assert sale == "15.00"

    def test_compare_at_equal_no_sale(self):
        regular, sale = _price_pair("20.00", "20.00")
        assert regular == "20.00"
        assert sale == ""

    def test_compare_at_lower_no_sale(self):
        """compare_at ≤ price → no sale (unusual data)."""
        regular, sale = _price_pair("20.00", "10.00")
        assert regular == "20.00"
        assert sale == ""

    def test_empty_price(self):
        regular, sale = _price_pair("", "25.00")
        assert regular == ""
        assert sale == ""

    def test_price_formatted_two_decimals(self):
        regular, sale = _price_pair("9.9", "")
        assert regular == "9.90"


class TestGramsToKg:
    def test_zero(self):
        assert _grams_to_kg(0) == ""

    def test_negative(self):
        assert _grams_to_kg(-1) == ""

    def test_500g(self):
        assert _grams_to_kg(500) == "0.5"

    def test_1000g(self):
        assert _grams_to_kg(1000) == "1"

    def test_1500g(self):
        assert _grams_to_kg(1500) == "1.5"

    def test_precision(self):
        # Should not have trailing zeros beyond meaningful digits
        result = _grams_to_kg(250)
        assert result == "0.25"


class TestIsVariable:
    def test_no_option_name_is_simple(self):
        p = _product(option1_name="", variants=[_variant()])
        assert not _is_variable(p)

    def test_default_title_only_is_simple(self):
        p = _product(
            option1_name="Title",
            variants=[_variant(option1_value="Default Title")],
        )
        assert not _is_variable(p)

    def test_two_option_values_is_variable(self):
        p = _product(
            option1_name="Color",
            variants=[
                _variant(sku="A", option1_value="Red"),
                _variant(sku="B", option1_value="Blue"),
            ],
        )
        assert _is_variable(p)

    def test_option2_name_forces_variable(self):
        p = _product(
            option1_name="Color",
            option2_name="Size",
            variants=[_variant(option1_value="Red", option2_value="S")],
        )
        assert _is_variable(p)

    def test_single_real_option_value_is_simple(self):
        """Single unique non-default option value → simple product."""
        p = _product(
            option1_name="Color",
            variants=[_variant(option1_value="Red")],
        )
        assert not _is_variable(p)


class TestBuildCategories:
    def test_empty(self):
        assert _build_categories("") == ""

    def test_simple(self):
        assert _build_categories("Clothing") == "Clothing"

    def test_hierarchical(self):
        assert _build_categories("Clothing > Tops > T-Shirts") == "Clothing > Tops > T-Shirts"


# ─────────────────────────────────────────────────────────────────────────────
# Simple product export
# ─────────────────────────────────────────────────────────────────────────────

class TestSimpleProductExport:
    def setup_method(self):
        self.product = _product(
            option1_name="Title",
            variants=[_variant(sku="SKU-001", price="19.99", compare_at_price="")],
        )
        self.rows = _export([self.product])

    def test_one_row(self):
        assert len(self.rows) == 1

    def test_type_is_simple(self):
        assert self.rows[0]["Type"] == "simple"

    def test_sku(self):
        assert self.rows[0]["SKU"] == "SKU-001"

    def test_regular_price(self):
        assert self.rows[0]["Regular price"] == "19.99"

    def test_no_sale_price(self):
        assert self.rows[0]["Sale price"] == ""

    def test_published(self):
        assert self.rows[0]["Published"] == "1"


# ─────────────────────────────────────────────────────────────────────────────
# Sale price mapping (critical correctness test)
# ─────────────────────────────────────────────────────────────────────────────

class TestSalePriceMapping:
    def test_on_sale_product_correct_prices(self):
        """
        Shopify: Price=15.00, Compare At=25.00 (was price)
        WooCommerce must output: Regular price=25.00, Sale price=15.00
        The previous implementation had these reversed.
        """
        product = _product(
            option1_name="Title",
            variants=[_variant(price="15.00", compare_at_price="25.00")],
        )
        rows = _export([product])
        assert rows[0]["Regular price"] == "25.00"
        assert rows[0]["Sale price"] == "15.00"

    def test_not_on_sale_has_no_sale_price(self):
        product = _product(
            option1_name="Title",
            variants=[_variant(price="25.00", compare_at_price="")],
        )
        rows = _export([product])
        assert rows[0]["Regular price"] == "25.00"
        assert rows[0]["Sale price"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# Variable product export
# ─────────────────────────────────────────────────────────────────────────────

class TestVariableProductExport:
    def setup_method(self):
        self.product = _product(
            handle="t-shirt",
            option1_name="Color",
            option2_name="Size",
            variants=[
                _variant(sku="TS-R-S", option1_value="Red", option2_value="S", price="15.00"),
                _variant(sku="TS-R-M", option1_value="Red", option2_value="M", price="15.00"),
                _variant(sku="TS-B-S", option1_value="Blue", option2_value="S", price="15.00"),
            ],
        )
        self.rows = _export([self.product])

    def test_parent_plus_three_children(self):
        assert len(self.rows) == 4  # 1 parent + 3 children

    def test_first_row_is_parent(self):
        assert self.rows[0]["Type"] == "variable"

    def test_child_rows_are_variations(self):
        for row in self.rows[1:]:
            assert row["Type"] == "variation"

    def test_parent_sku_is_handle(self):
        """Parent SKU must be the product handle, not the first variant's SKU."""
        assert self.rows[0]["SKU"] == "t-shirt"

    def test_parent_sku_distinct_from_variant_skus(self):
        """Parent SKU must not equal any variation SKU."""
        parent_sku = self.rows[0]["SKU"]
        variant_skus = [r["SKU"] for r in self.rows[1:]]
        assert parent_sku not in variant_skus

    def test_children_reference_correct_parent(self):
        parent_sku = self.rows[0]["SKU"]
        for row in self.rows[1:]:
            assert row["Parent"] == parent_sku

    def test_parent_has_all_attribute_values(self):
        assert "Red" in self.rows[0]["Attribute 1 value(s)"]
        assert "Blue" in self.rows[0]["Attribute 1 value(s)"]

    def test_child_has_single_attribute_value(self):
        child = self.rows[1]
        assert child["Attribute 1 value(s)"] in ("Red", "Blue")

    def test_parent_stock_is_blank(self):
        """Variable product parent stock must be blank (tracked per variation)."""
        assert self.rows[0]["Stock"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# Products with no variants (edge case)
# ─────────────────────────────────────────────────────────────────────────────

class TestProductWithNoVariants:
    def test_no_variants_uses_handle_as_sku(self):
        product = _product(handle="no-variant-prod", variants=[])
        rows = _export([product])
        assert len(rows) == 1
        assert rows[0]["SKU"] == "no-variant-prod"


# ─────────────────────────────────────────────────────────────────────────────
# Variant image fallback
# ─────────────────────────────────────────────────────────────────────────────

class TestVariantImageFallback:
    def test_variant_with_image_uses_it(self):
        product = _product(
            option1_name="Color",
            variants=[
                _variant(sku="A", option1_value="Red",
                         image_src="http://cdn.example.com/red.jpg"),
                _variant(sku="B", option1_value="Blue",
                         image_src="http://cdn.example.com/blue.jpg"),
            ],
        )
        rows = _export([product])
        children = [r for r in rows if r["Type"] == "variation"]
        assert children[0]["Images"] == "http://cdn.example.com/red.jpg"
        assert children[1]["Images"] == "http://cdn.example.com/blue.jpg"

    def test_variant_without_image_falls_back_to_product_image(self):
        product = _product(
            images=[("http://cdn.example.com/main.jpg", 1, "main")],
            option1_name="Color",
            variants=[
                _variant(sku="A", option1_value="Red", image_src=""),
                _variant(sku="B", option1_value="Blue", image_src=""),
            ],
        )
        rows = _export([product])
        children = [r for r in rows if r["Type"] == "variation"]
        for child in children:
            assert child["Images"] == "http://cdn.example.com/main.jpg"


# ─────────────────────────────────────────────────────────────────────────────
# Draft / unpublished products
# ─────────────────────────────────────────────────────────────────────────────

class TestDraftProduct:
    def test_draft_status_sets_published_zero(self):
        product = _product(
            published=True,
            status="draft",
            option1_name="Title",
            variants=[_variant()],
        )
        rows = _export([product])
        assert rows[0]["Published"] == "0"

    def test_published_false_sets_published_zero(self):
        product = _product(
            published=False,
            status="active",
            option1_name="Title",
            variants=[_variant()],
        )
        rows = _export([product])
        assert rows[0]["Published"] == "0"


# ─────────────────────────────────────────────────────────────────────────────
# Duplicate SKUs — all products still exported
# ─────────────────────────────────────────────────────────────────────────────

class TestDuplicateSkuExport:
    def test_both_products_exported_despite_dup_sku(self):
        p1 = _product(handle="prod-a", title="Product A",
                      option1_name="Title",
                      variants=[_variant(sku="SAME-SKU")])
        p2 = _product(handle="prod-b", title="Product B",
                      option1_name="Title",
                      variants=[_variant(sku="SAME-SKU")])
        rows = _export([p1, p2])
        assert len(rows) == 2
