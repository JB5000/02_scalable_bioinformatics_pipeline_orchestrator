"""Runtime and cost summary helpers for pipeline runs."""


def summarize_run(total_minutes: float, cost_usd: float, samples: int) -> dict[str, float]:
    per_sample_minutes = round(total_minutes / max(samples, 1), 2)
    per_sample_cost = round(cost_usd / max(samples, 1), 2)
    return {
        "total_minutes": round(total_minutes, 2),
        "cost_usd": round(cost_usd, 2),
        "per_sample_minutes": per_sample_minutes,
        "per_sample_cost": per_sample_cost,
    }
