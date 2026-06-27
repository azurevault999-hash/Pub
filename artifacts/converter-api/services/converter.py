"""Conversion orchestrator — Shopify → WooCommerce."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

from adapters.shopify import ShopifyAdapter
from adapters.woocommerce import (
    WooCommerceAdapter, _is_variable, _active_option_count, _all_option_values,
    verify_woocommerce_csv, compare_schema_to_reference,
)
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

    # ── Per-product metrics and logging ───────────────────────────────────
    products_converted = 0
    products_failed = 0
    variants_converted = 0
    categories_mapped = 0
    tags_preserved = 0
    images_mapped = 0
    simple_products = 0
    variable_products = 0
    valid_products = []

    for p in products:
        if not p.title:
            logger.warn(f"Product '{p.handle}' has no title — skipping.")
            products_failed += 1
            continue

        variable = _is_variable(p)
        product_type_label = "variable" if variable else "simple"
        active_opts = _active_option_count(p)

        logger.info(
            f"[PRODUCT] handle={p.handle!r} type={product_type_label} "
            f"variants={len(p.variants)} options={active_opts} images={len(p.images)}"
        )

        # Log each attribute mapping decision.
        for name, idx, num in [
            (p.option1_name, 0, "1"),
            (p.option2_name, 1, "2"),
            (p.option3_name, 2, "3"),
        ]:
            if name:
                if name.lower() == "title" and not variable:
                    logger.info(
                        f"[ATTR SKIP] handle={p.handle!r} "
                        f"option{num}_name={name!r} — Shopify placeholder, not exported as attribute"
                    )
                else:
                    all_vals = _all_option_values(p, idx)
                    logger.info(
                        f"[ATTR MAP] handle={p.handle!r} "
                        f"Attribute {num}: {name!r} → {all_vals!r}"
                    )

        # Log each variation being generated.
        if variable:
            for i, v in enumerate(p.variants):
                logger.info(
                    f"[VARIATION] handle={p.handle!r} idx={i} sku={v.sku!r} "
                    f"opt1={v.option1_value!r} opt2={v.option2_value!r} opt3={v.option3_value!r} "
                    f"price={v.price!r}"
                )

        valid_products.append(p)
        products_converted += 1
        variants_converted += len(p.variants)
        images_mapped += len(p.images)
        if p.product_type:
            categories_mapped += 1
        tags_preserved += len(p.tags)
        if variable:
            variable_products += 1
        else:
            simple_products += 1

    logger.info(
        f"Products: {products_converted} converted ({simple_products} simple, "
        f"{variable_products} variable), {products_failed} skipped. "
        f"Variants: {variants_converted}. Images: {images_mapped}."
    )

    # ── Schema sanity check ────────────────────────────────────────────────
    schema_check = compare_schema_to_reference()
    if schema_check["schema_valid"]:
        logger.info(
            f"Column schema matches WooCommerce 10.9.1 reference "
            f"({schema_check['our_column_count']} columns, "
            f"{schema_check['reference_column_count']} in reference)."
        )
    else:
        for missing in schema_check["missing_from_ours"]:
            logger.warn(f"[SCHEMA] Column missing vs WooCommerce 10.9.1 reference: '{missing}'")

    # ── Export to WooCommerce CSV ──────────────────────────────────────────
    output_files: list[str] = []
    woo_output = os.path.join(output_dir, "woocommerce_products.csv")
    audit_output = os.path.join(output_dir, "variation_audit.csv")
    woo = WooCommerceAdapter()
    rows_written = 0
    try:
        rows_written = woo.export(valid_products, woo_output, audit_path=audit_output)
        output_files.append("woocommerce_products.csv")
        logger.info(f"Exported {rows_written} WooCommerce row(s) to CSV.")
        if os.path.isfile(audit_output):
            output_files.append("variation_audit.csv")
            logger.info("Generated variation_audit.csv")
    except Exception as exc:
        logger.error(f"WooCommerce export failed: {exc}")

    # ── Post-export verification ───────────────────────────────────────────
    verification_errors: list[str] = []
    if rows_written > 0 and os.path.isfile(woo_output):
        logger.info("Running post-export WooCommerce CSV verification…")
        try:
            verification_errors = verify_woocommerce_csv(woo_output)
            if verification_errors:
                for ve in verification_errors:
                    logger.warn(f"[VERIFY] {ve}")
                logger.warn(
                    f"Verification found {len(verification_errors)} issue(s). "
                    "Review the migration report for details."
                )
            else:
                logger.info(
                    "Verification passed — CSV structure is valid for "
                    "WooCommerce 10.9.1 native importer."
                )
        except Exception as exc:
            logger.warn(f"Post-export verification failed to run: {exc}")

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
        simple_products=simple_products,
        variable_products=variable_products,
        verification_errors=verification_errors,
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
        simple_products=simple_products,
        variable_products=variable_products,
        verification_errors=verification_errors,
    )
