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
| P1 单机打通 | 🟡 中心服务栈 ✅、Panda 孪生 + 模拟数据 ✅；**G1 29 自由度：TM、孪生、适配器 ⬜** |
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

## 5. 下一步：G1 29 自由度打通（按顺序）

1. **TM**：
   - 新建 `component/battery-pack-1.0.0.tm.jsonld`（`type-design.md` §4 已定义字段）。真机 BMS 能提供：`soc`、`soh`、`cycle`、`current`、`bmsvoltage`、13 节 `cell_vol`、4 路 `temperature`，按需补充为可选属性。
   - 新建 `asset/humanoid-unitree-g1-29dof-1.0.0.tm.jsonld`，包含 29 个 `rotating-actuator` 子模型 + `battery` + `controller`。
   - 子模型实例名 = Menagerie `unitree_g1/g1.xml` 的 29 个关节名，顺序即 DDS 索引 0–28：左右腿各 6、腰 yaw/roll/pitch、左右臂各 7（shoulder pitch/roll/yaw、elbow、wrist roll/pitch/yaw）。
2. **孪生实例**：新建 `stack/things/lab.robots_g1-001.json`，运行 `./scripts/provision.sh`，确认骨架生成了 31 个 Feature。
   - `configuration.ratedTorque` 按电机型号取自 `unitree_ros/robots/g1_description/motor_info.md`。
3. **适配器**（胶水，≤ 300 行，用 `unitree_sdk2_python`）：
   - 订阅 `rt/lowstate`（`unitree_hg` 的 `LowState_`），**实测约 1 kHz**。映射关系：`q→position`、`dq→velocity`、`tau_est→torque`、`temperature[0..1]→windingTemperature/driverTemperature`（**含义待宇树文档确认**；部分手腕电机两路相差约 9 °C）、`vol→busVoltage`、`motorstate→faultCode`。
   - 订阅 `rt/lf/bmsstate`（`unitree_hg` 的 `BmsState_`），实测可读，映射到 `battery`。
   - 发布到 MQTT：raw 批量发送，state 5 Hz。
4. **先用仿真开发适配器**：`unitreerobotics/unitree_mujoco`（BSD-3）会通过 DDS 发布同样的 `rt/lowstate`，可以在接真机之前把适配器做通。
5. **上真机**（访问方式见 §4 跳板机）：适配器放在跳板机上自己的目录中运行，只订阅、不下发控制；验证 1 kHz 下是否丢包，以及跳板机能否连到 DGX 的 MQTT 11883 端口。
6. Grafana 增加 G1 温度和电池面板，作为 P3 热模型、电池 SOH 的输入。

## 6. 阻塞与未验证

- 待真机读取：G1 主控固件版本（DDS 读不到，需在宇树 App 查看；BMS 固件为 1.3）、Franka 系统版本（Panda 还是 FR3）、PiperX 固件版本（≥ 1.8-8 需用 `C_PiperInterface_V3`）。
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
