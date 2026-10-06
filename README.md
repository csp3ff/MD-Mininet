# MD-Mininet

MD-Mininet 是一个面向多 Worker 实验的 Mininet 项目，支持单机完整拓扑和多台物理机分区运行。每台 Worker 电脑安装**同一份源码**、读取**同一份场景配置**，再用不同的 Worker ID 选择本机负责的节点和链路。当前示例有 A、B 两个分区，每个分区包含 8 台模拟主机和 2 台模拟交换机。

> **当前状态：分布式 Mininet 网络已搭建。** 据使用者运行反馈，单个集中式 Ryu 控制器管理交换机，当前任意两个模拟主机可以相互发包；这不代表链路性能、故障恢复和多轮实验已经验收。默认 `up` 使用 OVS 桥；指定远程控制器后使用 OpenFlow 1.3 交换机。`--all-workers` 在单机创建完整拓扑；`--worker` 配合部署配置在每台物理机创建本地拓扑及跨机 VXLAN 端口。中央控制器发布链路时间片的源码已加入，完整参考文件覆盖 19 条链路，时间片数据面仍待现场验收。详见 [链路时间片说明](docs/CHANNEL_TIMELINE.md)与 [研究计划](docs/RESEARCH_PLAN.md)。`validate`、`plan` 和 `channel-plan` 都是只读命令。

## 场景目录与最新启动命令

一个场景目录包含 `workers.json`（仿真拓扑）、`deployment.yml`（物理机与控制器地址）和 `channel.json`（版本 2 时间片）。完整示例在 [`configs/scenes/two_workers/`](configs/scenes/two_workers)。同一目录须同步到控制器与所有 Worker；后两个文件的 `scene_digest` 必须与 `workers.json` 计算出的摘要一致。示例物理地址为 Worker a `192.168.145.131`、Worker b 和控制器 `192.168.145.132`，使用前应改成实际地址。

以下命令分别在控制器、Worker a、Worker b 所在机器的项目根目录运行。`--scene` 指向场景**文件夹**；控制器从 `deployment.yml` 取得监听地址和端口并加载 `channel.json`，Worker 自动读取部署配置并启用信道模式。控制器先启动，之后启动两个 Worker。按项目约定，这些命令目前仅作为操作说明，本次没有执行。

```bash
# 控制器机器（192.168.145.132）
./.venv/bin/md-controller --scene configs/scenes/two_workers

# Worker a 机器（192.168.145.131）
sudo ./start.sh --scene configs/scenes/two_workers --worker a

# Worker b 机器（192.168.145.132）
sudo ./start.sh --scene configs/scenes/two_workers --worker b
```

只读检查完整目录及每条链路的双向目标：

```bash
./.venv/bin/md-mininet validate configs/scenes/two_workers
./.venv/bin/md-mininet channel-plan configs/scenes/two_workers
./.venv/bin/md-mininet plan configs/scenes/two_workers --worker a
./.venv/bin/md-mininet plan configs/scenes/two_workers --worker b
```

基于已有拓扑生成另一套目录时，下面的命令用种子 42 为全部链路随机生成**场景假设**。默认只生成 `sim_time_ms=0` 的一个时间片；`--steps 10 --step-ms 1000` 会生成 10 片，时间分别为 0、1000、…、9000 ms，每片均包含全部链路的双向目标。如果有仅配置部分链路的版本 2 文件，可加 `--base-channel 文件路径`，保留其中的**首片**配置并随机补齐缺失链路；后续时间片全部重新随机生成。输出目录必须尚不存在；生成器不启动 Mininet。`--seed` 固定数值，若还需字节级复现，显式指定 `--recorded-at 2026-10-06T00:00:00+00:00`。生成结果不是实测性能参数，正式实验应替换并注明真实来源。

```bash
./.venv/bin/md-mininet generate-scene configs/two_workers.json configs/scenes/my_scene \
  --worker-ip a=192.168.145.131 --worker-ip b=192.168.145.132 \
  --controller-host 192.168.145.132 --seed 42 --steps 10 --step-ms 1000
```

也可同时随机创建拓扑与全部链路目标。下面的命令生成每个 Worker 8 台主机、2 台交换机；交换机组成一条连通链，主机随机接入本 Worker 的交换机。主机地址从 `10.77.0.0/24` 依次分配，随机种子决定接入交换机及每条链路的双向目标；仍需填入真实物理机地址。

```bash
./.venv/bin/md-mininet generate-random-scene configs/scenes/random_two_workers \
  --worker-ip a=192.168.145.131 --worker-ip b=192.168.145.132 \
  --controller-host 192.168.145.132 --seed 42 --steps 10 --step-ms 1000
```

## 开发进度与下一阶段

`[x]` 表示源码或文档已实现；运行结论另行注明，避免把“代码已写入”与“实验已验收”混为一谈。研究顺序与验收标准见 [RESEARCH_PLAN.md](docs/RESEARCH_PLAN.md)。

- [x] 建立 Python 包、命令入口和双 Worker 示例场景；实现校验、全局标识、`scene_digest`、Worker 划分与静态路径规划。
- [x] 实现标准 Mininet Host/OVS 的前台启动，以及跨机器 VXLAN 端口的规划、创建和正常退出回收。
- [x] 实现独立的集中式 Ryu 控制器、端口核对、IPv4/ARP 流表安装与 Barrier 回执处理。
- [x] **使用者运行反馈：** 分布式网络已搭建，任意两个模拟主机当前可以相互发包；曾查看到 `sa1` 的规则及命中计数。
- [x] **P1 源码进展：** 已写入带节点参数来源字段校验的通用双向静态快照计算和只读 `channel-plan` 命令；参考配置已完成 `la1` 双向计算的只读运行验证。
- [x] **时间片源码进展：** 已加入版本 2 数据校验、中央控制器直发、Worker 出口整形及跨机独立整形路径；这些新增路径均未运行验证，参考文件覆盖全部 19 条链路。
- [ ] **P1 数据与演化：** 为拟模拟设备采集有参考依据的能力与初始状态，增加节点状态、共享环境、仿真时间和可复现演化规则，再核对状态序列。
- [ ] **P2 运行验收：** 实测本地链路与跨 Worker VXLAN 的双向整形、时延、切换错位、失联关停和资源清理；当前只有未运行的实现代码。
- [ ] **P3 无线与有线模型：** 分别补充两类介质的输入参数与计算方法，共用 P1 输出和 P2 下发路径。
- [ ] **P4 稳定性与复现：** 完成性能标定、状态检查、异常退出恢复、故障场景和多轮实验记录；扩展三台及以上 Worker 的验收。
- [ ] **P5 按需评估 Docker：** 推迟每节点容器化；需要独立软件环境或交换机进程时再决定是否引入。

## 1. 代码如何放到另一台电脑

建议目标电脑使用原生 Linux。只读规划命令需要 Python 3.10 或更新版本及项目依赖；`up` 还需要 Linux、Mininet、OVS 和创建网络命名空间的权限。当前部署与后续 P1/P2 工作不以 Docker 为前置条件。

### 方式 A：通过 Git

先在开发电脑上将 `README.md`、`docs/`、`pyproject.toml`、`src/`、`configs/` 和 `.gitignore` 提交并推送。本仓库当前的远端名和分支名都叫 `master`，远端地址是 `https://github.com/csp3ff/MD-Mininet.git`：

```bash
git add .gitignore README.md docs pyproject.toml start.sh clean.sh src configs
git commit -m "Add basic Mininet runner"
git push -u master master
```

这些命令是给开发电脑操作的说明，本次没有执行。推送需要仓库写入权限；若远端已有不同提交，应先正常合并，勿强制推送。**`git clone` 只能取得已经推送的内容，不能取得开发电脑上尚未提交的文件。** 推送完成后，在目标电脑执行：

```bash
git clone https://github.com/csp3ff/MD-Mininet.git
cd MD-Mininet
```

如果暂时没有推送权限，或希望复制当前未提交的改动，使用方式 B。

### 方式 B：直接复制当前工作目录

在**开发电脑**上执行，先把 `USER` 和 `HOST` 换成目标电脑的 SSH 用户名与地址：

```bash
rsync -av --exclude='.git/' --exclude='.venv/' --exclude='__pycache__/' \
  /home/csp/data/MDNET/ USER@HOST:~/MDNET/
```

在**目标电脑**上进入复制得到的目录：

```bash
cd ~/MDNET
```

这种复制方式包含当前目录中的未提交源码。源目录不是 `/home/csp/data/MDNET` 时，改成实际绝对路径。目标电脑需能通过 SSH 连接，并安装 `rsync`。

## 2. 在目标电脑安装当前版本

以下命令在项目根目录执行。若 Mininet 通过系统包安装，虚拟环境需使用 `--system-site-packages` 才能访问对应的 Python 包。创建虚拟环境和安装本项目不需要 root 权限：

```bash
python3 -m venv --system-site-packages .venv
./.venv/bin/python -m pip install .
```

安装完成后，可直接使用虚拟环境内的 `md-mininet` 命令。项目依赖包含解析 YAML 部署文件的 PyYAML。`pip install .` 安装的是当时的源码快照；以后更新源码，需要再次运行该安装命令。若要在目标电脑继续修改源码，可改用 `./.venv/bin/python -m pip install -e .`。如果只需规划命令，可不用 `--system-site-packages`，也不必安装 Mininet/OVS。虚拟环境和本地项目安装的用法见 [Python venv 文档](https://docs.python.org/3/library/venv.html)与 [pip 文档](https://pip.pypa.io/en/stable/topics/local-project-installs/)。

## 3. 查看同一场景在不同 Worker 上的规划

先用同一份场景文件检查全局配置：

```bash
./.venv/bin/md-mininet validate configs/two_workers.json
```

Worker A 和 Worker B 分别查看自己的规划：

```bash
./.venv/bin/md-mininet plan configs/two_workers.json --worker a
./.venv/bin/md-mininet plan configs/two_workers.json --worker b
```

两台电脑分别运行时，每台都应放置**完全相同的**场景目录，一台使用 `--worker a`，另一台使用 `--worker b`。输出中的 `scene_digest` 应相同；该摘要用于识别场景不一致，不代表两台机器已经建立连接。传入旧式 JSON 文件时，`plan` 默认只输出节点、边界链路、逻辑路由及预定接口名，带 `--deployment` 才输出 VXLAN 端点规划；传入场景目录时会自动读取部署文件。两种方式都不会启动 Worker 进程。

示例场景位于 [`configs/two_workers.json`](configs/two_workers.json)。第一版把两个“网络”定义为拓扑和部署分区，所有模拟主机共用 `10.77.0.0/24`；它们目前不是两个独立的 IP 子网。修改示例时，应保持节点 ID、主机 IP/MAC、交换机 DPID 和链路 ID 全局唯一。每台主机当前只能有一条业务链路，跨 Worker 链路只能连接交换机。

### 信道规划：版本 1 物理输入与版本 2 时间片

源码提供只读的 `md-mininet channel-plan 场景文件 信道配置文件`。以下三条描述保留的 **版本 1 物理输入**；新参考文件已经升级为版本 2，格式与运行方式见 [链路时间片说明](docs/CHANNEL_TIMELINE.md)。版本 1 顶层包含 `version=1`、`scene_digest`、正整数 `revision`、带时区的 `effective_time`、`ports` 和 `links`。

- `ports` 中每项对应一条逻辑链路的一个端点，包含 `link_id`、`node_id`、`port_type`、正数 `rate_mbps` 和 `source`。`source` 必须给出 `kind`（`device_readout`、`field_measurement` 或 `datasheet`）、`reference`、真实 `device_model`、带时区的 `recorded_at`。这些字段描述拟模拟的真实设备，不能从 Mininet 的 veth/OVS 虚拟端口读取后冒充设备规格。
- `links` 中每项包含 `link_id`、`model="generic"`、`a_to_b` 和 `b_to_a`。每个方向都要给出 `available`、正数 `nominal_bandwidth_mbps`、非负 `distance_m`（实际传播路径长度，米）、大于零且不超过真空光速的 `propagation_speed_mps`（该介质中的传播速度，米/秒）和 `source`；`source` 含 `kind`（`measurement`、`datasheet` 或 `scenario_assumption`）、`reference`、带时区的 `recorded_at`，用于区分测量值与场景设定。名义容量不得超过两个端点中较低的有来源端口速率，配置错误会直接报出，不再靠输出时取最小值掩盖。可选 `max_distance_m` 是该方向明确给出的正数场景上界，提供后 `distance_m` 不得超过它；这不是所有介质通用的物理极限。可选 `velocity_factor_of_c` 须在 0 到 1 之间，提供后必须与 `propagation_speed_mps / 299792458` 一致。输出的 `delay_ms = 1000 × distance_m / propagation_speed_mps` **仅为单向传播时延**，不含发送/序列化、交换处理、排队或重传时延。可选 `jitter_ms`、`loss_pct`；未提供时输出 `null`，不自动猜测。仅有端口速率、带宽、频率或发射功率，无法推出传播时延；缺少长度或传播速度时配置报错。
- 可以只配置部分链路以做小规模研究；已配置链路必须包含两个端点的来源数据及两个方向。输出列出 `modeled_links`、`unmodeled_links` 和每个方向的 `ChannelState`，便于识别覆盖缺口。

[`configs/channel_profile.reference.json`](configs/channel_profile.reference.json) 现为版本 2 的完整单时间片样例，覆盖全部 19 条链路；它与场景目录中的 [`channel.json`](configs/scenes/two_workers/channel.json) 内容相同。`la1` 保留原有双向 1000 Mb/s、4.765 ms 附加时延设定，其他 18 条链路由种子 42 随机生成。所有数值均为场景假设，并非业务实测吞吐或传播测量值。Worker 将 `la1` 的时延换算为 `4765us` 下发给 `tc`。正数时延按微秒四舍五入；小于 0.5 µs、会量化为 0 µs 的配置直接拒绝。

在项目根目录运行只读规划：

```bash
PYTHONPATH=src python3 -m channel_mininet.cli channel-plan configs/two_workers.json configs/channel_profile.reference.json
```

`channel-plan` 对版本 2 显示每片的已配置链路、保持默认的链路、双向参数及发送出口；它不创建或配置网络。来源字段由程序校验，来源内容仍需人工核对。版本 2 文件由中央控制器加载并直接向 Worker 发布；具体启动方式和同步语义见 [链路时间片说明](docs/CHANNEL_TIMELINE.md)。

## 4. 启动单机基础网络

安装 Mininet 与 OVS，并确保它们能被当前虚拟环境使用后，在项目根目录执行以下命令。`up` 会实际创建网络命名空间、veth 和 OVS 桥，需要 root 权限；**项目当前约定暂不运行部署或代码测试。** 分布式受控模式已有使用者互通反馈；下述单机基础模式尚无单独验收记录。

```bash
sudo ./start.sh
```

`start.sh` 默认读取 `configs/two_workers.json` 并在本机启动所有 Worker 分区；可用 `--scene 路径` 指定其他场景，路径相对于项目根目录。脚本使用项目 `.venv/bin/md-mininet`，需先按上文安装项目。每次启动前会调用 `clean.sh`，按本次场景和 Worker 范围清理上一次异常退出遗留的资源；发现仍在运行的 Mininet 进程时会停止启动。

这会在**同一台 Linux 机器、同一个 Mininet 进程**中创建示例的 16 台主机、4 台交换机及跨分区链路，然后进入 Mininet CLI。预期可在 CLI 中查看节点与链路，并在退出 CLI 后由 `network.stop()` 回收本次 Mininet 创建的资源。该模式使用 OVS 桥的普通 MAC 学习转发，适合先检查拓扑和基本通信；它不验证中央 SDN 控制器或本文规划的 OpenFlow 规则。示例拓扑没有交换机环路；基础桥接模式会拒绝带交换机环路的场景。

同一份源码也支持只启动一个 Worker 的本地部分：

```bash
sudo ./start.sh --worker a
```

不带部署配置的单 Worker 模式**不创建跨 Worker 链路**。分别在两台电脑上仅运行 `--worker a` 和 `--worker b`，只能得到两张各自独立的本地网络。跨机器连接使用下文的 `--deployment`。退出 Mininet CLI 时输入 `exit`；项目不会调用全局的 `mn -c`。

Mininet 的安装方式见[官方安装说明](https://github.com/mininet/mininet/blob/master/INSTALL)。Mininet 和本项目虚拟环境必须使用兼容的 Python 版本；若 `up` 报 Mininet 无法导入，先核对其安装位置及虚拟环境的 `--system-site-packages` 设置。

### 独立启动 Ryu 中央控制器

控制器不由 Mininet 启动或停止。Ryu 4.34 的构建脚本调用了 setuptools 68 已移除的 `easy_install.get_script_args`，而关闭构建隔离后还必须预先安装其 `setup_requires` 指定的 PBR；否则会报 `Unknown distribution option: 'pbr'` 和 `Multiple top-level packages discovered`。先在项目虚拟环境中准备 Ryu 的构建依赖，再单独安装 Ryu 和本项目：

```bash
./.venv/bin/python -m pip install 'setuptools==67.8.0' 'pbr==5.11.1' wheel
./.venv/bin/python -m pip install --no-build-isolation --no-deps 'ryu==4.34'
./.venv/bin/python -m pip install -e '.[controller]'
```

`--no-build-isolation` 只用于构建 Ryu，使它使用刚安装的 setuptools 和 PBR；`--no-deps` 将 Ryu 的其余依赖交给最后一条命令正常安装。本项目的构建环境仍按 `pyproject.toml` 使用 setuptools 68 或更新版本。参见 [Ryu 的 setup.py](https://github.com/faucetsdn/ryu/blob/v4.34/setup.py)、[setuptools 68 变更记录](https://setuptools.pypa.io/en/latest/history.html#v68-0-0)和 [pip 构建隔离说明](https://pip.pypa.io/en/stable/reference/build-system/#disabling-build-isolation)。

Ryu 4.34 启动时还会导入新版 Eventlet 已移除的 `ALREADY_HANDLED`。项目的 `md-controller` 入口在导入 Ryu 前为缺失的符号提供兼容值；请使用包含这项修正的源码。Eventlet 的弃用提示是警告，不代表控制器已经启动。参见 [Ryu 已报告的问题](https://github.com/faucetsdn/ryu/issues/180)与 [Ryu 后续源码](https://github.com/faucetsdn/ryu/blob/master/ryu/app/wsgi.py)。

安装后，在一个终端启动控制器；它不需要 root：

```bash
./.venv/bin/md-controller configs/two_workers.json --listen-host 127.0.0.1 --listen-port 6653
```

在另一个终端启动单机完整拓扑，并指定已运行的控制器地址：

```bash
sudo ./start.sh --controller-host 127.0.0.1 --controller-port 6653
```

受控模式使用 `OVSSwitch`、OpenFlow 1.3 和 `failMode=secure`。控制器从同一场景读取 DPID 与链路，等待交换机上报端口描述，用实际 `ofport` 对应预定接口名；端口齐备后，按目的主机 IP 安装 IPv4 和 ARP 单播路径，并通过 OpenFlow Barrier 回执确认交换机处理了更新。控制器日志出现每台交换机的 `Flow update confirmed` 后，才适合在 Mininet CLI 中检查通信。未匹配的流量不会由网桥自动学习转发。路径由启动时的静态场景计算，端口故障会清除相关交换机的规则，目前不自动寻找替代路径。这里的 Worker 是部署分区，尚非独立的控制域；域控制器代码留待域边界定义后实现。

控制器和 Mininet 必须使用相同的场景配置。没有 `--deployment` 时，包含边界链路的 `--worker` 受控启动会报错。Ryu 4.34 已不再维护；本项目按当前要求使用它。已有使用者的分布式互通反馈，安装兼容性边界、断线恢复和性能行为仍待系统验收。[Ryu 项目状态](https://github.com/faucetsdn/ryu)

### 多机部署：每台机器运行一个 Worker

多机模式下，场景目录中的 `workers.json`、`deployment.yml` 和 `channel.json` 各司其职：前者描述仿真拓扑，中者描述物理地址，后者描述双向信道目标。每个 Worker 使用相同的源码和场景目录，只改变 `--worker` 参数。Worker 数量从场景读取，没有写死为两台。[`configs/deployment.example.yml`](configs/deployment.example.yml) 是旧式分文件部署的带注释模板；其中 `192.0.2.x` 和摘要占位符必须换成实际值。`workers` 必须与场景中的 Worker ID 完全一致，地址必须互不重复，且本机的 Worker 地址必须实际配置在本机网卡上。已有 `.json` 部署文件仍可读取。

先在所有机器准备相同的 `configs/scenes/two_workers` 目录，运行只读校验取得 `scene_digest`，核对并在场景变更后更新目录中的 `deployment.yml` 和 `channel.json`。仓库中示例部署文件当前填的是 `a=192.168.145.131`、`b=192.168.145.132`、中央控制器 `192.168.145.132`，只适用于实际地址与之相符的机器；摘要只由拓扑文件计算，修改物理 IP 不会改变它：

```bash
./.venv/bin/md-mininet validate configs/scenes/two_workers
./.venv/bin/md-mininet plan configs/scenes/two_workers --worker a
./.venv/bin/md-mininet plan configs/scenes/two_workers --worker b
```

`plan` 中的 `vxlan_tunnels` 显示每条边界链路在本机的交换机、接口、远端地址与 VNI。增加 Worker 时，将新 ID、节点、链路加入场景，并在部署文件 `workers` 中加入对应物理地址；每条跨 Worker 交换机链路都会得到两个端点，双方使用相同 VNI。部署代码会在场景内检测 VNI 冲突。各物理机之间需要可路由的 IPv4 底层网络，并允许双向 UDP 4789；所有交换机还需要能连接中央控制器的 TCP 6653（或配置中的端口）；时间片模式另外需要 TCP 6654。VXLAN 封装增加报文长度，底层 MTU 应留出封装余量。普通受控模式不进行时间片启动屏障；时间片模式在中央控制器中等待所有 Worker 就绪，但不自动同步物理机时钟。 

在控制器机器上监听 Worker 可达的地址（不能使用仅本机可达的 `127.0.0.1`）；`--listen-host`、`--listen-port` 须与部署配置中的 `controller` 一致：

```bash
./.venv/bin/md-controller --scene configs/scenes/two_workers
```

随后在每台 Worker 上分别前台启动，命令中的 Worker ID 必须不同：

```bash
# Worker a 所在机器
sudo ./start.sh --scene configs/scenes/two_workers --worker a

# Worker b 所在机器
sudo ./start.sh --scene configs/scenes/two_workers --worker b
```

每个进程先清理本机对应场景和 Worker 的残留资源，再创建本地 Mininet 节点和内部链路，并为本机边界交换机添加 OVS VXLAN 端口。端口名与场景中的逻辑链路对应，由中央控制器核对实际 OpenFlow 端口号并安装路径。所有相关交换机都收到控制器的 `Flow update confirmed` 日志后，才能据此判断规则已经安装；这条日志本身不证明跨机数据面可达。正常退出各自的 Mininet CLI 或向主进程发送 `SIGTERM` 时，本进程删除自己创建的 VXLAN 端口并停止本地网络。

### 多机时间片模式：中央控制器与各 Worker 完整启动顺序

控制器和所有 Worker 必须使用**同一版本源码**、相同的场景目录。更新源码后，若 `.venv` 中安装的不是可编辑版本，应按安装章节在每台机器重新安装项目，使 `md-controller` 和 `start.sh` 加载新代码。控制器单独读取版本 2 `channel.json`，Worker 不直接读取它；控制器发布完整时间片。参考数据覆盖 19 条链路，均属场景假设，实际时延仍须现场测量。`deployment.yml` 的 `controller.host`、`port`、`channel_port` 必须与控制器实际监听的地址和端口一致。下例假设控制器和 Worker b 均在 `192.168.145.132`，Worker a 在 `192.168.145.131`；如果物理地址不同，先改目录中的部署文件。

1. 在 **192.168.145.132 的终端 1** 启动中央控制器。它同时监听 OpenFlow 的 6653 和信道控制的 6654；不需要 `sudo`。等待日志出现 `Channel run ... listening`，再启动 Worker。

   ```bash
   cd ~/MDNET
   ./.venv/bin/md-controller --scene configs/scenes/two_workers
   ```

2. 在 **192.168.145.131 的终端** 启动 Worker a：

   ```bash
   cd ~/MDNET
   sudo ./start.sh --scene configs/scenes/two_workers --worker a
   ```

3. 在 **192.168.145.132 的终端 2** 启动 Worker b：

   ```bash
   cd ~/MDNET
   sudo ./start.sh --scene configs/scenes/two_workers --worker b
   ```

Worker a、b 可以互换启动顺序，但必须都连接且返回 `READY`，中央控制器才会发送首次 `COMMIT`。Mininet 显示 `Starting CLI` 只表示本地网络已创建；测量前等待 Worker 输出 `Channel snapshot 0 APPLIED`、控制器输出 `Channel snapshot 0 applied`，并确认相关交换机的 `Flow update confirmed`。中央控制器若只用上一节**不带** `--channel-profile` 的命令启动，就不会监听 6654；Worker 会报告 `Connection refused` 并保持实验接口关闭。Eventlet 的弃用警告本身不是失败；出现 `socket.gaierror` 或控制器 traceback 时，控制器已经退出，须先修正控制器命令。控制器正常运行期间须保持终端 1 的进程存在。

若在同一台机器上运行全部 Worker，则不用 `--deployment`。在终端 1 启动控制器：

```bash
cd ~/MDNET
./.venv/bin/md-controller configs/scenes/two_workers \
  --listen-host 127.0.0.1 --listen-port 6653 \
  --channel-profile configs/scenes/two_workers/channel.json \
  --channel-control-host 127.0.0.1 --channel-control-port 6654
```

等待 `Channel run ... listening` 后，在终端 2 启动全部 Worker：

```bash
cd ~/MDNET
sudo ./start.sh --scene configs/scenes/two_workers --all-workers \
  --controller-host 127.0.0.1 --controller-port 6653 \
  --channel --channel-control-port 6654
```

更多时间片格式、失联处理与测量口径见[链路时间片说明](docs/CHANNEL_TIMELINE.md)。

### 异常退出后的定向清理

`start.sh` 在网络启动前自动调用 `clean.sh`。清理程序按场景和本机 Worker 计算目标，只处理本机主交换机、场景接口、带 `mdnet_owner` 标记的私有整形桥。清理前会核对部署文件与本机 IP、主交换机 DPID 和私有桥标记；若有运行中的 `md-mininet up` 或 Mininet 节点 shell，则报错退出，不删除资源。要单独清理 Worker b，可运行：

```bash
cd ~/MDNET
sudo ./clean.sh --scene configs/scenes/two_workers --worker b
```

Worker a 在自己的机器上将 `b` 改成 `a`。单机全部 Worker 模式使用 `sudo ./clean.sh --scene configs/two_workers.json --all-workers`。`vxlan_sys_4789` 是 OVS 管理的共享 VXLAN 数据面设备，可被多个逻辑 VXLAN 端口复用；它的存在本身不表示本实验有遗留资源，清理脚本不会删除它。

#### 无标记的私有整形桥

旧版代码可能在创建私有桥后、写入 `mdnet_owner` 前退出。清理脚本会拒绝自动删除这类无标记桥。以 Worker b 报出的 `beabee2b5e23d95` 为例，先在 **Worker b 所在机器**核对旧 Worker 进程和桥端口：

```bash
cd ~/MDNET
bridge=beabee2b5e23d95
pgrep -af 'md-mininet up|mininet:' || true
sudo ovs-vsctl --timeout=10 get Bridge "$bridge" external_ids:mdnet_owner
sudo ovs-vsctl --timeout=10 list-ports "$bridge"
```

若标记为空，核对桥端口确为旧时间片 Worker 创建的 `p...`、`v...` 私有端口，并确认没有在用的 Worker 后，才删除这一座桥：

```bash
sudo ovs-vsctl --timeout=10 --if-exists del-br "$bridge"
```

若报出其他私有桥，逐个按其**实际报错名称**核对；未确认归属的桥不要删除。清理后按上面的完整启动顺序重新启动控制器和各 Worker。

#### 单机全部 Worker 模式的旧清理示例

正常情况在原 Mininet CLI 输入 `exit`，让 `network.stop()` 清理。若原 CLI 无法操作，先核对进程确实是这次实验的 `md-mininet up`。以下以已报告的 PID `95438` 和 `configs/two_workers.json` 的**单机全部 Worker 模式**为例；在另一台机器上要改成实际 PID 和原启动时使用的场景文件。若还有其他实例使用相同的交换机名或场景资源，先分别停掉，避免清理它们正在使用的资源。

```bash
cd ~/MDNET
ps -o pid,ppid,stat,args -p 95437,95438
ps -o pid,pgid,args --ppid 95438
```

确认 `95438` 是本次 `md-mininet up` 后，先给它创建的 Mininet 节点 shell 进程组发送 HUP，再停止主进程。Mininet 的节点 shell 通过 `mnexec -d` 建立独立进程组；仅结束主进程会绕过 Python 的 `finally`，留下节点 shell 和网络资源。以下只选择 `95438` 的直接子进程中带 `mininet:` 标记、且 PID 等于进程组 ID 的节点 shell，不会结束独立运行的 `md-controller`。

```bash
mapfile -t node_pgids < <(ps -o pid=,pgid=,args= --ppid 95438 | awk '$1 == $2 && /mininet:/ {print $2}')
for pgid in "${node_pgids[@]}"; do sudo kill -HUP -- "-$pgid"; done
sudo kill -TERM 95438
ps -o pid,ppid,stat,args -p 95437,95438
```

如果主进程仍在，先检查它的状态；确实无法正常结束时才对**同一个已核对的 PID**使用 `sudo kill -KILL 95438`。进程退出后运行下面的定向清理。脚本从场景文件计算本实验所有接口名，只对存在于当前主机根网络命名空间的接口执行删除；删掉 veth 的一端会同时删除另一端。

```bash
sudo ./clean.sh --scene configs/two_workers.json --all-workers
```

最后核对原进程、场景交换机和报错时的接口。`pgrep` 没有输出时会返回状态码 1，这表示没有匹配进程。

```bash
pgrep -af 'md-mininet up|mininet:'
sudo ovs-vsctl list-br
sudo ip -o link show | grep -E 'm5055743b946da9|m3db8518d37b5c7'
```

此流程不需要 `mn -c`。Mininet 2.3.0 的全局清理会删除机器上的所有 OVS 网桥，且其接口匹配规则不覆盖这里的 `m` 加哈希接口名；本项目的 Ryu 控制器保持独立运行。[Mininet 清理源码](https://github.com/mininet/mininet/blob/2.3.0/mininet/clean.py)、[节点进程源码](https://github.com/mininet/mininet/blob/2.3.0/mininet/node.py)。

## 5. 当前源码的边界

| 已有源码 | 作用 |
| --- | --- |
| `src/channel_mininet/schema.py` | 读取并校验场景，计算 `scene_digest` |
| `src/channel_mininet/channel.py` | 校验有来源的信道配置，计算已建模链路的双向 `ChannelState` |
| `src/channel_mininet/topology/` | 构建静态拓扑，选择 Worker 本地节点和边界链路 |
| `src/channel_mininet/control/` | 计算最短路径、静态邻居项和待安装流表 |
| `src/channel_mininet/runtime/` | 生成短接口名，定义链路资源登记格式 |
| `src/channel_mininet/runtime/deployment.py` | 校验共享部署配置、场景摘要和物理端点 |
| `src/channel_mininet/runtime/vxlan.py` | 规划边界 VXLAN 端口并在本机创建与回收 |
| `src/channel_mininet/runtime/cleanup.py` 与 `clean.sh` | 启动前按本机范围清理异常退出的残留资源 |
| `src/channel_mininet/backends/mininet.py` | 根据 Worker 分区或完整场景生成 Mininet Topo |
| `src/channel_mininet/runtime/worker.py` | 基础 Mininet 网络的前台启动与退出清理 |
| `src/controller/cli.py` | 独立启动 Ryu 中央控制器 |
| `src/controller/central/app.py` | DPID/端口核对、静态 IPv4/ARP 流表安装与 Barrier 回执 |

默认 `up` 使用标准 Mininet Host 和 OVSBridge；受控 `up` 使用 OVSSwitch，控制器只读取共享场景并复用纯计算的流表规划，不创建或管理 Mininet 进程。保留的 `make_worker_topo` 则是未来的容器化入口，需要调用方注入真正的 Docker 主机类和 Docker OVS 交换机类。

目前只有前台 `up`；没有独立的 `down` 或容器化部署命令。跨机器链路使用 OVS VXLAN，由每个 Worker 进程仅创建和回收本机端点。`start.sh` 会先执行定向残留清理；无标记的私有桥和仍在运行的 Mininet 进程需要按上文人工核对。

## 6. 完整网络部署还需要什么

通用模型的静态只读计算源码与单链路参考配置已完成规划验证；下一步需要采集目标设备数据，并区分稳定设备能力、初始节点状态和有来源的演化规则。仿真时钟驱动节点与共享环境变化，再计算和下发本地及跨 Worker 链路的单向状态序列，随后分别实现无线、有线物理模型。节点参数必须对应真实设备，能从只读设备信息、现场测量或公开规格表取得，并保留来源；缺少依据的处理时延等量不作为节点必填项。详细输入、输出、技术风险和验收顺序见 [研究计划](docs/RESEARCH_PLAN.md)。当前分布式网络使用普通 Mininet Host、OVS、VXLAN 和集中式 Ryu 控制器，无需每节点 Docker。若以后确有容器化需求，再验证 Docker Engine、Mininet/Containernet、容器内 OVS 和所需权限，先决定只容器化主机还是同时隔离交换机进程。多机器的物理地址和控制器连接仍由部署配置指定。安装资料可参考 [Docker Engine 官方文档](https://docs.docker.com/engine/install/)与 [Mininet 安装说明](https://github.com/mininet/mininet/blob/master/INSTALL)。

本项目当前的工作约定是不运行部署逻辑，也不运行代码测试；本 README 的 Mininet 和控制器启动命令均未在本次修改中执行。
