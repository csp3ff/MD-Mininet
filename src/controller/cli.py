"""Start the central Ryu application independently of Mininet."""

from __future__ import annotations

import argparse
from importlib.util import find_spec
from ipaddress import IPv4Address
import os

from channel_mininet.control.routing import build_routes
from channel_mininet.channel_schedule import load_channel_schedule
from channel_mininet.runtime.deployment import load_deployment
from channel_mininet.scene_bundle import bundled_file, scene_file
from channel_mininet.schema import SceneError, load_scene


def _listen_address(value: str) -> str:
    try:
        return str(IPv4Address(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not an IPv4 address; use this machine's actual address, "
            "not CONTROLLER_IP"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="md-controller")
    parser.add_argument("scene", nargs="?", help="legacy scene JSON or scene directory")
    parser.add_argument("--scene", dest="scene_dir", help="scene directory")
    parser.add_argument("--listen-host", type=_listen_address)
    parser.add_argument("--listen-port", type=int)
    parser.add_argument("--channel-profile", help="version-2 channel timeline; omitted links stay at Mininet defaults")
    parser.add_argument("--channel-control-host", type=_listen_address,
                        help="channel listener IPv4 address (defaults to --listen-host)")
    parser.add_argument("--channel-control-port", type=int)
    args = parser.parse_args(argv)
    if bool(args.scene) == bool(args.scene_dir):
        parser.error("specify exactly one scene path or --scene directory")
    scene_arg = args.scene_dir or args.scene
    try:
        scene_path = scene_file(scene_arg)
        scene = load_scene(scene_path)
        deployment_path = bundled_file(scene_arg, None, "deployment.yml")
        deployment = load_deployment(deployment_path, scene) if deployment_path else None
        profile_path = bundled_file(scene_arg, args.channel_profile, "channel.json")
        if profile_path:
            load_channel_schedule(profile_path, scene)
        build_routes(scene)
    except SceneError as exc:
        parser.error(str(exc))
    args.listen_host = args.listen_host or (str(deployment.controller_host) if deployment else "127.0.0.1")
    if args.listen_port is None:
        args.listen_port = deployment.controller_port if deployment else 6653
    if args.channel_control_port is None:
        args.channel_control_port = deployment.channel_port if deployment else 6654
    if not 1 <= args.listen_port <= 65535:
        parser.error("--listen-port must be between 1 and 65535")
    if not 1 <= args.channel_control_port <= 65535:
        parser.error("--channel-control-port must be 1..65535")
    if profile_path and args.channel_control_port == args.listen_port:
        parser.error("--channel-control-port must differ from --listen-port")
    if args.channel_control_host and not profile_path:
        parser.error("--channel-control-host requires --channel-profile")

    if find_spec("ryu") is None:
        parser.error("Ryu is unavailable; install the controller extra")

    # Ryu 4.34 imports this removed Eventlet symbol while loading its WSGI module.
    # Ryu's later source uses None when the symbol is absent; this app does not use WSGI.
    from eventlet import wsgi as eventlet_wsgi

    if not hasattr(eventlet_wsgi, "ALREADY_HANDLED"):
        eventlet_wsgi.ALREADY_HANDLED = None

    from ryu.cmd import manager

    os.environ["MDNET_SCENE"] = str(scene_path)
    if profile_path:
        os.environ["MDNET_CHANNEL_PROFILE"] = str(profile_path)
        os.environ["MDNET_CHANNEL_HOST"] = args.channel_control_host or args.listen_host
        os.environ["MDNET_CHANNEL_PORT"] = str(args.channel_control_port)
    else:
        for key in ("MDNET_CHANNEL_PROFILE", "MDNET_CHANNEL_HOST", "MDNET_CHANNEL_PORT"):
            os.environ.pop(key, None)
    manager.main(
        args=[
            "--ofp-listen-host", args.listen_host,
            "--ofp-tcp-listen-port", str(args.listen_port),
            "controller.central.app",
        ],
        prog="md-controller",
    )
    return 0
