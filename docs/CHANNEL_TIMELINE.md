# 中央控制器发布的链路时间片

本功能的源码已经接入，但按项目约定尚未运行部署或代码测试。物理链路效果、跨机 VXLAN 整形路径、时钟误差和故障关停时长均待现场验收。

## 文件格式与数值含义

中央控制器读取版本 2 的 JSON 时间片文件。顶层有 `version: 2`、与场景匹配的 `scene_digest`、正整数 `revision` 和 `snapshots`。每片含严格递增的整数 `sim_time_ms`，首片必须为 0。每片的 `links` 只列出需要配置的链路；未列出的链路保持普通 Mininet 默认配置。列出的每条链路都必须同时提供 `a_to_b`、`b_to_a`，分别有正数 `bandwidth_mbps`、非负 `netem_delay_ms`，以及 `source: {kind, reference, recorded_at}`；`kind` 为 `measurement`、`simulation` 或 `scenario_assumption`。`recorded_at` 是带时区的 ISO 8601 时间。相邻时间片之间沿用上一片状态；下一个时间片若省略先前配置的链路，Worker 会删除自己为它安装的整形规则，让它恢复默认。所有实验接口在首次 `APPLIED` 前仍按统一调度要求暂时关闭，控制器失联时也会关闭以避免继续使用过期时间片。

`bandwidth_mbps` 是发送出口的目标整形速率，不是物理端口标称速率或业务实测吞吐。`netem_delay_ms` 是直接加在出口的 **附加时延**，不是链路报文总单向时延，也不同于旧版 `ChannelState.delay_ms` 所表示的物理传播时延。当前样例中的 4.765 ms 是场景假设，不是 100 m 电缆传播估计或实测链路时延。

[`configs/channel_profile.reference.json`](../configs/channel_profile.reference.json) 与 [`configs/scenes/two_workers/channel.json`](../configs/scenes/two_workers/channel.json) 均覆盖 19 条链路，`la1` 保留原有设定，其余 18 条由种子 42 随机生成；中央控制器可直接加载场景目录。所有目标值目前都是场景假设。正式研究应由 MATLAB 或采集流程提供有来源的结果，替换这些假设。旧版 `version: 1` 物理输入仍可供 `channel-plan` 只读解析，但不参与时间片运行。

例如，`sudo ./start.sh --worker a --deployment configs/deployment.yml` 未指定 `--channel`，只创建普通 Mininet 链路，完全不读取参考文件，也不会设置 HTB/netem。启用信道后，`la1` 样例的 4.765 ms 换算为 `4765us`，分别配置在两个发送方向；经过该链路的往返报文目标附加时延合计为 9.53 ms，实际效果仍受内核定时与排队影响。验收应先确认中央控制器已加载文件且每个 Worker 报告 `APPLIED`，再检查对应发送接口的 `tc qdisc/class` 配置并测量实际时延。

`netem_delay_ms` 在下发时按四舍五入换算为整数微秒，使用 `us` 单位，以兼容 Worker 上的旧版 `tc`；非零值若量化为 0 µs 则拒绝，避免悄悄取消目标时延。旧版 `tc` 不能准确实现亚微秒目标，内核定时和排队也会影响实际效果。[旧版 iproute2 netem 源码](https://raw.githubusercontent.com/iproute2/iproute2/v5.15.0/tc/q_netem.c)、[时间解析源码](https://raw.githubusercontent.com/iproute2/iproute2/v5.15.0/lib/utils.c)

## 启动接口

只读查看样例：

```bash
./.venv/bin/md-mininet channel-plan configs/scenes/two_workers
```

中央控制器独自加载参考文件或其他版本 2 时间片文件：

```bash
./.venv/bin/md-controller --scene configs/scenes/two_workers
```

每台 Worker 使用同一场景目录，分别启动 `--worker a`、`--worker b`；目录模式自动读取部署文件并启用信道。部署文件 `controller.channel_port` 缺省为 6654。单机 `--all-workers` 也可通过 `--controller-host` 和 `--channel` 连接中央控制器。Worker 不读取时间片文件；控制器通过独立 TCP 通道发送完整时间片，Worker 只应用自己负责的出口。域控制器目前没有实现，信道通道不依赖它。

```bash
# 在 Worker a 机器上
sudo ./start.sh --scene configs/scenes/two_workers --worker a
# 在 Worker b 机器上
sudo ./start.sh --scene configs/scenes/two_workers --worker b
```

控制器的信道 TCP 端口需对 Worker 可达，并应限制在可信的实验网络中；当前协议按场景和 Worker ID 校验消息，但不提供独立的身份认证。

如果 Worker 显示 `Connection refused`，说明它连接的控制器地址和信道端口（示例部署文件中为 `192.168.145.132:6654`）没有接受连接。OpenFlow 的 `6653` 端口能连接，不代表信道端口已经启动。应先在中央控制器机器上按上面的命令启动控制器，再核对控制器日志中的 `Channel run ... listening` 和 Worker 侧的 `APPLIED` 回报。旧式 JSON 文件模式下，控制器不带 `--channel-profile` 不会监听 6654；目录模式自动加载 `channel.json`。

## 调度与故障

中央控制器生成 `run_id`，等待所有 Worker 连接，再逐片执行 `PREPARE → READY → COMMIT → APPLIED`。`PREPARE` 包含完整快照、摘要和未来生效时刻；只有全部 Worker 确认后才发送 `COMMIT`。Worker 在该时刻配置本地发送出口，返回每个 Worker 的实际完成时间。首片启动后，后续时刻按首片的控制器计划时间加 `sim_time_ms` 计算；若准备来不及、缺少确认或应用失败，实验标记失败并向在线 Worker 发送停止消息。

Worker 与中央控制器的信道连接失效时会关闭本机负责的实验接口；控制器也会撤销该 Worker 的路由流表。重连后由控制器重新发送当前已成功应用的时间片，Worker 完成后才恢复。正常切换不主动暂停业务，但各机时钟和逐接口 `tc` 操作仍会造成短暂错位。日志中的跨 Worker 时间差取自 Worker 报告的系统时钟；要把它用于验收，必须先核对物理机时钟同步。当前故障关停由进程和 OpenFlow 控制面触发，异常断电或 `SIGKILL` 后的遗留网络资源仍需单独处理。

本地链路在发送端的 veth 出口使用 HTB 与 netem。跨 Worker 的每个 VXLAN 端点增加独立的双端口 OVS 桥和 veth；主交换机上的 veth 保留原逻辑端口名，出口配置该方向的参数，不对共享物理网卡统一限速。正常退出只清理本进程创建并标记所有权的桥、隧道和接口。
