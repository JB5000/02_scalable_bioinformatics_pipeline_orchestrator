"""Select execution profile by environment and workload size."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Workload:
    samples: int
    use_cloud: bool
    hpc_available: bool


def choose_profile(workload: Workload) -> str:
    if workload.use_cloud and workload.samples >= 50:
        return "awsbatch"
    if workload.hpc_available and workload.samples >= 20:
        return "slurm"
    return "local"
