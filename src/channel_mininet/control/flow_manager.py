"""Compile logical routes only after runtime port discovery."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Address
from typing import Mapping

from channel_mininet.control.routing import Route
from channel_mininet.schema import SceneError


PortKey = tuple[str, str]  # (switch ID, logical link ID)


@dataclass(frozen=True, slots=True)
class FlowRule:
    switch_id: str
    destination_host: str
    destination_ip: IPv4Address
    output_port: int
    eth_type: int = 0x0800
    priority: int = 100


def compile_flow_rules(
    routes: tuple[Route, ...], observed_ports: Mapping[PortKey, int]
) -> tuple[FlowRule, ...]:
    """Require an observed, valid ofport for every route output.

    OpenFlow version negotiation, installation, errors, and Barrier replies
    belong to a controller adapter. This function never assumes port order.
    """

    rules: list[FlowRule] = []
    for route in routes:
        key = (route.switch_id, route.output_link)
        port = observed_ports.get(key)
        # OpenFlow 1.3 reserves values starting at OFPP_MAX (0xffffff00).
        if type(port) is not int or not 1 <= port < 0xFFFFFF00:
            raise SceneError(f"missing or invalid observed ofport for {key!r}: {port!r}")
        rules.append(
            FlowRule(
                switch_id=route.switch_id,
                destination_host=route.destination_host,
                destination_ip=route.destination_ip,
                output_port=port,
            )
        )
    return tuple(rules)
