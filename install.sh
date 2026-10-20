#!/usr/bin/env bash
# One-command installer for hermes-job-drop. All logic lives in install.py.
#   bash install.sh [--force] [--doctor] [--audit-user-data] [--help]
# Set PYTHON=/path/to/python3 to use a specific interpreter (--doctor needs PyYAML).
set -euo pipefail
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "error: $PY not found. Install Python 3.9+ or set PYTHON=/path/to/python3." >&2
  exit 1
fi
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || {
  echo "error: Python 3.9+ is required ($("$PY" --version 2>&1))." >&2
  exit 1
}
exec "$PY" "$(dirname "$0")/install.py" "$@"
