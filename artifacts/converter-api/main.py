"""
Shopify → WooCommerce CSV Converter — FastAPI backend.

Start with:
    uvicorn main:app --host 0.0.0.0 --port $PORT --reload
"""
from __future__ import annotations
import os
import tempfile
import traceback
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from adapters.shopify import ShopifyAdapter
from models.schemas import (
    AnalysisResult,
    ConversionResult,
    ErrorResponse,
    HealthStatus,
    SessionInfo,
    UploadResponse,
    ValidationResult,
)
from services.analyzer import analyze
from services.converter import convert
from services.session_manager import session_manager
from services.validator import validate


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Shopify → WooCommerce Converter",
    version="1.0.0",
    lifespan=lifespan,
)

BASE_PATH = os.environ.get("BASE_PATH", "/api")

# Strip trailing slash from base path for prefix matching
_api_prefix = BASE_PATH.rstrip("/")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────── Health ───────────────────────


@app.get(f"{_api_prefix}/healthz", response_model=HealthStatus, tags=["health"])
async def health_check() -> HealthStatus:
    return HealthStatus(status="ok")


# ─────────────────────── Upload ───────────────────────


@app.post(f"{_api_prefix}/upload", response_model=UploadResponse, tags=["upload"])
async def upload_file(file: UploadFile = File(...)) -> UploadResponse:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    MAX_SIZE = 100 * 1024 * 1024  # 100 MB

    # Write to a temp file
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 100 MB limit.")

    suffix = ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        adapter = ShopifyAdapter()
        df = adapter.read(tmp_path)
        analysis = analyze(df)
        session = session_manager.create_session(
            filename=file.filename,
            size_bytes=len(content),
            filepath=tmp_path,
            df=df,
            analysis=analysis,
        )
    except Exception as exc:
        os.unlink(tmp_path)
        raise HTTPException(status_code=400, detail=f"Failed to parse CSV: {exc}") from exc

    return UploadResponse(
        session_id=session.session_id,
        filename=session.filename,
        size_bytes=session.size_bytes,
        row_count=session.row_count,
        status=session.status,
        analysis=analysis,
    )


# ─────────────────────── Session ───────────────────────


@app.get(f"{_api_prefix}/sessions/{{session_id}}", response_model=SessionInfo, tags=["upload"])
async def get_session(session_id: str) -> SessionInfo:
    session = session_manager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return SessionInfo(
        session_id=session.session_id,
        filename=session.filename,
        size_bytes=session.size_bytes,
        row_count=session.row_count,
        status=session.status,
        created_at=session.created_at,
        has_analysis=session.analysis is not None,
        has_validation=session.validation is not None,
        has_conversion=session.conversion is not None,
    )


# ─────────────────────── Analysis ───────────────────────


@app.get(f"{_api_prefix}/sessions/{{session_id}}/analysis", response_model=AnalysisResult, tags=["analysis"])
async def get_analysis(session_id: str) -> AnalysisResult:
    session = session_manager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session.analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not available.")
    return session.analysis


# ─────────────────────── Validation ───────────────────────


@app.post(f"{_api_prefix}/sessions/{{session_id}}/validate", response_model=ValidationResult, tags=["validation"])
async def run_validation(session_id: str) -> ValidationResult:
    session = session_manager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session.df is None:
        raise HTTPException(status_code=400, detail="No data available for validation.")
    try:
        result = validate(session.df)
        session_manager.update_validation(session_id, result)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Validation error: {exc}") from exc


@app.get(f"{_api_prefix}/sessions/{{session_id}}/validation", response_model=ValidationResult, tags=["validation"])
async def get_validation(session_id: str) -> ValidationResult:
    session = session_manager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session.validation is None:
        raise HTTPException(status_code=404, detail="Validation results not available. Run validation first.")
    return session.validation


# ─────────────────────── Conversion ───────────────────────


@app.post(f"{_api_prefix}/sessions/{{session_id}}/convert", response_model=ConversionResult, tags=["conversion"])
async def run_conversion(session_id: str) -> ConversionResult:
    session = session_manager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    try:
        result = convert(
            filepath=session.filepath,
            output_dir=session.output_dir,
            validation_result=session.validation,
        )
        session_manager.update_conversion(session_id, result)
        return result
    except Exception as exc:
        tb = traceback.format_exc()
        raise HTTPException(status_code=400, detail=f"Conversion failed: {exc}\n{tb}") from exc


@app.get(f"{_api_prefix}/sessions/{{session_id}}/conversion", response_model=ConversionResult, tags=["conversion"])
async def get_conversion(session_id: str) -> ConversionResult:
    session = session_manager.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session.conversion is None:
        raise HTTPException(status_code=404, detail="Conversion results not available. Run conversion first.")
    return session.conversion


# ─────────────────────── Downloads ───────────────────────


ALLOWED_FILENAMES = {
    "woocommerce_products.csv",
    "migration_report.txt",
    "validation_report.xlsx",
    "conversion_log.txt",
}

MEDIA_TYPES = {
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@app.get(f"{_api_prefix}/sessions/{{session_id}}/download/{{filename}}", tags=["download"])
async def download_file(session_id: str, filename: str) -> FileResponse:
    if filename not in ALLOWED_FILENAMES:
        raise HTTPException(status_code=400, detail=f"File '{filename}' is not an allowed download.")
    path = session_manager.get_output_path(session_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail=f"File '{filename}' not found for this session.")
    ext = os.path.splitext(filename)[1].lower()
    media_type = MEDIA_TYPES.get(ext, "application/octet-stream")
    return FileResponse(path=path, filename=filename, media_type=media_type)
