from src.observability.metrics_exporter import MetricsExporter


def test_cost_efficiency_metrics() -> None:
    exporter = MetricsExporter()
    exporter.start_job("job-1")
    exporter.end_job("job-1", status="completed", cost_usd=4.0)
    exporter.start_job("job-2")
    exporter.end_job("job-2", status="failed", cost_usd=1.0)

    efficiency = exporter.get_cost_efficiency()
    assert efficiency["avg_cost_per_completed_job"] == 5.0
    assert efficiency["failure_rate"] == 0.5
