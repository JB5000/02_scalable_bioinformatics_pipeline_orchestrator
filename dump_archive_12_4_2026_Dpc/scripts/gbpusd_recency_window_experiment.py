#!/usr/bin/env python3
"""GBPUSD minute-data ingestion for the recency experiment.

This first stage only downloads or loads the raw 1m data, normalizes the OHLC
columns, and writes a CSV snapshot. Later commits in this branch add the
higher-timeframe feature engineering and walk-forward evaluation.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import numpy as np
from pathlib import Path

import matplotlib.pyplot as plt
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


def _window_start_pos(index: pd.DatetimeIndex, cutoff_pos: int, window_label: str) -> int:
    if window_label == "all":
        return 0
    window_hours = int(window_label)
    cutoff_time = index[cutoff_pos]
    start_time = cutoff_time - pd.Timedelta(hours=window_hours)
    return max(0, int(index.searchsorted(start_time, side="left")))


def _evaluate_thresholds(
    feature_frame: pd.DataFrame,
    start_pos: int,
    end_pos_exclusive: int,
    thresholds: list[float],
    cost_bps: float,
) -> tuple[float, dict[str, float], pd.Series]:
    best_threshold = thresholds[0]
    best_metrics: dict[str, float] | None = None
    best_equity: pd.Series | None = None
    best_score = -float("inf")

    period = feature_frame.iloc[start_pos:end_pos_exclusive].copy()
    for threshold in thresholds:
        eval_frame = period.copy()
        eval_frame["signal"] = _signal_from_scores(eval_frame, threshold)
        equity, metrics = _period_metrics(eval_frame, cost_bps=cost_bps)
        score = _score_metrics(metrics)
        if score > best_score:
            best_score = score
            best_threshold = threshold
            best_metrics = metrics
            best_equity = equity

    if best_metrics is None or best_equity is None:
        raise RuntimeError("No threshold candidate could be evaluated")
    return best_threshold, best_metrics, best_equity


def _evaluate_window_fold(
    feature_frame: pd.DataFrame,
    window_label: str,
    cutoff_pos: int,
    test_horizon_bars: int,
    thresholds: list[float],
    cost_bps: float,
) -> tuple[float, dict[str, float], dict[str, float], pd.Series, pd.Series]:
    index = feature_frame.index
    train_start_pos = _window_start_pos(index, cutoff_pos, window_label)
    train_end_pos_exclusive = cutoff_pos
    test_start_pos = cutoff_pos
    test_end_pos_exclusive = min(len(feature_frame), cutoff_pos + test_horizon_bars + 1)
    if test_end_pos_exclusive - test_start_pos < 2:
        raise RuntimeError("Test window is too short")

    best_threshold, train_metrics, train_equity = _evaluate_thresholds(
        feature_frame=feature_frame,
        start_pos=train_start_pos,
        end_pos_exclusive=train_end_pos_exclusive,
        thresholds=thresholds,
        cost_bps=cost_bps,
    )

    test_period = feature_frame.iloc[test_start_pos:test_end_pos_exclusive].copy()
    test_period["signal"] = _signal_from_scores(test_period, best_threshold)
    test_equity, test_metrics = _period_metrics(test_period, cost_bps=cost_bps)
    return best_threshold, train_metrics, test_metrics, train_equity, test_equity


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and snapshot GBPUSD 1m data")
    parser.add_argument("--symbol", default="GBPUSD=X")
    parser.add_argument("--period", default="7d", help="yfinance period for 1m data, e.g. 7d or 30d")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--input-csv", default=None, help="Optional local CSV with minute data instead of yfinance")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT / "gbpusd_recency_experiment"))
    parser.add_argument("--train-windows-hours", default="all,168,72,24,12")
    parser.add_argument("--test-horizon-hours", type=int, default=12)
    parser.add_argument("--fold-step-hours", type=int, default=12)
    parser.add_argument("--fast-spans", default="3,5,8")
    parser.add_argument("--slow-spans", default="12,24,48")
    parser.add_argument("--thresholds", default="0.0,0.25,0.5,0.75")
    parser.add_argument("--cost-bps", type=float, default=1.5)
    parser.add_argument("--min-train-bars", type=int, default=1500)
    parser.add_argument("--max-folds", type=int, default=20)
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

    if len(price_data) < args.min_train_bars + args.test_horizon_hours * 60 + 2:
        logger.warning("The loaded data is short (%s bars). Results will be noisy.", len(price_data))

    fast_spans = _parse_int_list(args.fast_spans)
    slow_spans = _parse_int_list(args.slow_spans)
    thresholds = _parse_float_list(args.thresholds)
    train_windows_hours = [item.strip().lower() for item in args.train_windows_hours.split(",") if item.strip()]
    test_horizon_bars = args.test_horizon_hours * 60
    fold_step_bars = args.fold_step_hours * 60

    fold_starts = list(range(args.min_train_bars, len(price_data) - test_horizon_bars - 1, fold_step_bars))
    if args.max_folds == 0:
        fold_starts = []
    elif args.max_folds > 0:
        fold_starts = fold_starts[: args.max_folds]
    if not fold_starts:
        raise RuntimeError("Not enough data to run a walk-forward experiment")

    rows: list[dict[str, object]] = []
    equity_curves: dict[int, pd.Series] = {}
    row_id = 0

    for fast_span in fast_spans:
        for slow_span in slow_spans:
            if slow_span <= fast_span:
                continue

            logger.info("Building feature frame for fast=%s slow=%s", fast_span, slow_span)
            feature_frame = build_feature_frame(price_data, fast_span=fast_span, slow_span=slow_span)

            for fold_id, cutoff_pos in enumerate(fold_starts, start=1):
                cutoff_time = price_data.index[cutoff_pos]
                logger.info("Fold %s cutoff=%s", fold_id, cutoff_time)

                for window_label in train_windows_hours:
                    try:
                        best_threshold, train_metrics, test_metrics, train_equity, test_equity = _evaluate_window_fold(
                            feature_frame=feature_frame,
                            window_label=window_label,
                            cutoff_pos=cutoff_pos,
                            test_horizon_bars=test_horizon_bars,
                            thresholds=thresholds,
                            cost_bps=args.cost_bps,
                        )
                    except RuntimeError as exc:
                        logger.warning("Skipping fold %s window=%s due to: %s", fold_id, window_label, exc)
                        continue

                    actual_window_label = "all_history" if window_label == "all" else f"recent_{window_label}h"
                    row_id += 1
                    rows.append(
                        {
                            "row_id": row_id,
                            "window_label": actual_window_label,
                            "fast_span": fast_span,
                            "slow_span": slow_span,
                            "threshold": best_threshold,
                            "fold_id": fold_id,
                            "train_start": price_data.index[_window_start_pos(price_data.index, cutoff_pos, window_label)].isoformat(),
                            "train_end": price_data.index[cutoff_pos - 1].isoformat(),
                            "test_start": price_data.index[cutoff_pos].isoformat(),
                            "test_end": price_data.index[min(len(price_data) - 1, cutoff_pos + test_horizon_bars)].isoformat(),
                            **{f"train_{key}": value for key, value in train_metrics.items()},
                            **{f"test_{key}": value for key, value in test_metrics.items()},
                            "train_score": _score_metrics(train_metrics),
                            "test_score": _score_metrics(test_metrics),
                        }
                    )
                    equity_curves[row_id] = test_equity

    if not rows:
        raise RuntimeError("No walk-forward folds were completed")

    results_df = pd.DataFrame(rows).sort_values(["window_label", "fold_id", "fast_span", "slow_span"]).reset_index(drop=True)
    results_csv = output_dir / "fold_results.csv"
    results_df.to_csv(results_csv, index=False)
    logger.info("Saved fold results to %s", results_csv)

    summary_rows: list[dict[str, object]] = []
    for window_label, group in results_df.groupby("window_label", sort=True):
        summary_rows.append(
            {
                "window_label": window_label,
                "folds": int(len(group)),
                "mean_train_score": float(group["train_score"].mean()),
                "mean_test_score": float(group["test_score"].mean()),
                "median_test_score": float(group["test_score"].median()),
                "mean_test_cagr_pct": float(group["test_cagr_pct"].mean()),
                "mean_test_max_drawdown_pct": float(group["test_max_drawdown_pct"].mean()),
                "mean_test_sharpe": float(group["test_sharpe"].mean()),
                "mean_test_hit_rate_pct": float(group["test_hit_rate_pct"].mean()),
                "mean_train_bars": float(group["train_num_bars"].mean()),
            }
        )

    summary_df = pd.DataFrame(summary_rows).sort_values("mean_test_score", ascending=False).reset_index(drop=True)
    summary_csv = output_dir / "window_summary.csv"
    summary_df.to_csv(summary_csv, index=False)
    logger.info("Saved summary to %s", summary_csv)

    ranking_df = summary_df[["window_label", "mean_test_score", "mean_test_cagr_pct", "mean_test_sharpe", "mean_test_max_drawdown_pct", "mean_test_hit_rate_pct", "folds"]].copy()
    ranking_csv = output_dir / "ranking.csv"
    ranking_df.to_csv(ranking_csv, index=False)

    latest_fold = int(results_df["fold_id"].max())
    latest_fold_rows = results_df[results_df["fold_id"] == latest_fold].copy()
    latest_fold_plot = output_dir / "latest_fold_equity_comparison.png"
    if not latest_fold_rows.empty:
        best_per_window = latest_fold_rows.sort_values("test_score", ascending=False).groupby("window_label", as_index=False).head(1)
        fig, ax = plt.subplots(figsize=(13, 6))
        for _, row in best_per_window.sort_values("window_label").iterrows():
            curve = equity_curves[int(row["row_id"])]
            if curve.empty:
                continue
            rebased = curve / float(curve.iloc[0]) * 1000.0
            ax.plot(rebased.index, rebased.values, linewidth=2.0, label=row["window_label"])
        ax.set_title("Latest fold out-of-sample equity by training window")
        ax.set_xlabel("Timestamp")
        ax.set_ylabel("Rebased equity")
        ax.grid(True, alpha=0.25)
        ax.legend()
        fig.tight_layout()
        fig.savefig(latest_fold_plot, dpi=180, bbox_inches="tight")
        plt.close(fig)

    window_score_plot = output_dir / "window_comparison.png"
    if not summary_df.empty:
        fig, ax = plt.subplots(figsize=(11, 6))
        colors = ["#4c78a8" if label == "all_history" else "#f58518" for label in summary_df["window_label"]]
        bars = ax.bar(summary_df["window_label"], summary_df["mean_test_score"], color=colors)
        ax.set_title("GBPUSD recency experiment: mean out-of-sample score by training window")
        ax.set_xlabel("Training window")
        ax.set_ylabel("Mean test score")
        ax.grid(True, axis="y", alpha=0.25)
        ax.tick_params(axis="x", rotation=25)
        for bar in bars:
            ax.text(bar.get_x() + bar.get_width() / 2.0, bar.get_height(), f"{bar.get_height():.2f}", ha="center", va="bottom", fontsize=8)
        fig.tight_layout()
        fig.savefig(window_score_plot, dpi=180, bbox_inches="tight")
        plt.close(fig)

    all_history_row = summary_df[summary_df["window_label"] == "all_history"]
    best_row = summary_df.iloc[0].to_dict()
    all_history_metrics = all_history_row.iloc[0].to_dict() if not all_history_row.empty else {}

    summary = {
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "symbol": args.symbol,
        "source": "csv" if input_csv is not None else "yfinance",
        "period": args.period,
        "interval": args.interval,
        "data_points": int(len(price_data)),
        "timeframes": list(TIMEFRAMES),
        "timeframe_weights": TIMEFRAME_WEIGHTS,
        "train_windows_hours": train_windows_hours,
        "test_horizon_hours": args.test_horizon_hours,
        "fold_step_hours": args.fold_step_hours,
        "cost_bps": args.cost_bps,
        "feature_families": [{"fast_span": fast, "slow_span": slow} for fast in fast_spans for slow in slow_spans if slow > fast],
        "files": {
            "raw_csv": str(raw_csv),
            "fold_results_csv": str(results_csv),
            "window_summary_csv": str(summary_csv),
            "ranking_csv": str(ranking_csv),
            "window_comparison_png": str(window_score_plot),
            "latest_fold_equity_png": str(latest_fold_plot),
            "log_file": str(output_dir / "gbpusd_recency_experiment.log"),
        },
        "comparison": {
            "all_history": all_history_metrics,
            "winner": best_row,
            "interpretation": "If a recent window beats all_history on mean test score, the recency hypothesis is supported on this dataset.",
        },
    }

    summary_json = output_dir / "summary.json"
    summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    logger.info("Experiment finished")
    logger.info("Winner window: %s", best_row.get("window_label"))
    logger.info("Summary JSON: %s", summary_json)
    print(json.dumps(summary, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
