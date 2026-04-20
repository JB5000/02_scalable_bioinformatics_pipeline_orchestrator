#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/home/jonyb/python_folder/.venv/bin/python}"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="${ROOT_DIR}/analysis_outputs/gbpusd_recency_experiment_${RUN_ID}"

mkdir -p "${OUT_DIR}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "[ERRO] Python nao encontrado/executavel: ${PYTHON_BIN}"
  exit 1
fi

echo "[INFO] Output dir: ${OUT_DIR}"

"${PYTHON_BIN}" "${ROOT_DIR}/scripts/gbpusd_recency_window_experiment.py" \
  --output-dir "${OUT_DIR}" \
  "$@"