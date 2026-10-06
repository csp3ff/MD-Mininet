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
controller_port_value=
deployment_opts=()
channel_opts=()
channel_selected=false
channel_control_port_selected=false
channel_control_port_value=

usage() {
    cat <<'EOF'
Usage: ./start.sh [--all-workers | --worker WORKER_ID] [--scene PATH]
                  [--controller-host IPv4] [--controller-port PORT]
                  [--deployment PATH]
                  [--channel] [--channel-control-port PORT]

Without options, start the complete example topology on this machine.
The scene path is relative to the project root unless absolute. A directory
uses workers.json, deployment.yml and channel.json. With --worker, deployment
and channel mode are selected automatically from that directory.
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
                echo "--scene requires a directory or JSON file path." >&2
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
        --deployment)
            if (($# < 2)) || [[ -z "$2" || "$2" == --* || ${#deployment_opts[@]} -ne 0 ]]; then
                echo "--deployment requires one file path." >&2
                exit 2
            fi
            deployment="$2"
            if [[ "$deployment" != /* ]]; then
                deployment="$project_dir/$deployment"
            fi
            deployment_opts=(--deployment "$deployment")
            shift 2
            ;;
        --controller-port)
            if (($# < 2)) || [[ -z "$2" || "$2" == --* || "$controller_port_selected" == true ]]; then
                echo "--controller-port requires one port number." >&2
                exit 2
            fi
            controller_opts+=(--controller-port "$2")
            controller_port_value="$2"
            controller_port_selected=true
            shift 2
            ;;
        --channel)
            if [[ "$channel_selected" == true ]]; then
                echo "--channel may be specified once." >&2
                exit 2
            fi
            channel_opts+=(--channel)
            channel_selected=true
            shift
            ;;
        --channel-control-port)
            if (($# < 2)) || [[ -z "$2" || "$2" == --* ||
                "$channel_control_port_selected" == true ]]; then
                echo "--channel-control-port requires one port number." >&2
                exit 2
            fi
            channel_opts+=(--channel-control-port "$2")
            channel_control_port_value="$2"
            channel_control_port_selected=true
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

if [[ -d "$scene" ]]; then
    scene_dir="$scene"
    scene="$scene_dir/workers.json"
    for required_file in "$scene" "$scene_dir/deployment.yml" "$scene_dir/channel.json"; do
        if [[ ! -f "$required_file" ]]; then
            echo "Scene directory is missing: $required_file" >&2
            exit 1
        fi
    done
    if [[ ${scope[0]} == --worker ]]; then
        if ((${#deployment_opts[@]} == 0)); then
            deployment_opts=(--deployment "$scene_dir/deployment.yml")
        fi
        if [[ "$channel_selected" == false ]]; then
            channel_opts+=(--channel)
            channel_selected=true
        fi
    fi
fi

if [[ "$controller_port_selected" == true && "$controller_host_selected" == false ]]; then
    echo "--controller-port requires --controller-host." >&2
    exit 2
fi
if ((${#deployment_opts[@]})) && [[ "$scope_selected" == false || ${scope[0]} != --worker ||
    "$controller_host_selected" == true || "$controller_port_selected" == true ]]; then
    echo "--deployment requires --worker and supplies the controller address." >&2
    exit 2
fi
if [[ "$channel_control_port_selected" == true && "$channel_selected" == false ]]; then
    echo "--channel-control-port requires --channel." >&2
    exit 2
fi
if [[ "$channel_selected" == true && ${#deployment_opts[@]} -eq 0 &&
    "$controller_host_selected" == false ]]; then
    echo "--channel requires a central controller." >&2
    exit 2
fi
if ((${#deployment_opts[@]})) && [[ "$channel_control_port_selected" == true ]]; then
    echo "--deployment supplies the channel control port." >&2
    exit 2
fi
for port in "$controller_port_value" "$channel_control_port_value"; do
    if [[ -n "$port" ]] && {
        [[ ! "$port" =~ ^[0-9]{1,5}$ ]] || ((10#$port < 1 || 10#$port > 65535))
    }; then
        echo "Port must be between 1 and 65535: $port" >&2
        exit 2
    fi
done

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

"$project_dir/clean.sh" --scene "$scene" "${scope[@]}" "${deployment_opts[@]}"
exec "$cli" up "$scene" "${scope[@]}" "${controller_opts[@]}" "${deployment_opts[@]}" "${channel_opts[@]}"
