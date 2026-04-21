#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/home/jonyb/python_folder/.venv/bin/python}"
PORT="8787"
HOST="127.0.0.1"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="${ROOT_DIR}/analysis_outputs/restart_training_${RUN_ID}"
LAUNCHER_LOG="${ROOT_DIR}/start_web_and_train.log"

log() {
  printf '[%s] %s\n' "$(date -Is)" "$1" | tee -a "${LAUNCHER_LOG}"
}

if [[ ! -x "${PYTHON_BIN}" ]]; then
  log "[ERRO] Python nao encontrado/executavel: ${PYTHON_BIN}"
  exit 1
fi

cd "${ROOT_DIR}"

if pgrep -af "http.server ${PORT}" >/dev/null 2>&1; then
  log "Servidor web ja estava ativo em http://${HOST}:${PORT}/"
else
  log "A iniciar servidor web em http://${HOST}:${PORT}/"
  "${PYTHON_BIN}" -m http.server "${PORT}" --bind "${HOST}" >/dev/null 2>&1 &
  disown || true
fi

log "A correr treino com output em ${OUT_DIR}"
./run_trading_training.sh --output-dir "${OUT_DIR}" "$@"

log "Treino concluido"
log "Abre no browser: http://${HOST}:${PORT}/dump_archive_12_4_2026_Dpc/analysis_outputs/$(basename "${OUT_DIR}")/"
log "Resumo: ${OUT_DIR}/summary.json"
log "Ranking: ${OUT_DIR}/ranking.csv"
