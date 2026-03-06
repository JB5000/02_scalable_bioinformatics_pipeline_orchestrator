"""Resource monitoring and metrics collection for bioinformatics pipelines."""

import json
import psutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, asdict
from enum import Enum


class MetricType(Enum):
    """Types of metrics collected."""
    CPU_USAGE = "cpu_usage"
    MEMORY_USAGE = "memory_usage"
    DISK_USAGE = "disk_usage"
    PROCESS_COUNT = "process_count"
    IO_STATS = "io_stats"
    NETWORK_STATS = "network_stats"


class HealthStatus(Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class ResourceMetric:
    """Single resource metric measurement."""
    timestamp: str
    metric_type: str
    value: float
    unit: str
    threshold: Optional[float] = None
    health_status: str = HealthStatus.HEALTHY.value


class ResourceMonitor:
    """
    Monitors system resources during bioinformatics pipeline execution.
    
    Tracks:
    - CPU usage and per-process usage
    - Memory consumption (physical and virtual)
    - Disk I/O operations
    - Network activity
    - Process resource allocation
    """
    
    def __init__(self, metrics_path: str, collection_interval: int = 60):
        """
        Initialize resource monitor.
        
        Args:
            metrics_path: Path to store metrics data
            collection_interval: Seconds between metric collections
        """
        self.metrics_path = Path(metrics_path)
        self.collection_interval = collection_interval
        self._metrics: List[ResourceMetric] = []
        self._process_counters: Dict[str, Any] = {}
        self._ensure_metrics_dir()
    
    def _ensure_metrics_dir(self) -> None:
        """Ensure metrics directory exists."""
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
    
    def collect_system_metrics(self) -> Dict[str, float]:
        """
        Collect current system-wide metrics.
        
        Returns:
            Dictionary of metric names to values
        """
        try:
            metrics = {
                "cpu_percent": psutil.cpu_percent(interval=1),
                "memory_percent": psutil.virtual_memory().percent,
                "memory_used_mb": psutil.virtual_memory().used / 1024 / 1024,
                "memory_available_mb": psutil.virtual_memory().available / 1024 / 1024,
                "disk_percent": psutil.disk_usage('/').percent,
                "process_count": len(psutil.pids()),
            }
            return metrics
        except Exception as e:
            print(f"Error collecting system metrics: {e}")
            return {}
    
    def collect_process_metrics(self, pid: int) -> Dict[str, Any]:
        """
        Collect metrics for a specific process.
        
        Args:
            pid: Process ID
        
        Returns:
            Process metrics dictionary
        """
        try:
            proc = psutil.Process(pid)
            metrics = {
                "pid": pid,
                "name": proc.name(),
                "cpu_percent": proc.cpu_percent(interval=0.1),
                "memory_percent": proc.memory_percent(),
                "memory_rss_mb": proc.memory_info().rss / 1024 / 1024,
                "threads": proc.num_threads(),
                "status": proc.status(),
            }
            
            try:
                io_counters = proc.io_counters()
                metrics["io_read_mb"] = io_counters.read_bytes / 1024 / 1024
                metrics["io_write_mb"] = io_counters.write_bytes / 1024 / 1024
            except (AttributeError, psutil.AccessDenied):
                pass
            
            return metrics
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            return {"pid": pid, "error": str(e)}
    
    def record_metric(
        self,
        metric_type: MetricType,
        value: float,
        unit: str = "",
        threshold: Optional[float] = None
    ) -> ResourceMetric:
        """
        Record a resource metric measurement.
        
        Args:
            metric_type: Type of metric
            value: Measured value
            unit: Unit of measurement
            threshold: Optional threshold for alerting
        
        Returns:
            Recorded metric
        """
        health_status = self._assess_health(metric_type, value, threshold)
        
        metric = ResourceMetric(
            timestamp=datetime.utcnow().isoformat(),
            metric_type=metric_type.value,
            value=value,
            unit=unit,
            threshold=threshold,
            health_status=health_status
        )
        
        self._metrics.append(metric)
        return metric
    
    def _assess_health(
        self,
        metric_type: MetricType,
        value: float,
        threshold: Optional[float] = None
    ) -> str:
        """
        Assess health status based on metric value.
        
        Args:
            metric_type: Type of metric
            value: Current value
            threshold: Alert threshold
        
        Returns:
            Health status string
        """
        # Default thresholds
        thresholds = {
            MetricType.CPU_USAGE: (70, 90),  # (warning, critical)
            MetricType.MEMORY_USAGE: (75, 90),
            MetricType.DISK_USAGE: (80, 95),
        }
        
        if metric_type in thresholds:
            warning_level, critical_level = thresholds[metric_type]
            if value >= critical_level:
                return HealthStatus.CRITICAL.value
            elif value >= warning_level:
                return HealthStatus.WARNING.value
        
        return HealthStatus.HEALTHY.value
    
    def get_system_health_summary(self) -> Dict[str, Any]:
        """
        Get current system health summary.
        
        Returns:
            Health summary with overall status
        """
        metrics = self.collect_system_metrics()
        
        summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "overall_status": HealthStatus.HEALTHY.value,
            "metrics": {},
            "alerts": []
        }
        
        # Check each metric
        for metric_name, value in metrics.items():
            metric_type_map = {
                "cpu_percent": MetricType.CPU_USAGE,
                "memory_percent": MetricType.MEMORY_USAGE,
                "disk_percent": MetricType.DISK_USAGE,
                "process_count": MetricType.PROCESS_COUNT,
            }
            
            if metric_name in metric_type_map:
                metric_type = metric_type_map[metric_name]
                health = self._assess_health(metric_type, value)
                summary["metrics"][metric_name] = {
                    "value": value,
                    "health": health
                }
                
                if health == HealthStatus.CRITICAL.value:
                    summary["overall_status"] = HealthStatus.CRITICAL.value
                    summary["alerts"].append({
                        "metric": metric_name,
                        "value": value,
                        "level": "critical"
                    })
                elif health == HealthStatus.WARNING.value and summary["overall_status"] != HealthStatus.CRITICAL.value:
                    summary["overall_status"] = HealthStatus.WARNING.value
                    summary["alerts"].append({
                        "metric": metric_name,
                        "value": value,
                        "level": "warning"
                    })
        
        return summary
    
    def save_metrics(self) -> None:
        """Save collected metrics to file."""
        if not self._metrics:
            return
        
        try:
            metrics_data = [asdict(m) for m in self._metrics]
            with open(self.metrics_path, 'w') as f:
                json.dump(metrics_data, f, indent=2)
        except Exception as e:
            print(f"Error saving metrics: {e}")
    
    def export_metrics_summary(self) -> Dict[str, Any]:
        """
        Export summary statistics of collected metrics.
        
        Returns:
            Summary statistics
        """
        if not self._metrics:
            return {}
        
        summary = {
            "total_measurements": len(self._metrics),
            "collection_period_seconds": (
                (datetime.fromisoformat(self._metrics[-1].timestamp) -
                 datetime.fromisoformat(self._metrics[0].timestamp)).total_seconds()
                if len(self._metrics) > 1 else 0
            ),
            "metrics_by_type": {}
        }
        
        for metric in self._metrics:
            metric_type = metric.metric_type
            if metric_type not in summary["metrics_by_type"]:
                summary["metrics_by_type"][metric_type] = {
                    "count": 0,
                    "min": float('inf'),
                    "max": float('-inf'),
                    "avg": 0,
                }
            
            stats = summary["metrics_by_type"][metric_type]
            stats["count"] += 1
            stats["min"] = min(stats["min"], metric.value)
            stats["max"] = max(stats["max"], metric.value)
            stats["avg"] += metric.value
        
        # Calculate averages
        for metric_type in summary["metrics_by_type"]:
            stats = summary["metrics_by_type"][metric_type]
            if stats["count"] > 0:
                stats["avg"] = stats["avg"] / stats["count"]
        
        return summary
