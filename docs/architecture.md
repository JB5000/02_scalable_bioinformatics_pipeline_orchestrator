# Scalable Bioinformatics Pipeline Orchestrator - Architecture

## Problem Statement

Managing bioinformatics workflows across heterogeneous compute environments (local machines, HPC clusters, cloud platforms) is complex due to:
- Different job submission mechanisms (local execution, SLURM, AWS Batch)
- Variable resource availability and constraints
- Need for reproducibility and cost optimization
- Lack of unified interface for workflow management

This system provides a unified orchestration layer that abstracts away these differences.

## Core Components

### 1. Ingestion Layer
- Accepts genomics data in standard formats (FASTQ, BAM, VCF)
- Handles data from S3, local filesystems, or HTTP sources
- Manages data versioning and provenance tracking

### 2. Validation Layer
- Validates file formats and integrity
- Checks metadata compliance
- Performs sanity checks on input parameters

### 3. Orchestration Layer
- Routes jobs to optimal execution environment based on:
  - Workload size (number of samples)
  - Available resources (local vs HPC vs cloud)
  - Cost constraints
  - User preferences
- Manages job lifecycle (submission, polling, completion)
- Handles retries and error recovery

### 4. Processing Layer
- Executes Nextflow workflows
- Provides standardized container execution
- Manages resource allocation
- Collects runtime metrics

### 5. Results Layer
- Aggregates workflow outputs
- Manages result versioning
- Provides query interface for downstream analysis

## Technology Stack

```
Frontend/API:
  - FastAPI (Python REST API)
  - Click/Typer (CLI)
  - OpenAPI/Swagger documentation

Backend/Orchestration:
  - Python 3.10+ (core orchestration logic)
  - Nextflow (workflow definition)
  - SQLAlchemy (database ORM)
  - Pydantic (data validation)

Execution Environments:
  - Local: Direct Python subprocess execution
  - HPC: SLURM job scheduler
  - Cloud: AWS Batch

Infrastructure:
  - Docker (containerization)
  - Docker Compose (local development)
  - PostgreSQL (state database)
  - Redis (caching, job queues)

Observability:
  - Prometheus (metrics collection)
  - Grafana (dashboards)
  - Structured logging (JSON format)
  - ELK Stack (optional: log aggregation)

CI/CD:
  - GitHub Actions (automated testing, deployment)
  - Docker Registry (image storage)
```

## Non-Functional Requirements

### Reproducibility
- ✅ Containerized execution ensures consistent environments
- ✅ Fixed tool versions in containers
- ✅ Immutable workflow definitions
- ✅ Complete audit trail of executions

### Observability
- ✅ Structured logging at all levels
- ✅ Prometheus metrics for system health
- ✅ Grafana dashboards for visualization
- ✅ Distributed tracing (optional)

### Auditability
- ✅ Complete job history in database
- ✅ Resource usage tracking per job/sample
- ✅ User action logging
- ✅ Data lineage tracking

### Security
- ✅ Authentication (API keys, OAuth)
- ✅ Authorization (role-based access)
- ✅ Data encryption at rest (database, S3)
- ✅ Data encryption in transit (TLS)
- ✅ Credential management (secrets in env vars)
- ✅ Audit logging for sensitive operations

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER INTERFACES                          │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐    │
│  │   REST API     │  │  CLI Tools     │  │  Web Dashboard │    │
│  │   (FastAPI)    │  │  (Click/Typer) │  │  (Frontend)    │    │
│  └────────────────┘  └────────────────┘  └────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                           │
┌─────────────────────────────────────────────────────────────────┐
│                   ORCHESTRATION LAYER                            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Request Validation  │  Profile Selection  │  Job Routing │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
┌───────▼──────┐  ┌───────▼──────┐  ┌───────▼──────┐
│   LOCAL      │  │    SLURM     │  │  AWS BATCH   │
│  EXECUTION   │  │   CLUSTER    │  │   (Cloud)    │
│              │  │              │  │              │
│ Direct Python│  │ sbatch/squeue│  │ aws batch    │
│ Subprocess   │  │ SLURM Queue  │  │ Job Queue    │
└───────┬──────┘  └───────┬──────┘  └───────┬──────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
        ┌──────────────────▼──────────────────┐
        │   NEXTFLOW WORKFLOW ENGINE           │
        │  (Process execution, containerization)
        └──────────────────┬──────────────────┘
                           │
        ┌──────────────────▼──────────────────┐
        │   Docker Containers                  │
        │  (FastQC, BWA, GATK, VEP, etc.)      │
        └──────────────────┬──────────────────┘
                           │
┌───────────────────────────▼────────────────────────┐
│        PERSISTENT STORAGE & DATABASES             │
│  ┌──────────────┐  ┌──────────────┐              │
│  │ PostgreSQL   │  │    S3/NFS    │              │
│  │ (State DB)   │  │ (Data Store) │              │
│  └──────────────┘  └──────────────┘              │
└───────────────────────────────────────────────────┘
```

## Data Flow

### Sample Processing Pipeline
```
Raw Data (FASTQ)
    │
    ▼
[Validation] → Check format, size, content
    │
    ├─→ ✓ Valid → Queue for processing
    │
    └─→ ✗ Invalid → Error notification
         │
         ▼
    [Profile Selection]
    • Analyze workload characteristics
    • Estimate costs
    • Select execution environment (local/SLURM/AWS)
         │
         ▼
    [Job Submission]
    • Create job record in database
    • Submit to selected executor
    • Return job ID to user
         │
         ▼
    [Nextflow Workflow]
    • Quality Control (FastQC)
    • Read Alignment (BWA)
    • Variant Calling (GATK)
    • Annotation (VEP)
         │
         ▼
    [Results Aggregation]
    • Collect outputs
    • Generate summary stats
    • Store in database
         │
         ▼
    Processed Results (VCF, BAM, Summary)
```

## Database Schema (Key Tables)

```sql
-- Samples
CREATE TABLE samples (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    data_path VARCHAR(1024),
    status VARCHAR(50),
    created_at TIMESTAMP
);

-- Jobs
CREATE TABLE jobs (
    id SERIAL PRIMARY KEY,
    sample_id INTEGER REFERENCES samples(id),
    pipeline_id INTEGER,
    execution_profile VARCHAR(50),
    status VARCHAR(50),
    job_id_remote VARCHAR(255),
    submitted_at TIMESTAMP,
    completed_at TIMESTAMP
);

-- Metrics
CREATE TABLE metrics (
    id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES jobs(id),
    duration_minutes FLOAT,
    cpu_hours FLOAT,
    memory_gb FLOAT,
    cost_usd FLOAT
);

-- Runs
CREATE TABLE runs (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    status VARCHAR(50),
    total_samples INTEGER,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);
```

## Execution Profiles

### Local Profile
```yaml
executor: local
cpus: 4
memory: 8GB
disk: 100GB
cost_per_hour: 0
best_for: Development, testing, small datasets
```

### SLURM Profile
```yaml
executor: slurm
queue: general
time: 24h
cpus_per_task: 8
memory_per_task: 32GB
cost_per_hour: 0.50  # estimated
best_for: Medium datasets, HPC clusters
```

### AWS Batch Profile
```yaml
executor: awsbatch
jobQueue: genomics-queue
jobDefinition: genomics-processor
instanceType: t3.large
vCPU: 4
memory: 8GB
cost_per_hour: 0.15
best_for: Large datasets, cloud-native deployments
```

## Deployment Architecture

### Development (Local)
```
docker-compose up
├── PostgreSQL (localhost:5432)
├── Redis (localhost:6379)
└── FastAPI Server (localhost:8000)
```

### Staging (Single Server)
```
AWS EC2 + RDS + S3
├── FastAPI + Gunicorn
├── PostgreSQL RDS
├── Redis ElastiCache
└── S3 for data storage
```

### Production (Multi-Region)
```
AWS Multi-AZ
├── ALB (Load Balancer)
├── ECS/Fargate (API servers)
├── Aurora PostgreSQL (managed database)
├── ElastiCache Redis (caching)
├── S3 (data storage)
├── AWS Batch (job execution)
└── CloudWatch (monitoring)
```

## API Endpoints

```
POST   /api/v1/pipelines/submit      - Submit new pipeline
GET    /api/v1/jobs/{job_id}         - Get job status
GET    /api/v1/jobs/{job_id}/logs    - Get job logs
GET    /api/v1/runs/{run_id}         - Get run summary
GET    /api/v1/runs/{run_id}/results - Get aggregated results
GET    /api/v1/metrics               - Get system metrics
GET    /api/v1/health                - Health check
```

## Error Handling Strategy

```
Job Failure Detection
    │
    ├─→ Network Error
    │   └─→ Retry with exponential backoff (up to 3 times)
    │
    ├─→ Resource Error
    │   └─→ Fall back to larger instance/queue
    │
    ├─→ Data Error
    │   └─→ Notify user, skip sample, continue
    │
    └─→ Unknown Error
        └─→ Log, alert, require manual intervention
```

## Performance Targets

| Metric | Target | Notes |
|--------|--------|-------|
| API Response Time | <100ms | For non-blocking endpoints |
| Job Submission Latency | <1s | Time to queue job |
| Workflow Startup | <5s | Container pull + process setup |
| Data Validation | <10s per sample | For 100MB FASTQ |
| Results Query | <500ms | Indexed database queries |

## Security Considerations

1. **Authentication**: API key + optional OAuth2
2. **Authorization**: Role-based access control (admin, user, guest)
3. **Data Protection**: Encryption at rest (database, S3) and in transit (TLS)
4. **Secrets Management**: Environment variables or AWS Secrets Manager
5. **Audit Trail**: All API calls logged with timestamp and user
6. **Rate Limiting**: Prevent abuse (100 requests/minute per user)
7. **Input Validation**: Strict validation of all inputs
8. **Dependency Updates**: Regular security patches

## Scalability

### Horizontal Scaling
- Stateless API servers behind load balancer
- Multiple Nextflow workers
- Database read replicas for queries

### Vertical Scaling
- Larger instance types for API servers
- Upgraded database resources
- Increased memory/CPU for Nextflow workers

### Expected Capacity
- **Small**: Up to 100 samples/day (single server)
- **Medium**: Up to 1000 samples/day (3-5 servers)
- **Large**: 10,000+ samples/day (Kubernetes, auto-scaling)

---

**Last Updated**: 2026-02-28
**Version**: 1.0
**Status**: Complete Architecture
