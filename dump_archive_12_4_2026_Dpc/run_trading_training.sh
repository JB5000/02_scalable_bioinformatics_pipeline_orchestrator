#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/home/jonyb/python_folder/.venv/bin/python}"
TRIALS="40"
END_DATE="2026-04-05"
START_DATE="1957-03-04"
SEED="20260407"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="${ROOT_DIR}/analysis_outputs/restart_training_${RUN_ID}"
LOG_FILE="${OUT_DIR}/trading_training.log"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --trials)
      TRIALS="$2"
      shift 2
      ;;
    --end)
      END_DATE="$2"
      shift 2
      ;;
    --start)
      START_DATE="$2"
      shift 2
      ;;
    --seed)
      SEED="$2"
      shift 2
      ;;
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --output-dir)
      OUT_DIR="$2"
      LOG_FILE="${OUT_DIR}/trading_training.log"
      shift 2
      ;;
    -h|--help)
      cat <<'EOF'
Uso:
  ./run_trading_training.sh [--trials N] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--seed N] [--python /path/python] [--output-dir /path/out]

Exemplo:
  ./run_trading_training.sh --trials 60 --end 2026-04-15
EOF
      exit 0
      ;;
    *)
      echo "[ERRO] Argumento desconhecido: $1"
      echo "Usa --help para ver as opcoes."
      exit 1
      ;;
  esac
done

mkdir -p "${OUT_DIR}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "[ERRO] Python nao encontrado/executavel: ${PYTHON_BIN}" | tee -a "${LOG_FILE}"
  echo "Define PYTHON_BIN=/caminho/python e corre novamente." | tee -a "${LOG_FILE}"
  exit 1
fi

{
  echo "[$(date -Is)] Inicio do treino de paper trading"
  echo "[$(date -Is)] ROOT_DIR=${ROOT_DIR}"
  echo "[$(date -Is)] PYTHON_BIN=${PYTHON_BIN}"
  echo "[$(date -Is)] TRIALS=${TRIALS} START_DATE=${START_DATE} END_DATE=${END_DATE} SEED=${SEED}"
  echo "[$(date -Is)] OUT_DIR=${OUT_DIR}"
} | tee -a "${LOG_FILE}"

MISSING_PKGS="$(${PYTHON_BIN} - <<'PY'
import importlib.util
required = ["pandas", "numpy", "matplotlib", "yfinance"]
missing = [name for name in required if importlib.util.find_spec(name) is None]
print(" ".join(missing))
PY
)"

if [[ -n "${MISSING_PKGS}" ]]; then
  echo "[$(date -Is)] A instalar dependencias em falta: ${MISSING_PKGS}" | tee -a "${LOG_FILE}"
  ${PYTHON_BIN} -m pip install ${MISSING_PKGS} 2>&1 | tee -a "${LOG_FILE}"
fi

${PYTHON_BIN} "${ROOT_DIR}/scripts/optimize_mix_with_money_management.py" \
  --trials "${TRIALS}" \
  --start "${START_DATE}" \
  --end "${END_DATE}" \
  --seed "${SEED}" \
  --output-dir "${OUT_DIR}" 2>&1 | tee -a "${LOG_FILE}"

{
  echo "[$(date -Is)] Treino terminado."
  echo "[$(date -Is)] Log: ${LOG_FILE}"
  echo "[$(date -Is)] Ranking: ${OUT_DIR}/ranking.csv"
  echo "[$(date -Is)] Summary: ${OUT_DIR}/summary.json"
} | tee -a "${LOG_FILE}"
