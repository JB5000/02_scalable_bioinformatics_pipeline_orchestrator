# 02 scalable bioinformatics pipeline orchestrator

## Objective
Industrial-grade project focused on bioinformatics/data engineering hiring signal.

## MVP Scope
- Define production-like architecture
- Implement one core end-to-end workflow
- Add tests and reproducibility guarantees
- Containerize and document execution

## Folder Layout
- src/: application modules
- tests/: unit/integration tests
- configs/: YAML/TOML settings
- docs/: architecture, ADRs, runbooks
- data/raw and data/processed: local data boundaries
- scripts/: automation helpers

## First Build Steps
1. Write architecture in docs/architecture.md
2. Add initial config in configs/
3. Implement minimal vertical slice in src/
4. Add one integration test in tests/
5. Add Dockerfile + CI workflow

## MVP Progress
- Added deterministic profile selector for local/SLURM/AWS Batch.
- Added run metrics summarization (time and cost per sample).
- Added tests covering orchestration decision logic.
