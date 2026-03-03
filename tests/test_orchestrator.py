from src.orchestration.metrics import summarize_run
from src.orchestration.profile_selector import Workload, choose_profile, choose_profile_with_reason


def test_profile_awsbatch_for_large_cloud_workload() -> None:
    profile = choose_profile(Workload(samples=120, use_cloud=True, hpc_available=True))
    assert profile == "awsbatch"


def test_metrics_summary_per_sample_values() -> None:
    summary = summarize_run(total_minutes=180.0, cost_usd=54.0, samples=60)
    assert summary["per_sample_minutes"] == 3.0
    assert summary["per_sample_cost"] == 0.9


def test_choose_profile_with_reason_for_slurm_path() -> None:
    profile, reason = choose_profile_with_reason(
        Workload(samples=24, use_cloud=False, hpc_available=True)
    )
    assert profile == "slurm"
    assert "hpc" in reason
