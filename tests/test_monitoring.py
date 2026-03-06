"""Tests for resource monitoring system."""

import pytest
from unittest.mock import patch, MagicMock
from src.monitoring import (
    ResourceMonitor,
    ResourceMetric,
    MetricType,
    HealthStatus,
)


class TestResourceMonitor:
    """Tests for resource monitoring."""
    
    def test_record_metric(self, tmp_path):
        """Test recording a metric."""
        monitor = ResourceMonitor(str(tmp_path / "metrics.json"))
        
        metric = monitor.record_metric(
            metric_type=MetricType.CPU_USAGE,
            value=45.5,
            unit="percent"
        )
        
        assert metric.metric_type == MetricType.CPU_USAGE.value
        assert metric.value == 45.5
        assert metric.unit == "percent"
        assert metric.health_status == HealthStatus.HEALTHY.value
    
    def test_health_assessment_critical(self, tmp_path):
        """Test health assessment for critical threshold."""
        monitor = ResourceMonitor(str(tmp_path / "metrics.json"))
        
        metric = monitor.record_metric(
            metric_type=MetricType.MEMORY_USAGE,
            value=95.0,  # Above critical threshold
            unit="percent"
        )
        
        assert metric.health_status == HealthStatus.CRITICAL.value
    
    def test_health_assessment_warning(self, tmp_path):
        """Test health assessment for warning threshold."""
        monitor = ResourceMonitor(str(tmp_path / "metrics.json"))
        
        metric = monitor.record_metric(
            metric_type=MetricType.DISK_USAGE,
            value=82.0,  # Between warning and critical
            unit="percent"
        )
        
        assert metric.health_status == HealthStatus.WARNING.value
    
    @patch('src.monitoring.psutil.cpu_percent')
    @patch('src.monitoring.psutil.virtual_memory')
    @patch('src.monitoring.psutil.disk_usage')
    @patch('src.monitoring.psutil.pids')
    def test_collect_system_metrics(self, mock_pids, mock_disk, mock_vm, mock_cpu, tmp_path):
        """Test system metrics collection."""
        mock_cpu.return_value = 35.0
        mock_vm.return_value = MagicMock(percent=60.0, used=4000000000, available=3000000000)
        mock_disk.return_value = MagicMock(percent=50.0)
        mock_pids.return_value = list(range(150))
        
        monitor = ResourceMonitor(str(tmp_path / "metrics.json"))
        metrics = monitor.collect_system_metrics()
        
        assert metrics["cpu_percent"] == 35.0
        assert metrics["memory_percent"] == 60.0
        assert metrics["disk_percent"] == 50.0
        assert metrics["process_count"] == 150
    
    def test_save_metrics(self, tmp_path):
        """Test saving metrics to file."""
        metrics_file = tmp_path / "metrics.json"
        monitor = ResourceMonitor(str(metrics_file))
        
        monitor.record_metric(
            metric_type=MetricType.CPU_USAGE,
            value=50.0,
            unit="percent"
        )
        monitor.save_metrics()
        
        assert metrics_file.exists()
        with open(metrics_file) as f:
            data = f.read()
            assert "CPU_USAGE" in data or "cpu_usage" in data
    
    def test_export_metrics_summary(self, tmp_path):
        """Test exporting metrics summary."""
        monitor = ResourceMonitor(str(tmp_path / "metrics.json"))
        
        monitor.record_metric(MetricType.CPU_USAGE, 30.0, "percent")
        monitor.record_metric(MetricType.CPU_USAGE, 50.0, "percent")
        monitor.record_metric(MetricType.CPU_USAGE, 40.0, "percent")
        
        summary = monitor.export_metrics_summary()
        
        assert summary["total_measurements"] == 3
        assert "cpu_usage" in summary["metrics_by_type"]
        stats = summary["metrics_by_type"]["cpu_usage"]
        assert stats["min"] == 30.0
        assert stats["max"] == 50.0
        assert stats["avg"] == 40.0
    
    @patch('src.monitoring.psutil')
    def test_system_health_summary(self, mock_psutil, tmp_path):
        """Test system health summary generation."""
        monitor = ResourceMonitor(str(tmp_path / "metrics.json"))
        
        with patch.object(monitor, 'collect_system_metrics') as mock_collect:
            mock_collect.return_value = {
                "cpu_percent": 25.0,
                "memory_percent": 50.0,
                "disk_percent": 60.0,
                "process_count": 120
            }
            
            summary = monitor.get_system_health_summary()
            
            assert summary["overall_status"] == HealthStatus.HEALTHY.value
            assert "cpu_percent" in summary["metrics"]
            assert len(summary["alerts"]) == 0
