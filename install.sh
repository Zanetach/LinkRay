#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${LINKRAY_INSTALL_DIR:-/opt/linkray}"
BIN_PATH="${LINKRAY_BIN_PATH:-/usr/local/bin/linkray}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "install.sh must run as root because it writes ${INSTALL_DIR} and ${BIN_PATH}" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip
  else
    echo "python3 is required and automatic install is only implemented for apt-based systems" >&2
    exit 1
  fi
fi

if ! python3 -m venv --help >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-pip
  else
    echo "python3 venv support is required" >&2
    exit 1
  fi
fi

tmp_venv_check="$(mktemp -d)"
if ! python3 -m venv "${tmp_venv_check}/venv" >/dev/null 2>&1; then
  rm -rf "${tmp_venv_check}"
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-pip
  else
    echo "python3 venv ensurepip support is required" >&2
    exit 1
  fi
else
  rm -rf "${tmp_venv_check}"
fi

mkdir -p "${INSTALL_DIR}"
python3 -m venv "${INSTALL_DIR}/venv"
"${INSTALL_DIR}/venv/bin/pip" install --upgrade pip
"${INSTALL_DIR}/venv/bin/pip" install "${SCRIPT_DIR}"

cat >"${BIN_PATH}" <<EOF
#!/usr/bin/env bash
exec "${INSTALL_DIR}/venv/bin/linkray" "\$@"
EOF
chmod 0755 "${BIN_PATH}"

echo "LinkRay installed: ${BIN_PATH}"
echo "Try: linkray --help"
