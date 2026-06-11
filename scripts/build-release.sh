#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${LINKRAY_DIST_DIR:-${ROOT_DIR}/dist}"
SMOKE_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "${SMOKE_DIR}"
}
trap cleanup EXIT

cd "${ROOT_DIR}"
rm -rf "${DIST_DIR}"
python3 -m build --sdist --wheel --outdir "${DIST_DIR}"

python3 -m venv "${SMOKE_DIR}/venv"
"${SMOKE_DIR}/venv/bin/pip" install --no-index "${DIST_DIR}"/linkray-*.whl
"${SMOKE_DIR}/venv/bin/linkray" --help >/dev/null

if command -v twine >/dev/null 2>&1; then
  twine check "${DIST_DIR}"/*
fi

echo "Release artifacts written to ${DIST_DIR}"
