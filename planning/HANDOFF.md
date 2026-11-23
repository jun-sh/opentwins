# 交接文档（更新于 2026-11-23）

新对话从这里开始：先读本文件，按需再读 `p0-verification.md`、`type-design.md`、`../stack/README.md`。

## 1. 目标（一句话）

只集成成熟开源项目，构建设备数字孪生 + PHM 参考架构。用 Unitree G1、Franka Panda、PiperX 三台真机验证，未来迁移到核电资产。通用性靠"WoT Type 复用 + 适配器"证明，不靠自研算法或平台。

## 2. 已定决策（不再讨论）

| 主题 | 决策 |
|---|---|
| 对标主线 | 孪生平台 + PHM（对标 ThingWorx/ADT + PRiSM/SmartSignal）；PI 类时序库只作底座 |
| 主干 | **Eclipse Ditto 直接使用**；OpenTwins 只借鉴概念和 Apache-2.0 插件（v1 基本停更，extended-api 无许可证） |
| Type | **W3C WoT Thing Model**，由 Ditto 原生解析：`tm:extends` 继承、`tm:submodel` 组合，3.6 起写入校验；厂商差异只用 `tm:optional` 表达 |
| 时序库 | InfluxDB 2.x（3 Core 默认只能查约 72 小时） |
| 部署 | docker-compose（本机是 v2.6.0，命令是 `docker-compose`，不是 `docker compose`） |
| 胶水代码 | 允许，但每块 ≤ 300 行，并在 `stack/README.md` 的登记表中公开 |
| 关节名 | 取自 MuJoCo Menagerie MJCF（G1 用 `unitree_g1/g1.xml`，29 个关节，顺序与 DDS 索引一致） |
| PHM 回写 | 每次评估都写回 Feature 的 `phm` 分组，周期为分钟级 |
| 核电演示（P4） | 泵—电机—轴承组合，经 OPC UA 接入 |
| **P1 首台真机** | **G1 29 自由度**（2026-11-23 由 Franka 改为 G1；最初登记为 23 自由度，经真机探测和用户确认改为 29） |

## 3. 路线图与状态

| 阶段 | 状态 |
|---|---|
| P0 选型冻结 | ✅ |
| P1 单机打通 | 🟡 中心服务栈 ✅、Panda 孪生 + 模拟数据 ✅；**G1 29 自由度：TM、孪生、适配器、真机上行 ✅；Grafana 面板 ✅** |
| P2 Type 复用 | ⬜ Panda、PiperX 的真机适配器；验收标准是核心代码改动 0 行 |
| P3 PHM 链路 | ⬜ ProgPy/PyOD → 写回 `phm`；Event Frame；Atlas CMMS |
| P4 核电演示 | ⬜ |
| P5 加固 | ⬜ 离线部署、SBOM、审计 |

## 4. 当前环境

- 分支 `feat/phm-p1-stack`（未推送，没有 PR）。服务栈运行在本机 DGX 上（12 个容器，项目名 `phm`）。
- 登录：Grafana http://127.0.0.1:13000，Ditto UI http://127.0.0.1:18080/ui/。两者都用 `admin`，密码在 `stack/.env`（git 忽略）。
- MQTT 供边缘接入：`<DGX>:11883`，用户 `edge`。主题约定见 `stack/README.md`。
- **G1 跳板机**：`ssh server@10.10.61.210`（本机已配好 SSH 密钥，不用密码）。网卡 `enp6s0`（192.168.123.99）直连 G1 内网，G1 的 PC2 是 192.168.123.164。可用的 SDK 解释器：`/home/server/workspace/gr00t_wbc/.venv/bin/python`（含 `unitree_sdk2py`）。**gr00t_wbc 属于他人正在进行的工作，禁止修改其中任何文件**：脚本放在 `/tmp` 或自己的目录，运行时设置 `PYTHONDONTWRITEBYTECODE=1`。
- 已有孪生 `lab.robots:panda-001`，InfluxDB 里有 30 分钟的模拟数据。模拟器在会话临时目录中，**不在仓库里**，可能已被清理。

## 5. 下一步：G1 剩余工作

已完成（2026-11-23，提交见 git log）：battery-pack / G1 29dof TM，`lab.robots:g1-001`（31 个 Feature），`stack/adapters/g1_dds_mqtt.py`（154 行，已登记）。已在跳板机 `~/phm-adapter/` 上对真机实测：`rt/lowstate` ≈1040 Hz，丢包 0.01–0.11%；Ditto 与 InfluxDB（29 个关节）均有数据；跳板机能连 DGX MQTT（10.10.60.128:11883）。paho 是从 DGX 复制到 `~/phm-adapter/lib/`（不碰 gr00t_wbc 的 venv）。

- BMS 单位已核实：`cell_vol`、`bmsvoltage` 为 mV，`current` 为 mA（机器人开机时为负），`temperature` 为 °C。
- `ratedTorque` 暂用 `unitree_rl_gym/.../g1_29dof.urdf` 的 `effort`（峰值力矩上限，不是额定值）；`motor_info.md` 未找到，需要时再替换。
- 未做：用 `unitree_mujoco` 仿真测试（真机已覆盖验证）；`mainboardstate` 映射到 `controller`（`temperature[0]`≈44 °C 是否为 CPU 温度待确认，因此未映射）；适配器常驻运行（目前只手动跑过 45 秒）。
- Grafana 面板 `G1 Thermal & Battery`（`stack/grafana/dashboards/g1-thermal-battery.json`）：SOC/SOH/循环/电压/电流/最热绕组，29 关节绕组与驱动温度，电池电压/单体极值/温度。查询已通过 Grafana API 验证（数据可用、无报错），视觉效果未人工看过。电池 raw 在适配器中拍平为标量字段（`cellVoltageMin/Max`、`temperature0..3`）写入 InfluxDB，因为 raw 通道只支持标量。
- `provision.sh` 现在对已存在的 Thing 只更新 attributes（否则 PUT 会因 WoT 校验缺少骨架 Feature 而 400）。

## 6. 阻塞与未验证

- G1 主控固件版本：**暂时无法获取，不阻塞开发**。实验室没有宇树 App；`LowState.version` 为 `[0,0]`；loco/audio 服务的 `GetServerApiVersion` 返回错误 3102/3104（高层服务未响应，可能因机器人处于底层调试模式）。已知的版本线索：`mode_machine=5`、BMS 固件 1.3。孪生中 `controller.configuration.firmwareVersion` 暂不填写（它在 TM 中是可选项）。`rt/lf/mainboardstate` 可读（主板温度、电压），可映射到 `controller`。
- 待真机读取：Franka 系统版本（Panda 还是 FR3）、PiperX 固件版本（≥ 1.8-8 需用 `C_PiperInterface_V3`）。
- 未验证：MQTT ACL（smoke test 没覆盖）、Grafana 曲线的视觉效果、Telegraf 磁盘缓冲的容量上限。
- 许可证：Grafana 和 Atlas CMMS 为 AGPL，ProgPy 为 NOSA，交付核电前需要法务意见。

## 7. 常用命令（在 `stack/` 下执行）

```bash
docker-compose ps
./scripts/provision.sh
./scripts/smoke-test.sh
```

## 8. 踩过的坑

- Ditto 默认禁止从私网地址下载 TM（防 SSRF），`things` 服务已用 `THINGS_WOT_THING_MODEL_HTTP_SECURITY_ALLOWED_HOSTNAMES=phm-models` 放行。新增 TM 一律用 `http://phm-models/models/...` 引用。
- Telegraf 磁盘缓冲目录的权限：已在 compose 中通过 entrypoint 修复。
- 本机已被占用的端口包括 1883、8080、5432 等，所以服务栈用 11883/13000/18080/18086。
- Grafana 密码只在首次启动时读取 `.env`，之后要用 `grafana cli admin reset-admin-password` 修改。
- Ditto 登录用户名由 `.env` 的 `DITTO_USER` 决定，对应 Policy 主体 `nginx:<user>`；更换用户名前要先更新现有 Policy。
