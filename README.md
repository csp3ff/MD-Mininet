# MD-Mininet

MD-Mininet 是一个面向多 Worker 实验的单机 Mininet 项目。每台 Worker 电脑安装**同一份源码**、读取**同一份场景配置**，再用不同的 Worker ID 选择本机负责的节点和链路。当前示例有 A、B 两个分区，每个分区包含 8 台模拟主机和 2 台模拟交换机。

> **当前状态：已有基础 Mininet 入口和独立的 Ryu 中央控制器入口，新增的受控模式尚未运行验证。** 默认 `up` 仍使用 OVS 桥；指定远程控制器后使用 OpenFlow 1.3 交换机。全部 Worker 模式只在一台 Linux 主机上创建完整拓扑；目前没有跨物理机器链路。每节点 Docker 容器化排在基础流程之后。`validate` 和 `plan` 仍是只读命令。

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
- [ ] 实现跨 Worker 链路的统一创建和定向回收。
- [ ] 实现并验证 VXLAN 后端；真实跨机器连通性待两台 Linux 主机验收（P5）。
- [ ] 完成实验记录、指标采集和可重复性验收（P6）。
- [ ] 在运行时能力验证通过后补齐完整仿真网络的部署命令和版本要求。

## 1. 代码如何放到另一台电脑

建议目标电脑使用原生 Linux。只读规划命令仅需 Python 3.10 或更新版本；`up` 需要 Linux、Mininet、OVS 和创建网络命名空间的权限。Docker 是后续节点容器化阶段的依赖。

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

安装完成后，可直接使用虚拟环境内的 `md-mininet` 命令。`pip install .` 安装的是当时的源码快照；以后更新源码，需要再次运行该安装命令。若要在目标电脑继续修改源码，可改用 `./.venv/bin/python -m pip install -e .`。如果只需规划命令，可不用 `--system-site-packages`，也不必安装 Mininet/OVS。虚拟环境和本地项目安装的用法见 [Python venv 文档](https://docs.python.org/3/library/venv.html)与 [pip 文档](https://pip.pypa.io/en/stable/topics/local-project-installs/)。

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

两台电脑分别运行时，每台都应放置**完全相同的** `configs/two_workers.json`，一台使用 `--worker a`，另一台使用 `--worker b`。输出中的 `scene_digest` 应相同；该摘要用于识别场景不一致，不代表两台机器已经建立连接。`plan` 只输出节点、边界链路、逻辑路由及预定接口名，不会启动 Worker 进程。

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

单 Worker 模式**不创建跨 Worker 链路**。分别在两台电脑上运行 `--worker a` 和 `--worker b`，目前只能得到两张各自独立的本地网络，不会自动互通。退出 Mininet CLI 时输入 `exit`；项目不会调用全局的 `mn -c`。

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

控制器和 Mininet 必须使用相同的场景配置。当前没有跨 Worker 物理链路，因此使用示例双 Worker 场景时，受控模式只支持 `--all-workers`；`--worker` 受控启动会明确报错。Ryu 4.34 已不再维护；本项目按当前要求使用它，实际安装兼容性及网络行为仍待允许运行后验证。[Ryu 项目状态](https://github.com/faucetsdn/ryu)

## 5. 当前源码的边界

| 已有源码 | 作用 |
| --- | --- |
| `src/channel_mininet/schema.py` | 读取并校验场景，计算 `scene_digest` |
| `src/channel_mininet/topology/` | 构建静态拓扑，选择 Worker 本地节点和边界链路 |
| `src/channel_mininet/control/` | 计算最短路径、静态邻居项和待安装流表 |
| `src/channel_mininet/runtime/` | 生成短接口名，定义链路资源登记格式 |
| `src/channel_mininet/backends/mininet.py` | 根据 Worker 分区或完整场景生成 Mininet Topo |
| `src/channel_mininet/runtime/worker.py` | 基础 Mininet 网络的前台启动与退出清理 |
| `src/controller/cli.py` | 独立启动 Ryu 中央控制器 |
| `src/controller/central/app.py` | DPID/端口核对、静态 IPv4/ARP 流表安装与 Barrier 回执 |

默认 `up` 使用标准 Mininet Host 和 OVSBridge；受控 `up` 使用 OVSSwitch，控制器只读取共享场景并复用纯计算的流表规划，不创建或管理 Mininet 进程。保留的 `make_worker_topo` 则是未来的容器化入口，需要调用方注入真正的 Docker 主机类和 Docker OVS 交换机类。

目前只有前台 `up`；没有独立的 `down`、跨机器链路或容器化部署命令。前台进程异常终止后的资源恢复尚未实现，不要用 `mn -c` 代替本项目未来按实验和 Worker 归属的定向回收流程。

## 6. 完整网络部署还需要什么

后续实现每节点容器化时，每台实际运行 Worker 的 Linux 主机预计还需要 Docker Engine、与其 Python 版本兼容的 Mininet/Containernet、容器内 OVS 所需的内核能力，以及相应网络操作权限。跨 Worker 链路及多机器控制器连接也需要单独的部署配置。具体版本、权限和镜像必须先完成能力验证，再写成可执行步骤。安装资料可参考 [Docker Engine 官方文档](https://docs.docker.com/engine/install/)与 [Mininet 安装说明](https://github.com/mininet/mininet/blob/master/INSTALL)。

本项目当前的工作约定是不运行部署逻辑，也不运行代码测试；本 README 的 Mininet 和控制器启动命令均未在本次修改中执行。
