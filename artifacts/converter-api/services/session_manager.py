"""In-memory session store for uploaded CSV files and conversion results."""
from __future__ import annotations
import uuid
import tempfile
import os
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any
import pandas as pd

from models.schemas import AnalysisResult, ValidationResult, ConversionResult


@dataclass
class Session:
    session_id: str
    filename: str
    size_bytes: int
    row_count: int
    status: str
    created_at: str
    filepath: str
    df: pd.DataFrame | None = None
    analysis: AnalysisResult | None = None
    validation: ValidationResult | None = None
    conversion: ConversionResult | None = None
    output_dir: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._tmp_dir = tempfile.mkdtemp(prefix="shopify_converter_")

    def create_session(
        self,
        filename: str,
        size_bytes: int,
        filepath: str,
        df: pd.DataFrame,
        analysis: AnalysisResult,
    ) -> Session:
        sid = str(uuid.uuid4())
        output_dir = os.path.join(self._tmp_dir, sid)
        os.makedirs(output_dir, exist_ok=True)
        session = Session(
            session_id=sid,
            filename=filename,
            size_bytes=size_bytes,
            row_count=len(df),
            status="ready",
            created_at=datetime.now(timezone.utc).isoformat(),
            filepath=filepath,
            df=df,
            analysis=analysis,
            output_dir=output_dir,
        )
        self._sessions[sid] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def update_validation(self, session_id: str, result: ValidationResult) -> None:
        s = self._sessions.get(session_id)
        if s:
            s.validation = result

    def update_conversion(self, session_id: str, result: ConversionResult) -> None:
        s = self._sessions.get(session_id)
        if s:
            s.conversion = result
            s.status = "converted"

    def get_output_path(self, session_id: str, filename: str) -> str | None:
        s = self._sessions.get(session_id)
        if not s:
            return None
        path = os.path.join(s.output_dir, filename)
        return path if os.path.exists(path) else None


# Global singleton
session_manager = SessionManager()
