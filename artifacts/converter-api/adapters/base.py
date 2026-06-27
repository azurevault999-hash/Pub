"""
Base adapter interfaces for the import/export pipeline.
New importers (Magento, BigCommerce, OpenCart, PrestaShop) implement ImportAdapter.
New exporters implement ExportAdapter.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
import pandas as pd


@dataclass
class NormalizedProduct:
    """Platform-agnostic product representation."""
    handle: str
    title: str
    body_html: str
    vendor: str
    product_type: str
    tags: list[str]
    published: bool
    seo_title: str
    seo_description: str
    status: str
    # Options (up to 3)
    option1_name: str = ""
    option2_name: str = ""
    option3_name: str = ""
    # Images: list of (src, position, alt)
    images: list[tuple[str, int, str]] = field(default_factory=list)
    # Variants
    variants: list[NormalizedVariant] = field(default_factory=list)
    # Extra metadata for future use
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedVariant:
    """Platform-agnostic variant representation."""
    sku: str
    option1_value: str = ""
    option2_value: str = ""
    option3_value: str = ""
    price: str = ""
    compare_at_price: str = ""
    weight_grams: float = 0.0
    inventory_qty: int = 0
    taxable: bool = True
    barcode: str = ""
    image_src: str = ""
    requires_shipping: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


class ImportAdapter(ABC):
    """Abstract base class for all import adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable adapter name."""
        ...

    @property
    @abstractmethod
    def supported_columns(self) -> list[str]:
        """Column names this adapter recognises."""
        ...

    @abstractmethod
    def read(self, filepath: str) -> pd.DataFrame:
        """Read raw data from source file into a DataFrame."""
        ...

    @abstractmethod
    def normalize(self, df: pd.DataFrame) -> list[NormalizedProduct]:
        """Convert raw DataFrame into normalized products."""
        ...


class ExportAdapter(ABC):
    """Abstract base class for all export adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable adapter name."""
        ...

    @abstractmethod
    def export(self, products: list[NormalizedProduct], output_path: str) -> int:
        """Write products to output_path. Returns number of rows written."""
        ...
