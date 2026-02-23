#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
converter="$repo_root/crawler/html_to_json.py"
python_exec="$repo_root/.venv/bin/python"

if [[ ! -x "$python_exec" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    python_exec="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    python_exec="$(command -v python)"
  else
    echo "Python is not available in PATH" >&2
    exit 1
  fi
fi

"$python_exec" "$converter" "$@"
