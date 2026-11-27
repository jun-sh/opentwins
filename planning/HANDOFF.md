# 交接文档（更新于 2026-11-24：总目标改为只做机器人，核电/泵组部分已全部移除）

新对话从这里开始：先读本文件，按需再读 `p0-verification.md`、`type-design.md`、`p3-phm.md`、`../stack/README.md`。

## 1. 目标（一句话）

只集成成熟开源项目，构建设备数字孪生 + PHM 参考架构。**只面向机器人**：用 Unitree G1、Franka Panda、PiperX 三台真机验证，通用性靠"WoT Type 复用 + 适配器"证明（同一套部件 Type 跨厂商、跨构型复用，新增机器人只加适配器和资产 TM），不靠自研算法或平台。

> 2026-11-24 用户决定：彻底剥离核电相关内容（原 P4 泵—电机—轴承 OPC UA 演示），项目只专注机器人。代码、TM、孪生、面板、离线包条目、运行中的容器和数据均已删除；历史见 git（P4 合并提交 `8f74638`）。

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
| **P1 首台真机** | **G1 29 自由度**（2026-11-23 由 Franka 改为 G1；最初登记为 23 自由度，经真机探测和用户确认改为 29） |

## 3. 路线图与状态

| 阶段 | 状态 |
|---|---|
| P0 选型冻结 | ✅ |
| P1 单机打通 | 🟡 中心服务栈 ✅、Panda 孪生 + 模拟数据 ✅；**G1 29 自由度：TM、孪生、适配器、真机上行 ✅；Grafana 面板 ✅** |
| P2 Type 复用 | 🟡 Panda 适配器 `stack/adapters/panda_franka_mqtt.py` 已写好，fake 后端端到端通过（核心代码改动 0 行），**真机未跑**（无访问方式）；PiperX 适配器 + TM + 孪生 `lab.robots:piperx-001` 已建，fake 后端端到端通过，**真机未跑**；两者都有 MuJoCo 仿真后端（`--backend sim`，Menagerie 模型），在 DGX 上持续产生数据（见 §5 仿真） |
| P3 PHM 链路 | 🟡 PHM worker（ProgPy 热模型 + PyOD ECOD）每 120 s 评估三台机器人（G1 29 + Panda 7 + PiperX 6 个关节）并写回 `phm` ✅；Grafana `PHM Fleet Overview` + `PHM Health per Robot` ✅；Event Frame（InfluxDB `event_frame` + Ditto `conditionChanged`）✅；**检出验证 ✅（2026-11-26）**：PiperX joint2 仿真磨损在 +3.5 h 报 watch、5 个对照关节 0 误报（固定基线 + 防抖，见 `p3-phm.md`「检出验证」）；worker 改读 InfluxDB 降采样 bucket `phm_agg`，每轮 0.1–0.2 s（原 30–74 s）；Atlas CMMS 只评估未部署（见 `p3-phm.md`）；`maxTemperature` 用占位 80 °C |
| P4 ~~核电演示~~ | ❌ 已取消（2026-11-24，项目只做机器人） |
| P5 加固 | 🟡 离线部署 + SBOM ✅（无网络隔离环境安装已验证，见 §5 P5）；审计未做 |

## 4. 当前环境

- 分支 `feat/phm-p1-stack` 已推送到 fork（远程 `fork` = jun-sh/opentwins），PR：https://github.com/jun-sh/opentwins/pull/1（fork 内，base main，未合并）。`origin` 是上游 ertis-research/opentwins，不要推送到那里。服务栈运行在本机 DGX 上（核心 compose 项目 `phm`；另有独立项目 `phm-analytics`（P3 worker，`stack/phm/`），只加入 `phm_default` 网络）。
- 登录：Grafana http://127.0.0.1:13000，Ditto UI http://127.0.0.1:18080/ui/。两者都用 `admin`，密码在 `stack/.env`（git 忽略）。
- MQTT 供边缘接入：`<DGX>:11883`，用户 `edge`。主题约定见 `stack/README.md`。
- **G1 跳板机**：`ssh server@10.10.61.210`（本机已配好 SSH 密钥，不用密码）。网卡 `enp6s0`（192.168.123.99）直连 G1 内网，G1 的 PC2 是 192.168.123.164。可用的 SDK 解释器：`/home/server/workspace/gr00t_wbc/.venv/bin/python`（含 `unitree_sdk2py`）。**gr00t_wbc 属于他人正在进行的工作，禁止修改其中任何文件**：脚本放在 `/tmp` 或自己的目录，运行时设置 `PYTHONDONTWRITEBYTECODE=1`。
- 孪生：`lab.robots:g1-001`（真机实时数据 + PHM 评估）、`lab.robots:panda-001` 和 `lab.robots:piperx-001`（只有 fake 后端测试数据）。模拟器在会话临时目录中，**不在仓库里**，可能已被清理。

## 5. 下一步

G1 29 自由度已打通（见 git log `feat/phm-p1-stack`）：TM、孪生 `lab.robots:g1-001`（31 个 Feature）、适配器 `stack/adapters/g1_dds_mqtt.py`（167 行，已登记；原始数据已压缩以适应跳板机 WiFi，入库 99.5–100%）、Grafana 面板 `G1 Thermal & Battery`、跳板机 systemd 常驻服务。

**优先级建议**（不依赖人的工作已做完，以下都要人提供信息或到现场）：① 查明 G1 `rt/lowstate` 间歇停发（18:36、20:05 CST 各一次，BMS 正常），可能是有人在用或切了模式；② 提供 Panda、PiperX 真机接入方式（哪台机器、控制柜 IP / CAN 口），然后跑通两个适配器并记录采样率和丢包；③ 确认 G1 关节 `maxTemperature`（现为占位 80 °C）和 PHM 阈值；④ 决定是否部署 Atlas CMMS（AGPL）；⑤ P5 加固（离线部署、SBOM）可无人值守进行；⑥ 有条件时把跳板机改为有线连 DGX（WiFi 余量约 0.7 MB/s）。

### 仿真与多机器人 PHM（2026-11-24，A1+A2）
- `stack/adapters/mujoco_sim.py`（84 行）：Menagerie MJCF 在自带位置伺服下跑平滑往复轨迹（关闭 PiPER 模型的重力补偿，让驱动承担重力），实时步进；一阶热模型（绕组/驱动器温升 ∝ 扭矩²）、传感器噪声；`--sim-wear JOINT=RATE` 每小时增加阻尼和摩擦，用来给 PHM 制造可检测的退化。Panda 仿真按 FCI 实际情况不输出温度。
- Menagerie 稀疏克隆在 `~/models/mujoco_menagerie`（只含 `franka_emika_panda`、`agilex_piper`，提交 eea4c74），不进仓库。宿主机 Python 已有 mujoco 3.11.0、paho 1.5.1。
- 验证：Panda 仿真 990–1000 Hz、丢包 0；PiperX 新帧 184–194 Hz；PHM worker 每轮三台机器人（G1 74 s 含重拟合，Panda 0.4 s，PiperX 0.2 s）；Fleet 面板和单机面板全部查询有数据、无错误。
- **两个仿真适配器已作为 DGX 用户服务常驻（2026-11-26）**：`panda-sim-adapter`、`piperx-sim-adapter`（已 enable，linger 已开，开机自启；`Restart=always`），`systemctl --user status|restart|stop <名>`，日志 `journalctl --user -u <名>`。环境文件 `~/.config/phm-sim/env`（权限 600：`OPENTWINS_STACK`、`MENAGERIE_DIR=~/models/mujoco_menagerie`、`MQTT_EDGE_PASSWORD`）；单元文件改了要重新 `cp stack/adapters/systemd/*-sim-adapter.service ~/.config/systemd/user/ && systemctl --user daemon-reload`。切换后实测 Panda 991 Hz 0 丢包、PiperX 198 Hz，InfluxDB 和 Ditto 均有新数据。两个单元都带 `--sim-wear-cycle-h 24`：磨损按 UTC 墙钟 24 h 周期计算，重启不清零，每天 00:00 UTC 归零（相当于检修），PiperX joint2 每天约 03:30 UTC 进 watch、约 14:30 UTC fault；接真机前先 `disable --now` 对应仿真服务，避免两个来源写同一个孪生。
- PiPER 单元对 `joint2` 注入磨损 0.5/小时（阻尼 N·m·s/rad 与摩擦 N·m），重启适配器即复位；预计数小时后 `joint2` 扭矩/温度上升、ECOD 打分升高。
- 坑：`stack/.env` 含 `COMPOSE_PROJECT_NAME=phm`，在 `stack/phm` 里用 `--env-file ../.env` 会把 worker 建进 `phm` 项目；必须 `docker-compose -p phm-analytics --env-file ../.env up -d --build`。

### P5 离线部署与 SBOM 状态（2026-11-23，分支 `claude/phm-p5-offline-sbom-f4b530`）
- 全部在 `stack/offline/`，用法见 `stack/README.md` 的 P5 小节。**核心文件改动 0 个**：compose 文件、Dockerfile、`scripts/`、各类配置均未修改；只新增 `offline/` 下文件，外加 `stack/README.md`（登记表 + P5 小节）和本文件（文档）。
- `bundle.sh lock`：`images.lock` 把 compose 文件和 Dockerfile 中的 上游镜像引用固定到注册表摘要（取自本机正在运行的镜像）；`python/phm-worker.lock.txt`（29 个制品）记录每个 PyPI 制品的 sha256（x86_64、cp311）。
- `bundle.sh build`：按哈希下载 wheel（`fastdtw` 只有 sdist，打包时在固定的 Python 基础镜像中构建成 wheel，sdist 一并放入包中供审计），用 `docker build --network none` 构建自定义镜像（标签带 `-offline`，不覆盖运行中的 `phm-worker:0.1` 等），`docker save` 全部镜像，生成 SBOM 和许可证汇总，输出 `dist/opentwins-phm-offline-<日期>-<提交>-<arch>.tar`（2026-11-25 重建：`opentwins-phm-offline-20261125-48b55dd-x86_64.tar`，1.9 GB，15 个镜像，Grafana 12.4.15 + 修补版 ditto-ui，无泵组；`offline-proof.sh --rebuild` 断网隔离安装通过）+ `.tar.sha256`，包内有 `SHA256SUMS`。本机上的 tar 不进 git（`dist/` 已忽略）。
- `install.sh`：校验 → `docker load` → 逐个核对镜像 ID → 解包 `stack/` → `init-env.sh`（密钥在目标机生成，不进包）→ 两个项目用离线覆盖文件（`pull_policy: never`、`--no-build`）启动 → 等待 InfluxDB/Grafana/Ditto → `provision.sh` → `smoke-test.sh`。`--rebuild` 在无网络情况下从包内 wheel 重新构建自定义镜像。
- **验证**（`offline/test/offline-proof.sh`）：在 `--network none` 的一次性 Docker-in-Docker 中（镜像库为空，网卡只有 lo/docker0，访问 Docker Hub 和 PyPI 失败）安装本次的包并加 `--rebuild`：16 个镜像 ID 全部一致；InfluxDB `pass` v2.10.1、Grafana `ok` 12.4.9、Ditto `UP`；provision 全部 201；smoke test 两项 PASS；15 个容器 restarts=0、5 个 Ditto 服务 healthy；PHM worker 第一轮因 Ditto 尚未启动返回 502，下一轮（120 s 后）正常（29 个关节因无 G1 数据标为 stale，符合预期）。全程约 3 分钟；结束后只删除了自己的容器和卷，运行中的服务栈未受影响（启动时间未变）。
- SBOM：Syft v1.56.0（CycloneDX JSON），漏洞：Grype v0.121.1（数据库 2026-11-23），两者都按摘要固定。仓库内副本在 `stack/offline/sbom/`：`cyclonedx.tar.gz`（每个镜像一份 + 自定义镜像的 Python 专用 SBOM）、`licence-summary.md`、`licence-flags.csv`、`vuln-summary.md`。
- **许可证（需法务，未做决定）**：已知 Grafana AGPL-3.0、ProgPy NOSA（NASA-1.3）、Atlas CMMS AGPL（未部署）。**新发现**：MongoDB 7.0 为 SSPL-1.0（非 OSI，Ditto 的存储）；mongo 镜像内的 `mongodb-mongosh` 声明 `Apache-2.0 ; Proprietary`；Python 依赖 `certifi` 为 MPL-2.0、`autocommand` 为 LGPL-3.0。Go/Java 组件大量显示 unknown（扫描器读不到二进制里的许可证），产品级许可证见手工维护的 `offline/components.json`。
- 漏洞（匹配数）：Grafana 33 Critical/154 High、ditto-ui 16/63、InfluxDB 4/61、Python 基础镜像（含 worker）4/99、mongo 3/43；Ditto 后端服务 0 Critical、6–8 High。均为上游镜像自带，未升级任何版本（升级需人决定）。
- 遗留：一个包只支持一种 CPU 架构（arm64 需重新 lock）；sdist 构建后端在打包时从 PyPI 取、未固定；审计（访问日志、变更记录）未做；离线 Dockerfile 需与在线版手工保持一致。

### P2 Panda 适配器状态（2026-11-23）
- `stack/adapters/panda_franka_mqtt.py`（208 行，已登记）：`Robot.read_once()` 循环读 `RobotState`，映射 `q→position`、`dq→velocity`、`tau_J→torque`、`theta→motorPosition`、`tau_ext_hat_filtered→externalTorque`；`faultCode` 位 0 = `joint_collision[i]`、位 1 = `joint_contact[i]`、位 2 = 任一 `current_errors`；`controller.status` 写 `mode`（`kIdle` 等）和 `faultCodes`（激活的错误名）。丢包按 `RobotState.time` 的毫秒跳变统计（每 10 s 打印）。
- 后端：`pylibfranka`（FR3，系统 ≥ 5，libfranka ≥ 0.16，PyPI 轮子 ≥ 0.20.2；无 `server_version()`，`RobotMode` 名无 k 前缀，`Duration` 只有 `to_sec`）、`panda_py`（Panda 系统 4.x，需对应 libfranka 0.9.x 构建）、`fake`（合成数据，离线测试）。绑定差异已在代码里兼容，依据为两个仓库的 pybind 源码，**未在真机验证**。
- 离线验证（fake，DGX 本机，注入 0.2% 丢包）：适配器统计 1000 Hz、丢 0.20%；Ditto `panda-001` 7 个关节 + controller 实时更新；InfluxDB 7 个关节都有 `motorPosition` 等字段，当时只入库约 30%（Telegraf 丢数，已于 2026-11-23 修复，见 §6）。核心代码（TM、`provision.sh`、Telegraf/Ditto 配置）改动 0 行。
- 真机步骤：① Desk（浏览器打开控制柜 IP）Settings→System 读系统版本，激活 FCI；② 4.x → `--backend panda_py`，≥ 5 → `--backend pylibfranka`（`pip install pylibfranka==<与系统匹配的版本>`）；版本不匹配时连接报错会给出 server version；③ `MQTT_EDGE_PASSWORD=... python panda_franka_mqtt.py --backend <b> --robot-ip <ip> --mqtt-host 10.10.60.128 --duration 60`，记录 `[stats]` 的采样率和丢包；④ 仿照 G1 做 systemd 单元。注意 FCI 同时只允许一个客户端。

### P2 PiperX 适配器状态（2026-11-23）
- 新增 TM `asset/arm-agilex-piperx-1.0.0`（6 个 `rotating-actuator` 关节 `joint1..6` + `controller`，关节名取自 Menagerie `agilex_piper`，那是标准 PiPER，PiPER X 运动学待确认；夹爪暂不建模）、孪生 `lab.robots:piperx-001`（现有 `provision.sh` 创建）。核心代码改动 0 行。
- `stack/adapters/piperx_can_mqtt.py`（204 行，已登记）：以 `--poll-hz`（默认 200）轮询 piper_sdk 的反馈缓存，高速帧 `time_stamp` 变化才记一条样本。映射：`joint_state.joint_i`（0.001°）→`position`；高速 `motor_speed`（0.001 rad/s）→`velocity`、`effort`（0.001 N·m）→`torque`、`current`（0.001 A）→`current`；低速 `vol`（0.1 V）→`busVoltage`、`motor_temp`→`windingTemperature`、`foc_temp`→`driverTemperature`、`foc_status` 8 个标志位→`faultCode`（位序见代码 `FOC_BITS`；位 6 `driver_enable_status` 是状态不是故障，2026-11-24 起恒为 0，正常值 0）。`controller.status.mode` = `ctrl_mode/arm_status`，`faultCodes` = 非正常 `arm_status` + `err_status` 中为真的标志；固件版本写入 `controller.configuration.firmwareVersion`。
- 字段名和单位来自 piper_sdk 的 INTERFACE_V2/V3 文档，**未对照代码和真机核对**；反馈频率文档未给出，运行时打印 SDK 的 `Hz` 字段。
- 离线验证（fake，DGX）：200 Hz 新帧；Ditto 6 关节 + controller 实时更新；InfluxDB 25 s 内每关节 4930 条（≈ 200 Hz × 运行时长）。
- 真机步骤：① 工控机上 `pip install piper_sdk`，配置 SocketCAN（`can0`，1 Mbit/s）；② `--dry-run --duration 10` 读固件版本（≥ 1.8-8 用 V3）并确认机型是 PiPER X；③ 正式运行 60 s，记录 `[stats]` 的帧率；④ 做 systemd 单元。需用户提供：PiperX 连在哪台机器、CAN 口名。

### P3 PHM 状态（2026-11-23，分支 `claude/phm-p3-pipeline-4cb468`）
- 设计、参数、局限、Atlas 评估：`planning/p3-phm.md`。核心代码（TM、Ditto/Telegraf/mosquitto 配置、主 compose）改动 0 行；worker 是独立 compose 项目 `phm-analytics`（`stack/phm/`），只加入 `phm_default` 网络。
- 运行：`cd stack/phm && docker-compose -p phm-analytics --env-file ../.env up -d --build`（`-p` 必须带）。`restart: unless-stopped` + `init: true`；进程被 kill -9 后自动拉起已验证；未结束的 Event Frame 重启后从 InfluxDB 恢复（已用临时 thing_id 验证后删除）。
- Grafana 面板 `PHM Health per Robot`（原 `G1 PHM Health`，uid `phm-g1-health` 未改，按 thing_id 切换机器人）已通过 API 导入运行中的 Grafana；文件在 `stack/grafana/dashboards/g1-phm-health.json`，分支合并后由文件 provisioning 接管。
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
- **InfluxDB 磁盘增长（已处理 2026-11-27）**：raw 每天约 25 GB（主要是 Panda 1 kHz 仿真 + G1）。按用户决定，raw 保留 14 天（`INFLUX_RAW_RETENTION=14d`，`provision.sh` 设置，1 天一个 shard），稳定后约 350 GB。PHM 结果 `phm`、`event_frame`、`phm_baseline` 已迁到 `phm_agg`（永久保留），历史数据已复制过去；Grafana PHM 看板改读 `phm_agg`，遥测看板仍读 raw，最多显示 14 天。离线包已重打（`opentwins-phm-offline-20261127-61a4999-x86_64.tar`），断网验证通过：15 个镜像 ID 一致；`phm_agg` 永久保留、raw 保留 1209600 s；降采样任务 active/success；13 个容器 restarts=0；worker 第一轮因 `phm_agg` 尚未创建报 404（provision 在 worker 之后），下一轮正常，验证脚本现在会等到 worker 成功跑完一轮。
- **G1 关节数据已停 24 h 以上**（2026-11-26 15:20 UTC 查：只有 `battery` 有数据，29 个关节全部 stale）：即 `rt/lowstate` 停发问题，需到现场确认机器人状态。
- 未验证：MQTT ACL（smoke test 没覆盖）、Grafana 面板的视觉效果（查询已用 API 验证）、Telegraf 内存缓冲在 InfluxDB 长时间停机下的行为。
- 许可证：Grafana 和 Atlas CMMS 为 AGPL，ProgPy 为 NOSA，对外交付前需要法务意见（另见 P5 小节：MongoDB SSPL）。
- **CVE 升级（2026-11-24，分支 `claude/phm-cve-upgrade-89a9e7`）**：Grafana 12.4.9 → **12.4.15**（同主版本；Grype Critical/High 33/154 → 1/25；13.3.1 为 5/55，未选）。先在隔离项目（独立端口、卷为在线卷的副本）验证，再在线只重建 grafana（`up -d --no-deps`，其他容器启动时间未变）：登录正常，4 个面板 37 个查询全部有数据、0 错误，结果与 12.4.9 逐项一致。旧卷冷备份：`~/opentwins-backups/phm_grafana-data-12.4.9-20261124T013354Z.tar.gz`（12.4.15 已迁移数据库，回退需恢复此备份）。**ditto-ui 修补（2026-11-25，用户改为升级）**：上游 3.9.9 仍是最新、镜像摘要未变，故用 `stack/ditto-ui/Dockerfile`（`FROM ditto-ui:3.9.9` + `apk upgrade`，以 root 升级后切回用户 101）构建 `phm-ditto-ui:3.9.9-apk`；Grype Critical/High 16/63 → **0/10**（剩余 10 个 High 是 openssl 3.5.9-r1，Alpine 尚无修复）；UI 静态文件与原版逐字节一致，隔离容器内页面 200。compose 已改为该镜像；2026-11-25 用户确认后在线只重建 ditto-ui（`up -d --no-deps ditto-ui`），经 nginx 访问 `/ui/` 和 `dist/main.js` 均 200、`/api/2` 正常，无需重启 nginx。回退：compose 中 ditto-ui 改回 `eclipse/ditto-ui:3.9.9` 后同样只重建该容器。离线包：`bundle.sh` 联网从锁定的基础镜像摘要构建 `phm-ditto-ui:3.9.9-apk-offline` 并打入包（`install.sh --rebuild` 不重建它，需 Alpine 源）；2026-11-25 重建 `opentwins-phm-offline-20261125-48b55dd-x86_64.tar`（1.9 GB，15 个镜像），`offline-proof.sh --rebuild` 断网隔离安装通过（新增 UI 检查：HTTP 200，镜像为修补版）。

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
