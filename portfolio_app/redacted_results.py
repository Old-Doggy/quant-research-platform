"""Load the reviewed aggregate result layer without exposing private artifacts."""

from __future__ import annotations

from pathlib import Path
import re

import pandas as pd


REDACTED_RESULT_COLUMNS = [
    "model",
    "evidence_case",
    "asset_scope",
    "status",
    "status_label",
    "period",
    "annual_return",
    "sharpe",
    "max_drawdown",
    "cost_assumption",
    "limitations",
    "source_label",
]

PUBLIC_SOURCE_LABEL = "curated research summary"
SUMMARY_FILES = {f"model{number}": f"model{number}_summary.csv" for number in range(1, 7)}
REQUIRED_RESULT_COLUMNS = {
    "model",
    "evidence_case",
    "asset_scope",
    "status",
    "status_label",
    "period",
    "annual_return",
    "sharpe",
    "max_drawdown",
    "cost_assumption",
    "limitations",
}
FORBIDDEN_RESULT_FIELDS = {
    "exact_parameters",
    "parameters",
    "model_weights",
    "target_positions",
    "holdings",
    "account_id",
    "broker_account",
    "raw_data_path",
    "private_path",
}

_PRIVATE_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\|/(?:home|Users|mnt|tmp)/|(?:data/output|模型7/output|output/latest))[^,;\n]*",
    re.IGNORECASE,
)


def _safe_text(value: object) -> str:
    """Remove path-shaped text from the small set of public narrative fields."""
    if pd.isna(value):
        return ""
    return _PRIVATE_PATH.sub("[redacted source]", str(value))


def redact_result_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return only aggregate fields approved for portfolio presentation."""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=REDACTED_RESULT_COLUMNS)

    result = pd.DataFrame(index=frame.index)
    for column in REDACTED_RESULT_COLUMNS:
        if column == "source_label":
            result[column] = PUBLIC_SOURCE_LABEL
        elif column in {"annual_return", "sharpe", "max_drawdown"}:
            result[column] = pd.to_numeric(frame.get(column), errors="coerce")
        else:
            values = frame[column] if column in frame else pd.Series("", index=frame.index)
            result[column] = values.map(_safe_text)
    return result[REDACTED_RESULT_COLUMNS].reset_index(drop=True)


def validate_redacted_input(frame: pd.DataFrame) -> None:
    """Reject result bundles that are incomplete or contain private payload fields."""
    missing = sorted(REQUIRED_RESULT_COLUMNS.difference(frame.columns))
    if missing:
        raise ValueError(f"redacted result is missing required columns: {', '.join(missing)}")
    forbidden = sorted(FORBIDDEN_RESULT_FIELDS.intersection(frame.columns))
    if forbidden:
        raise ValueError(f"redacted result contains forbidden fields: {', '.join(forbidden)}")
    if "source" in frame.columns:
        source_values = frame["source"].dropna().astype(str)
        if any(value != PUBLIC_SOURCE_LABEL for value in source_values):
            raise ValueError("redacted result source must use the curated public label")


def _read_summary(root: Path, filename: str) -> pd.DataFrame:
    path = root / "public_evidence" / filename
    if not path.is_file():
        raise FileNotFoundError(path)
    return pd.read_csv(path)


def load_redacted_results(project_root: str | Path) -> list[dict[str, object]]:
    """Load model 1-6 aggregate summaries from the reviewed evidence directory."""
    root = Path(project_root)
    rows: list[dict[str, object]] = []
    for _, filename in SUMMARY_FILES.items():
        try:
            frame = _read_summary(root, filename)
            validate_redacted_input(frame)
            rows.extend(redact_result_frame(frame).to_dict("records"))
        except (FileNotFoundError, pd.errors.ParserError):
            continue
    return rows


def load_redacted_model7_results(project_root: str | Path) -> list[dict[str, object]]:
    """Load model 7 while preserving selection, latest and runtime evidence layers."""
    root = Path(project_root)
    try:
        frame = _read_summary(root, "model7_summary.csv")
        validate_redacted_input(frame)
        return redact_result_frame(frame).to_dict("records")
    except (FileNotFoundError, pd.errors.ParserError):
        return []


def load_redacted_annual_oos(project_root: str | Path) -> list[dict[str, object]]:
    """Load the reviewed annual OOS table with its source field removed."""
    root = Path(project_root)
    try:
        frame = _read_summary(root, "model3_annual_oos.csv")
    except (FileNotFoundError, pd.errors.ParserError):
        return []
    allowed = [
        "model",
        "year",
        "period_start",
        "period_end",
        "days",
        "annual_return",
        "sharpe",
        "max_drawdown",
        "ending_nav",
        "evidence_case",
        "status",
        "status_label",
        "cost_assumption",
        "limitations",
    ]
    result = frame.reindex(columns=allowed).copy()
    for column in ("annual_return", "sharpe", "max_drawdown", "ending_nav"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    for column in ("model", "year", "period_start", "period_end", "evidence_case", "status", "status_label", "cost_assumption", "limitations"):
        result[column] = result[column].map(_safe_text)
    return result.to_dict("records")
