# MD-Mininet

MD-Mininet 是一个面向多 Worker 实验的单机 Mininet 项目。每台 Worker 电脑安装**同一份源码**、读取**同一份场景配置**，再用不同的 Worker ID 选择本机负责的节点和链路。当前示例有 A、B 两个分区，每个分区包含 8 台模拟主机和 2 台模拟交换机。

> **当前状态：已有基础 Mininet 网络启动入口，尚未运行验证。** `up` 使用标准 Mininet 主机和 OVS 桥，能按一个 Worker 或全部 Worker 构建拓扑；全部 Worker 模式用于在一台 Linux 主机上检查跨分区连通。它不使用中央 SDN 控制器，也不提供跨物理机器链路。每节点 Docker 容器化排在基础流程之后。`validate` 和 `plan` 仍是只读命令。

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
- [ ] 实现中央 SDN 控制器、实际端口核对、OpenFlow 规则安装与 Barrier 确认。
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
git add .gitignore README.md pyproject.toml src configs
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
sudo ./.venv/bin/md-mininet up configs/two_workers.json --all-workers
```

这会在**同一台 Linux 机器、同一个 Mininet 进程**中创建示例的 16 台主机、4 台交换机及跨分区链路，然后进入 Mininet CLI。预期可在 CLI 中查看节点与链路，并在退出 CLI 后由 `network.stop()` 回收本次 Mininet 创建的资源。该模式使用 OVS 桥的普通 MAC 学习转发，适合先检查拓扑和基本通信；它不验证中央 SDN 控制器或本文规划的 OpenFlow 规则。示例拓扑没有交换机环路；基础桥接模式会拒绝带交换机环路的场景。

同一份源码也支持只启动一个 Worker 的本地部分：

```bash
sudo ./.venv/bin/md-mininet up configs/two_workers.json --worker a
```

单 Worker 模式**不创建跨 Worker 链路**。分别在两台电脑上运行 `--worker a` 和 `--worker b`，目前只能得到两张各自独立的本地网络，不会自动互通。退出 Mininet CLI 时输入 `exit`；项目不会调用全局的 `mn -c`。

Mininet 的安装方式见[官方安装说明](https://github.com/mininet/mininet/blob/master/INSTALL)。Mininet 和本项目虚拟环境必须使用兼容的 Python 版本；若 `up` 报 Mininet 无法导入，先核对其安装位置及虚拟环境的 `--system-site-packages` 设置。

## 5. 当前源码的边界

| 已有源码 | 作用 |
| --- | --- |
| `src/channel_mininet/schema.py` | 读取并校验场景，计算 `scene_digest` |
| `src/channel_mininet/topology/` | 构建静态拓扑，选择 Worker 本地节点和边界链路 |
| `src/channel_mininet/control/` | 计算最短路径、静态邻居项和待安装流表 |
| `src/channel_mininet/runtime/` | 生成短接口名，定义链路资源登记格式 |
| `src/channel_mininet/backends/mininet.py` | 根据 Worker 分区或完整场景生成 Mininet Topo |
| `src/channel_mininet/runtime/worker.py` | 基础 Mininet 网络的前台启动与退出清理 |

基础 `up` 使用标准 Mininet Host 和 OVSBridge。保留的 `make_worker_topo` 则是未来的容器化入口，需要调用方注入真正的 Docker 主机类和 Docker OVS 交换机类。`control/flow_manager.py` 只把逻辑路径映射到**已观测到的** OpenFlow 端口，没有向交换机发送规则；基础 `up` 不使用这份流表规划。

目前只有前台 `up`；没有独立的 `down`、跨机器链路或容器化部署命令。前台进程异常终止后的资源恢复尚未实现，不要用 `mn -c` 代替本项目未来按实验和 Worker 归属的定向回收流程。

## 6. 完整网络部署还需要什么

后续实现每节点容器化时，每台实际运行 Worker 的 Linux 主机预计还需要 Docker Engine、与其 Python 版本兼容的 Mininet/Containernet、容器内 OVS 所需的内核能力，以及相应网络操作权限。中央控制器和跨 Worker 链路也需要单独的部署与连接配置。具体版本、权限和镜像必须先完成能力验证，再写成可执行步骤。安装资料可参考 [Docker Engine 官方文档](https://docs.docker.com/engine/install/)与 [Mininet 安装说明](https://github.com/mininet/mininet/blob/master/INSTALL)。

本项目当前的工作约定是不运行部署逻辑，也不运行代码测试；本 README 的 `up` 命令尚未在本次修改中执行。
