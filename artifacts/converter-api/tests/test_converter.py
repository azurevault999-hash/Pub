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
    _active_option_count,
    verify_woocommerce_csv,
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


def _export_to_file(products: list[NormalizedProduct]) -> str:
    """Export products to a temp file and return the path (caller must unlink)."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8-sig"
    ) as f:
        path = f.name
    adapter = WooCommerceAdapter()
    adapter.export(products, path)
    return path


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

    def test_option3_name_forces_variable(self):
        p = _product(
            option1_name="Color",
            option2_name="Size",
            option3_name="Material",
            variants=[_variant(option1_value="Red", option2_value="S", option3_value="Cotton")],
        )
        assert _is_variable(p)


class TestBuildCategories:
    def test_empty(self):
        assert _build_categories("") == ""

    def test_simple(self):
        assert _build_categories("Clothing") == "Clothing"

    def test_hierarchical(self):
        assert _build_categories("Clothing > Tops > T-Shirts") == "Clothing > Tops > T-Shirts"


class TestActiveOptionCount:
    def test_zero_options(self):
        p = _product(option1_name="", option2_name="", option3_name="")
        assert _active_option_count(p) == 0

    def test_one_option(self):
        p = _product(option1_name="Size", option2_name="", option3_name="")
        assert _active_option_count(p) == 1

    def test_two_options(self):
        p = _product(option1_name="Color", option2_name="Size", option3_name="")
        assert _active_option_count(p) == 2

    def test_three_options(self):
        p = _product(option1_name="Color", option2_name="Size", option3_name="Material")
        assert _active_option_count(p) == 3


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

    def test_used_for_variations_is_zero_on_simple(self):
        """Simple products must never set 'used for variations' = 1."""
        for n in ("1", "2", "3"):
            assert self.rows[0].get(f"Attribute {n} used for variations", "0") != "1"


# ─────────────────────────────────────────────────────────────────────────────
# Sale price mapping (critical correctness test)
# ─────────────────────────────────────────────────────────────────────────────

class TestSalePriceMapping:
    def test_on_sale_product_correct_prices(self):
        """
        Shopify: Price=15.00, Compare At=25.00 (was price)
        WooCommerce must output: Regular price=25.00, Sale price=15.00
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
# Single-attribute variable product
# ─────────────────────────────────────────────────────────────────────────────

class TestSingleAttributeVariable:
    """Products with one option dimension (e.g. Size only)."""

    def setup_method(self):
        self.product = _product(
            handle="hoodie",
            option1_name="Size",
            variants=[
                _variant(sku="H-S", option1_value="S", price="49.99"),
                _variant(sku="H-M", option1_value="M", price="49.99"),
                _variant(sku="H-L", option1_value="L", price="49.99"),
                _variant(sku="H-XL", option1_value="XL", price="49.99"),
            ],
        )
        self.rows = _export([self.product])

    def test_correct_row_count(self):
        assert len(self.rows) == 5  # 1 parent + 4 variations

    def test_parent_is_variable(self):
        assert self.rows[0]["Type"] == "variable"

    def test_parent_attribute_name(self):
        assert self.rows[0]["Attribute 1 name"] == "Size"

    def test_parent_attribute_all_values(self):
        """Parent must list every possible size value."""
        parent_vals = self.rows[0]["Attribute 1 value(s)"]
        for size in ("S", "M", "L", "XL"):
            assert size in parent_vals

    def test_parent_used_for_variations(self):
        """Critical flag — must be '1' or dropdowns will be empty."""
        assert self.rows[0]["Attribute 1 used for variations"] == "1"

    def test_variation_attribute_single_value(self):
        """Each variation must carry exactly its own size, not all sizes."""
        variation_rows = [r for r in self.rows if r["Type"] == "variation"]
        for row in variation_rows:
            val = row["Attribute 1 value(s)"]
            assert "|" not in val, f"Variation has pipe-separated values: {val!r}"
            assert val in ("S", "M", "L", "XL"), f"Unexpected value: {val!r}"

    def test_no_any_in_variations(self):
        """The word 'Any' must never appear as a variation attribute value."""
        variation_rows = [r for r in self.rows if r["Type"] == "variation"]
        for row in variation_rows:
            assert row["Attribute 1 value(s)"].lower() != "any"
            assert row["Attribute 1 value(s)"] != ""

    def test_variation_parent_reference(self):
        variation_rows = [r for r in self.rows if r["Type"] == "variation"]
        for row in variation_rows:
            assert row["Parent"] == "hoodie"


# ─────────────────────────────────────────────────────────────────────────────
# Two-attribute variable product
# ─────────────────────────────────────────────────────────────────────────────

class TestTwoAttributeVariable:
    """Products with two option dimensions (e.g. Colour + Size)."""

    def setup_method(self):
        self.product = _product(
            handle="t-shirt",
            option1_name="Colour",
            option2_name="Size",
            variants=[
                _variant(sku="TS-B-S", option1_value="Black", option2_value="S", price="29.99"),
                _variant(sku="TS-B-M", option1_value="Black", option2_value="M", price="29.99"),
                _variant(sku="TS-W-S", option1_value="White", option2_value="S", price="29.99"),
                _variant(sku="TS-W-M", option1_value="White", option2_value="M", price="29.99"),
            ],
        )
        self.rows = _export([self.product])

    def test_correct_row_count(self):
        assert len(self.rows) == 5  # 1 parent + 4 variations

    def test_parent_has_both_attribute_names(self):
        assert self.rows[0]["Attribute 1 name"] == "Colour"
        assert self.rows[0]["Attribute 2 name"] == "Size"

    def test_parent_colour_all_values(self):
        colour_vals = self.rows[0]["Attribute 1 value(s)"]
        assert "Black" in colour_vals
        assert "White" in colour_vals

    def test_parent_size_all_values(self):
        size_vals = self.rows[0]["Attribute 2 value(s)"]
        assert "S" in size_vals
        assert "M" in size_vals

    def test_parent_both_used_for_variations(self):
        """Both attribute dimensions must be flagged for variations."""
        assert self.rows[0]["Attribute 1 used for variations"] == "1"
        assert self.rows[0]["Attribute 2 used for variations"] == "1"

    def test_variation_colour_single_value(self):
        variation_rows = [r for r in self.rows if r["Type"] == "variation"]
        for row in variation_rows:
            val = row["Attribute 1 value(s)"]
            assert val in ("Black", "White"), f"Unexpected colour value: {val!r}"
            assert "|" not in val

    def test_variation_size_single_value(self):
        variation_rows = [r for r in self.rows if r["Type"] == "variation"]
        for row in variation_rows:
            val = row["Attribute 2 value(s)"]
            assert val in ("S", "M"), f"Unexpected size value: {val!r}"
            assert "|" not in val

    def test_no_any_in_any_variation_attribute(self):
        variation_rows = [r for r in self.rows if r["Type"] == "variation"]
        for row in variation_rows:
            assert row["Attribute 1 value(s)"].lower() != "any"
            assert row["Attribute 2 value(s)"].lower() != "any"
            assert row["Attribute 1 value(s)"] != ""
            assert row["Attribute 2 value(s)"] != ""

    def test_specific_variation_values(self):
        """Black/S variation must have Colour=Black and Size=S."""
        variation_rows = [r for r in self.rows if r["Type"] == "variation"]
        bs = next((r for r in variation_rows if r["SKU"] == "TS-B-S"), None)
        assert bs is not None
        assert bs["Attribute 1 value(s)"] == "Black"
        assert bs["Attribute 2 value(s)"] == "S"


# ─────────────────────────────────────────────────────────────────────────────
# Three-attribute variable product
# ─────────────────────────────────────────────────────────────────────────────

class TestThreeAttributeVariable:
    """Products with three option dimensions (e.g. Colour + Size + Gender)."""

    def setup_method(self):
        self.product = _product(
            handle="jacket",
            option1_name="Colour",
            option2_name="Size",
            option3_name="Gender",
            variants=[
                _variant(sku="J-B-S-M", option1_value="Black", option2_value="S", option3_value="Mens", price="99.99"),
                _variant(sku="J-B-S-W", option1_value="Black", option2_value="S", option3_value="Womens", price="99.99"),
                _variant(sku="J-B-M-M", option1_value="Black", option2_value="M", option3_value="Mens", price="99.99"),
                _variant(sku="J-W-S-M", option1_value="White", option2_value="S", option3_value="Mens", price="99.99"),
            ],
        )
        self.rows = _export([self.product])

    def test_correct_row_count(self):
        assert len(self.rows) == 5  # 1 parent + 4 variations

    def test_parent_has_all_three_attributes(self):
        assert self.rows[0]["Attribute 1 name"] == "Colour"
        assert self.rows[0]["Attribute 2 name"] == "Size"
        assert self.rows[0]["Attribute 3 name"] == "Gender"

    def test_parent_all_three_used_for_variations(self):
        assert self.rows[0]["Attribute 1 used for variations"] == "1"
        assert self.rows[0]["Attribute 2 used for variations"] == "1"
        assert self.rows[0]["Attribute 3 used for variations"] == "1"

    def test_parent_gender_all_values(self):
        gender_vals = self.rows[0]["Attribute 3 value(s)"]
        assert "Mens" in gender_vals
        assert "Womens" in gender_vals

    def test_variation_all_attributes_set(self):
        variation_rows = [r for r in self.rows if r["Type"] == "variation"]
        for row in variation_rows:
            assert row["Attribute 1 value(s)"] != "", "Attribute 1 must not be empty"
            assert row["Attribute 2 value(s)"] != "", "Attribute 2 must not be empty"
            assert row["Attribute 3 value(s)"] != "", "Attribute 3 must not be empty"

    def test_no_any_in_any_variation(self):
        variation_rows = [r for r in self.rows if r["Type"] == "variation"]
        for row in variation_rows:
            for n in ("1", "2", "3"):
                assert row[f"Attribute {n} value(s)"].lower() != "any"

    def test_specific_three_attribute_variation(self):
        """Black/S/Mens variation must have all three exact values."""
        variation_rows = [r for r in self.rows if r["Type"] == "variation"]
        bsm = next((r for r in variation_rows if r["SKU"] == "J-B-S-M"), None)
        assert bsm is not None
        assert bsm["Attribute 1 value(s)"] == "Black"
        assert bsm["Attribute 2 value(s)"] == "S"
        assert bsm["Attribute 3 value(s)"] == "Mens"


# ─────────────────────────────────────────────────────────────────────────────
# Shopify "Title" / "Default Title" placeholder — must produce simple product
# ─────────────────────────────────────────────────────────────────────────────

class TestDefaultTitleOption:
    def test_title_default_title_is_simple(self):
        """
        Shopify uses Option1 Name='Title', Option1 Value='Default Title' as a
        placeholder for products with no real variant options.  These must
        become Simple products, not Variable.
        """
        product = _product(
            option1_name="Title",
            variants=[_variant(sku="PLAIN-001", option1_value="Default Title", price="14.99")],
        )
        rows = _export([product])
        assert len(rows) == 1
        assert rows[0]["Type"] == "simple"

    def test_title_default_title_sku_preserved(self):
        product = _product(
            option1_name="Title",
            variants=[_variant(sku="PLAIN-001", option1_value="Default Title", price="14.99")],
        )
        rows = _export([product])
        assert rows[0]["SKU"] == "PLAIN-001"

    def test_title_with_real_value_and_one_variant_is_simple(self):
        """
        A single meaningful value for Option1 Name='Title' should still be
        simple — there's nothing for the customer to choose between.
        """
        product = _product(
            option1_name="Title",
            variants=[_variant(sku="PLAIN-002", option1_value="Special Edition", price="19.99")],
        )
        rows = _export([product])
        assert rows[0]["Type"] == "simple"


# ─────────────────────────────────────────────────────────────────────────────
# Variable product export (original tests preserved)
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

    def test_parent_used_for_variations_set(self):
        """Attribute 1 and 2 must be flagged as used for variations on the parent."""
        assert self.rows[0]["Attribute 1 used for variations"] == "1"
        assert self.rows[0]["Attribute 2 used for variations"] == "1"

    def test_variation_used_for_variations_not_set(self):
        """Variation rows do not need 'used for variations' = 1."""
        for row in self.rows[1:]:
            assert row.get("Attribute 1 used for variations", "0") != "1"


# ─────────────────────────────────────────────────────────────────────────────
# Products with no variants (edge case)
# ─────────────────────────────────────────────────────────────────────────────

class TestProductWithNoVariants:
    def test_no_variants_uses_handle_as_sku(self):
        product = _product(handle="no-variant-prod", variants=[])
        rows = _export([product])
        assert len(rows) == 1
        assert rows[0]["SKU"] == "no-variant-prod"

    def test_no_variants_type_is_simple(self):
        product = _product(handle="no-variant-prod", variants=[])
        rows = _export([product])
        assert rows[0]["Type"] == "simple"


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
        """
        Variant Image is optional. When blank, the product's first Image Src
        must be inherited for the variation row.
        """
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

    def test_variant_no_image_no_product_image_is_empty(self):
        """When neither Variant Image nor product Image Src exist, Images is empty."""
        product = _product(
            images=[],
            option1_name="Color",
            variants=[
                _variant(sku="A", option1_value="Red", image_src=""),
                _variant(sku="B", option1_value="Blue", image_src=""),
            ],
        )
        rows = _export([product])
        children = [r for r in rows if r["Type"] == "variation"]
        for child in children:
            assert child["Images"] == ""


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

    def test_duplicate_sku_detected_by_verification(self):
        """verify_woocommerce_csv must flag duplicate SKUs."""
        # Build two simple products with the same SKU.
        p1 = _product(handle="prod-a", title="Product A",
                      option1_name="Title",
                      variants=[_variant(sku="DUPE-SKU", price="9.99")])
        p2 = _product(handle="prod-b", title="Product B",
                      option1_name="Title",
                      variants=[_variant(sku="DUPE-SKU", price="9.99")])
        path = _export_to_file([p1, p2])
        try:
            errors = verify_woocommerce_csv(path)
        finally:
            os.unlink(path)
        dup_errors = [e for e in errors if "Duplicate SKU" in e]
        assert len(dup_errors) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Post-export verification
# ─────────────────────────────────────────────────────────────────────────────

class TestVerifyWooCommerceCsv:
    def test_valid_variable_product_passes(self):
        product = _product(
            handle="valid-var",
            option1_name="Size",
            variants=[
                _variant(sku="V-S", option1_value="S", price="10.00"),
                _variant(sku="V-M", option1_value="M", price="10.00"),
            ],
        )
        path = _export_to_file([product])
        try:
            errors = verify_woocommerce_csv(path)
        finally:
            os.unlink(path)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_valid_two_attribute_product_passes(self):
        product = _product(
            handle="valid-two",
            option1_name="Color",
            option2_name="Size",
            variants=[
                _variant(sku="V-R-S", option1_value="Red", option2_value="S", price="10.00"),
                _variant(sku="V-B-M", option1_value="Blue", option2_value="M", price="10.00"),
            ],
        )
        path = _export_to_file([product])
        try:
            errors = verify_woocommerce_csv(path)
        finally:
            os.unlink(path)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_valid_three_attribute_product_passes(self):
        product = _product(
            handle="valid-three",
            option1_name="Color",
            option2_name="Size",
            option3_name="Gender",
            variants=[
                _variant(sku="V-R-S-M", option1_value="Red", option2_value="S", option3_value="Mens", price="10.00"),
                _variant(sku="V-B-M-W", option1_value="Blue", option2_value="M", option3_value="Womens", price="10.00"),
            ],
        )
        path = _export_to_file([product])
        try:
            errors = verify_woocommerce_csv(path)
        finally:
            os.unlink(path)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_valid_simple_product_passes(self):
        product = _product(
            option1_name="Title",
            variants=[_variant(sku="SIMPLE", option1_value="Default Title", price="9.99")],
        )
        path = _export_to_file([product])
        try:
            errors = verify_woocommerce_csv(path)
        finally:
            os.unlink(path)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_used_for_variations_is_present_in_output(self):
        """The generated CSV must have 'Attribute N used for variations' columns."""
        product = _product(
            handle="check-cols",
            option1_name="Size",
            variants=[
                _variant(sku="C-S", option1_value="S", price="5.00"),
                _variant(sku="C-M", option1_value="M", price="5.00"),
            ],
        )
        path = _export_to_file([product])
        try:
            with open(path, encoding="utf-8-sig") as f:
                headers = next(csv.reader(f))
        finally:
            os.unlink(path)
        assert "Attribute 1 used for variations" in headers
        assert "Attribute 2 used for variations" in headers
        assert "Attribute 3 used for variations" in headers


# ─────────────────────────────────────────────────────────────────────────────
# Attribute mapping — comprehensive
# ─────────────────────────────────────────────────────────────────────────────

class TestAttributeMapping:
    def test_attribute_name_mapped_correctly(self):
        """Option1 Name must become Attribute 1 name on both parent and variation rows."""
        product = _product(
            handle="map-test",
            option1_name="Colour",
            variants=[
                _variant(sku="M-B", option1_value="Black", price="10.00"),
                _variant(sku="M-W", option1_value="White", price="10.00"),
            ],
        )
        rows = _export([product])
        parent = rows[0]
        assert parent["Attribute 1 name"] == "Colour"
        for var_row in rows[1:]:
            assert var_row["Attribute 1 name"] == "Colour"

    def test_custom_attribute_names_supported(self):
        """Any custom option name (Gender, Material, Qty, etc.) must be preserved."""
        product = _product(
            handle="custom-attr",
            option1_name="Material",
            option2_name="Qty",
            variants=[
                _variant(sku="C-C-1", option1_value="Cotton", option2_value="1", price="5.00"),
                _variant(sku="C-P-1", option1_value="Polyester", option2_value="1", price="5.00"),
            ],
        )
        rows = _export([product])
        parent = rows[0]
        assert parent["Attribute 1 name"] == "Material"
        assert parent["Attribute 2 name"] == "Qty"

    def test_parent_attributes_visible(self):
        """Parent attributes must be visible (Attribute N visible = 1)."""
        product = _product(
            handle="vis-test",
            option1_name="Size",
            variants=[
                _variant(sku="V-S", option1_value="S", price="10.00"),
                _variant(sku="V-M", option1_value="M", price="10.00"),
            ],
        )
        rows = _export([product])
        assert rows[0]["Attribute 1 visible"] == "1"

    def test_parent_variation_attribute_values_pipe_separated(self):
        """Parent attribute value list must use ' | ' as separator."""
        product = _product(
            handle="pipe-test",
            option1_name="Size",
            variants=[
                _variant(sku="P-S", option1_value="S", price="10.00"),
                _variant(sku="P-M", option1_value="M", price="10.00"),
                _variant(sku="P-L", option1_value="L", price="10.00"),
            ],
        )
        rows = _export([product])
        parent_vals = rows[0]["Attribute 1 value(s)"]
        assert " | " in parent_vals, f"Values not pipe-separated: {parent_vals!r}"

    def test_parent_preserves_value_order(self):
        """Parent attribute values must preserve insertion order (S, M, L, XL)."""
        product = _product(
            handle="order-test",
            option1_name="Size",
            variants=[
                _variant(sku="O-S", option1_value="S", price="10.00"),
                _variant(sku="O-M", option1_value="M", price="10.00"),
                _variant(sku="O-L", option1_value="L", price="10.00"),
                _variant(sku="O-XL", option1_value="XL", price="10.00"),
            ],
        )
        rows = _export([product])
        parent_vals = rows[0]["Attribute 1 value(s)"]
        assert parent_vals == "S | M | L | XL", f"Wrong order: {parent_vals!r}"


# ─────────────────────────────────────────────────────────────────────────────
# Parent / variation relationship
# ─────────────────────────────────────────────────────────────────────────────

class TestParentVariationRelationship:
    def test_parent_sku_used_as_parent_ref(self):
        """Variations must reference the parent's SKU (= handle), not any variant SKU."""
        product = _product(
            handle="rel-test",
            option1_name="Color",
            variants=[
                _variant(sku="RT-R", option1_value="Red", price="10.00"),
                _variant(sku="RT-B", option1_value="Blue", price="10.00"),
            ],
        )
        rows = _export([product])
        parent_sku = rows[0]["SKU"]
        assert parent_sku == "rel-test"
        for var_row in rows[1:]:
            assert var_row["Parent"] == "rel-test"

    def test_variation_has_no_parent_field_on_parent(self):
        """The parent row itself must have an empty Parent field."""
        product = _product(
            handle="rel-test2",
            option1_name="Size",
            variants=[
                _variant(sku="R2-S", option1_value="S", price="10.00"),
                _variant(sku="R2-M", option1_value="M", price="10.00"),
            ],
        )
        rows = _export([product])
        assert rows[0]["Parent"] == ""

    def test_multiple_variable_products_correct_parents(self):
        """Each variation must reference its own product's parent, not another's."""
        p1 = _product(
            handle="prod-1",
            title="Product 1",
            option1_name="Size",
            variants=[
                _variant(sku="P1-S", option1_value="S", price="10.00"),
                _variant(sku="P1-M", option1_value="M", price="10.00"),
            ],
        )
        p2 = _product(
            handle="prod-2",
            title="Product 2",
            option1_name="Size",
            variants=[
                _variant(sku="P2-S", option1_value="S", price="20.00"),
                _variant(sku="P2-M", option1_value="M", price="20.00"),
            ],
        )
        rows = _export([p1, p2])
        p1_vars = [r for r in rows if r["Type"] == "variation" and r["Parent"] == "prod-1"]
        p2_vars = [r for r in rows if r["Type"] == "variation" and r["Parent"] == "prod-2"]
        assert len(p1_vars) == 2
        assert len(p2_vars) == 2

    def test_verification_validates_parent_relationships(self):
        """verify_woocommerce_csv must pass for correctly linked products."""
        product = _product(
            handle="rel-verify",
            option1_name="Size",
            variants=[
                _variant(sku="RV-S", option1_value="S", price="10.00"),
                _variant(sku="RV-M", option1_value="M", price="10.00"),
            ],
        )
        path = _export_to_file([product])
        try:
            errors = verify_woocommerce_csv(path)
        finally:
            os.unlink(path)
        parent_errors = [e for e in errors if "parent" in e.lower()]
        assert parent_errors == [], f"Unexpected parent relationship errors: {parent_errors}"
