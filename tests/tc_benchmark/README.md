# tc 切换耗时基准

这个独立脚本在单机真实 Mininet/OVS 网络上创建一条无环交换机链，并将主机随机接入交换机。默认配置为 10 台交换机、91 台主机、100 条链路。每条链路双向设置带宽和附加时延，然后分别测量只修改 10、20、…、100 条链路，以及完整 100 链路时间片的本地应用耗时。

在目标 Linux 机器的项目根目录安装最新源码、Mininet、OVS、`tc` 后，**手动**运行：

```bash
./.venv/bin/python -m pip install -e .
sudo ./.venv/bin/python tests/tc_benchmark/benchmark.py --repeats 5 --warmups 1 --seed 42
```

程序需要 root 权限；如果 Mininet 来自系统安装，项目 `.venv` 需以 `--system-site-packages` 创建。脚本不会启动中央控制器，也不会调用全局 `mn -c`。运行前请预留创建约 100 个 Mininet 节点的容量。结果自动写入 `tests/tc_benchmark/results/时间戳-随机编号/`，其中 `raw.csv` 是逐条命令及整批耗时，`summary.csv` 是各规模统计，`command_summary.csv` 汇总单条命令，`trend.svg` 是趋势图，`REPORT.md` 是带实测数字的说明。脚本在正常退出或抛出异常时调用本次网络的 `stop()`；异常中断可能需要按项目清理流程人工检查残留资源。

`--links`、`--switches`、`--step-links`、`--repeats`、`--warmups`、`--seed` 可调整规模与采样。计时前会在所有出口安装 HTB/netem；测试随机参数范围为带宽 5–1000 Mb/s、时延 1–200 ms。每轮都随机选择对应数量的链路并修改两个方向的两个参数。计时不包含建网或首次安装；单条 `tc` 耗时包含 Mininet `node.popen()` 启动命令的成本。

`selected` 模式临时将本轮 `ChannelShaper` 的出口集合限于选中的链路，测量修改 N 条链路的规模趋势；`full_snapshot` 模式保持全部出口，测量当前生产实现面对完整 100 链路时间片的耗时。后者不会跳过数值未变化的链路，因此即使本轮只改变 10 条，仍会执行全部 100 条链路的 `tc` 更新。两个结果不能混为一谈。

此脚本和文档仅已写入仓库；按项目约定，未在开发机器运行部署或代码测试。
