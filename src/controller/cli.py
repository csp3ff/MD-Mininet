"""Start the central Ryu application independently of Mininet."""

from __future__ import annotations

import argparse
from importlib.util import find_spec
import os
from pathlib import Path

from channel_mininet.control.routing import build_routes
from channel_mininet.channel_schedule import load_channel_schedule
from channel_mininet.schema import SceneError, load_scene


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="md-controller")
    parser.add_argument("scene", help="scene JSON shared with the Mininet workers")
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=6653)
    parser.add_argument("--channel-profile", help="complete version-2 channel timeline")
    parser.add_argument("--channel-control-host", help="channel listener address (defaults to --listen-host)")
    parser.add_argument("--channel-control-port", type=int, default=6654)
    args = parser.parse_args(argv)
    if not 1 <= args.listen_port <= 65535:
        parser.error("--listen-port must be between 1 and 65535")
    if not 1 <= args.channel_control_port <= 65535:
        parser.error("--channel-control-port must be 1..65535")
    if args.channel_profile and args.channel_control_port == args.listen_port:
        parser.error("--channel-control-port must differ from --listen-port")
    if args.channel_control_host and not args.channel_profile:
        parser.error("--channel-control-host requires --channel-profile")

    scene_path = Path(args.scene).expanduser().resolve()
    try:
        scene = load_scene(scene_path)
        build_routes(scene)
        if args.channel_profile:
            load_channel_schedule(args.channel_profile, scene, complete=True)
    except SceneError as exc:
        parser.error(str(exc))

    if find_spec("ryu") is None:
        parser.error("Ryu is unavailable; install the controller extra")

    # Ryu 4.34 imports this removed Eventlet symbol while loading its WSGI module.
    # Ryu's later source uses None when the symbol is absent; this app does not use WSGI.
    from eventlet import wsgi as eventlet_wsgi

    if not hasattr(eventlet_wsgi, "ALREADY_HANDLED"):
        eventlet_wsgi.ALREADY_HANDLED = None

    from ryu.cmd import manager

    os.environ["MDNET_SCENE"] = str(scene_path)
    if args.channel_profile:
        os.environ["MDNET_CHANNEL_PROFILE"] = str(Path(args.channel_profile).expanduser().resolve())
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
