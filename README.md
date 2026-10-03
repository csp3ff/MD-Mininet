# MD-Mininet

MD-Mininet 是一个面向多 Worker 实验的 Mininet 项目，支持单机完整拓扑和多台物理机分区运行。每台 Worker 电脑安装**同一份源码**、读取**同一份场景配置**，再用不同的 Worker ID 选择本机负责的节点和链路。当前示例有 A、B 两个分区，每个分区包含 8 台模拟主机和 2 台模拟交换机。

> **当前状态：多机 VXLAN 部署代码已写入，但尚未运行验证。** 默认 `up` 仍使用 OVS 桥；指定远程控制器后使用 OpenFlow 1.3 交换机。`--all-workers` 在单机创建完整拓扑；`--worker` 配合部署配置在每台物理机创建本地拓扑及跨机 VXLAN 端口。每节点 Docker 容器化排在基础流程之后。`validate` 和 `plan` 仍是只读命令。

## 开发 TODO

`[x]` 表示对应源码或文档已经写入仓库，**不表示已经运行或验证**；`[ ]` 表示尚未完成。

- [x] 建立 Python 包、命令入口和双 Worker 示例场景。
- [x] 实现场景校验、全局标识检查和 `scene_digest`。
- [x] 实现 Worker 本地节点、内部链路与边界链路的静态划分。
- [x] 实现静态拓扑、最短路径、邻居项和逻辑流表规划。
- [x] 实现短接口名、链路登记格式和 Mininet Topo 构建入口；未来的容器化 Topo 仍需注入容器节点类。
- [x] 实现标准 Mininet Host + OVSBridge 的前台 `up` 命令，支持单 Worker 和单机全部 Worker。
- [x] 编写当前版本的复制、安装、规划和基础网络启动说明。
- [ ] 在允许运行后，验证基础 Mininet 环境与单机双分区拓扑、通信和退出清理。
- [x] 写入独立启动的 Ryu 中央控制器、端口核对、IPv4/ARP 规则安装与 Barrier 回执处理。
- [ ] 在允许运行后，验证控制器连接、端口映射、实际流表及断线恢复。
- [ ] 实现完整的状态检查、异常退出恢复和资源残留检查。
- [ ] 完成最小节点、单 Worker、双 Worker 的功能验收。
- [ ] 验证 Docker、容器内 OVS、内核和网络操作权限，再实现每节点容器化。
- [ ] 实现每台模拟主机一个 Docker 容器，以及业务接口和静态邻居项配置。
- [ ] 实现每台模拟交换机一个 Docker 容器，验证两个独立 OVS 实例同时运行。
- [x] 实现任意数量 Worker 的跨机器 VXLAN 端口规划、创建和正常退出时的定向回收。
- [ ] 在两台 Linux 主机上验证 VXLAN、控制器流表和跨机连通性，并验证三台及以上的配置规划（P5）。
- [ ] 完成实验记录、指标采集和可重复性验收（P6）。
- [ ] 在运行时能力验证通过后补齐完整仿真网络的部署命令和版本要求。

## 1. 代码如何放到另一台电脑

建议目标电脑使用原生 Linux。只读规划命令需要 Python 3.10 或更新版本及项目依赖；`up` 还需要 Linux、Mininet、OVS 和创建网络命名空间的权限。Docker 是后续节点容器化阶段的依赖。

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

## 4. 启动单机基础网络

安装 Mininet 与 OVS，并确保它们能被当前虚拟环境使用后，在项目根目录执行以下命令。`up` 会实际创建网络命名空间、veth 和 OVS 桥，需要 root 权限；**项目当前约定暂不执行部署或测试，以下只是准备好的操作方式，尚未在本项目验证。**

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

控制器和 Mininet 必须使用相同的场景配置。没有 `--deployment` 时，包含边界链路的 `--worker` 受控启动会报错。Ryu 4.34 已不再维护；本项目按当前要求使用它，实际安装兼容性及网络行为仍待允许运行后验证。[Ryu 项目状态](https://github.com/faucetsdn/ryu)

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

后续实现每节点容器化时，每台实际运行 Worker 的 Linux 主机预计还需要 Docker Engine、与其 Python 版本兼容的 Mininet/Containernet、容器内 OVS 所需的内核能力，以及相应网络操作权限。多机器的物理地址和控制器连接由部署配置指定。具体版本、权限和镜像必须先完成能力验证，再写成可执行步骤。安装资料可参考 [Docker Engine 官方文档](https://docs.docker.com/engine/install/)与 [Mininet 安装说明](https://github.com/mininet/mininet/blob/master/INSTALL)。

本项目当前的工作约定是不运行部署逻辑，也不运行代码测试；本 README 的 Mininet 和控制器启动命令均未在本次修改中执行。
