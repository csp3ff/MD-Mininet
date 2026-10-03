#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cli="$project_dir/.venv/bin/md-mininet"
scene="$project_dir/configs/two_workers.json"
scope=(--all-workers)
scope_selected=false
controller_opts=()
controller_host_selected=false
controller_port_selected=false

usage() {
    cat <<'EOF'
Usage: ./start.sh [--all-workers | --worker WORKER_ID] [--scene PATH]
                  [--controller-host IPv4] [--controller-port PORT]

Without options, start the complete example topology on this machine.
The scene path is relative to the project root unless absolute.
EOF
}

while (($#)); do
    case "$1" in
        --all-workers)
            if [[ "$scope_selected" == true ]]; then
                echo "Choose --all-workers or --worker once." >&2
                exit 2
            fi
            scope=(--all-workers)
            scope_selected=true
            shift
            ;;
        --worker)
            if [[ "$scope_selected" == true || $# -lt 2 || -z "$2" || "$2" == --* ]]; then
                echo "--worker requires one worker ID and cannot be combined with --all-workers." >&2
                exit 2
            fi
            scope=(--worker "$2")
            scope_selected=true
            shift 2
            ;;
        --scene)
            if (($# < 2)) || [[ -z "$2" || "$2" == --* ]]; then
                echo "--scene requires a file path." >&2
                exit 2
            fi
            scene="$2"
            if [[ "$scene" != /* ]]; then
                scene="$project_dir/$scene"
            fi
            shift 2
            ;;
        --controller-host)
            if (($# < 2)) || [[ -z "$2" || "$2" == --* || "$controller_host_selected" == true ]]; then
                echo "--controller-host requires one IPv4 address." >&2
                exit 2
            fi
            controller_opts+=(--controller-host "$2")
            controller_host_selected=true
            shift 2
            ;;
        --controller-port)
            if (($# < 2)) || [[ -z "$2" || "$2" == --* || "$controller_port_selected" == true ]]; then
                echo "--controller-port requires one port number." >&2
                exit 2
            fi
            controller_opts+=(--controller-port "$2")
            controller_port_selected=true
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ "$controller_port_selected" == true && "$controller_host_selected" == false ]]; then
    echo "--controller-port requires --controller-host." >&2
    exit 2
fi

if [[ ! -f "$scene" ]]; then
    echo "Scene file not found: $scene" >&2
    exit 1
fi
if [[ ! -x "$cli" ]]; then
    echo "Project CLI not found: $cli" >&2
    echo "Install the project into .venv as described in README.md." >&2
    exit 1
fi
if ((EUID != 0)); then
    echo "Mininet startup requires root. Run: sudo ./start.sh ${scope[*]}" >&2
    exit 1
fi

exec "$cli" up "$scene" "${scope[@]}" "${controller_opts[@]}"
