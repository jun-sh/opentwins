# 交接文档（更新于 2026-11-23，P2 Panda 适配器）

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
| P2 Type 复用 | 🟡 Panda 适配器 `stack/adapters/panda_franka_mqtt.py` 已写好，fake 后端端到端通过（核心代码改动 0 行），**真机未跑**（无访问方式）；PiperX ⬜ |
| P3 PHM 链路 | ⬜ ProgPy/PyOD → 写回 `phm`；Event Frame；Atlas CMMS |
| P4 核电演示 | 🟡 OPC UA 泵组模拟器 + Telegraf OPC UA→MQTT + 孪生 `plant.sim:pump-set-01` + Grafana 面板 ✅（DGX 上运行，核心代码改动 0 行）；见 §5 P4 |
| P5 加固 | ⬜ 离线部署、SBOM、审计 |

## 4. 当前环境

- 分支 `feat/phm-p1-stack` 已推送到 fork（远程 `fork` = jun-sh/opentwins），PR：https://github.com/jun-sh/opentwins/pull/1（fork 内，base main，未合并）。`origin` 是上游 ertis-research/opentwins，不要推送到那里。服务栈运行在本机 DGX 上（12 个容器，项目名 `phm`）。
- 登录：Grafana http://127.0.0.1:13000，Ditto UI http://127.0.0.1:18080/ui/。两者都用 `admin`，密码在 `stack/.env`（git 忽略）。
- MQTT 供边缘接入：`<DGX>:11883`，用户 `edge`。主题约定见 `stack/README.md`。
- **G1 跳板机**：`ssh server@10.10.61.210`（本机已配好 SSH 密钥，不用密码）。网卡 `enp6s0`（192.168.123.99）直连 G1 内网，G1 的 PC2 是 192.168.123.164。可用的 SDK 解释器：`/home/server/workspace/gr00t_wbc/.venv/bin/python`（含 `unitree_sdk2py`）。**gr00t_wbc 属于他人正在进行的工作，禁止修改其中任何文件**：脚本放在 `/tmp` 或自己的目录，运行时设置 `PYTHONDONTWRITEBYTECODE=1`。
- 已有孪生 `lab.robots:panda-001`（InfluxDB 里有模拟数据）和 `lab.robots:g1-001`（真机实时数据）。模拟器在会话临时目录中，**不在仓库里**，可能已被清理。

## 5. 下一步

G1 29 自由度已打通（见 git log `feat/phm-p1-stack`）：TM、孪生 `lab.robots:g1-001`（31 个 Feature）、适配器 `stack/adapters/g1_dds_mqtt.py`（159 行，已登记）、Grafana 面板 `G1 Thermal & Battery`、跳板机 systemd 常驻服务。

**优先级建议**：① 把分支推送并开 PR；② P2：Panda 真机适配器（验证"核心代码 0 行改动"）；③ P3：用 G1 温度做 ProgPy 热模型、写回 `phm`。

### P2 Panda 适配器状态（2026-11-23）
- `stack/adapters/panda_franka_mqtt.py`（208 行，已登记）：`Robot.read_once()` 循环读 `RobotState`，映射 `q→position`、`dq→velocity`、`tau_J→torque`、`theta→motorPosition`、`tau_ext_hat_filtered→externalTorque`；`faultCode` 位 0 = `joint_collision[i]`、位 1 = `joint_contact[i]`、位 2 = 任一 `current_errors`；`controller.status` 写 `mode`（`kIdle` 等）和 `faultCodes`（激活的错误名）。丢包按 `RobotState.time` 的毫秒跳变统计（每 10 s 打印）。
- 后端：`pylibfranka`（FR3，系统 ≥ 5，libfranka ≥ 0.16，PyPI 轮子 ≥ 0.20.2；无 `server_version()`，`RobotMode` 名无 k 前缀，`Duration` 只有 `to_sec`）、`panda_py`（Panda 系统 4.x，需对应 libfranka 0.9.x 构建）、`fake`（合成数据，离线测试）。绑定差异已在代码里兼容，依据为两个仓库的 pybind 源码，**未在真机验证**。
- 离线验证（fake，DGX 本机，注入 0.2% 丢包）：适配器统计 1000 Hz、丢 0.20%；Ditto `panda-001` 7 个关节 + controller 实时更新；InfluxDB 7 个关节都有 `motorPosition` 等字段，但只入库约 30%（见 §6 Telegraf 丢数）。核心代码（TM、`provision.sh`、Telegraf/Ditto 配置）改动 0 行。
- 真机步骤：① Desk（浏览器打开控制柜 IP）Settings→System 读系统版本，激活 FCI；② 4.x → `--backend panda_py`，≥ 5 → `--backend pylibfranka`（`pip install pylibfranka==<与系统匹配的版本>`）；版本不匹配时连接报错会给出 server version；③ `MQTT_EDGE_PASSWORD=... python panda_franka_mqtt.py --backend <b> --robot-ip <ip> --mqtt-host 10.10.60.128 --duration 60`，记录 `[stats]` 的采样率和丢包；④ 仿照 G1 做 systemd 单元。注意 FCI 同时只允许一个客户端。

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
- **Telegraf 丢原始数据（P1 遗留，2026-11-23 发现）**：mosquitto 日志 "Outgoing messages are being dropped for client telegraf-phm-raw"，Telegraf 每 1–2 分钟 `pingresp not received` 重连；G1 每分钟只入库 1–2 万条/关节（应约 6.2 万），即约 20–30%。修复要改 Telegraf/mosquitto 配置（核心代码），应作为独立任务，不算 P2 适配器改动。
- 未验证：MQTT ACL（smoke test 没覆盖）、Grafana 面板的视觉效果（查询已用 API 验证）、Telegraf 磁盘缓冲的容量上限。
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
