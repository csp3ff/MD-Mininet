"""Ryu OpenFlow 1.3 controller for the current static MDNET scene.

The process is started by ``md-controller``. It never creates Mininet nodes.
Only switches and interface names declared by the scene are accepted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Any

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, DEAD_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3

from channel_mininet.control.flow_manager import FlowRule, compile_flow_rules
from channel_mininet.control.routing import build_routes
from channel_mininet.runtime.names import planned_interface_names
from channel_mininet.schema import SceneError, load_scene, scene_fingerprint


_COOKIE = 0x4D444E5400000000  # "MDNT" in the high 32 bits.
_COOKIE_MASK = 0xFFFFFFFF00000000


@dataclass
class _PortRequest:
    datapath: Any
    xid: int
    ports: list[Any] = field(default_factory=list)


@dataclass
class _InstallBatch:
    datapath: Any
    barrier_xid: int
    message_xids: set[int]
    has_rules: bool
    failed: bool = False


class CentralController(app_manager.RyuApp):
    """Install static, destination-based IPv4 and ARP paths on known OVS switches."""

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        scene_path = os.environ.get("MDNET_SCENE")
        if not scene_path:
            raise RuntimeError("MDNET_SCENE is required; start with md-controller")
        self.scene = load_scene(scene_path)
        routes = build_routes(self.scene)
        names = planned_interface_names(self.scene)
        self.switch_ids = {int(switch.dpid, 16): switch.id for switch in self.scene.switches}
        self.routes_by_switch = {
            switch.id: tuple(route for route in routes if route.switch_id == switch.id)
            for switch in self.scene.switches
        }
        self.expected_ports = {
            switch.id: {
                names[(link.id, switch.id)]: link.id
                for link in self.scene.links
                if switch.id in (link.a, link.b)
            }
            for switch in self.scene.switches
        }
        self.datapaths: dict[int, Any] = {}
        self.port_requests: dict[int, _PortRequest] = {}
        self.install_batches: dict[int, _InstallBatch] = {}
        self.ready: set[int] = set()
        self.logger.info("Loaded scene %s (digest %s)", self.scene.experiment, scene_fingerprint(self.scene))

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev: Any) -> None:
        datapath = ev.msg.datapath
        switch_id = self.switch_ids.get(datapath.id)
        if switch_id is None:
            self.logger.error("Ignoring unknown switch DPID %016x", datapath.id)
            return
        self.datapaths[datapath.id] = datapath
        self.port_requests.pop(datapath.id, None)
        self.install_batches.pop(datapath.id, None)
        self.ready.discard(datapath.id)
        self.logger.info("Switch %s connected (DPID %016x)", switch_id, datapath.id)
        self._request_ports(datapath)

    @set_ev_cls(ofp_event.EventOFPStateChange, DEAD_DISPATCHER)
    def switch_disconnected_handler(self, ev: Any) -> None:
        datapath = ev.datapath
        if self.datapaths.get(datapath.id) is not datapath:
            return
        self.datapaths.pop(datapath.id, None)
        self.port_requests.pop(datapath.id, None)
        self.install_batches.pop(datapath.id, None)
        self.ready.discard(datapath.id)
        self.logger.warning("Switch %s disconnected", self.switch_ids[datapath.id])

    @set_ev_cls(ofp_event.EventOFPPortStatus, [CONFIG_DISPATCHER, MAIN_DISPATCHER])
    def port_status_handler(self, ev: Any) -> None:
        datapath = ev.msg.datapath
        if self.datapaths.get(datapath.id) is datapath:
            self._request_ports(datapath)

    def _request_ports(self, datapath: Any) -> None:
        self.ready.discard(datapath.id)
        request = datapath.ofproto_parser.OFPPortDescStatsRequest(datapath, 0)
        datapath.set_xid(request)
        self.port_requests[datapath.id] = _PortRequest(datapath, request.xid)
        if not datapath.send_msg(request):
            self.port_requests.pop(datapath.id, None)
            self.logger.error("Cannot request ports from %s", self.switch_ids[datapath.id])

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, [CONFIG_DISPATCHER, MAIN_DISPATCHER])
    def port_description_handler(self, ev: Any) -> None:
        message = ev.msg
        datapath = message.datapath
        pending = self.port_requests.get(datapath.id)
        if pending is None or pending.datapath is not datapath or pending.xid != message.xid:
            return
        pending.ports.extend(message.body)
        if message.flags & datapath.ofproto.OFPMPF_REPLY_MORE:
            return
        self.port_requests.pop(datapath.id, None)
        self._reconcile(datapath, pending.ports)

    def _reconcile(self, datapath: Any, ports: list[Any]) -> None:
        switch_id = self.switch_ids[datapath.id]
        expected = self.expected_ports[switch_id]
        observed: dict[str, int] = {}
        down: set[str] = set()
        for port in ports:
            name = port.name.decode("utf-8", "replace") if isinstance(port.name, bytes) else port.name
            name = name.rstrip("\x00")
            if name not in expected:
                continue
            if (name in observed or port.port_no in observed.values() or
                    not 1 <= port.port_no < datapath.ofproto.OFPP_MAX):
                self.logger.error("Invalid or duplicate port %r on %s", name, switch_id)
                self._replace_flows(datapath, ())
                return
            observed[name] = port.port_no
            if (port.config & datapath.ofproto.OFPPC_PORT_DOWN or
                    port.state & datapath.ofproto.OFPPS_LINK_DOWN):
                down.add(name)
        missing = set(expected) - set(observed)
        if missing or down:
            self.logger.warning(
                "Switch %s not ready; missing interfaces=%s, down interfaces=%s",
                switch_id, sorted(missing), sorted(down),
            )
            self._replace_flows(datapath, ())
            return
        observed_links = {(switch_id, link_id): observed[name] for name, link_id in expected.items()}
        try:
            rules = compile_flow_rules(self.routes_by_switch[switch_id], observed_links)
        except SceneError as exc:
            self.logger.error("Cannot compile flows for %s: %s", switch_id, exc)
            self._replace_flows(datapath, ())
            return
        self._replace_flows(datapath, rules)

    def _replace_flows(self, datapath: Any, rules: tuple[FlowRule, ...]) -> None:
        """Replace only this project's flows; wait for a barrier before marking ready."""
        ofp = datapath.ofproto
        parser = datapath.ofproto_parser
        messages = [parser.OFPFlowMod(
            datapath=datapath,
            cookie=_COOKIE,
            cookie_mask=_COOKIE_MASK,
            table_id=ofp.OFPTT_ALL,
            command=ofp.OFPFC_DELETE,
            out_port=ofp.OFPP_ANY,
            out_group=ofp.OFPG_ANY,
            match=parser.OFPMatch(),
        )]
        for rule in rules:
            instructions = [parser.OFPInstructionActions(
                ofp.OFPIT_APPLY_ACTIONS, [parser.OFPActionOutput(rule.output_port)]
            )]
            messages.append(parser.OFPFlowMod(
                datapath=datapath,
                cookie=_COOKIE,
                table_id=0,
                command=ofp.OFPFC_ADD,
                priority=rule.priority,
                match=parser.OFPMatch(eth_type=rule.eth_type, ipv4_dst=str(rule.destination_ip)),
                instructions=instructions,
            ))
            messages.append(parser.OFPFlowMod(
                datapath=datapath,
                cookie=_COOKIE,
                table_id=0,
                command=ofp.OFPFC_ADD,
                priority=rule.priority,
                match=parser.OFPMatch(eth_type=0x0806, arp_tpa=str(rule.destination_ip)),
                instructions=instructions,
            ))
        self.ready.discard(datapath.id)
        self.install_batches.pop(datapath.id, None)
        xids: set[int] = set()
        failed = False
        for message in messages:
            datapath.set_xid(message)
            xids.add(message.xid)
            if not datapath.send_msg(message):
                failed = True
                break
        if failed:
            self.logger.error("Could not queue flow update for %s", self.switch_ids[datapath.id])
            return
        barrier = parser.OFPBarrierRequest(datapath)
        datapath.set_xid(barrier)
        self.install_batches[datapath.id] = _InstallBatch(datapath, barrier.xid, xids, bool(rules))
        if not datapath.send_msg(barrier):
            self.install_batches.pop(datapath.id, None)
            self.logger.error("Could not queue barrier for %s", self.switch_ids[datapath.id])

    @set_ev_cls(ofp_event.EventOFPErrorMsg, [CONFIG_DISPATCHER, MAIN_DISPATCHER])
    def error_handler(self, ev: Any) -> None:
        message = ev.msg
        self.ready.discard(message.datapath.id)
        batch = self.install_batches.get(message.datapath.id)
        if batch is not None and batch.datapath is message.datapath and message.xid in batch.message_xids:
            batch.failed = True
        self.logger.error(
            "OpenFlow error on DPID %016x: type=%s code=%s xid=%s",
            message.datapath.id, message.type, message.code, message.xid,
        )

    @set_ev_cls(ofp_event.EventOFPBarrierReply, MAIN_DISPATCHER)
    def barrier_reply_handler(self, ev: Any) -> None:
        message = ev.msg
        batch = self.install_batches.get(message.datapath.id)
        if batch is None or batch.datapath is not message.datapath or batch.barrier_xid != message.xid:
            return
        self.install_batches.pop(message.datapath.id, None)
        switch_id = self.switch_ids[message.datapath.id]
        if batch.failed:
            self.logger.error("Flow update failed for %s", switch_id)
        elif batch.has_rules:
            self.ready.add(message.datapath.id)
            self.logger.info("Flow update confirmed for %s", switch_id)
        else:
            self.logger.warning("Flows cleared for %s while ports are unavailable", switch_id)
