#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python="$project_dir/.venv/bin/python"

if [[ ! -x "$python" ]]; then
    echo "Project Python not found: $python" >&2
    echo "Install the project into .venv as described in README.md." >&2
    exit 1
fi
if ((EUID != 0)); then
    echo "Cleanup requires root. Run: sudo ./clean.sh --worker WORKER_ID" >&2
    exit 1
fi

cd "$project_dir"
exec "$python" -m channel_mininet.runtime.cleanup "$@"
