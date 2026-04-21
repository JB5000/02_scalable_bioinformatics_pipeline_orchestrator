#!/usr/bin/env python3
"""Fully automatic monthly investment planner.

Research-only note:
- This script is used to study and simulate the strategy.
- Live execution should be handled separately by Hermes or another agent.
- The simulation itself should remain unconstrained so the study is honest.

This script combines:
- monthly top-1 momentum selection
- optional market risk-off filter from the benchmark
- monthly contribution sizing based on portfolio drawdown
- optional cash-reserve carry-over when no valid entry exists
- optional hard stop-loss for the current position (for example, 50% from entry)

It is designed to answer the practical question:
"What should I invest each month, and in which asset, based on historical data and current performance?"

Outputs:
- monthly_plan.csv: monthly recommendation table
- monthly_plan_summary.json: summary metrics and latest recommendation
- monthly_equity_curve.csv: strategy equity curve from the backtest
- monthly_equity_curve.png: equity curve plot
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:  # Prefer local src imports so the script runs directly from the repo.
    from src.backtests.sp500_momentum_rotation import (  # noqa: E402
        BacktestConfig,
        load_fx_series_from_yfinance,
        load_price_panel_from_yfinance,
        load_sp500_universe_history,
        prepare_currency_adjusted_tables,
        run_backtest_with_decisions,
    )
except ModuleNotFoundError:  # Backward-compatible fallback for old package name.
    from dump_archive_12_4_2026_pc.src.backtests.sp500_momentum_rotation import (  # noqa: E402
        BacktestConfig,
        load_fx_series_from_yfinance,
        load_price_panel_from_yfinance,
        load_sp500_universe_history,
        prepare_currency_adjusted_tables,
        run_backtest_with_decisions,
    )


@dataclass(frozen=True)
class PlannerParams:
    lookback_years: int
    ma_window_months: int
    stop_loss_pct: float
    min_trailing_return: float


def _build_interval_decisions(close_prices: pd.DataFrame, universe: pd.DataFrame, hold_days: int, lookback_years: int):
    """Build fixed-interval top-1 decisions using trading-day cadence.

    This is used instead of calendar-month rebalancing so the planner truly
    operates on a 30-trading-day cadence, as requested.
    """

    idx = pd.DatetimeIndex(close_prices.index).sort_values().tz_localize(None)
    signal_days = idx[::hold_days]

    rows = []
    for signal_date in signal_days:
        signal_date = pd.Timestamp(signal_date).normalize()
        pos = idx.searchsorted(signal_date, side="right")
        if pos >= len(idx):
            continue
        execution_date = pd.Timestamp(idx[pos]).normalize()

        lookback_anchor = signal_date - pd.DateOffset(years=lookback_years)
        best_ticker = None
        best_ret = -np.inf

        eligible = universe[(universe["start_date"] <= signal_date) & (universe["end_date"].isna() | (universe["end_date"] >= signal_date))]
        for ticker in eligible["ticker"].tolist():
            if ticker not in close_prices.columns:
                continue
            series = close_prices[ticker]
            signal_price = _asof(series, signal_date)
            lookback_price = _asof(series, lookback_anchor)
            if not np.isfinite(signal_price) or not np.isfinite(lookback_price) or lookback_price <= 0:
                continue
            trailing_return = signal_price / lookback_price - 1.0
            if trailing_return > best_ret:
                best_ret = trailing_return
                best_ticker = ticker

        if best_ticker is None:
            continue

        rows.append(
            {
                "signal_date": signal_date,
                "execution_date": execution_date,
                "target_ticker": best_ticker,
                "trailing_return": float(best_ret),
            }
        )

    return pd.DataFrame(rows)


def _asof(series: pd.Series, date: pd.Timestamp) -> float:
    s = series.dropna()
    if s.empty:
        return float("nan")
    pos = s.index.searchsorted(date, side="right") - 1
    if pos < 0:
        return float("nan")
    return float(s.iloc[pos])


def _load_best_params(best_json: Path) -> PlannerParams:
    if not best_json.exists():
        return PlannerParams(
            lookback_years=1,
            ma_window_months=8,
            stop_loss_pct=0.15,
            min_trailing_return=0.0,
        )

    payload = json.loads(best_json.read_text(encoding="utf-8"))
    params = payload["best"]["params"]
    return PlannerParams(
        lookback_years=int(params["lookback_years"]),
        ma_window_months=int(params["ma_window_months"]),
        stop_loss_pct=float(params["stop_loss_pct"]),
        min_trailing_return=float(params["min_trailing_return"]),
    )


def _load_prices(
    universe_csv: Path,
    benchmark: str,
    start: str,
    end: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series, pd.DataFrame, pd.DataFrame]:
    universe = load_sp500_universe_history(universe_csv)
    tickers = sorted(set(universe["ticker"]).union({benchmark}))

    price_panel = load_price_panel_from_yfinance(tickers, start=start, end=end)
    fx_series = load_fx_series_from_yfinance(start=start, end=end)
    open_prices, close_prices = prepare_currency_adjusted_tables(price_panel, fx_series)

    benchmark_panel = price_panel[price_panel["ticker"] == benchmark]
    if benchmark_panel.empty:
        raise RuntimeError(f"Benchmark ticker not found in downloaded data: {benchmark}")
    benchmark_open, benchmark_close = prepare_currency_adjusted_tables(benchmark_panel, fx_series)
    benchmark_series = benchmark_close.iloc[:, 0].dropna().sort_index()
    return universe, open_prices, close_prices, benchmark_series, benchmark_open, benchmark_close


def _monthly_decision_frame(decisions) -> pd.DataFrame:
    if decisions is None:
        return pd.DataFrame(columns=["signal_date", "execution_date", "target_ticker", "trailing_return"])

    if isinstance(decisions, pd.DataFrame):
        if decisions.empty:
            return pd.DataFrame(columns=["signal_date", "execution_date", "target_ticker", "trailing_return"])
        return decisions[["signal_date", "execution_date", "target_ticker", "trailing_return"]].copy().sort_values("execution_date").reset_index(drop=True)

    if not decisions:
        return pd.DataFrame(columns=["signal_date", "execution_date", "target_ticker", "trailing_return"])
    return pd.DataFrame(
        {
            "signal_date": [d.signal_date for d in decisions],
            "execution_date": [d.execution_date for d in decisions],
            "target_ticker": [d.target_ticker for d in decisions],
            "trailing_return": [d.trailing_return for d in decisions],
        }
    ).sort_values("execution_date").reset_index(drop=True)


def _build_plan(
    decisions_df: pd.DataFrame,
    equity_curve: pd.DataFrame,
    benchmark_series: pd.Series,
    params: PlannerParams,
    base_monthly: float,
    dd_factor: float,
    max_multiplier: float,
    defer_cash: bool,
    hard_stop_loss_pct: float,
) -> pd.DataFrame:
    if decisions_df.empty:
        return pd.DataFrame(
            columns=[
                "signal_date",
                "execution_date",
                "target_ticker",
                "trailing_return",
                "benchmark_monthly_close",
                "benchmark_monthly_ma",
                "risk_off",
                "strategy_equity_eur",
                "portfolio_peak_eur",
                "portfolio_drawdown_pct",
                "monthly_contribution_eur",
                "invested_now_eur",
                "cash_reserve_after_eur",
                "action",
                "notes",
            ]
        )

    equity = equity_curve.set_index("date")["equity_eur"].astype(float)
    equity = equity.sort_index()
    benchmark_monthly = benchmark_series.resample("ME").last().dropna()
    benchmark_ma = benchmark_monthly.rolling(params.ma_window_months).mean()

    rows: list[dict[str, object]] = []
    reserve_eur = 0.0
    previous_target: Optional[str] = None
    peak_eur = -np.inf

    for _, row in decisions_df.iterrows():
        exec_day = pd.Timestamp(row["execution_date"]).normalize()
        signal_day = pd.Timestamp(row["signal_date"]).normalize()
        target = str(row["target_ticker"])
        trailing = float(row["trailing_return"])

        eq_now = _asof(equity, exec_day)
        if np.isfinite(eq_now):
            peak_eur = max(peak_eur, eq_now)
        dd_pct = 0.0 if not np.isfinite(eq_now) or peak_eur <= 0 else (eq_now / peak_eur - 1.0) * 100.0

        b_px_m = _asof(benchmark_monthly, exec_day)
        b_ma_m = _asof(benchmark_ma, exec_day)
        risk_off = np.isfinite(b_px_m) and np.isfinite(b_ma_m) and (b_px_m < b_ma_m)
        passes_momentum = trailing >= params.min_trailing_return
        valid_target = target if (not risk_off and passes_momentum) else "CASH"

        if valid_target == "CASH":
            monthly_contribution = base_monthly
            if dd_pct < 0:
                monthly_contribution = base_monthly * (1.0 + dd_factor * abs(dd_pct) / 100.0)
                monthly_contribution = min(monthly_contribution, base_monthly * max_multiplier)

            if defer_cash:
                invested_now = 0.0
                reserve_eur += monthly_contribution
            else:
                invested_now = 0.0
                reserve_eur = 0.0

            if previous_target is None:
                action = "WAIT_CASH"
            elif previous_target == "CASH":
                action = "STAY_CASH"
            else:
                action = "EXIT_TO_CASH"
            notes = "No valid entry; keep capital in cash/reserve."
        else:
            monthly_contribution = base_monthly
            if dd_pct < 0:
                monthly_contribution = base_monthly * (1.0 + dd_factor * abs(dd_pct) / 100.0)
                monthly_contribution = min(monthly_contribution, base_monthly * max_multiplier)

            invested_now = monthly_contribution + (reserve_eur if defer_cash else 0.0)
            reserve_eur = 0.0 if defer_cash else 0.0

            if previous_target is None:
                action = "ENTER"
            elif previous_target == valid_target:
                action = "HOLD"
            elif previous_target == "CASH":
                action = "ENTER"
            else:
                action = "SWITCH"
            notes = "Valid top-1 momentum entry."

        # NOTE:
        # The hard stop-loss is intentionally separated from the monthly
        # drawdown-based sizing. The monthly contribution can increase on
        # drawdowns, while the hard stop-loss acts as a safety exit if the
        # current position falls too far from its entry price.
        rows.append(
            {
                "signal_date": signal_day,
                "execution_date": exec_day,
                "target_ticker": valid_target,
                "trailing_return": trailing,
                "benchmark_monthly_close": None if not np.isfinite(b_px_m) else float(b_px_m),
                "benchmark_monthly_ma": None if not np.isfinite(b_ma_m) else float(b_ma_m),
                "risk_off": bool(risk_off),
                "strategy_equity_eur": None if not np.isfinite(eq_now) else float(eq_now),
                "portfolio_peak_eur": None if peak_eur == -np.inf else float(peak_eur),
                "portfolio_drawdown_pct": float(dd_pct),
                "monthly_contribution_eur": float(monthly_contribution),
                "invested_now_eur": float(invested_now),
                "cash_reserve_after_eur": float(reserve_eur),
                "action": action,
                "notes": notes,
                "hard_stop_loss_pct": float(hard_stop_loss_pct),
            }
        )
        previous_target = valid_target

    return pd.DataFrame(rows)


def _apply_risk_filters_to_decisions(
    decisions_df: pd.DataFrame,
    benchmark_series: pd.Series,
    params: PlannerParams,
    risk_off_buffer: float = 0.0,
) -> pd.DataFrame:
    """Apply benchmark and momentum filters to decision targets.

    If benchmark monthly close is below its MA window, or trailing momentum is
    below the minimum threshold, target is switched to CASH.
    """

    if decisions_df is None or decisions_df.empty:
        return pd.DataFrame(columns=["signal_date", "execution_date", "target_ticker", "trailing_return"])

    out = decisions_df.copy()
    out["execution_date"] = pd.to_datetime(out["execution_date"]).dt.tz_localize(None).dt.normalize()
    out["signal_date"] = pd.to_datetime(out["signal_date"]).dt.tz_localize(None).dt.normalize()

    benchmark_monthly = benchmark_series.resample("ME").last().dropna()
    benchmark_ma = benchmark_monthly.rolling(params.ma_window_months).mean()

    b_close = []
    b_ma = []
    risk_off_flags = []
    below_momentum = []
    target = []

    for _, row in out.iterrows():
        exec_day = pd.Timestamp(row["execution_date"]).normalize()
        trailing = float(row["trailing_return"])
        candidate = str(row["target_ticker"])

        b_px = _asof(benchmark_monthly, exec_day)
        b_ma_v = _asof(benchmark_ma, exec_day)
        threshold = b_ma_v * (1.0 + risk_off_buffer) if np.isfinite(b_ma_v) else float("nan")
        risk_off = np.isfinite(b_px) and np.isfinite(threshold) and (b_px < threshold)
        weak_momentum = trailing < params.min_trailing_return
        final_target = "CASH" if (risk_off or weak_momentum) else candidate

        b_close.append(None if not np.isfinite(b_px) else float(b_px))
        b_ma.append(None if not np.isfinite(b_ma_v) else float(b_ma_v))
        risk_off_flags.append(bool(risk_off))
        below_momentum.append(bool(weak_momentum))
        target.append(final_target)

    out["benchmark_monthly_close"] = b_close
    out["benchmark_monthly_ma"] = b_ma
    out["risk_off"] = risk_off_flags
    out["below_min_momentum"] = below_momentum
    out["target_ticker"] = target
    return out


def _plot_plan(plan: pd.DataFrame, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(14, 7))
    if not plan.empty and "strategy_equity_eur" in plan.columns:
        series = plan.dropna(subset=["strategy_equity_eur"])
        ax.plot(series["execution_date"], series["strategy_equity_eur"], label="Strategy equity", linewidth=2)
        ax2 = ax.twinx()
        ax2.plot(series["execution_date"], series["cash_reserve_after_eur"], label="Cash reserve", color="tab:orange", alpha=0.7, linewidth=1.8)
        ax2.set_ylabel("Cash reserve (EUR)")
        ax2.legend(loc="upper right")
    ax.set_title("Automatic Monthly Planner")
    ax.set_xlabel("Date")
    ax.set_ylabel("Equity (EUR)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(output_path, dpi=170, bbox_inches="tight")
    plt.close(fig)
    return output_path


def _plot_comparison(plan: pd.DataFrame, benchmark_series: pd.Series, output_path: Path, start_year: int = 1970) -> Path:
    """Plot strategy equity and benchmark baseline on a common start date.

    The chart is rebased to 1000 at the first date >= start_year.
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if plan.empty:
        return output_path

    strategy = plan.dropna(subset=["strategy_equity_eur"])[["execution_date", "strategy_equity_eur"]].copy()
    strategy["execution_date"] = pd.to_datetime(strategy["execution_date"]).dt.tz_localize(None)
    strategy = strategy.sort_values("execution_date").reset_index(drop=True)

    benchmark = pd.DataFrame({"date": benchmark_series.index, "benchmark": benchmark_series.values}).copy()
    benchmark["date"] = pd.to_datetime(benchmark["date"]).dt.tz_localize(None)
    benchmark = benchmark.sort_values("date").reset_index(drop=True)

    start_ts = pd.Timestamp(f"{start_year}-01-01")
    strategy = strategy[strategy["execution_date"] >= start_ts].copy()
    benchmark = benchmark[benchmark["date"] >= start_ts].copy()

    if strategy.empty or benchmark.empty:
        return output_path

    first_strategy = float(strategy.iloc[0]["strategy_equity_eur"])
    first_benchmark = float(benchmark.iloc[0]["benchmark"])
    strategy["rebased"] = (strategy["strategy_equity_eur"] / first_strategy) * 1000.0
    benchmark["rebased"] = (benchmark["benchmark"] / first_benchmark) * 1000.0

    fig, ax = plt.subplots(figsize=(14, 7))
    ax.plot(strategy["execution_date"], strategy["rebased"], label="Strategy equity (rebased 1000)", linewidth=2.2)
    ax.plot(benchmark["date"], benchmark["rebased"], label="S&P 500 baseline (rebased 1000)", linewidth=1.8)
    ax.set_yscale("log")
    ax.set_title(f"Strategy vs S&P 500 baseline from {start_year} (log scale)")
    ax.set_xlabel("Date")
    ax.set_ylabel("Rebased equity (EUR)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=170, bbox_inches="tight")
    plt.close(fig)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Fully automatic monthly investment planner")
    parser.add_argument("--universe-csv", default=str(ROOT / "data" / "sp500_current_universe.csv"))
    parser.add_argument("--best-json", default=str(ROOT / "analysis_outputs" / "sp500_ga_optimization_run2" / "best_result.json"), help="GA best-result JSON with strategy params")
    parser.add_argument("--benchmark", default="^GSPC")
    parser.add_argument("--start", default="1957-03-04")
    parser.add_argument("--end", default="2026-04-05")
    parser.add_argument("--base-monthly", type=float, default=1000.0)
    parser.add_argument("--dd-factor", type=float, default=1.0, help="Extra contribution factor on drawdown (1.0 => -10%% DD adds +10%%)")
    parser.add_argument("--max-multiplier", type=float, default=2.0, help="Cap on monthly contribution multiple, e.g. 2.0 => max 2000 on a 1000 base")
    parser.add_argument("--hard-stop-loss-pct", type=float, default=0.50, help="Hard stop-loss for the current position; 0.50 means exit if price falls 50%% from entry")
    parser.add_argument(
        "--risk-off-buffer",
        type=float,
        default=0.0,
        help="Benchmark MA buffer for risk-off filter. Example: 0.01 requires benchmark >= MA*1.01 to stay risk-on.",
    )
    parser.add_argument("--rebalance-hold-days", type=int, default=30, help="Trading-day cadence for rebalance decisions; 30 means true 30-trading-day cadence")
    parser.add_argument("--defer-cash", action="store_true", default=True, help="Accumulate contributions in cash until a valid entry appears (default: on)")
    parser.add_argument("--commission-bps", type=float, default=5.0, help="Commission in bps for each trade")
    parser.add_argument("--slippage-bps", type=float, default=10.0, help="Slippage in bps for each trade")
    parser.add_argument("--tax-rate", type=float, default=0.28, help="Tax rate applied to realized gains")
    parser.add_argument(
        "--execution-mode",
        default="overnight_only",
        choices=["mixed_current", "overnight_only", "intraday_only"],
        help="Execution timing mode for backtest simulation",
    )
    parser.add_argument("--output-dir", default=str(ROOT / "analysis_outputs" / "auto_monthly_planner"))
    parser.add_argument("--current-ticker", default="", help="Optional current held ticker for the latest actionable signal")
    parser.add_argument("--current-entry-price", type=float, default=float("nan"), help="Optional current entry price for stop-loss reference")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    params = _load_best_params(Path(args.best_json))
    universe, open_prices, close_prices, benchmark_series, benchmark_open, benchmark_close = _load_prices(
        universe_csv=Path(args.universe_csv),
        benchmark=args.benchmark,
        start=args.start,
        end=args.end,
    )

    cfg = BacktestConfig(
        initial_capital=1000.0,
        commission_bps=args.commission_bps,
        slippage_bps=args.slippage_bps,
        tax_rate=args.tax_rate,
        lookback_years=params.lookback_years,
        benchmark_ticker=args.benchmark,
    )

    decisions = _build_interval_decisions(
        close_prices=close_prices,
        universe=universe,
        hold_days=args.rebalance_hold_days,
        lookback_years=params.lookback_years,
    )
    decisions_df = _monthly_decision_frame(decisions)
    filtered_decisions_df = _apply_risk_filters_to_decisions(
        decisions_df,
        benchmark_series=benchmark_series,
        params=params,
        risk_off_buffer=args.risk_off_buffer,
    )

    backtest = run_backtest_with_decisions(
        open_prices=open_prices,
        close_prices=close_prices,
        decisions=filtered_decisions_df,
        config=cfg,
        benchmark_open=benchmark_open,
        benchmark_close=benchmark_close,
        hard_stop_loss_pct=args.hard_stop_loss_pct if args.execution_mode == "mixed_current" else None,
        execution_mode=args.execution_mode,
    )

    plan = _build_plan(
        decisions_df=filtered_decisions_df,
        equity_curve=backtest.equity_curve,
        benchmark_series=benchmark_series,
        params=params,
        base_monthly=args.base_monthly,
        dd_factor=args.dd_factor,
        max_multiplier=args.max_multiplier,
        defer_cash=args.defer_cash,
        hard_stop_loss_pct=args.hard_stop_loss_pct,
    )

    plan_path = output_dir / "monthly_plan.csv"
    plan.to_csv(plan_path, index=False)

    equity_path = output_dir / "monthly_equity_curve.csv"
    backtest.equity_curve.to_csv(equity_path, index=False)

    plot_path = _plot_plan(plan, output_dir / "monthly_equity_curve.png")
    comparison_path = _plot_comparison(plan, benchmark_series, output_dir / "strategy_vs_baseline_1970_log.png", start_year=1970)

    latest = plan.iloc[-1] if not plan.empty else None
    current_ticker = args.current_ticker.strip().upper() if args.current_ticker else ""
    latest_action = None
    stop_loss_trigger = None
    if latest is not None:
        if current_ticker:
            if latest["target_ticker"] == "CASH":
                latest_action = "EXIT_TO_CASH"
            elif current_ticker == latest["target_ticker"]:
                latest_action = "HOLD"
            else:
                latest_action = "SWITCH"
        else:
            latest_action = "ENTER" if latest["target_ticker"] != "CASH" else "WAIT_CASH"

        if current_ticker and np.isfinite(args.current_entry_price) and args.current_entry_price > 0:
            stop_loss_trigger = float(args.current_entry_price * (1.0 - params.stop_loss_pct))

    summary = {
        "as_of": str(plan.iloc[-1]["execution_date"]) if not plan.empty else None,
        "strategy_params": {
            "lookback_years": params.lookback_years,
            "ma_window_months": params.ma_window_months,
            "stop_loss_pct": params.stop_loss_pct,
            "min_trailing_return": params.min_trailing_return,
            "rebalance_hold_days": args.rebalance_hold_days,
            "base_monthly": args.base_monthly,
            "dd_factor": args.dd_factor,
            "max_multiplier": args.max_multiplier,
            "hard_stop_loss_pct": args.hard_stop_loss_pct,
            "risk_off_buffer": args.risk_off_buffer,
            "defer_cash": bool(args.defer_cash),
            "commission_bps": args.commission_bps,
            "slippage_bps": args.slippage_bps,
            "tax_rate": args.tax_rate,
            "execution_mode": args.execution_mode,
        },
        "latest_recommendation": None if latest is None else {
            "signal_date": str(latest["signal_date"]),
            "execution_date": str(latest["execution_date"]),
            "target_ticker": latest["target_ticker"],
            "action": latest_action,
            "rebalance_hold_days": args.rebalance_hold_days,
            "monthly_contribution_eur": float(latest["monthly_contribution_eur"]),
            "invested_now_eur": float(latest["invested_now_eur"]),
            "cash_reserve_after_eur": float(latest["cash_reserve_after_eur"]),
            "portfolio_drawdown_pct": float(latest["portfolio_drawdown_pct"]),
            "risk_off": bool(latest["risk_off"]),
            "hard_stop_loss_pct": float(latest["hard_stop_loss_pct"]),
        },
        "backtest_metrics": backtest.metrics,
        "files": {
            "monthly_plan_csv": str(plan_path),
            "monthly_equity_curve_csv": str(equity_path),
            "monthly_equity_curve_png": str(plot_path),
            "strategy_vs_baseline_1970_log_png": str(comparison_path),
        },
        "notes": [
            "Monthly allocations are derived from historical top-1 momentum decisions.",
            "Drawdown-based contribution sizing uses portfolio drawdown before each monthly decision.",
            "Cash accumulation is enabled by default when no valid entry exists and is deployed on the next valid entry.",
            "Hard stop-loss is only applied in mixed_current execution mode.",
            "This is a model output, not financial advice.",
        ],
    }

    out_json = output_dir / "monthly_plan_summary.json"
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
