"""Start the central Ryu application independently of Mininet."""

from __future__ import annotations

import argparse
from importlib.util import find_spec
import os
from pathlib import Path

from channel_mininet.control.routing import build_routes
from channel_mininet.schema import SceneError, load_scene


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="md-controller")
    parser.add_argument("scene", help="scene JSON shared with the Mininet workers")
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=6653)
    args = parser.parse_args(argv)
    if not 1 <= args.listen_port <= 65535:
        parser.error("--listen-port must be between 1 and 65535")

    scene_path = Path(args.scene).expanduser().resolve()
    try:
        build_routes(load_scene(scene_path))
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
    manager.main(
        args=[
            "--ofp-listen-host", args.listen_host,
            "--ofp-tcp-listen-port", str(args.listen_port),
            "controller.central.app",
        ],
        prog="md-controller",
    )
    return 0
