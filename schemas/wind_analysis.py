"""Pydantic input schema for wind analysis."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, field_validator


class WindAnalysisInput(BaseModel):
    excel_path: str

    @field_validator("excel_path")
    @classmethod
    def _validate_excel_path(cls, value: str) -> str:
        p = Path(str(value)).expanduser()
        if not p.exists() or not p.is_file():
            raise ValueError(f"excel file not found: {value}")
        if p.suffix.lower() not in {".xlsx", ".xls"}:
            raise ValueError(f"unsupported excel extension: {p.suffix}")
        return str(p.resolve())

