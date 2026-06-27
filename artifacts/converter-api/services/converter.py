"""Conversion orchestrator — Shopify → WooCommerce."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import pandas as pd

from adapters.shopify import ShopifyAdapter
from adapters.woocommerce import WooCommerceAdapter
from models.schemas import ConversionResult, ValidationResult
from services.report_generator import (
    generate_conversion_log,
    generate_migration_report,
    generate_validation_html,
)

_log = logging.getLogger(__name__)


class ConversionLogger:
    """
    Lightweight structured log buffer for per-conversion messages.

    Each entry is also forwarded to the stdlib logger so it appears in the
    server's output alongside normal request logs.
    """

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.warning_count = 0
        self.error_count = 0

    def _append(self, level: str, message: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        line = f"[{ts}] [{level}] {message}"
        self.lines.append(line)
        getattr(_log, level.lower(), _log.info)(message)

    def info(self, msg: str) -> None:
        self._append("INFO", msg)

    def warn(self, msg: str) -> None:
        self.warning_count += 1
        self._append("WARNING", msg)

    def error(self, msg: str) -> None:
        self.error_count += 1
        self._append("ERROR", msg)


def convert(
    filepath: str,
    output_dir: str,
    validation_result: ValidationResult | None = None,
) -> ConversionResult:
    logger = ConversionLogger()
    start = time.perf_counter()

    logger.info(f"Starting conversion of '{os.path.basename(filepath)}'")

    # ── Read ──────────────────────────────────────────────────────────────
    shopify = ShopifyAdapter()
    try:
        df = shopify.read(filepath)
        logger.info(f"Loaded {len(df)} row(s) from source file.")
    except Exception as exc:
        logger.error(f"Failed to read source file: {exc}")
        return ConversionResult(
            products_converted=0,
            products_failed=1,
            variants_converted=0,
            warnings=logger.warning_count,
            errors=logger.error_count,
            categories_mapped=0,
            tags_preserved=0,
            images_mapped=0,
            execution_time_seconds=round(time.perf_counter() - start, 3),
            output_files=[],
            log_lines=logger.lines,
        )

    # ── Normalize ─────────────────────────────────────────────────────────
    try:
        products = shopify.normalize(df)
        logger.info(f"Normalized {len(products)} product(s).")
    except Exception as exc:
        logger.error(f"Normalization failed: {exc}")
        products = []

    # ── Per-product metrics ────────────────────────────────────────────────
    products_converted = 0
    products_failed = 0
    variants_converted = 0
    categories_mapped = 0
    tags_preserved = 0
    images_mapped = 0
    valid_products = []

    for p in products:
        if not p.title:
            logger.warn(f"Product '{p.handle}' has no title — skipping.")
            products_failed += 1
            continue
        valid_products.append(p)
        products_converted += 1
        variants_converted += len(p.variants)
        images_mapped += len(p.images)
        if p.product_type:
            categories_mapped += 1
        tags_preserved += len(p.tags)

    logger.info(
        f"Products: {products_converted} converted, {products_failed} skipped. "
        f"Variants: {variants_converted}. Images: {images_mapped}."
    )

    # ── Export to WooCommerce CSV ──────────────────────────────────────────
    output_files: list[str] = []
    woo_output = os.path.join(output_dir, "woocommerce_products.csv")
    woo = WooCommerceAdapter()
    try:
        rows_written = woo.export(valid_products, woo_output)
        output_files.append("woocommerce_products.csv")
        logger.info(f"Exported {rows_written} WooCommerce row(s).")
    except Exception as exc:
        logger.error(f"WooCommerce export failed: {exc}")

    # ── Migration report ──────────────────────────────────────────────────
    provisional = ConversionResult(
        products_converted=products_converted,
        products_failed=products_failed,
        variants_converted=variants_converted,
        warnings=logger.warning_count,
        errors=logger.error_count,
        categories_mapped=categories_mapped,
        tags_preserved=tags_preserved,
        images_mapped=images_mapped,
        execution_time_seconds=round(time.perf_counter() - start, 3),
        output_files=output_files,
        log_lines=logger.lines,
    )

    report_path = os.path.join(output_dir, "migration_report.txt")
    try:
        generate_migration_report(os.path.basename(filepath), provisional, report_path)
        output_files.append("migration_report.txt")
        logger.info("Generated migration_report.txt")
    except Exception as exc:
        logger.error(f"Failed to write migration_report.txt: {exc}")

    # ── HTML validation report ─────────────────────────────────────────────
    if validation_result is not None:
        html_path = os.path.join(output_dir, "validation_report.html")
        try:
            generate_validation_html(
                os.path.basename(filepath), validation_result, html_path
            )
            output_files.append("validation_report.html")
            logger.info("Generated validation_report.html")
        except Exception as exc:
            logger.error(f"Failed to write validation_report.html: {exc}")

    # ── Conversion log ─────────────────────────────────────────────────────
    logger.info("Conversion complete.")
    log_path = os.path.join(output_dir, "conversion_log.txt")
    try:
        generate_conversion_log(logger.lines, log_path)
        output_files.append("conversion_log.txt")
    except Exception as exc:
        logger.error(f"Failed to write conversion_log.txt: {exc}")

    elapsed = round(time.perf_counter() - start, 3)
    logger.info(f"Total elapsed time: {elapsed}s")

    return ConversionResult(
        products_converted=products_converted,
        products_failed=products_failed,
        variants_converted=variants_converted,
        warnings=logger.warning_count,
        errors=logger.error_count,
        categories_mapped=categories_mapped,
        tags_preserved=tags_preserved,
        images_mapped=images_mapped,
        execution_time_seconds=elapsed,
        output_files=output_files,
        log_lines=logger.lines,
    )
