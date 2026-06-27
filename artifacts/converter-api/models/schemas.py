from __future__ import annotations
from typing import Literal
from pydantic import BaseModel


class HealthStatus(BaseModel):
    status: str


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


class AnalysisResult(BaseModel):
    product_count: int
    variant_count: int
    image_count: int
    categories: list[str]
    vendors: list[str]
    product_types: list[str]
    duplicate_skus: int
    missing_prices: int
    missing_images: int
    invalid_html_count: int
    unknown_columns: list[str]
    total_rows: int


class UploadResponse(BaseModel):
    session_id: str
    filename: str
    size_bytes: int
    row_count: int
    status: str
    analysis: AnalysisResult


class SessionInfo(BaseModel):
    session_id: str
    filename: str
    size_bytes: int
    row_count: int
    status: str
    created_at: str
    has_analysis: bool
    has_validation: bool
    has_conversion: bool


class ValidationIssue(BaseModel):
    level: Literal["pass", "info", "warning", "error"]
    check: str
    message: str
    count: int
    details: list[str]


class ValidationResult(BaseModel):
    issues: list[ValidationIssue]
    pass_count: int
    info_count: int
    warning_count: int
    error_count: int
    can_convert: bool


class ConversionResult(BaseModel):
    products_converted: int
    products_failed: int
    variants_converted: int
    warnings: int
    errors: int
    categories_mapped: int
    tags_preserved: int
    images_mapped: int
    execution_time_seconds: float
    output_files: list[str]
    log_lines: list[str]
