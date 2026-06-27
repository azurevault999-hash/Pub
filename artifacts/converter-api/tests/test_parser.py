"""Unit tests for the Shopify CSV adapter (parser)."""
from __future__ import annotations

import io
import os
import tempfile
import textwrap

import pandas as pd
import pytest

from adapters.shopify import ShopifyAdapter, _is_variant_row


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _csv(content: str) -> str:
    """Write *content* to a temp CSV file and return the path."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as f:
        f.write(textwrap.dedent(content).strip())
        return f.name


def _cleanup(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# _is_variant_row
# ─────────────────────────────────────────────────────────────────────────────

class TestIsVariantRow:
    def _row(self, **kwargs) -> pd.Series:
        return pd.Series(kwargs)

    def test_price_present(self):
        assert _is_variant_row(self._row(**{"Variant Price": "9.99"}))

    def test_option1_present(self):
        assert _is_variant_row(self._row(**{"Option1 Value": "Red"}))

    def test_both_absent(self):
        assert not _is_variant_row(self._row(**{"Image Src": "http://example.com/a.jpg"}))

    def test_all_absent(self):
        assert not _is_variant_row(self._row())


# ─────────────────────────────────────────────────────────────────────────────
# Simple product (no real variants)
# ─────────────────────────────────────────────────────────────────────────────

class TestSimpleProduct:
    CSV = """\
        Handle,Title,Body (HTML),Vendor,Type,Tags,Published,Option1 Name,Option1 Value,Variant SKU,Variant Price,Variant Grams,Variant Inventory Qty,Variant Taxable,Image Src,Image Position,SEO Title,SEO Description,Status
        my-product,My Product,<p>Desc</p>,Acme,Widgets,tag1,true,Title,Default Title,SKU-001,19.99,500,10,true,http://cdn.example.com/img1.jpg,1,SEO Title,SEO Desc,active
    """

    def setup_method(self):
        self.path = _csv(self.CSV)
        self.adapter = ShopifyAdapter()
        self.df = self.adapter.read(self.path)
        self.products = self.adapter.normalize(self.df)

    def teardown_method(self):
        _cleanup(self.path)

    def test_one_product(self):
        assert len(self.products) == 1

    def test_title(self):
        assert self.products[0].title == "My Product"

    def test_handle(self):
        assert self.products[0].handle == "my-product"

    def test_one_variant(self):
        assert len(self.products[0].variants) == 1

    def test_sku(self):
        assert self.products[0].variants[0].sku == "SKU-001"

    def test_price(self):
        assert self.products[0].variants[0].price == "19.99"

    def test_weight_grams(self):
        assert self.products[0].variants[0].weight_grams == 500.0

    def test_image(self):
        assert len(self.products[0].images) == 1
        assert self.products[0].images[0][0] == "http://cdn.example.com/img1.jpg"

    def test_tags(self):
        assert self.products[0].tags == ["tag1"]

    def test_seo(self):
        assert self.products[0].seo_title == "SEO Title"
        assert self.products[0].seo_description == "SEO Desc"


# ─────────────────────────────────────────────────────────────────────────────
# Product with multiple images (image-only rows must not become variants)
# ─────────────────────────────────────────────────────────────────────────────

class TestMultipleImages:
    CSV = """\
        Handle,Title,Option1 Name,Option1 Value,Variant SKU,Variant Price,Variant Grams,Variant Inventory Qty,Variant Taxable,Image Src,Image Position
        photo-book,Photo Book,Title,Default Title,PB-001,29.99,300,5,true,http://cdn.example.com/img1.jpg,1
        photo-book,,,,,,,,,,http://cdn.example.com/img2.jpg,2
        photo-book,,,,,,,,,,http://cdn.example.com/img3.jpg,3
    """

    def setup_method(self):
        self.path = _csv(self.CSV)
        self.adapter = ShopifyAdapter()
        self.df = self.adapter.read(self.path)
        self.products = self.adapter.normalize(self.df)

    def teardown_method(self):
        _cleanup(self.path)

    def test_one_product(self):
        assert len(self.products) == 1

    def test_exactly_one_variant(self):
        """Image-only rows must NOT become phantom variants."""
        assert len(self.products[0].variants) == 1

    def test_all_images_collected(self):
        assert len(self.products[0].images) == 3

    def test_images_sorted_by_position(self):
        positions = [pos for _, pos, _ in self.products[0].images]
        assert positions == sorted(positions)


# ─────────────────────────────────────────────────────────────────────────────
# Product with multiple variants and multiple option dimensions
# ─────────────────────────────────────────────────────────────────────────────

class TestMultiVariant:
    CSV = """\
        Handle,Title,Option1 Name,Option1 Value,Option2 Name,Option2 Value,Variant SKU,Variant Price,Variant Grams,Variant Inventory Qty,Variant Taxable,Image Src,Image Position
        t-shirt,T-Shirt,Color,Red,Size,S,TS-R-S,15.00,200,10,true,http://cdn.example.com/red.jpg,1
        t-shirt,,Color,Red,Size,M,TS-R-M,15.00,220,8,true,,
        t-shirt,,Color,Blue,Size,S,TS-B-S,15.00,200,12,true,http://cdn.example.com/blue.jpg,2
        t-shirt,,Color,Blue,Size,M,TS-B-M,15.00,220,6,true,,
    """

    def setup_method(self):
        self.path = _csv(self.CSV)
        self.adapter = ShopifyAdapter()
        self.df = self.adapter.read(self.path)
        self.products = self.adapter.normalize(self.df)

    def teardown_method(self):
        _cleanup(self.path)

    def test_one_product(self):
        assert len(self.products) == 1

    def test_four_variants(self):
        assert len(self.products[0].variants) == 4

    def test_option_names(self):
        p = self.products[0]
        assert p.option1_name == "Color"
        assert p.option2_name == "Size"

    def test_variant_skus(self):
        skus = [v.sku for v in self.products[0].variants]
        assert "TS-R-S" in skus
        assert "TS-B-M" in skus

    def test_two_images(self):
        assert len(self.products[0].images) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Multiple products in one file
# ─────────────────────────────────────────────────────────────────────────────

class TestMultipleProducts:
    CSV = """\
        Handle,Title,Option1 Name,Option1 Value,Variant SKU,Variant Price,Variant Grams,Variant Inventory Qty,Variant Taxable,Image Src,Image Position
        prod-a,Product A,Title,Default Title,A-001,10.00,100,5,true,http://cdn.example.com/a.jpg,1
        prod-b,Product B,Title,Default Title,B-001,20.00,200,3,true,http://cdn.example.com/b.jpg,1
    """

    def setup_method(self):
        self.path = _csv(self.CSV)
        self.adapter = ShopifyAdapter()
        self.df = self.adapter.read(self.path)
        self.products = self.adapter.normalize(self.df)

    def teardown_method(self):
        _cleanup(self.path)

    def test_two_products(self):
        assert len(self.products) == 2

    def test_handles(self):
        handles = {p.handle for p in self.products}
        assert handles == {"prod-a", "prod-b"}


# ─────────────────────────────────────────────────────────────────────────────
# Published / status parsing
# ─────────────────────────────────────────────────────────────────────────────

class TestPublishedStatus:
    def _product(self, published: str, status: str = "active"):
        csv = f"""\
Handle,Title,Option1 Name,Option1 Value,Variant SKU,Variant Price,Variant Taxable,Published,Status
prod,Product,Title,Default Title,SKU,9.99,true,{published},{status}
"""
        path = _csv(csv)
        adapter = ShopifyAdapter()
        df = adapter.read(path)
        products = adapter.normalize(df)
        _cleanup(path)
        return products[0]

    def test_published_true(self):
        assert self._product("true").published is True

    def test_published_false(self):
        assert self._product("false").published is False

    def test_status_draft(self):
        p = self._product("true", "draft")
        assert p.status == "draft"

    def test_status_active(self):
        p = self._product("true", "active")
        assert p.status == "active"


# ─────────────────────────────────────────────────────────────────────────────
# Duplicate image de-duplication
# ─────────────────────────────────────────────────────────────────────────────

class TestDuplicateImages:
    CSV = """\
        Handle,Title,Option1 Name,Option1 Value,Variant SKU,Variant Price,Variant Taxable,Image Src,Image Position
        prod-x,Product X,Title,Default Title,X-001,5.00,true,http://cdn.example.com/same.jpg,1
        prod-x,,,,,,,,http://cdn.example.com/same.jpg,2
    """

    def setup_method(self):
        self.path = _csv(self.CSV)
        self.adapter = ShopifyAdapter()
        self.df = self.adapter.read(self.path)
        self.products = self.adapter.normalize(self.df)

    def teardown_method(self):
        _cleanup(self.path)

    def test_duplicate_images_deduplicated(self):
        """The same URL appearing twice should result in only one image entry."""
        assert len(self.products[0].images) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Product with no variants (after filtering image rows)
# ─────────────────────────────────────────────────────────────────────────────

class TestNoVariantRows:
    """A product whose rows are all image-only should be skipped entirely."""

    CSV = """\
        Handle,Title,Variant Price,Image Src,Image Position
        ghost-product,Ghost,,,http://cdn.example.com/ghost.jpg,1
    """

    def setup_method(self):
        self.path = _csv(self.CSV)
        self.adapter = ShopifyAdapter()
        self.df = self.adapter.read(self.path)
        self.products = self.adapter.normalize(self.df)

    def teardown_method(self):
        _cleanup(self.path)

    def test_product_skipped(self):
        assert len(self.products) == 0
