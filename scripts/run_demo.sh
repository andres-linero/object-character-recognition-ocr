#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
if [ -n "${OCR_PYTHON:-}" ]; then
    PYTHON_BIN="$OCR_PYTHON"
elif [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON_BIN="$ROOT/.venv/bin/python"
elif [ -x "$ROOT/../.venv/bin/python" ]; then
    PYTHON_BIN="$ROOT/../.venv/bin/python"
else
    PYTHON_BIN=python3
fi
if [ ! -f demo_runtime/demo.sqlite ]; then
    "$PYTHON_BIN" scripts/prepare_demo.py
fi
exec "$PYTHON_BIN" -m streamlit run ADK_Agentic/demo_app.py --server.address 127.0.0.1 --server.port 8502 --server.headless true
