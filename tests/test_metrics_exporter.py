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


def test_runtime_efficiency_metrics() -> None:
    exporter = MetricsExporter()
    job = exporter.start_job("job-1")
    job.start_time = 10.0
    job.end_time = 20.0
    job.status = "completed"
    job.cpu_seconds = 7.5

    runtime = exporter.get_runtime_efficiency()
    assert runtime["completed_jobs"] == 1
    assert runtime["avg_duration_seconds"] == 10.0
    assert runtime["avg_cpu_seconds"] == 7.5
    assert runtime["cpu_utilization_ratio"] == 0.75
