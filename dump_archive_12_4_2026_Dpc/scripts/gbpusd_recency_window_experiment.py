#!/usr/bin/env python3
"""GBPUSD minute-data ingestion for the recency experiment.

This first stage only downloads or loads the raw 1m data, normalizes the OHLC
columns, and writes a CSV snapshot. Later commits in this branch add the
higher-timeframe feature engineering and walk-forward evaluation.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

try:  # pragma: no cover - optional dependency in some environments
    import yfinance as yf
except Exception:  # pragma: no cover - handled at runtime
    yf = None

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = ROOT / "analysis_outputs"


def _setup_logging(output_dir: Path) -> logging.Logger:
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("gbpusd_recency")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s")
    file_handler = logging.FileHandler(output_dir / "gbpusd_recency_experiment.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def _parse_int_list(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _parse_float_list(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def _drop_timezone(index: pd.Index) -> pd.DatetimeIndex:
    dt_index = pd.DatetimeIndex(pd.to_datetime(index))
    if getattr(dt_index, "tz", None) is not None:
        dt_index = dt_index.tz_localize(None)
    return dt_index


def _normalize_price_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        raise RuntimeError("Downloaded GBPUSD data is empty")

    data = frame.copy()
    data.index = _drop_timezone(data.index)

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [str(column[0]) if isinstance(column, tuple) else str(column) for column in data.columns]

    rename_map: dict[str, str] = {}
    for column in data.columns:
        key = str(column).strip().lower()
        if key in {"open", "high", "low", "close", "volume"}:
            rename_map[column] = key
    data = data.rename(columns=rename_map)

    required = ["open", "high", "low", "close"]
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise RuntimeError(f"GBPUSD data is missing required columns: {missing}")

    keep_columns = [column for column in ["open", "high", "low", "close", "volume"] if column in data.columns]
    data = data[keep_columns].astype(float)
    data = data.sort_index()
    data = data[~data.index.duplicated(keep="last")]
    data = data.dropna(subset=["open", "high", "low", "close"])
    return data


def load_gbpusd_1m_data(
    *,
    symbol: str,
    period: str,
    interval: str,
    input_csv: Path | None,
    logger: logging.Logger,
) -> pd.DataFrame:
    if input_csv is not None:
        logger.info("Loading GBPUSD minute data from CSV: %s", input_csv)
        raw = pd.read_csv(input_csv)
        datetime_column = next(
            (column for column in raw.columns if str(column).strip().lower() in {"timestamp", "datetime", "date", "time"}),
            None,
        )
        if datetime_column is None:
            raise RuntimeError("CSV input must include a timestamp/datetime/date/time column")
        raw[datetime_column] = pd.to_datetime(raw[datetime_column], utc=True, errors="coerce").dt.tz_localize(None)
        data = raw.rename(columns={datetime_column: "timestamp"}).set_index("timestamp")
        return _normalize_price_frame(data)

    if yf is None:  # pragma: no cover - runtime dependency guard
        raise ImportError("yfinance is required to download GBPUSD 1m data")

    logger.info("Downloading %s data from yfinance: period=%s interval=%s", symbol, period, interval)
    raw = yf.download(
        symbol,
        period=period,
        interval=interval,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise RuntimeError(f"No GBPUSD data downloaded for {symbol}")
    return _normalize_price_frame(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and snapshot GBPUSD 1m data")
    parser.add_argument("--symbol", default="GBPUSD=X")
    parser.add_argument("--period", default="7d", help="yfinance period for 1m data, e.g. 7d or 30d")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--input-csv", default=None, help="Optional local CSV with minute data instead of yfinance")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT / "gbpusd_recency_experiment"))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    logger = _setup_logging(output_dir)
    logger.info("Starting GBPUSD recency experiment")
    logger.info("Output directory: %s", output_dir)

    input_csv = Path(args.input_csv) if args.input_csv else None
    price_data = load_gbpusd_1m_data(
        symbol=args.symbol,
        period=args.period,
        interval=args.interval,
        input_csv=input_csv,
        logger=logger,
    )

    raw_csv = output_dir / "gbpusd_1m_raw.csv"
    price_data.to_csv(raw_csv, index_label="timestamp")
    logger.info("Saved raw minute data to %s", raw_csv)
    print(f"Saved {len(price_data)} bars to {raw_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
