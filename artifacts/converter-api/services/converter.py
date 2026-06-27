"""Conversion orchestrator — Shopify → WooCommerce."""
from __future__ import annotations
import os
import time
import logging
from datetime import datetime, timezone

import pandas as pd

from adapters.shopify import ShopifyAdapter
from adapters.woocommerce import WooCommerceAdapter
from models.schemas import ConversionResult
from services.report_generator import (
    generate_migration_report,
    generate_validation_xlsx,
    generate_conversion_log,
)
from models.schemas import ValidationResult


class ConversionLogger:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def log(self, level: str, message: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        line = f"[{ts}] [{level.upper()}] {message}"
        self.lines.append(line)

    def info(self, msg: str) -> None:
        self.log("INFO", msg)

    def warn(self, msg: str) -> None:
        self.log("WARNING", msg)

    def error(self, msg: str) -> None:
        self.log("ERROR", msg)


def convert(
    filepath: str,
    output_dir: str,
    validation_result: ValidationResult | None = None,
) -> ConversionResult:
    logger = ConversionLogger()
    start = time.time()
    warnings = 0
    errors = 0

    logger.info(f"Starting conversion of {os.path.basename(filepath)}")

    # Read with Shopify adapter
    shopify = ShopifyAdapter()
    try:
        df = shopify.read(filepath)
        logger.info(f"Loaded {len(df)} rows from source file.")
    except Exception as e:
        logger.error(f"Failed to read source file: {e}")
        return ConversionResult(
            products_converted=0,
            products_failed=1,
            variants_converted=0,
            warnings=0,
            errors=1,
            categories_mapped=0,
            tags_preserved=0,
            images_mapped=0,
            execution_time_seconds=time.time() - start,
            output_files=[],
            log_lines=logger.lines,
        )

    # Normalize products
    try:
        products = shopify.normalize(df)
        logger.info(f"Normalized {len(products)} product(s).")
    except Exception as e:
        logger.error(f"Normalization failed: {e}")
        errors += 1
        products = []

    # Metrics
    products_converted = 0
    products_failed = 0
    variants_converted = 0
    categories_mapped = 0
    tags_preserved = 0
    images_mapped = 0

    for p in products:
        if not p.title:
            logger.warn(f"Product '{p.handle}' has no title — skipping.")
            products_failed += 1
            warnings += 1
            continue
        products_converted += 1
        variants_converted += len(p.variants)
        images_mapped += len(p.images)
        if p.product_type:
            categories_mapped += 1
        tags_preserved += len(p.tags)

    # Export to WooCommerce CSV
    woo_output = os.path.join(output_dir, "woocommerce_products.csv")
    woo = WooCommerceAdapter()
    try:
        valid_products = [p for p in products if p.title]
        rows_written = woo.export(valid_products, woo_output)
        logger.info(f"Exported {rows_written} WooCommerce rows to {os.path.basename(woo_output)}")
    except Exception as e:
        logger.error(f"WooCommerce export failed: {e}")
        errors += 1

    output_files = ["woocommerce_products.csv"]

    # Build a provisional ConversionResult for the report
    provisional = ConversionResult(
        products_converted=products_converted,
        products_failed=products_failed,
        variants_converted=variants_converted,
        warnings=warnings,
        errors=errors,
        categories_mapped=categories_mapped,
        tags_preserved=tags_preserved,
        images_mapped=images_mapped,
        execution_time_seconds=time.time() - start,
        output_files=output_files,
        log_lines=logger.lines,
    )

    # Migration report
    report_path = os.path.join(output_dir, "migration_report.txt")
    try:
        generate_migration_report(os.path.basename(filepath), provisional, report_path)
        output_files.append("migration_report.txt")
        logger.info("Generated migration_report.txt")
    except Exception as e:
        logger.error(f"Failed to generate migration report: {e}")

    # Validation xlsx
    if validation_result is not None:
        xlsx_path = os.path.join(output_dir, "validation_report.xlsx")
        try:
            generate_validation_xlsx(os.path.basename(filepath), validation_result, xlsx_path)
            output_files.append("validation_report.xlsx")
            logger.info("Generated validation_report.xlsx")
        except Exception as e:
            logger.error(f"Failed to generate validation XLSX: {e}")

    # Conversion log
    log_path = os.path.join(output_dir, "conversion_log.txt")
    logger.info("Conversion complete.")
    try:
        generate_conversion_log(logger.lines, log_path)
        output_files.append("conversion_log.txt")
    except Exception as e:
        pass

    elapsed = time.time() - start
    return ConversionResult(
        products_converted=products_converted,
        products_failed=products_failed,
        variants_converted=variants_converted,
        warnings=warnings,
        errors=errors,
        categories_mapped=categories_mapped,
        tags_preserved=tags_preserved,
        images_mapped=images_mapped,
        execution_time_seconds=round(elapsed, 3),
        output_files=output_files,
        log_lines=logger.lines,
    )
