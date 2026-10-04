# MD-Mininet

MD-Mininet 是一个面向多 Worker 实验的 Mininet 项目，支持单机完整拓扑和多台物理机分区运行。每台 Worker 电脑安装**同一份源码**、读取**同一份场景配置**，再用不同的 Worker ID 选择本机负责的节点和链路。当前示例有 A、B 两个分区，每个分区包含 8 台模拟主机和 2 台模拟交换机。

> **当前状态：分布式 Mininet 网络已搭建。** 据使用者运行反馈，单个集中式 Ryu 控制器管理交换机，当前任意两个模拟主机可以相互发包；这不代表链路性能、故障恢复和多轮实验已经验收。默认 `up` 使用 OVS 桥；指定远程控制器后使用 OpenFlow 1.3 交换机。`--all-workers` 在单机创建完整拓扑；`--worker` 配合部署配置在每台物理机创建本地拓扑及跨机 VXLAN 端口。通用链路模型目前只计算一个静态快照，已有单链路公开规格参考配置；下一步需采集目标设备参数、实现节点状态演化，再按仿真时间下发单向链路状态。后续分别实现无线、有线模型，Docker 容器化推迟。详见根目录的 [研究计划](RESEARCH_PLAN.md)。`validate`、`plan` 和 `channel-plan` 都是只读命令。

## 开发进度与下一阶段

`[x]` 表示源码或文档已实现；运行结论另行注明，避免把“代码已写入”与“实验已验收”混为一谈。研究顺序与验收标准见 [RESEARCH_PLAN.md](RESEARCH_PLAN.md)。

- [x] 建立 Python 包、命令入口和双 Worker 示例场景；实现校验、全局标识、`scene_digest`、Worker 划分与静态路径规划。
- [x] 实现标准 Mininet Host/OVS 的前台启动，以及跨机器 VXLAN 端口的规划、创建和正常退出回收。
- [x] 实现独立的集中式 Ryu 控制器、端口核对、IPv4/ARP 流表安装与 Barrier 回执处理。
- [x] **使用者运行反馈：** 分布式网络已搭建，任意两个模拟主机当前可以相互发包；曾查看到 `sa1` 的规则及命中计数。
- [x] **P1 源码进展：** 已写入带节点参数来源字段校验的通用双向静态快照计算和只读 `channel-plan` 命令；参考配置已完成 `la1` 双向计算的只读运行验证。
- [ ] **P1 数据与演化：** 为拟模拟设备采集有参考依据的能力与初始状态，增加节点状态、共享环境、仿真时间和可复现演化规则，再核对状态序列。
- [ ] **P2 参数下发：** 将按仿真时间产生的单向状态序列应用到本地链路及跨 Worker 的 VXLAN 链路，并测量实际效果。
- [ ] **P3 无线与有线模型：** 分别补充两类介质的输入参数与计算方法，共用 P1 输出和 P2 下发路径。
- [ ] **P4 稳定性与复现：** 完成性能标定、状态检查、异常退出恢复、故障场景和多轮实验记录；扩展三台及以上 Worker 的验收。
- [ ] **P5 按需评估 Docker：** 推迟每节点容器化；需要独立软件环境或交换机进程时再决定是否引入。

## 1. 代码如何放到另一台电脑

建议目标电脑使用原生 Linux。只读规划命令需要 Python 3.10 或更新版本及项目依赖；`up` 还需要 Linux、Mininet、OVS 和创建网络命名空间的权限。当前部署与后续 P1/P2 工作不以 Docker 为前置条件。

### 方式 A：通过 Git

先在开发电脑上将 `README.md`、`pyproject.toml`、`src/`、`configs/` 和 `.gitignore` 提交并推送。本仓库当前的远端名和分支名都叫 `master`，远端地址是 `https://github.com/csp3ff/MD-Mininet.git`：

```bash
git add .gitignore README.md pyproject.toml start.sh src configs
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

两台电脑分别运行时，每台都应放置**完全相同的** `configs/two_workers.json`，一台使用 `--worker a`，另一台使用 `--worker b`。输出中的 `scene_digest` 应相同；该摘要用于识别场景不一致，不代表两台机器已经建立连接。默认 `plan` 只输出节点、边界链路、逻辑路由及预定接口名；带 `--deployment` 时还输出 VXLAN 端点规划。两种方式都不会启动 Worker 进程。

示例场景位于 [`configs/two_workers.json`](configs/two_workers.json)。第一版把两个“网络”定义为拓扑和部署分区，所有模拟主机共用 `10.77.0.0/24`；它们目前不是两个独立的 IP 子网。修改示例时，应保持节点 ID、主机 IP/MAC、交换机 DPID 和链路 ID 全局唯一。每台主机当前只能有一条业务链路，跨 Worker 链路只能连接交换机。

### 只读通用信道规划（P1）

源码提供 `md-mininet channel-plan 场景文件 信道配置文件`。信道配置独立于现有拓扑文件，并用 `scene_digest` 绑定场景，因此旧场景与当前控制器无需修改。配置 JSON 顶层包含 `version=1`、`scene_digest`、正整数 `revision`、带时区的 `effective_time`、`ports` 和 `links`。

- `ports` 中每项对应一条逻辑链路的一个端点，包含 `link_id`、`node_id`、`port_type`、正数 `rate_mbps` 和 `source`。`source` 必须给出 `kind`（`device_readout`、`field_measurement` 或 `datasheet`）、`reference`、真实 `device_model`、带时区的 `recorded_at`。这些字段描述拟模拟的真实设备，不能从 Mininet 的 veth/OVS 虚拟端口读取后冒充设备规格。
- `links` 中每项包含 `link_id`、`model="generic"`、`a_to_b` 和 `b_to_a`。每个方向都要给出 `available`、正数 `nominal_bandwidth_mbps`、非负 `distance_m`（实际传播路径长度，米）、大于零且不超过真空光速的 `propagation_speed_mps`（该介质中的传播速度，米/秒）和 `source`；`source` 含 `kind`（`measurement`、`datasheet` 或 `scenario_assumption`）、`reference`、带时区的 `recorded_at`，用于区分测量值与场景设定。名义容量不得超过两个端点中较低的有来源端口速率，配置错误会直接报出，不再靠输出时取最小值掩盖。可选 `max_distance_m` 是该方向明确给出的正数场景上界，提供后 `distance_m` 不得超过它；这不是所有介质通用的物理极限。可选 `velocity_factor_of_c` 须在 0 到 1 之间，提供后必须与 `propagation_speed_mps / 299792458` 一致。输出的 `delay_ms = 1000 × distance_m / propagation_speed_mps` **仅为单向传播时延**，不含发送/序列化、交换处理、排队或重传时延。可选 `jitter_ms`、`loss_pct`；未提供时输出 `null`，不自动猜测。仅有端口速率、带宽、频率或发射功率，无法推出传播时延；缺少长度或传播速度时配置报错。
- 可以只配置部分链路以做小规模研究；已配置链路必须包含两个端点的来源数据及两个方向。输出列出 `modeled_links`、`unmodeled_links` 和每个方向的 `ChannelState`，便于识别覆盖缺口。

[`configs/channel_profile.reference.json`](configs/channel_profile.reference.json) 是用于只读规划的最小**有线**参考配置，绑定示例场景摘要，仅覆盖 `ha1`—`sa1` 的 `la1`，其余 18 条链路在输出中标为未建模；其数值不能直接套用到无人机、车辆或卫星链路。`ha1` 端的 1000 Mb/s 参考 [Intel I210-AT 官方规格](https://www.intel.com/content/www/us/en/products/sku/64400/intel-ethernet-controller-i210at/specifications.html)，`sa1` 端口的 1000 Mb/s 参考 [NETGEAR GS108v3 官方规格](https://www.downloads.netgear.com/files/GDC/datasheet/en/GS105v3-GS108v3.pdf)。这些是**拟模拟设备的参考端口能力**，不表示物理 Worker 实际装有这些设备，也不表示 GS108v3 是当前的 OpenFlow 交换机；当前交换机仍为 OVS。链路方向上的名义容量设为参考端口上限。传播路径长度 **100 m 是场景设定**，不是已测线长；该例同时设置 `max_distance_m=100`，作为所选 [1000BASE-T 百米链路参考](https://www.ieee802.org/3/10GBT/public/material/diminico_IWCS.PDF)下的建模上界，并不声称所有设备超过 100 m 就必然断链。传播速度取 [Belden 2412 电缆规格](https://catalog.belden.com/techdata/EN/2412_techdata.pdf)中标称的真空光速 70%，并用 `velocity_factor_of_c=0.7` 与数值互相核对；以 [NIST 的真空光速](https://www.nist.gov/si-redefinition/definitions-si-base-units)换算为 209854720.6 m/s。该电缆规格还列出 100 MHz 时最大传播时延 537.6 ns/100 m，和这里按标称速度得到的结果不是同一种保证值。因此计算的是这条**假设电缆**的标称传播时延，不是实际部署的单向时延；抖动和丢包未建模。

在项目根目录运行只读规划：

```bash
PYTHONPATH=src python3 -m channel_mininet.cli channel-plan configs/two_workers.json configs/channel_profile.reference.json
```

按上述参考数据计算，`la1` 的 a→b、b→a 目标值各为 1000 Mb/s，标称传播时延各约 0.0004765 ms（0.4765 µs）；`jitter_ms` 和 `loss_pct` 为 `null`。本次约束修改后未运行该命令复核。该命令只解析配置并计算一个静态目标快照，不表示节点移动或参数随时间演化；它不会设置 veth、OVS 或 `tc`，也不代表 P2 参数下发已经实现。换用实际设备时，应以设备只读信息或对应型号规格替换参考参数，以布线记录/现场测量替换假设线长，核对对应介质的传播速度，并更新场景摘要。
来源字段是否齐全由程序检查，来源内容及设备型号是否真实匹配仍需人工核对。
当前拓扑只支持已声明的链路，且每台主机只有一条业务链路；未来的状态演化可以先改变这些链路的参数/可用性，新的邻接关系或切换接入点还需要扩展拓扑与路由逻辑。

## 4. 启动单机基础网络

安装 Mininet 与 OVS，并确保它们能被当前虚拟环境使用后，在项目根目录执行以下命令。`up` 会实际创建网络命名空间、veth 和 OVS 桥，需要 root 权限；**项目当前约定暂不由本次文档工作执行部署或测试。** 分布式受控模式已有使用者互通反馈；下述单机基础模式尚无单独验收记录。

```bash
sudo ./start.sh
```

`start.sh` 默认读取 `configs/two_workers.json` 并在本机启动所有 Worker 分区；可用 `--scene 路径` 指定其他场景，路径相对于项目根目录。脚本使用项目 `.venv/bin/md-mininet`，需先按上文安装项目。

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

多机模式下，`two_workers.json` 和 `deployment.yml` **同时存在，不合并内容**：前者描述仿真节点与逻辑链路，后者描述物理机和控制器地址。每个 Worker 使用相同的源码、场景和部署配置，只改变 `--worker` 参数。Worker 数量从场景读取，没有写死为两台。[`configs/deployment.example.yml`](configs/deployment.example.yml) 是带注释的模板；其中 `192.0.2.x` 和摘要占位符必须换成实际值。`workers` 必须与场景中的 Worker ID 完全一致，地址必须互不重复，且本机的 Worker 地址必须实际配置在本机网卡上。已有 `.json` 部署文件仍可读取。

先在所有机器准备相同的 `configs/two_workers.json`，运行只读校验取得 `scene_digest`，再把该摘要填入 `configs/deployment.yml`，并将这份 YAML 文件复制到所有 Worker。仓库中的 `deployment.yml` 已保留原 `deployment.json` 的地址值，但摘要仍是占位符。摘要只由场景文件计算；修改部署文件里的物理 IP 不会改变它：

```bash
./.venv/bin/md-mininet validate configs/two_workers.json
./.venv/bin/md-mininet plan configs/two_workers.json --worker a --deployment configs/deployment.yml
./.venv/bin/md-mininet plan configs/two_workers.json --worker b --deployment configs/deployment.yml
```

`plan` 中的 `vxlan_tunnels` 显示每条边界链路在本机的交换机、接口、远端地址与 VNI。增加 Worker 时，将新 ID、节点、链路加入场景，并在部署文件 `workers` 中加入对应物理地址；每条跨 Worker 交换机链路都会得到两个端点，双方使用相同 VNI。部署代码会在场景内检测 VNI 冲突。各物理机之间需要可路由的 IPv4 底层网络，并允许双向 UDP 4789；所有交换机还需要能连接中央控制器的 TCP 6653（或配置中的端口）。VXLAN 封装增加报文长度，底层 MTU 应留出封装余量。当前没有自动进行时钟同步、跨机器启动屏障或控制器健康检查。

在控制器机器上监听 Worker 可达的地址（不能使用仅本机可达的 `127.0.0.1`）；`--listen-host`、`--listen-port` 须与部署配置中的 `controller` 一致：

```bash
./.venv/bin/md-controller configs/two_workers.json --listen-host 192.168.145.132 --listen-port 6653
```

随后在每台 Worker 上分别前台启动，命令中的 Worker ID 必须不同：

```bash
# Worker a 所在机器
sudo ./start.sh --scene configs/two_workers.json --worker a --deployment configs/deployment.yml

# Worker b 所在机器
sudo ./start.sh --scene configs/two_workers.json --worker b --deployment configs/deployment.yml
```

每个进程先创建本地 Mininet 节点和内部链路，再为本机边界交换机添加 OVS VXLAN 端口。端口名与场景中的逻辑链路对应，由中央控制器核对实际 OpenFlow 端口号并安装路径。所有相关交换机都收到控制器的 `Flow update confirmed` 日志后，才能据此判断规则已经安装；这条日志本身不证明跨机数据面可达。正常退出各自的 Mininet CLI 或向主进程发送 `SIGTERM` 时，本进程删除自己创建的 VXLAN 端口并停止本地网络。异常断电或 `SIGKILL` 后的自动残留清理尚未实现；不要把下文单机全部 Worker 的清理命令直接用于多机模式。

### 异常退出后的定向清理

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

如果主进程仍在，先检查它的状态；确实无法正常结束时才对**同一个已核对的 PID**使用 `sudo kill -KILL 95438`。进程退出后运行下面的定向清理。脚本从场景文件计算本实验所有接口名，只对存在于当前主机根网络命名空间的接口执行删除；删掉 veth 的一端会同时删除另一端。OVS 操作也只针对场景中的交换机名。

```bash
sudo ./.venv/bin/python - <<'PY'
import subprocess

from channel_mininet.runtime.names import planned_interface_names
from channel_mininet.schema import load_scene

scene = load_scene("configs/two_workers.json")
for switch in scene.switches:
    subprocess.run(["ovs-vsctl", "--if-exists", "del-br", switch.id], check=True)
for name in sorted(set(planned_interface_names(scene).values())):
    exists = subprocess.run(
        ["ip", "link", "show", "dev", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    if exists:
        print("deleting interface", name)
        subprocess.run(["ip", "link", "delete", "dev", name], check=True)
PY
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
| `src/channel_mininet/backends/mininet.py` | 根据 Worker 分区或完整场景生成 Mininet Topo |
| `src/channel_mininet/runtime/worker.py` | 基础 Mininet 网络的前台启动与退出清理 |
| `src/controller/cli.py` | 独立启动 Ryu 中央控制器 |
| `src/controller/central/app.py` | DPID/端口核对、静态 IPv4/ARP 流表安装与 Barrier 回执 |

默认 `up` 使用标准 Mininet Host 和 OVSBridge；受控 `up` 使用 OVSSwitch，控制器只读取共享场景并复用纯计算的流表规划，不创建或管理 Mininet 进程。保留的 `make_worker_topo` 则是未来的容器化入口，需要调用方注入真正的 Docker 主机类和 Docker OVS 交换机类。

目前只有前台 `up`；没有独立的 `down` 或容器化部署命令。跨机器链路使用 OVS VXLAN，由每个 Worker 进程仅创建和回收本机端点。前台进程异常终止后的自动资源恢复尚未实现；上面的手工清理示例仅针对单机全部 Worker 模式。

## 6. 完整网络部署还需要什么

通用模型的静态只读计算源码与单链路参考配置已完成规划验证；下一步需要采集目标设备数据，并区分稳定设备能力、初始节点状态和有来源的演化规则。仿真时钟驱动节点与共享环境变化，再计算和下发本地及跨 Worker 链路的单向状态序列，随后分别实现无线、有线物理模型。节点参数必须对应真实设备，能从只读设备信息、现场测量或公开规格表取得，并保留来源；缺少依据的处理时延等量不作为节点必填项。详细输入、输出、技术风险和验收顺序见 [研究计划](RESEARCH_PLAN.md)。当前分布式网络使用普通 Mininet Host、OVS、VXLAN 和集中式 Ryu 控制器，无需每节点 Docker。若以后确有容器化需求，再验证 Docker Engine、Mininet/Containernet、容器内 OVS 和所需权限，先决定只容器化主机还是同时隔离交换机进程。多机器的物理地址和控制器连接仍由部署配置指定。安装资料可参考 [Docker Engine 官方文档](https://docs.docker.com/engine/install/)与 [Mininet 安装说明](https://github.com/mininet/mininet/blob/master/INSTALL)。

本项目当前的工作约定是不运行部署逻辑，也不运行代码测试；本 README 的 Mininet 和控制器启动命令均未在本次修改中执行。
