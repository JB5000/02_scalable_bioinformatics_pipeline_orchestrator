#!/usr/bin/env python
"""Command-line interface for orchestrator."""
import click
import json
from pathlib import Path
from datetime import datetime
import sys

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.orchestration.engine import OrchestrationEngine
from src.models.pipeline import ExecutionProfile, Sample, Pipeline, SubmitPipelineRequest
from src.observability import get_logger

logger = get_logger(__name__)


@click.group()
def cli():
    """Bioinformatics Pipeline Orchestrator CLI."""
    pass


@cli.command()
@click.option('--sample-path', required=True, help='Path to sample file')
@click.option('--format', default='fastq', help='File format (fastq, bam, vcf)')
@click.option('--profile', default='local', help='Execution profile (local, slurm, awsbatch)')
def submit(sample_path, format, profile):
    """Submit a bioinformatics pipeline job."""
    try:
        engine = OrchestrationEngine()
        
        sample = Sample(
            name=Path(sample_path).stem,
            data_path=str(sample_path),
            file_format=format,
            size_bytes=Path(sample_path).stat().st_size if Path(sample_path).exists() else 0,
            metadata={"submitted_at": datetime.utcnow().isoformat()}
        )
        
        pipeline = Pipeline(
            name="genomics-qc",
            version="1.0.0",
            nextflow_script="nextflow/main.nf",
            parameters={"min_quality": 20, "min_length": 50}
        )
        
        request = SubmitPipelineRequest(
            samples=[sample],
            pipeline=pipeline,
            execution_profile=ExecutionProfile[profile.upper()]
        )
        
        job = engine.submit_job(request.samples, request.pipeline, request.execution_profile)
        
        click.echo(json.dumps({
            "status": "success",
            "job_id": job.id,
            "sample": sample.name,
            "execution_profile": job.execution_profile.name
        }, indent=2))
        
    except Exception as e:
        logger.error(f"Submission failed: {e}")
        click.echo(json.dumps({"status": "error", "message": str(e)}), err=True)
        sys.exit(1)


@cli.command()
@click.option('--job-id', required=True, help='Job ID')
def status(job_id):
    """Check job status."""
    try:
        engine = OrchestrationEngine()
        job = engine.get_job_status(job_id)
        
        if job:
            click.echo(json.dumps({
                "job_id": job.id,
                "status": job.status.name,
                "sample": job.sample_id,
                "profile": job.execution_profile.name
            }, indent=2))
        else:
            click.echo(json.dumps({"status": "error", "message": f"Job {job_id} not found"}), err=True)
            sys.exit(1)
    except Exception as e:
        click.echo(json.dumps({"status": "error", "message": str(e)}), err=True)
        sys.exit(1)


@cli.command()
@click.option('--status-filter', default=None, help='Filter by status (QUEUED, RUNNING, COMPLETED, FAILED)')
def list_jobs(status_filter):
    """List all jobs."""
    try:
        engine = OrchestrationEngine()
        jobs = engine.list_jobs(status=status_filter)
        
        click.echo(json.dumps({
            "total_jobs": len(jobs),
            "jobs": [
                {
                    "job_id": j.id,
                    "status": j.status.name,
                    "sample": j.sample_id,
                    "profile": j.execution_profile.name
                }
                for j in jobs
            ]
        }, indent=2))
    except Exception as e:
        click.echo(json.dumps({"status": "error", "message": str(e)}), err=True)
        sys.exit(1)


@cli.command()
@click.option('--job-id', required=True, help='Job ID')
def cancel(job_id):
    """Cancel a running job."""
    try:
        engine = OrchestrationEngine()
        success = engine.cancel_job(job_id)
        
        if success:
            click.echo(json.dumps({"status": "success", "message": f"Job {job_id} cancelled"}))
        else:
            click.echo(json.dumps({"status": "error", "message": f"Could not cancel {job_id}"}), err=True)
    except Exception as e:
        click.echo(json.dumps({"status": "error", "message": str(e)}), err=True)
        sys.exit(1)


@cli.command()
def health():
    """Check orchestrator health."""
    try:
        engine = OrchestrationEngine()
        click.echo(json.dumps({
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "total_jobs": len(engine.list_jobs())
        }))
    except Exception as e:
        click.echo(json.dumps({"status": "unhealthy", "error": str(e)}), err=True)
        sys.exit(1)


if __name__ == '__main__':
    cli()

# TODO(2026-03): add --dry-run flag to CLI for safer pipeline testing
# TODO(2026-03): add --dry-run flag to CLI for safer pipeline testing – 2026-03-08 22:57:37 [84a21a7d]
# TODO(2026-03): add --dry-run flag to CLI for safer pipeline testing – 2026-03-08 22:58:28 [48b2f4c2]
# TODO(2026-03): add --dry-run flag to CLI for safer pipeline testing – 2026-03-08 23:00:17 [3f39de2c]
# TODO(2026-03): add --dry-run flag to CLI for safer pipeline testing – 2026-03-10 09:17:58 [20e7005f]
