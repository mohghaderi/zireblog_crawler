#!/usr/bin/env bash
set -euo pipefail

run_zireblog_crawler() {
  local repo_root
  repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  local env_file="$repo_root/.env"
  if [[ -f "$env_file" ]]; then
    # shellcheck disable=SC1090
    source "$env_file"
  fi

  local crawler="$repo_root/crawler/crawl.py"
  if [[ ! -f "$crawler" ]]; then
    echo "Crawler script not found at $crawler" >&2
    return 1
  fi

  local venv_python="$repo_root/.venv/bin/python"
  local python_exec
  if [[ -x "$venv_python" ]]; then
    python_exec="$venv_python"
  elif command -v python3 >/dev/null 2>&1; then
    python_exec="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    python_exec="$(command -v python)"
  else
    echo "Python is not available in PATH" >&2
    return 1
  fi

  local requirements="$repo_root/requirements.txt"
  if [[ -f "$requirements" ]]; then
    "$python_exec" -m pip install --upgrade -r "$requirements"
  fi

  "$python_exec" "$crawler" "$@"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  run_zireblog_crawler "$@"
fi
