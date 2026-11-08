#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
if [ -n "${OCR_PYTHON:-}" ]; then
    PYTHON_BIN="$OCR_PYTHON"
elif [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON_BIN="$ROOT/.venv/bin/python"
else
    PYTHON_BIN=python3
fi
if [ ! -f "$ROOT/demo_runtime/workspace.sqlite" ]; then
    "$PYTHON_BIN" "$ROOT/scripts/prepare_workspace.py"
fi
exec "$PYTHON_BIN" -m uvicorn ADK_Agentic.web_api:app --host 127.0.0.1 --port 8700
