"""Measure real Mininet tc update latency without starting the controller.

Run this standalone script explicitly as root. It is intentionally not named
test_*.py, so normal unit-test discovery cannot start a network.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from ipaddress import ip_network
import math
import os
from pathlib import Path
import platform
import random
import shutil
import statistics
import sys
import time
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from channel_mininet.backends.mininet import make_basic_topo  # noqa: E402
from channel_mininet.channel_schedule import parse_snapshot  # noqa: E402
from channel_mininet.runtime.channel_shaper import ChannelShaper  # noqa: E402
from channel_mininet.runtime.worker import _check_bridge_names  # noqa: E402
from channel_mininet.schema import Scene, scene_from_dict  # noqa: E402


FIELDS = (
    "phase", "changed_links", "trial", "operation", "link_id", "direction",
    "duration_ms", "started_unix_ns", "ended_unix_ns", "status",
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--links", type=int, help="total links; default 100 unless --hosts is given")
    result.add_argument("--hosts", type=int, help="number of hosts; each has one link")
    result.add_argument("--switches", type=int, default=10, help="switches in a chain (default: 10)")
    result.add_argument("--step-links", type=int, default=10, help="link count increment (default: 10)")
    result.add_argument("--repeats", type=int, default=5, help="measured rounds per count (default: 5)")
    result.add_argument("--warmups", type=int, default=1, help="unmeasured full rounds (default: 1)")
    result.add_argument("--seed", type=int, default=42)
    return result


def make_scene(host_count: int, switch_count: int, rng: random.Random, token: str) -> Scene:
    subnet = ip_network("10.199.0.0/16")
    if host_count < 1 or host_count > subnet.num_addresses - 2:
        raise ValueError("need at least one host and enough 10.199.0.0/16 addresses")
    switches = [f"b{token}s{i}" for i in range(1, switch_count + 1)]
    data = {
        "version": 1,
        "experiment": f"tb{token}",
        "subnet": str(subnet),
        "workers": ["bench"],
        "hosts": [],
        "switches": [
            {"id": name, "worker": "bench", "dpid": f"{int(token, 16) << 16 | i:016x}"}
            for i, name in enumerate(switches, 1)
        ],
        "links": [],
    }
    addresses = subnet.hosts()
    for i in range(1, host_count + 1):
        host = f"b{token}h{i}"
        data["hosts"].append({
            "id": host, "worker": "bench", "ip": str(next(addresses)),
            "mac": "02:bc:" + ":".join(f"{(i >> shift) & 255:02x}" for shift in (24, 16, 8, 0)),
        })
        data["links"].append({
            "id": f"l{len(data['links']) + 1}", "a": host, "b": rng.choice(switches),
        })
    for left, right in zip(switches, switches[1:]):
        data["links"].append({
            "id": f"l{len(data['links']) + 1}", "a": left, "b": right,
        })
    return scene_from_dict(data)


def random_target(rng: random.Random, recorded_at: str) -> dict:
    return {
        "bandwidth_mbps": round(rng.uniform(5, 1000), 3),
        "netem_delay_ms": round(rng.uniform(1, 200), 3),
        "source": {
            "kind": "scenario_assumption",
            "reference": "Synthetic tc benchmark input; not a measured link property.",
            "recorded_at": recorded_at,
        },
    }


def changed_state(state: dict, chosen: list[str], rng: random.Random, recorded_at: str) -> dict:
    result = state.copy()
    for link_id in chosen:
        replacement = {
            "a_to_b": random_target(rng, recorded_at),
            "b_to_a": random_target(rng, recorded_at),
        }
        if link_id in state:
            for direction in ("a_to_b", "b_to_a"):
                previous = state[link_id][direction]
                while all(replacement[direction][key] == previous[key]
                          for key in ("bandwidth_mbps", "netem_delay_ms")):
                    replacement[direction] = random_target(rng, recorded_at)
        result[link_id] = replacement
    return result


def snapshot_for(scene: Scene, state: dict, selected: list[str]):
    return parse_snapshot({
        "sim_time_ms": 0,
        "links": [{"link_id": link_id, **state[link_id]} for link_id in selected],
    }, scene, 0)


class TimedShaper(ChannelShaper):
    def __init__(self, scene: Scene, network, rows: list[dict]):
        super().__init__(scene, network, ("bench",))
        self.rows = rows
        self.phase: str | None = None
        self.changed_links = 0
        self.trial = 0

    def _run(self, egress, args: list[str]) -> None:
        start_wall = time.time_ns()
        start = time.perf_counter_ns()
        status = "ok"
        try:
            super()._run(egress, args)
        except Exception:
            status = "error"
            raise
        finally:
            end = time.perf_counter_ns()
            if self.phase is not None:
                self.rows.append({
                    "phase": self.phase, "changed_links": self.changed_links,
                    "trial": self.trial, "operation": " ".join(args[:2]),
                    "link_id": egress.link_id, "direction": egress.direction,
                    "duration_ms": (end - start) / 1_000_000,
                    "started_unix_ns": start_wall, "ended_unix_ns": time.time_ns(),
                    "status": status,
                })


def measure(shaper: TimedShaper, scene: Scene, state: dict, selected: list[str],
            all_ids: list[str], phase: str, trial: int, rows: list[dict]) -> None:
    original_egresses = shaper.egresses
    if phase == "selected":
        selected_set = set(selected)
        shaper.egresses = tuple(e for e in original_egresses if e.link_id in selected_set)
        included = selected
    else:
        included = all_ids
    snapshot = snapshot_for(scene, state, included)
    shaper.phase = phase
    shaper.changed_links = len(selected)
    shaper.trial = trial
    start_wall = time.time_ns()
    start = time.perf_counter_ns()
    status = "ok"
    try:
        shaper.apply(snapshot)
    except Exception:
        status = "error"
        raise
    finally:
        end = time.perf_counter_ns()
        rows.append({
            "phase": phase, "changed_links": len(selected), "trial": trial,
            "operation": "batch", "link_id": "", "direction": "",
            "duration_ms": (end - start) / 1_000_000,
            "started_unix_ns": start_wall, "ended_unix_ns": time.time_ns(),
            "status": status,
        })
        shaper.phase = None
        shaper.egresses = original_egresses


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summary_rows(rows: list[dict], counts: list[int]) -> list[dict]:
    result = []
    for phase in ("selected", "full_snapshot"):
        for count in counts:
            group = [row for row in rows if row["phase"] == phase and row["changed_links"] == count]
            batches = [row["duration_ms"] for row in group if row["operation"] == "batch"]
            commands = [row["duration_ms"] for row in group if row["operation"] != "batch"]
            classes = [row["duration_ms"] for row in group if row["operation"] == "tc class"]
            qdiscs = [row["duration_ms"] for row in group if row["operation"] == "tc qdisc"]
            result.append({
                "phase": phase, "changed_links": count, "repeats": len(batches),
                "tc_commands_per_batch": len(commands) // len(batches),
                "batch_mean_ms": statistics.mean(batches),
                "batch_median_ms": statistics.median(batches),
                "batch_p95_ms": percentile(batches, 0.95),
                "tc_mean_ms": statistics.mean(commands),
                "tc_median_ms": statistics.median(commands),
                "tc_p95_ms": percentile(commands, 0.95),
                "class_mean_ms": statistics.mean(classes),
                "netem_mean_ms": statistics.mean(qdiscs),
            })
    return result


def command_summary_rows(rows: list[dict]) -> list[dict]:
    result = []
    for phase in ("selected", "full_snapshot"):
        for operation in ("tc class", "tc qdisc", "all tc"):
            values = [row["duration_ms"] for row in rows
                      if row["phase"] == phase and
                      (row["operation"] == operation or
                       (operation == "all tc" and row["operation"] != "batch"))]
            result.append({
                "phase": phase, "operation": operation, "samples": len(values),
                "mean_ms": statistics.mean(values),
                "median_ms": statistics.median(values),
                "p95_ms": percentile(values, 0.95),
            })
    return result


def write_csv(path: Path, rows: list[dict], fields) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def append_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writerows(rows)


def write_chart(path: Path, summary: list[dict], counts: list[int]) -> None:
    width, height = 920, 560
    left, top, plot_width, plot_height = 95, 55, 775, 410
    maximum = max(row["batch_mean_ms"] for row in summary) * 1.12
    maximum = max(maximum, 1.0)
    minimum_x, maximum_x = min(counts), max(counts)

    def x_position(value: int) -> float:
        return left + (value - minimum_x) / max(1, maximum_x - minimum_x) * plot_width
    def y_position(value: float) -> float:
        return top + plot_height - value / maximum * plot_height

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#253449;font-size:14px} .grid{stroke:#e4e8ef;stroke-width:1}</style>',
        '<text x="95" y="29" font-size="20">tc update duration versus changed links</text>',
    ]
    for tick in range(6):
        value = maximum * tick / 5
        y = y_position(value)
        parts.append(f'<line class="grid" x1="{left}" y1="{y:.2f}" x2="{left + plot_width}" y2="{y:.2f}"/>')
        parts.append(f'<text x="{left - 12}" y="{y + 5:.2f}" text-anchor="end">{value:.0f}</text>')
    for count in counts:
        x = x_position(count)
        parts.append(f'<text x="{x:.2f}" y="{top + plot_height + 25}" text-anchor="middle">{count}</text>')
    parts.append(f'<text x="{left + plot_width / 2:.0f}" y="{height - 38}" text-anchor="middle">Changed links</text>')
    parts.append(f'<text x="25" y="{top + plot_height / 2:.0f}" transform="rotate(-90 25 {top + plot_height / 2:.0f})" text-anchor="middle">Mean batch time (ms)</text>')
    for phase, color, label in (
        ("selected", "#2563eb", "Selected links only"),
        ("full_snapshot", "#d97706", "Full topology snapshot"),
    ):
        series = sorted((row for row in summary if row["phase"] == phase), key=lambda row: row["changed_links"])
        points = " ".join(f'{x_position(row["changed_links"]):.2f},{y_position(row["batch_mean_ms"]):.2f}' for row in series)
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="3"/>')
        for row in series:
            parts.append(f'<circle cx="{x_position(row["changed_links"]):.2f}" cy="{y_position(row["batch_mean_ms"]):.2f}" r="4" fill="{color}"/>')
        legend_y = top + plot_height + 48 if phase == "selected" else top + plot_height + 72
        parts.append(f'<line x1="{left}" y1="{legend_y}" x2="{left + 35}" y2="{legend_y}" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<text x="{left + 45}" y="{legend_y + 5}">{label}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def write_report(path: Path, summary: list[dict], commands: list[dict], args,
                 host_count: int, run_name: str) -> None:
    lines = [
        "# tc 切换耗时基准结果", "",
        f"运行编号：`{run_name}`。平台：`{platform.platform()}`；CPU 数：`{os.cpu_count()}`。", "",
        f"拓扑：{host_count} 台主机、{args.switches} 台交换机、{args.links} 条链路；随机种子 {args.seed}。每个规模测量 {args.repeats} 次，预热 {args.warmups} 轮。", "",
        "![耗时趋势](trend.svg)", "",
        "| 修改链路数 | 仅选中链路均值 / P95 (ms) | 完整时间片均值 / P95 (ms) |",
        "| ---: | ---: | ---: |",
    ]
    by_key = {(row["phase"], row["changed_links"]): row for row in summary}
    for count in sorted({row["changed_links"] for row in summary}):
        selected = by_key["selected", count]
        full = by_key["full_snapshot", count]
        lines.append(
            f"| {count} | {selected['batch_mean_ms']:.2f} / {selected['batch_p95_ms']:.2f} "
            f"| {full['batch_mean_ms']:.2f} / {full['batch_p95_ms']:.2f} |"
        )
    selected_tc = next(row for row in commands
                       if row["phase"] == "selected" and row["operation"] == "all tc")
    full_tc = next(row for row in commands
                   if row["phase"] == "full_snapshot" and row["operation"] == "all tc")
    first_count = min(row["changed_links"] for row in summary)
    last_count = max(row["changed_links"] for row in summary)
    selected_first = by_key["selected", first_count]["batch_mean_ms"]
    selected_last = by_key["selected", last_count]["batch_mean_ms"]
    full_first = by_key["full_snapshot", first_count]["batch_mean_ms"]
    full_last = by_key["full_snapshot", last_count]["batch_mean_ms"]
    full_p95 = max(row["batch_p95_ms"] for row in summary
                   if row["phase"] == "full_snapshot")
    lines += [
        "", "## 实测比较", "",
        f"仅修改选中链路时，从 {first_count} 条增至 {last_count} 条，平均整批耗时从 {selected_first:.2f} ms 增至 {selected_last:.2f} ms（{selected_last / selected_first:.2f} 倍）。", "",
        f"完整 {args.links} 链路时间片中，虽然实际变化的链路从 {first_count} 条增至 {last_count} 条，平均整批耗时为 {full_first:.2f} ms 与 {full_last:.2f} ms；当前实现每片都处理全部链路。", "",
        f"完整时间片各规模中最大的实测 P95 为 {full_p95:.2f} ms。再加控制器代码要求的 500 ms 提交提前量，得到 {full_p95 + 500:.2f} ms 的粗略下限；这尚未计入网络传输、准备和确认耗时，不能直接作为安全时间片间隔。", "",
        "## 口径", "",
        "- `raw.csv` 逐条记录每个 `tc class change`、`tc qdisc change` 和整批 `apply()` 的耗时；`summary.csv` 给出各规模统计，`command_summary.csv` 汇总单条命令的耗时。耗时使用单调时钟，时间戳使用 Unix 时钟。",
        f"- `selected`：固定 {args.links} 链路拓扑，只让 `ChannelShaper` 遍历本轮选中的链路。每条双向链路执行 4 条 `tc` 命令；该模式用于观察修改规模的增长趋势。",
        "- `full_snapshot`：同一拓扑始终向 `ChannelShaper.apply()` 提交全部链路，即使只有表中的 N 条链路数值变化，当前实现仍更新所有链路。这是现有控制器发布完整时间片时 Worker 的本地配置路径。",
        "- 创建 Mininet、首次安装 HTB/netem 和清理资源均不计入表中的耗时。没有控制器、跨机 VXLAN 或业务流量；结果不能直接代表跨机器切换错位或实际端到端性能。",
        "- 每条命令的时间含 Mininet `node.popen()`、进程启动及命令完成；整批时间含 Python 循环。各接口串行修改，整批完成时间与第一个接口生效时间不同。",
        "- 控制器会等上一片全部 `APPLIED` 后才准备下一片，且要求下一片至少提前 0.5 秒完成 `COMMIT`。因此时间片间隔需要大于本地最慢批次耗时、上报与准备延迟，再加 0.5 秒余量。",
        "- P95 来自有限重复样本，仅描述本次机器和负载；正式设定时间片间隔应增加重复次数并单独验证控制器到多 Worker 的完整切换。",
        "", "## 单条 tc 命令", "",
        f"仅选中链路模式：{selected_tc['samples']} 条命令，均值 {selected_tc['mean_ms']:.3f} ms，中位数 {selected_tc['median_ms']:.3f} ms，P95 {selected_tc['p95_ms']:.3f} ms。", "",
        f"完整时间片模式：{full_tc['samples']} 条命令，均值 {full_tc['mean_ms']:.3f} ms，中位数 {full_tc['median_ms']:.3f} ms，P95 {full_tc['p95_ms']:.3f} ms。", "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parser().parse_args()
    if args.switches < 1 or args.step_links < 1:
        raise SystemExit("Require --switches >= 1 and --step-links >= 1.")
    if args.hosts is None:
        args.links = 100 if args.links is None else args.links
        args.hosts = args.links - args.switches + 1
    else:
        expected_links = args.hosts + args.switches - 1
        if args.links is not None and args.links != expected_links:
            raise SystemExit(
                f"A connected tree with {args.hosts} hosts and {args.switches} switches "
                f"has {expected_links} links; --links={args.links} conflicts with that."
            )
        args.links = expected_links
    if args.hosts < 1:
        raise SystemExit("Require at least one host; increase --links or reduce --switches.")
    if os.geteuid() != 0:
        raise SystemExit("This benchmark creates Mininet namespaces; run with sudo.")
    if args.repeats < 1 or args.warmups < 0:
        raise SystemExit("Require --repeats >= 1 and --warmups >= 0.")
    for executable in ("tc", "ip", "ovs-vsctl"):
        if shutil.which(executable) is None:
            raise SystemExit(f"Required executable not found: {executable}")
    from mininet.net import Mininet
    from mininet.node import Host, OVSBridge

    rng = random.Random(args.seed)
    token = uuid4().hex[:6]
    run_name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + token
    output = Path(__file__).resolve().parent / "results" / run_name
    output.mkdir(parents=True, exist_ok=False)
    scene = make_scene(args.hosts, args.switches, rng, token)
    _check_bridge_names(scene, None)
    all_ids = [link.id for link in scene.links]
    counts = list(range(args.step_links, args.links + 1, args.step_links))
    if args.links not in counts:
        counts.append(args.links)
    recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state = changed_state({}, all_ids, rng, recorded_at)
    rows: list[dict] = []
    raw_path = output / "raw.csv"
    write_csv(raw_path, [], FIELDS)
    network = Mininet(
        topo=make_basic_topo(scene), host=Host, switch=OVSBridge, controller=None,
        build=False, cleanup=False, autoSetMacs=False, autoStaticArp=False,
    )
    try:
        network.build()
        network.start()
        shaper = TimedShaper(scene, network, rows)
        shaper.apply(snapshot_for(scene, state, all_ids))  # Untimed first installation.
        all_egresses = shaper.egresses
        for _ in range(args.warmups):
            chosen = rng.sample(all_ids, args.links)
            state = changed_state(state, chosen, rng, recorded_at)
            measure(shaper, scene, state, chosen, all_ids, "selected", 0, rows)
            state = changed_state(state, chosen, rng, recorded_at)
            measure(shaper, scene, state, chosen, all_ids, "full_snapshot", 0, rows)
        rows.clear()
        written = 0
        for trial in range(1, args.repeats + 1):
            order = counts[:]
            rng.shuffle(order)
            for count in order:
                chosen = rng.sample(all_ids, count)
                try:
                    state = changed_state(state, chosen, rng, recorded_at)
                    measure(shaper, scene, state, chosen, all_ids, "selected", trial, rows)
                    state = changed_state(state, chosen, rng, recorded_at)
                    measure(shaper, scene, state, chosen, all_ids, "full_snapshot", trial, rows)
                finally:
                    append_csv(raw_path, rows[written:])
                    written = len(rows)
                print(f"trial={trial} changed_links={count} complete", flush=True)
        shaper.egresses = all_egresses
    finally:
        network.stop()
    summary = summary_rows(rows, counts)
    commands = command_summary_rows(rows)
    write_csv(output / "summary.csv", summary, tuple(summary[0]))
    write_csv(output / "command_summary.csv", commands, tuple(commands[0]))
    write_chart(output / "trend.svg", summary, counts)
    write_report(output / "REPORT.md", summary, commands, args, len(scene.hosts), run_name)
    for row in summary:
        print(
            f"{row['phase']:13s} links={row['changed_links']:3d} "
            f"batch_mean={row['batch_mean_ms']:.2f} ms "
            f"batch_p95={row['batch_p95_ms']:.2f} ms "
            f"single_tc_mean={row['tc_mean_ms']:.3f} ms"
        )
    print(f"Results: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
