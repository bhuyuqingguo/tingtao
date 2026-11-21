#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
  echo "错误：请在银河麒麟 V10 x86_64 或兼容的 Linux x86_64 构建机上运行。" >&2
  exit 1
fi

PYTHON_BIN="${PYTHON:-python3}"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 10), "需要 Python 3.10 或更高版本，建议 3.12"; print(sys.version)'
"$PYTHON_BIN" -c 'import venv, tkinter; print("venv 与 tkinter 可用")' || {
  echo "错误：构建机需要 Python venv 和 tkinter（请从麒麟离线软件源安装对应组件）。" >&2
  exit 1
}

VENV="$ROOT/.venv-kylin"
if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$VENV"
fi

if [[ "${OFFLINE_BUILD:-0}" == "1" ]]; then
  if [[ ! -d "$ROOT/wheelhouse" ]]; then
    echo "错误：OFFLINE_BUILD=1 时，请先将 Linux x86_64 wheel 放入 $ROOT/wheelhouse。" >&2
    exit 1
  fi
  PIP_NO_INDEX=1 PIP_FIND_LINKS="$ROOT/wheelhouse" \
    "$VENV/bin/python" -m pip install -r "$ROOT/requirements-kylin.txt"
else
  "$VENV/bin/python" -m pip install -r "$ROOT/requirements-kylin.txt"
fi

exec "$VENV/bin/python" "$ROOT/scripts/build_kylin_package.py"
