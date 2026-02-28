# HPC (SLURM) Deployment Runbook

## Prerequisites

- Access to HPC cluster with SLURM
- Nextflow installed on cluster
- Python 3.10+ on cluster
- Singularity or Docker for containerization

## Step 1: Cluster Configuration

Edit `configs/default.yaml` for your cluster:

```yaml
profiles:
  slurm:
    partition: "gpu"          # Your partition
    cpus_per_job: 16
    memory_per_job: "64G"
    max_concurrent_jobs: 100
    job_timeout: "48:00:00"   # HH:MM:SS
    container_engine: "singularity"
    work_dir: "/cluster/scratch/$USER/nf-work"
```

## Step 2: Nextflow Configuration

Create `.nextflow/nextflow.config` on cluster:

```groovy
process {
    executor = 'slurm'
    clusterOptions = '--partition=gpu --constraint=v100'
    
    withLabel: 'large' {
        cpus = 16
        memory = '64 GB'
    }
}

singularity {
    enabled = true
    cacheDir = '/cluster/singularity'
    autoMounts = true
}
```

## Step 3: API Server Deployment

```bash
# On login node (non-interactive)
nohup python -m uvicorn src.api.app:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4 &

# Or with systemd (if available)
sudo systemctl start orchestrator
```

## Step 4: Submit Jobs to HPC

```bash
# Via CLI with SLURM profile
python scripts/cli.py submit \
  --sample-path sample.fastq \
  --profile slurm

# Via API
curl -X POST http://cluster-api:8000/api/v1/pipelines/submit \
  -H "Content-Type: application/json" \
  -d '{
    "samples": [...],
    "pipeline": {...},
    "execution_profile": "SLURM"
  }'
```

## Step 5: Monitor Jobs

```bash
# Via SLURM
squeue -u $USER

# Via API
python scripts/cli.py list-jobs --status-filter RUNNING

# View logs
ls -la results/nf-logs/
```

## Performance Tuning

```yaml
# configs/default.yaml
profiles:
  slurm:
    # Increase parallelism
    max_concurrent_jobs: 500
    
    # Optimize memory usage
    memory_per_job: "32G"
    cpus_per_job: 8
    
    # Set retry policy
    max_retries: 3
    retry_backoff: "exponential"
```

## Troubleshooting

### Jobs Not Submitting
```bash
# Check SLURM availability
sinfo

# Check resource limits
scontrol show node <nodename>

# Enable debug logging in API
export LOG_LEVEL=DEBUG
python -m uvicorn src.api.app:app --reload
```

### Out of Memory Errors
```yaml
# Increase memory allocation
profiles:
  slurm:
    memory_per_job: "128G"  # Increase
```

### Singularity Issues
```bash
# Pull image manually
singularity pull library://biocontainers/samtools

# Test container
singularity exec samtools.sif samtools --version
```
