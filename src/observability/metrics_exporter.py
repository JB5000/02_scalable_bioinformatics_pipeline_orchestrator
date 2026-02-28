"""Metrics collection and export."""
import time
from datetime import datetime
from typing import Dict
from dataclasses import dataclass, asdict


@dataclass
class JobMetrics:
    """Job execution metrics."""
    job_id: str
    start_time: float
    end_time: float = 0.0
    status: str = "running"
    cpu_seconds: float = 0.0
    memory_mb: float = 0.0
    cost_usd: float = 0.0
    
    def duration_seconds(self) -> float:
        """Calculate job duration."""
        return self.end_time - self.start_time if self.end_time else 0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)


class MetricsExporter:
    """Export metrics to various backends."""
    
    def __init__(self):
        """Initialize metrics exporter."""
        self.jobs: Dict[str, JobMetrics] = {}
        self.counters: Dict[str, int] = {
            "total_jobs": 0,
            "completed_jobs": 0,
            "failed_jobs": 0,
            "total_cost_usd": 0.0,
        }
    
    def start_job(self, job_id: str) -> JobMetrics:
        """Record job start."""
        metrics = JobMetrics(job_id=job_id, start_time=time.time())
        self.jobs[job_id] = metrics
        self.counters["total_jobs"] += 1
        return metrics
    
    def end_job(self, job_id: str, status: str, cost_usd: float = 0.0):
        """Record job completion."""
        if job_id in self.jobs:
            metrics = self.jobs[job_id]
            metrics.end_time = time.time()
            metrics.status = status
            metrics.cost_usd = cost_usd
            
            if status == "completed":
                self.counters["completed_jobs"] += 1
            elif status == "failed":
                self.counters["failed_jobs"] += 1
            
            self.counters["total_cost_usd"] += cost_usd
    
    def get_metrics(self, job_id: str = None) -> Dict:
        """Get metrics."""
        if job_id:
            return self.jobs.get(job_id, {}).to_dict() if job_id in self.jobs else {}
        
        return {
            "counters": self.counters,
            "jobs": {jid: m.to_dict() for jid, m in self.jobs.items()},
        }
    
    def get_summary(self) -> Dict:
        """Get metrics summary."""
        total = self.counters["total_jobs"]
        completed = self.counters["completed_jobs"]
        failed = self.counters["failed_jobs"]
        
        return {
            "total_jobs": total,
            "completed_jobs": completed,
            "failed_jobs": failed,
            "success_rate": completed / max(total, 1),
            "total_cost_usd": self.counters["total_cost_usd"],
        }
