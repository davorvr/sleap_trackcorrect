#!/bin/bash
# SLEAP Social Track Corrector — start server
#
# Usage:
#   bash explore/sleap_review/start_server.sh [LABELS_DIR VIDEO_DIR] [PORT]

set -euo pipefail

if [[ $# -ne 0 && $# -ne 1 && $# -ne 2 && $# -ne 3 ]]; then
  echo "Usage: bash explore/sleap_review/start_server.sh [LABELS_DIR VIDEO_DIR] [PORT]" >&2
  echo "" >&2
  echo "Defaults:" >&2
  echo "  LABELS_DIR = ./predictions" >&2
  echo "  VIDEO_DIR  = ./videos" >&2
  echo "  PORT       = 8500" >&2
  echo "" >&2
  echo "Examples:" >&2
  echo "  bash explore/sleap_review/start_server.sh" >&2
  echo "  bash explore/sleap_review/start_server.sh 8501" >&2
  echo "  bash explore/sleap_review/start_server.sh \\" >&2
  echo "    sources/predictions/cleaned/social \\" >&2
  echo "    /path/to/video/files \\" >&2
  echo "    8500" >&2
  exit 2
fi

CALL_DIR="$(pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ $# -eq 0 ]]; then
  LABELS_ARG="${SCRIPT_DIR}/predictions"
  VIDEO_ARG="${SCRIPT_DIR}/videos"
  PORT="8500"
elif [[ $# -eq 1 ]]; then
  LABELS_ARG="${SCRIPT_DIR}/predictions"
  VIDEO_ARG="${SCRIPT_DIR}/videos"
  PORT="$1"
else
  LABELS_ARG="$1"
  VIDEO_ARG="$2"
  PORT="${3:-8500}"
fi

resolve_dir() {
  local input="$1"
  local candidate=""

  if [[ "${input}" = /* ]]; then
    candidate="${input}"
  elif [[ -d "${CALL_DIR}/${input}" ]]; then
    candidate="${CALL_DIR}/${input}"
  else
    candidate="${PROJECT_ROOT}/${input}"
  fi

  if [[ ! -d "${candidate}" ]]; then
    echo "Directory does not exist: ${input}" >&2
    echo "Tried: ${candidate}" >&2
    exit 2
  fi

  realpath "${candidate}"
}

LABELS_DIR="$(resolve_dir "${LABELS_ARG}")"
VIDEO_DIR="$(resolve_dir "${VIDEO_ARG}")"

cd "${PROJECT_ROOT}" || exit 1

echo "=== SLEAP Social Track Corrector ==="
echo "Project root: ${PROJECT_ROOT}"
echo "Tool env:     ${SCRIPT_DIR}"
echo "Labels dir:   ${LABELS_DIR}"
echo "Video dir:    ${VIDEO_DIR}"
echo "Indexing social .slp files (this may take a few seconds)..."
echo "Once ready, open http://localhost:${PORT}"
echo ""
uv run --project "${SCRIPT_DIR}" python "${SCRIPT_DIR}/serve.py" \
  --labels-dir "${LABELS_DIR}" \
  --video-dir "${VIDEO_DIR}" \
  --port "${PORT}"
