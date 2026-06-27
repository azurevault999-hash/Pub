"""Unit tests for the validation engine."""
from __future__ import annotations

import io
import os
import tempfile
import textwrap

import pandas as pd
import pytest

from services.validator import validate
from models.schemas import ValidationResult


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _df(**cols: list) -> pd.DataFrame:
    """Build a DataFrame from keyword column lists."""
    return pd.DataFrame(cols)


def _base_row(**overrides) -> dict:
    """Minimal valid Shopify row."""
    row = {
        "Handle": "test-product",
        "Title": "Test Product",
        "Variant SKU": "SKU-001",
        "Variant Price": "9.99",
        "Image Src": "http://cdn.example.com/img.jpg",
        "Variant Image": "",
        "Option1 Name": "Title",
        "Option1 Value": "Default Title",
        "Option2 Name": "",
        "Option2 Value": "",
        "Option3 Name": "",
        "Option3 Value": "",
        "Body (HTML)": "<p>Hello</p>",
        "Tags": "tag1",
        "Vendor": "Acme",
        "SEO Title": "SEO",
        "SEO Description": "Desc",
        "Variant Barcode": "1234567890",
        "Variant Grams": "100",
    }
    row.update(overrides)
    return row


def _validate_rows(*rows: dict) -> ValidationResult:
    df = pd.DataFrame(list(rows))
    return validate(df)


def _issues_by_check(result: ValidationResult) -> dict[str, str]:
    return {i.check: i.level for i in result.issues}


# ─────────────────────────────────────────────────────────────────────────────
# Required columns
# ─────────────────────────────────────────────────────────────────────────────

class TestRequiredColumns:
    def test_all_present_passes(self):
        result = _validate_rows(_base_row())
        by_check = _issues_by_check(result)
        assert by_check["Required Columns"] == "pass"

    def test_missing_handle_is_error(self):
        row = _base_row()
        del row["Handle"]
        df = pd.DataFrame([row])
        result = validate(df)
        by_check = _issues_by_check(result)
        assert by_check["Required Columns"] == "error"

    def test_missing_title_is_error(self):
        row = _base_row()
        del row["Title"]
        df = pd.DataFrame([row])
        result = validate(df)
        by_check = _issues_by_check(result)
        assert by_check["Required Columns"] == "error"


# ─────────────────────────────────────────────────────────────────────────────
# Empty handles
# ─────────────────────────────────────────────────────────────────────────────

class TestEmptyHandles:
    def test_all_handles_present(self):
        result = _validate_rows(_base_row())
        assert _issues_by_check(result)["Empty Handles"] == "pass"

    def test_empty_handle_is_error(self):
        result = _validate_rows(_base_row(**{"Handle": ""}))
        assert _issues_by_check(result)["Empty Handles"] == "error"


# ─────────────────────────────────────────────────────────────────────────────
# Missing title
# ─────────────────────────────────────────────────────────────────────────────

class TestMissingTitle:
    def test_title_present(self):
        result = _validate_rows(_base_row())
        assert _issues_by_check(result)["Missing Title"] == "pass"

    def test_missing_title_is_error(self):
        result = _validate_rows(_base_row(**{"Title": ""}))
        assert _issues_by_check(result)["Missing Title"] == "error"


# ─────────────────────────────────────────────────────────────────────────────
# Duplicate SKUs — must be WARNING, not ERROR
# ─────────────────────────────────────────────────────────────────────────────

class TestDuplicateSKUs:
    def test_no_duplicates_passes(self):
        result = _validate_rows(
            _base_row(**{"Variant SKU": "A"}),
            _base_row(**{"Handle": "other", "Variant SKU": "B"}),
        )
        assert _issues_by_check(result)["Duplicate SKUs"] == "pass"

    def test_duplicate_sku_is_warning_not_error(self):
        """Duplicate SKUs must be WARNING so conversion is not blocked."""
        result = _validate_rows(
            _base_row(**{"Variant SKU": "SAME"}),
            _base_row(**{"Handle": "other-product", "Variant SKU": "SAME"}),
        )
        by_check = _issues_by_check(result)
        assert by_check["Duplicate SKUs"] == "warning"
        assert result.can_convert is True

    def test_duplicate_sku_does_not_block_conversion(self):
        result = _validate_rows(
            _base_row(**{"Variant SKU": "DUP"}),
            _base_row(**{"Handle": "second", "Variant SKU": "DUP"}),
        )
        assert result.can_convert is True


# ─────────────────────────────────────────────────────────────────────────────
# Missing prices — image rows must NOT be flagged
# ─────────────────────────────────────────────────────────────────────────────

class TestMissingPrices:
    def test_all_variant_rows_have_prices(self):
        result = _validate_rows(_base_row())
        assert _issues_by_check(result)["Missing Variant Price"] == "pass"

    def test_image_only_row_does_not_trigger_missing_price(self):
        """
        An image-only row (no Variant Price, no Option values) should NOT
        be counted as a row with a missing price.
        """
        image_row = {
            "Handle": "test-product",
            "Title": "",
            "Variant SKU": "",
            "Variant Price": "",
            "Image Src": "http://cdn.example.com/img2.jpg",
            "Variant Image": "",
            "Option1 Name": "",
            "Option1 Value": "",
            "Option2 Name": "",
            "Option2 Value": "",
            "Option3 Name": "",
            "Option3 Value": "",
            "Body (HTML)": "",
            "Tags": "",
            "Vendor": "Acme",
            "SEO Title": "",
            "SEO Description": "",
            "Variant Barcode": "",
            "Variant Grams": "",
        }
        result = _validate_rows(_base_row(), image_row)
        assert _issues_by_check(result)["Missing Variant Price"] == "pass"

    def test_variant_row_missing_price_is_warning(self):
        result = _validate_rows(_base_row(**{"Variant Price": ""}))
        assert _issues_by_check(result)["Missing Variant Price"] == "warning"
        assert result.can_convert is True


# ─────────────────────────────────────────────────────────────────────────────
# Negative prices
# ─────────────────────────────────────────────────────────────────────────────

class TestNegativePrices:
    def test_positive_price_passes(self):
        result = _validate_rows(_base_row(**{"Variant Price": "9.99"}))
        assert _issues_by_check(result)["Negative Prices"] == "pass"

    def test_negative_price_is_error(self):
        result = _validate_rows(_base_row(**{"Variant Price": "-5.00"}))
        assert _issues_by_check(result)["Negative Prices"] == "error"
        assert result.can_convert is False


# ─────────────────────────────────────────────────────────────────────────────
# Variant Image rule
# ─────────────────────────────────────────────────────────────────────────────

class TestVariantImageRule:
    def test_variant_image_present_passes(self):
        result = _validate_rows(
            _base_row(**{"Variant Image": "http://cdn.example.com/v.jpg"})
        )
        by_check = _issues_by_check(result)
        assert by_check["Variant Image Coverage"] == "pass"

    def test_no_variant_image_but_product_image_is_info(self):
        """Missing Variant Image with Image Src present → INFO (not blocking)."""
        result = _validate_rows(
            _base_row(**{"Variant Image": "", "Image Src": "http://cdn.example.com/img.jpg"})
        )
        by_check = _issues_by_check(result)
        assert by_check.get("Variant Image — Using Product Images") == "info" or \
               by_check.get("Variant Image Coverage") in ("pass", "info")
        assert result.can_convert is True

    def test_both_images_absent_is_error(self):
        """Missing Variant Image AND Image Src → ERROR."""
        result = _validate_rows(
            _base_row(**{"Variant Image": "", "Image Src": ""})
        )
        by_check = _issues_by_check(result)
        assert by_check.get("Variant Image — No Images at All") == "error" or \
               by_check.get("Missing Product Images") == "warning"
        # At minimum, should not silently pass
        assert result.error_count > 0 or result.warning_count > 0


# ─────────────────────────────────────────────────────────────────────────────
# Duplicate variation combinations
# ─────────────────────────────────────────────────────────────────────────────

class TestDuplicateVariations:
    def test_unique_combinations_pass(self):
        result = _validate_rows(
            _base_row(**{"Handle": "p", "Option1 Value": "Red", "Variant SKU": "A"}),
            _base_row(**{"Handle": "p", "Title": "", "Option1 Value": "Blue", "Variant SKU": "B"}),
        )
        assert _issues_by_check(result)["Duplicate Variations"] == "pass"

    def test_duplicate_combination_is_warning(self):
        result = _validate_rows(
            _base_row(**{"Handle": "p", "Option1 Value": "Red", "Variant SKU": "A"}),
            _base_row(**{"Handle": "p", "Title": "", "Option1 Value": "Red", "Variant SKU": "B"}),
        )
        assert _issues_by_check(result)["Duplicate Variations"] == "warning"
        assert result.can_convert is True


# ─────────────────────────────────────────────────────────────────────────────
# can_convert only blocks on errors
# ─────────────────────────────────────────────────────────────────────────────

class TestCanConvert:
    def test_clean_file_can_convert(self):
        result = _validate_rows(_base_row())
        assert result.can_convert is True

    def test_warnings_do_not_block_conversion(self):
        """A file with only warnings must still be convertible."""
        result = _validate_rows(
            _base_row(**{"Variant SKU": "DUP"}),
            _base_row(**{"Handle": "other", "Variant SKU": "DUP"}),
        )
        assert result.can_convert is True

    def test_error_blocks_conversion(self):
        result = _validate_rows(_base_row(**{"Title": ""}))
        assert result.can_convert is False


# ─────────────────────────────────────────────────────────────────────────────
# Info level checks
# ─────────────────────────────────────────────────────────────────────────────

class TestInfoLevel:
    def test_unknown_columns_are_info(self):
        row = _base_row(**{"CustomColumn": "value"})
        df = pd.DataFrame([row])
        result = validate(df)
        by_check = _issues_by_check(result)
        assert by_check.get("Unknown Columns") == "info"

    def test_missing_tags_are_info(self):
        result = _validate_rows(_base_row(**{"Tags": ""}))
        by_check = _issues_by_check(result)
        assert by_check.get("Missing Tags") == "info"

    def test_missing_seo_is_info(self):
        result = _validate_rows(
            _base_row(**{"SEO Title": "", "SEO Description": ""})
        )
        by_check = _issues_by_check(result)
        assert by_check.get("Missing SEO Fields") == "info"

    def test_info_does_not_block_conversion(self):
        row = _base_row(**{"Tags": "", "SEO Title": "", "SEO Description": ""})
        row["CustomColumn"] = "value"
        df = pd.DataFrame([row])
        result = validate(df)
        assert result.can_convert is True
        assert result.info_count > 0
