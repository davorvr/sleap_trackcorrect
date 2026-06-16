#!/bin/bash
# SLEAP Social Track Corrector — start server
#
# Usage:
#   bash explore/sleap_review/start_server.sh LABELS_DIR VIDEO_DIR [PORT]

set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: bash explore/sleap_review/start_server.sh LABELS_DIR VIDEO_DIR [PORT]" >&2
  echo "" >&2
  echo "Example:" >&2
  echo "  bash explore/sleap_review/start_server.sh \\" >&2
  echo "    sources/predictions/cleaned/social \\" >&2
  echo "    /path/to/video/files \\" >&2
  echo "    8500" >&2
  exit 2
fi

PORT="${3:-8500}"
CALL_DIR="$(pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

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

LABELS_DIR="$(resolve_dir "$1")"
VIDEO_DIR="$(resolve_dir "$2")"

cd "${PROJECT_ROOT}" || exit 1

echo "=== SLEAP Social Track Corrector ==="
echo "Project root: ${PROJECT_ROOT}"
echo "Labels dir:   ${LABELS_DIR}"
echo "Video dir:    ${VIDEO_DIR}"
echo "Indexing social .slp files (this may take a few seconds)..."
echo "Once ready, open http://localhost:${PORT}"
echo ""
uv run --extra dev python explore/sleap_review/serve.py \
  --labels-dir "${LABELS_DIR}" \
  --video-dir "${VIDEO_DIR}" \
  --port "${PORT}"
