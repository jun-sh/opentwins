# 交接文档（更新于 2026-11-23 20:10 CST：P2 适配器、P3、P4 已合并，G1 上行稳定）

新对话从这里开始：先读本文件，按需再读 `p0-verification.md`、`type-design.md`、`p3-phm.md`、`../stack/README.md`。

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
| P2 Type 复用 | 🟡 Panda 适配器 `stack/adapters/panda_franka_mqtt.py` 已写好，fake 后端端到端通过（核心代码改动 0 行），**真机未跑**（无访问方式）；PiperX 适配器 + TM + 孪生 `lab.robots:piperx-001` 已建，fake 后端端到端通过，**真机未跑** |
| P3 PHM 链路 | 🟡 G1：PHM worker（ProgPy 热模型 + PyOD ECOD）每 120 s 写回 29 个关节的 `phm` ✅；Event Frame（InfluxDB `event_frame` + Ditto `conditionChanged`）✅；Grafana `G1 PHM Health` ✅；Atlas CMMS 只评估未部署（见 `p3-phm.md`）；`maxTemperature` 用占位 80 °C |
| P4 核电演示 | 🟡 OPC UA 泵组模拟器 + Telegraf OPC UA→MQTT + 孪生 `plant.sim:pump-set-01` + Grafana 面板 ✅（DGX 上运行，核心代码改动 0 行）；见 §5 P4 |
| P5 加固 | 🟡 离线部署 + SBOM ✅（无网络隔离环境安装已验证，见 §5 P5）；审计未做 |

## 4. 当前环境

- 分支 `feat/phm-p1-stack` 已推送到 fork（远程 `fork` = jun-sh/opentwins），PR：https://github.com/jun-sh/opentwins/pull/1（fork 内，base main，未合并）。`origin` 是上游 ertis-research/opentwins，不要推送到那里。服务栈运行在本机 DGX 上（核心 compose 项目 `phm`；另有独立项目 `phm-analytics`（P3 worker，`stack/phm/`）和 P4 泵组模拟（`stack/plant-sim/`），均只加入 `phm_default` 网络）。
- 登录：Grafana http://127.0.0.1:13000，Ditto UI http://127.0.0.1:18080/ui/。两者都用 `admin`，密码在 `stack/.env`（git 忽略）。
- MQTT 供边缘接入：`<DGX>:11883`，用户 `edge`。主题约定见 `stack/README.md`。
- **G1 跳板机**：`ssh server@10.10.61.210`（本机已配好 SSH 密钥，不用密码）。网卡 `enp6s0`（192.168.123.99）直连 G1 内网，G1 的 PC2 是 192.168.123.164。可用的 SDK 解释器：`/home/server/workspace/gr00t_wbc/.venv/bin/python`（含 `unitree_sdk2py`）。**gr00t_wbc 属于他人正在进行的工作，禁止修改其中任何文件**：脚本放在 `/tmp` 或自己的目录，运行时设置 `PYTHONDONTWRITEBYTECODE=1`。
- 孪生：`lab.robots:g1-001`（真机实时数据 + PHM 评估）、`lab.robots:panda-001` 和 `lab.robots:piperx-001`（只有 fake 后端测试数据）、`plant.sim:pump-set-01`（OPC UA 模拟器实时数据）。模拟器在会话临时目录中，**不在仓库里**，可能已被清理。

## 5. 下一步

G1 29 自由度已打通（见 git log `feat/phm-p1-stack`）：TM、孪生 `lab.robots:g1-001`（31 个 Feature）、适配器 `stack/adapters/g1_dds_mqtt.py`（167 行，已登记；原始数据已压缩以适应跳板机 WiFi，入库 99.5–100%）、Grafana 面板 `G1 Thermal & Battery`、跳板机 systemd 常驻服务。

**优先级建议**（不依赖人的工作已做完，以下都要人提供信息或到现场）：① 查明 G1 `rt/lowstate` 间歇停发（18:36、20:05 CST 各一次，BMS 正常），可能是有人在用或切了模式；② 提供 Panda、PiperX 真机接入方式（哪台机器、控制柜 IP / CAN 口），然后跑通两个适配器并记录采样率和丢包；③ 确认 G1 关节 `maxTemperature`（现为占位 80 °C）和 PHM 阈值；④ 决定是否部署 Atlas CMMS（AGPL）；⑤ P5 加固（离线部署、SBOM）可无人值守进行；⑥ 有条件时把跳板机改为有线连 DGX（WiFi 余量约 0.7 MB/s）。

### P5 离线部署与 SBOM 状态（2026-11-23，分支 `claude/phm-p5-offline-sbom-f4b530`）
- 全部在 `stack/offline/`，用法见 `stack/README.md` 的 P5 小节。**核心文件改动 0 个**：三个 compose 文件、Dockerfile、`scripts/`、各类配置均未修改；只新增 `offline/` 下文件，外加 `stack/README.md`（登记表 + P5 小节）和本文件（文档）。
- `bundle.sh lock`：`images.lock` 把 compose 文件和 Dockerfile 中的 13 个上游镜像引用固定到注册表摘要（取自本机正在运行的镜像）；`python/phm-worker.lock.txt`（29 个制品）、`python/pump-sim.lock.txt`（13 个）记录每个 PyPI 制品的 sha256（x86_64、cp311）。
- `bundle.sh build`：按哈希下载 wheel（`fastdtw`、`wait_for2` 只有 sdist，打包时在固定的 Python 基础镜像中构建成 wheel，sdist 一并放入包中供审计），用 `docker build --network none` 构建 3 个自定义镜像（标签带 `-offline`，不覆盖运行中的 `phm-worker:0.1` 等），`docker save` 共 16 个镜像，生成 SBOM 和许可证汇总，输出 `dist/opentwins-phm-offline-<日期>-<提交>-<arch>.tar`（本次 1.9 GB，sha256 `051020345a6a…`）+ `.tar.sha256`，包内有 `SHA256SUMS`。本机上的 tar 不进 git（`dist/` 已忽略）。
- `install.sh`：校验 → `docker load` → 逐个核对镜像 ID → 解包 `stack/` → `init-env.sh`（密钥在目标机生成，不进包）→ 三个项目用离线覆盖文件（`pull_policy: never`、`--no-build`）启动 → 等待 InfluxDB/Grafana/Ditto → `provision.sh` → `smoke-test.sh`。`--rebuild` 在无网络情况下从包内 wheel 重新构建自定义镜像。
- **验证**（`offline/test/offline-proof.sh`）：在 `--network none` 的一次性 Docker-in-Docker 中（镜像库为空，网卡只有 lo/docker0，访问 Docker Hub 和 PyPI 失败）安装本次的包并加 `--rebuild`：16 个镜像 ID 全部一致；InfluxDB `pass` v2.10.1、Grafana `ok` 12.4.9、Ditto `UP`；provision 全部 201；smoke test 两项 PASS；15 个容器 restarts=0、5 个 Ditto 服务 healthy；P4 链路（OPC UA 模拟器 → Telegraf → MQTT → Ditto）`pump-set-01` 有实时转速；PHM worker 第一轮因 Ditto 尚未启动返回 502，下一轮（120 s 后）正常（29 个关节因无 G1 数据标为 stale，符合预期）。全程约 3 分钟；结束后只删除了自己的容器和卷，运行中的服务栈未受影响（启动时间未变）。
- SBOM：Syft v1.56.0（CycloneDX JSON），漏洞：Grype v0.121.1（数据库 2026-11-23），两者都按摘要固定。仓库内副本在 `stack/offline/sbom/`：`cyclonedx.tar.gz`（每个镜像一份 + 自定义镜像的 Python 专用 SBOM）、`licence-summary.md`、`licence-flags.csv`、`vuln-summary.md`。
- **许可证（需法务，未做决定）**：已知 Grafana AGPL-3.0、ProgPy NOSA（NASA-1.3）、Atlas CMMS AGPL（未部署）。**新发现**：MongoDB 7.0 为 SSPL-1.0（非 OSI，Ditto 的存储）；mongo 镜像内的 `mongodb-mongosh` 声明 `Apache-2.0 ; Proprietary`；asyncua 为 LGPL-3.0（只在模拟器中）；Python 依赖 `certifi` 为 MPL-2.0、`autocommand` 为 LGPL-3.0。Go/Java 组件大量显示 unknown（扫描器读不到二进制里的许可证），产品级许可证见手工维护的 `offline/components.json`。
- 漏洞（匹配数）：Grafana 33 Critical/154 High、ditto-ui 16/63、InfluxDB 4/61、Python 基础镜像（含 worker、模拟器）4/99、mongo 3/43；Ditto 后端服务 0 Critical、6–8 High。均为上游镜像自带，未升级任何版本（升级需人决定）。
- 遗留：一个包只支持一种 CPU 架构（arm64 需重新 lock）；sdist 构建后端在打包时从 PyPI 取、未固定；审计（访问日志、变更记录）未做；离线 Dockerfile 需与在线版手工保持一致。

### P2 Panda 适配器状态（2026-11-23）
- `stack/adapters/panda_franka_mqtt.py`（208 行，已登记）：`Robot.read_once()` 循环读 `RobotState`，映射 `q→position`、`dq→velocity`、`tau_J→torque`、`theta→motorPosition`、`tau_ext_hat_filtered→externalTorque`；`faultCode` 位 0 = `joint_collision[i]`、位 1 = `joint_contact[i]`、位 2 = 任一 `current_errors`；`controller.status` 写 `mode`（`kIdle` 等）和 `faultCodes`（激活的错误名）。丢包按 `RobotState.time` 的毫秒跳变统计（每 10 s 打印）。
- 后端：`pylibfranka`（FR3，系统 ≥ 5，libfranka ≥ 0.16，PyPI 轮子 ≥ 0.20.2；无 `server_version()`，`RobotMode` 名无 k 前缀，`Duration` 只有 `to_sec`）、`panda_py`（Panda 系统 4.x，需对应 libfranka 0.9.x 构建）、`fake`（合成数据，离线测试）。绑定差异已在代码里兼容，依据为两个仓库的 pybind 源码，**未在真机验证**。
- 离线验证（fake，DGX 本机，注入 0.2% 丢包）：适配器统计 1000 Hz、丢 0.20%；Ditto `panda-001` 7 个关节 + controller 实时更新；InfluxDB 7 个关节都有 `motorPosition` 等字段，当时只入库约 30%（Telegraf 丢数，已于 2026-11-23 修复，见 §6）。核心代码（TM、`provision.sh`、Telegraf/Ditto 配置）改动 0 行。
- 真机步骤：① Desk（浏览器打开控制柜 IP）Settings→System 读系统版本，激活 FCI；② 4.x → `--backend panda_py`，≥ 5 → `--backend pylibfranka`（`pip install pylibfranka==<与系统匹配的版本>`）；版本不匹配时连接报错会给出 server version；③ `MQTT_EDGE_PASSWORD=... python panda_franka_mqtt.py --backend <b> --robot-ip <ip> --mqtt-host 10.10.60.128 --duration 60`，记录 `[stats]` 的采样率和丢包；④ 仿照 G1 做 systemd 单元。注意 FCI 同时只允许一个客户端。

### P2 PiperX 适配器状态（2026-11-23）
- 新增 TM `asset/arm-agilex-piperx-1.0.0`（6 个 `rotating-actuator` 关节 `joint1..6` + `controller`，关节名取自 Menagerie `agilex_piper`，那是标准 PiPER，PiPER X 运动学待确认；夹爪暂不建模）、孪生 `lab.robots:piperx-001`（现有 `provision.sh` 创建）。核心代码改动 0 行。
- `stack/adapters/piperx_can_mqtt.py`（204 行，已登记）：以 `--poll-hz`（默认 200）轮询 piper_sdk 的反馈缓存，高速帧 `time_stamp` 变化才记一条样本。映射：`joint_state.joint_i`（0.001°）→`position`；高速 `motor_speed`（0.001 rad/s）→`velocity`、`effort`（0.001 N·m）→`torque`、`current`（0.001 A）→`current`；低速 `vol`（0.1 V）→`busVoltage`、`motor_temp`→`windingTemperature`、`foc_temp`→`driverTemperature`、`foc_status` 8 个标志位→`faultCode`（位序见代码 `FOC_BITS`；位 6 `driver_enable_status` 在正常使能时为 1，即正常值 64）。`controller.status.mode` = `ctrl_mode/arm_status`，`faultCodes` = 非正常 `arm_status` + `err_status` 中为真的标志；固件版本写入 `controller.configuration.firmwareVersion`。
- 字段名和单位来自 piper_sdk 的 INTERFACE_V2/V3 文档，**未对照代码和真机核对**；反馈频率文档未给出，运行时打印 SDK 的 `Hz` 字段。
- 离线验证（fake，DGX）：200 Hz 新帧；Ditto 6 关节 + controller 实时更新；InfluxDB 25 s 内每关节 4930 条（≈ 200 Hz × 运行时长）。
- 真机步骤：① 工控机上 `pip install piper_sdk`，配置 SocketCAN（`can0`，1 Mbit/s）；② `--dry-run --duration 10` 读固件版本（≥ 1.8-8 用 V3）并确认机型是 PiPER X；③ 正式运行 60 s，记录 `[stats]` 的帧率；④ 做 systemd 单元。需用户提供：PiperX 连在哪台机器、CAN 口名。

### P4 OPC UA 泵组状态（2026-11-23）
- 组成：`stack/plant-sim/`，独立 compose 项目 `phm-plant`（接入外部网络 `phm_default`，不动核心服务）。启动：`cd stack/plant-sim && docker-compose -p phm-plant --env-file ../.env up -d --build`。配置打包进镜像，不依赖本检出目录。
  - `pump-sim`：asyncua 1.1.8 的 OPC UA 服务器（`pump_set_opcua_sim.py`，190 行，已登记），宿主机 `127.0.0.1:14840`，命名空间 `urn:opentwins:plant-sim`，节点 `PumpSet01.*`；转速、定子电流、转矩、绕组温度、DE/NDE 轴承振动 RMS/峰值与温度、流量、进出口压力、6 个报警点（布尔）+ 报警字。
  - 退化注入：`PumpSet01.Sim.BearingWear`（0–1，可写）按 `Sim.BearingWearRate`（默认 0.5/h）增长，驱动端振动、轴承温度、电流随之升高；到 1 自动"换轴承"归零（2 小时一个锯齿周期）。阈值按 ISO 10816-3：7.1 mm/s 报警、11.2 停机。写节点即可注入故障（已验证：写 0.8 → `motor.faultCode=1`、`controller.faultCodes=["VibrationHigh"]`；写回 0.05 → 报警清除）。
  - `telegraf-opcua`：Telegraf 1.40.3 `inputs.opcua` → `outputs.mqtt`，**纯配置**（`telegraf-opcua.conf`）。10 Hz 原始数据每秒批量发到 `phm/raw/...`，1 Hz 状态以 Ditto merge 发到 `phm/state/...`；用 JSONata 生成负载，报警布尔量转成 `controller.faultCodes`。节点列表写了两遍（10 Hz 与 1 Hz 两路输入），因为 Telegraf 聚合器不能串联。
- Type：新增 `component/bearing-1.0.0`、`component/centrifugal-pump-1.0.0`、`asset/motor-pump-set-1.0.0`；电机复用 `rotating-actuator`（`velocity`、`current`、`torque`、`windingTemperature`、`faultCode`），控制器复用 `controller`。孪生 `plant.sim:pump-set-01` 用现有 `provision.sh` 创建（复用 `policy-robot.json`）。
- 验证：Ditto 5 个 Feature 每秒更新；InfluxDB 每个 Feature 约 10 样本/秒；Grafana 面板 *Pump Set (OPC UA, P4)*（uid `phm-pump-set`，14 个面板）全部查询经 API 返回数据。面板视觉效果未用浏览器检查。
- **核心代码改动 0 行**：现有 TM、`provision.sh`、核心 compose、Telegraf/mosquitto/Ditto 配置均未修改；只新增文件，外加 `stack/README.md` 登记表和 P4 小节（文档）。
- **部署注意**：运行中的 nginx/Grafana 挂载的是主检出目录 `opentwins/stack/`（分支 `feat/phm-p1-stack`）。为让服务即时生效，已把 3 个新 TM 和 `pump-set.json` **复制**到主检出目录（未跟踪文件）。合并本分支后这些文件会变成已跟踪文件，内容相同；合并时若 git 报"untracked file would be overwritten"，先删除主检出目录中的这 4 个副本。
- 遗留：未实现 OPC UA Alarms & Conditions 事件（报警是布尔变量，Telegraf 只轮询值）；OPC UA 安全策略为 None（核电部署需 Basic256Sha256 + 证书）；轴承几何、额定值等 configuration 属性未填写（TM 中为可选）；未与 Microsoft OPC PLC 等第三方服务器做互通测试。

### P3 PHM 状态（2026-11-23，分支 `claude/phm-p3-pipeline-4cb468`）
- 设计、参数、局限、Atlas 评估：`planning/p3-phm.md`。核心代码（TM、Ditto/Telegraf/mosquitto 配置、主 compose）改动 0 行；worker 是独立 compose 项目 `phm-analytics`（`stack/phm/`），只加入 `phm_default` 网络。
- 运行：`cd stack/phm && docker-compose -p phm-analytics --env-file ../.env up -d --build`（`-p` 必须带）。`restart: unless-stopped` + `init: true`；进程被 kill -9 后自动拉起已验证；未结束的 Event Frame 重启后从 InfluxDB 恢复（已用临时 thing_id 验证后删除）。
- Grafana 面板 `G1 PHM Health`（uid `phm-g1-health`）已通过 API 导入运行中的 Grafana；文件在 `stack/grafana/dashboards/g1-phm-health.json`，分支合并后由文件 provisioning 接管。
- 待人工：① 宇树 G1 关节过温限值 → 写入各关节 `configuration.maxTemperature`；② 是否部署 Atlas CMMS（AGPL）；③ 阈值（watch/alert）需要带载数据后再调。
- G1 曾离线：`rt/lowstate` 10:36–11:20 UTC（18:36–19:20 CST）为 0 Hz（电池数据正常）；11:45 UTC 复查时已恢复（10 min 约 45 万样本/关节，Telegraf 修复后）。worker 对 10 min 无数据的关节不评估（`rulHours=-1`，InfluxDB 标 `stale`），历史回放模式见 `p3-phm.md`。**若机器人再次离线，实时链路需在其恢复后复查**；最后一次实时复查：2026-11-23 11:43 UTC，29 个关节均有新评估。

### G1 运行状态
- 跳板机用户服务 `g1-adapter`：`systemctl --user status|restart|stop g1-adapter`，日志 `journalctl --user -u g1-adapter`。单元文件在 `stack/adapters/systemd/`；`~/phm-adapter/env`（权限 600）存 MQTT 密码；已 `enable-linger`。kill -9 后 5 秒自动拉起已验证；**整机重启后自启未实测**。更新适配器：scp 到 `~/phm-adapter/` 后 restart。在 G1 上做别的底层调试前可先 stop（适配器只订阅，不下发）。
- 实测：`rt/lowstate` ≈1040 Hz，丢包 0.01–0.12%；Ditto 与 InfluxDB（29 关节 + battery）均有数据。paho 从 DGX 复制到 `~/phm-adapter/lib/`（不碰 gr00t_wbc 的 venv）。跳板机连 DGX MQTT 用 10.10.60.128:11883。
- BMS 单位：`cell_vol`、`bmsvoltage` 为 mV，`current` 为 mA（开机时为负），`temperature` 为 °C。
- 电池 raw 在适配器中拍平为标量字段（`cellVoltageMin/Max`、`temperature0..3`）写入 InfluxDB，因为 raw 通道只支持标量。
- `provision.sh` 对已存在的 Thing 只更新 attributes（PUT 会因 WoT 校验缺骨架 Feature 而 400）。

### G1 遗留
- `ratedTorque` 暂用 `unitree_rl_gym/.../g1_29dof.urdf` 的 `effort`（峰值上限，不是额定值）；`motor_info.md` 未找到。
- `temperature[0..1]` 是否为绕组/驱动器温度未经宇树文档确认（面板标题已注明）。
- `mainboardstate` 未映射到 `controller`（`temperature[0]`≈44 °C 是否为 CPU 温度待确认）。
- 未用 `unitree_mujoco` 仿真测试（真机已覆盖）。

## 6. 阻塞与未验证

- G1 主控固件版本：**暂时无法获取，不阻塞开发**。实验室没有宇树 App；`LowState.version` 为 `[0,0]`；loco/audio 服务的 `GetServerApiVersion` 返回错误 3102/3104（高层服务未响应，可能因机器人处于底层调试模式）。已知的版本线索：`mode_machine=5`、BMS 固件 1.3。孪生中 `controller.configuration.firmwareVersion` 暂不填写（它在 TM 中是可选项）。`rt/lf/mainboardstate` 可读（主板温度、电压），映射见 §5 遗留。
- **Panda 真机访问方式未知**（2026-11-23 用户答复"暂时无法接入"）：需要直连控制柜的主机、SSH 方式、控制柜 IP。待真机读取：Franka 系统版本（Panda 还是 FR3）、PiperX 固件版本（≥ 1.8-8 需用 `C_PiperInterface_V3`）。
- **Telegraf 丢原始数据：已修复（2026-11-23）**。根因：Telegraf 磁盘缓冲（实验性 WAL）在 G1 速率（约 3 万点/秒）下写放大严重（容器累计写盘 437 GB），输出跟不上 → `mqtt_consumer` 的未交付消息达到上限（默认 1000）后停止读取 → paho 收不到 PINGRESP 断线重连、mosquitto 丢弃发往 telegraf 的消息。修复（只改 `stack/telegraf/telegraf.conf`，mosquitto 未改）：`buffer_strategy = "memory"`、`metric_buffer_limit = 3000000`（约 100 s 的 G1 数据）、`max_undelivered_messages = 10000`。验证：G1 当时离线，用同速率合成负载（29 关节 × 1040 Hz、200 ms 批）跑 5 分钟，入库 9,048,000/9,048,000（100%），Telegraf 零重连、mosquitto 无 dropped；测试数据已删除。代价：InfluxDB 停机超过约 100 s 或 Telegraf 重启会丢原始数据；接入更多机器人时要调大 `metric_buffer_limit`。G1 真机恢复后应复核每关节每分钟约 6.2 万条。
- **G1 原始数据经 WiFi 丢约 25%：已修复（2026-11-23 19:54 CST）**。根因：跳板机到 DGX 走 WiFi（`wlo1`），原始 JSON 约 4.3 MB/s 超出带宽 → paho 队列积压、约每 2 分钟 keepalive 超时重连，QoS0 积压消息丢失（Telegraf/mosquitto 无报错）。修复只改适配器 `g1_dds_mqtt.py`（161→167 行）：快字段取整（position 1e-5 rad、velocity 1e-4、torque 1e-3），慢字段（busVoltage、温度、faultCode）只在变化或每 100 ms 发一次，JSON 紧凑分隔符 → 2.64 MB/s（降 39%）。实测：broker 每关节 1042 样本/s（适配器 1041 Hz），InfluxDB 整分钟 62,450 条/关节（≈100%），重连 0；PHM worker 正常（30 s 均值不受慢字段稀疏影响）。10 分钟复核（11:56–12:05 UTC）：29 关节合计每分钟 1,802,640–1,812,152 条，理论值 1,811,340（1041 Hz × 60 × 29），即 99.5–100%；mosquitto 重连 0、Telegraf 报错 0。20:05:50 CST 起 `rt/lowstate` 再次变为 0 Hz（BMS 仍有数据），是机器人侧停发，与传输无关（同 18:36 那次）。旧版备份在跳板机 `~/phm-adapter/g1_dds_mqtt.py.bak-*`。余量有限：WiFi 实测能过约 3.3 MB/s，再加机器人或字段需改有线。
- 未验证：MQTT ACL（smoke test 没覆盖）、Grafana 面板的视觉效果（查询已用 API 验证）、Telegraf 内存缓冲在 InfluxDB 长时间停机下的行为。
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
