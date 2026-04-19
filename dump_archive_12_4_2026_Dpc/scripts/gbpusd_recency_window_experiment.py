#!/usr/bin/env python3
"""GBPUSD minute-data ingestion for the recency experiment.

This first stage only downloads or loads the raw 1m data, normalizes the OHLC
columns, and writes a CSV snapshot. Later commits in this branch add the
higher-timeframe feature engineering and walk-forward evaluation.
"""

from __future__ import annotations

import argparse
import logging
import numpy as np
from pathlib import Path

import pandas as pd

try:  # pragma: no cover - optional dependency in some environments
    import yfinance as yf
except Exception:  # pragma: no cover - handled at runtime
    yf = None

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = ROOT / "analysis_outputs"
TIMEFRAMES = ("5min", "15min", "1h", "4h")
TIMEFRAME_WEIGHTS = {
    "5min": 0.10,
    "15min": 0.15,
    "1h": 0.25,
    "4h": 0.50,
}


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


def _resample_ohlc(data: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    aggregation: dict[str, str] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if "volume" in data.columns:
        aggregation["volume"] = "sum"

    resampled = data.resample(timeframe, label="right", closed="right").agg(aggregation)
    resampled = resampled.dropna(subset=["open", "high", "low", "close"])
    return resampled


def _trend_score_series(bars: pd.DataFrame, fast_span: int, slow_span: int) -> pd.Series:
    close = bars["close"].astype(float)
    fast = close.ewm(span=fast_span, adjust=False).mean()
    slow = close.ewm(span=slow_span, adjust=False).mean()
    raw_gap = (fast - slow) / close.replace(0.0, np.nan)
    volatility = close.pct_change().rolling(max(5, slow_span // 2), min_periods=max(3, fast_span // 2)).std()
    score = raw_gap / volatility.replace(0.0, np.nan)
    score = score.replace([np.inf, -np.inf], np.nan).ffill().fillna(0.0)
    score.index.name = "timestamp"
    return score


def build_feature_frame(data: pd.DataFrame, fast_span: int, slow_span: int) -> pd.DataFrame:
    minute = data.copy()
    minute.index.name = "timestamp"
    feature_frame = minute[["close"]].reset_index().sort_values("timestamp")

    for timeframe in TIMEFRAMES:
        resampled = _resample_ohlc(minute, timeframe)
        if resampled.empty:
            feature_frame[f"score_{timeframe}"] = 0.0
            continue

        score = _trend_score_series(resampled, fast_span=fast_span, slow_span=slow_span).rename(f"score_{timeframe}")
        score_frame = score.reset_index().sort_values("timestamp")
        feature_frame = pd.merge_asof(feature_frame, score_frame, on="timestamp", direction="backward")

    for timeframe in TIMEFRAMES:
        column = f"score_{timeframe}"
        feature_frame[column] = feature_frame[column].fillna(0.0).astype(float)

    feature_frame["composite_score"] = 0.0
    for timeframe in TIMEFRAMES:
        feature_frame["composite_score"] += feature_frame[f"score_{timeframe}"] * TIMEFRAME_WEIGHTS[timeframe]
    feature_frame["composite_score"] = feature_frame["composite_score"].replace([np.inf, -np.inf], np.nan).fillna(0.0)

    return feature_frame.set_index("timestamp").sort_index()


def _signal_from_scores(feature_frame: pd.DataFrame, threshold: float) -> pd.Series:
    signal = pd.Series(0, index=feature_frame.index, dtype=int)
    signal.loc[feature_frame["composite_score"] > threshold] = 1
    signal.loc[feature_frame["composite_score"] < -threshold] = -1
    signal.name = "signal"
    return signal


def _period_metrics(period_frame: pd.DataFrame, *, initial_equity: float = 1000.0, cost_bps: float = 0.0) -> tuple[pd.Series, dict[str, float]]:
    if period_frame.empty or len(period_frame) < 2:
        return pd.Series(dtype=float), {
            "final_equity_eur": initial_equity,
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "annualized_volatility_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": 0.0,
            "num_bars": float(len(period_frame)),
            "hit_rate_pct": 0.0,
            "turnover": 0.0,
        }

    closes = period_frame["close"].astype(float).to_numpy()
    signals = period_frame["signal"].astype(float).to_numpy()
    next_returns = closes[1:] / closes[:-1] - 1.0

    cost_rate = cost_bps / 10000.0
    turnover = np.empty(len(next_returns), dtype=float)
    previous_position = 0.0
    for i, position in enumerate(signals[:-1]):
        turnover[i] = abs(position - previous_position)
        previous_position = position

    net_returns = signals[:-1] * next_returns - turnover * cost_rate
    equity = np.empty(len(period_frame), dtype=float)
    equity[0] = initial_equity
    for i, period_return in enumerate(net_returns, start=1):
        equity[i] = equity[i - 1] * (1.0 + period_return)

    equity_series = pd.Series(equity, index=period_frame.index, name="equity_eur")
    positive_equity = equity_series[equity_series > 0]
    if positive_equity.empty:
        return equity_series, {
            "final_equity_eur": initial_equity,
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "annualized_volatility_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": 0.0,
            "num_bars": float(len(period_frame)),
            "hit_rate_pct": 0.0,
            "turnover": float(turnover.sum()),
        }

    returns_series = equity_series.pct_change().dropna()
    years = max((positive_equity.index[-1] - positive_equity.index[0]).total_seconds() / (365.25 * 24 * 3600), 1.0 / (365.25 * 24 * 60))
    final_equity = float(positive_equity.iloc[-1])
    total_return = final_equity / initial_equity - 1.0
    cagr = (final_equity / initial_equity) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    annualization = 365.25 * 24 * 60
    volatility = float(returns_series.std() * np.sqrt(annualization)) if not returns_series.empty else 0.0
    sharpe = float((returns_series.mean() / returns_series.std()) * np.sqrt(annualization)) if returns_series.std() and returns_series.std() > 0 else 0.0
    drawdown = equity_series / equity_series.cummax() - 1.0
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0
    hit_rate = float((net_returns > 0).mean()) if len(net_returns) else 0.0
    return equity_series, {
        "final_equity_eur": final_equity,
        "total_return_pct": total_return * 100.0,
        "cagr_pct": cagr * 100.0,
        "annualized_volatility_pct": volatility * 100.0,
        "max_drawdown_pct": max_drawdown * 100.0,
        "sharpe": sharpe,
        "num_bars": float(len(period_frame)),
        "hit_rate_pct": hit_rate * 100.0,
        "turnover": float(turnover.sum()),
    }


def _score_metrics(metrics: dict[str, float]) -> float:
    return float(metrics["cagr_pct"] - 0.4 * abs(metrics["max_drawdown_pct"]) + 0.35 * metrics["sharpe"])


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
