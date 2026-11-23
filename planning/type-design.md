# 组合孪生 Type 设计（基于 Ditto 原生 WoT）— 草案 v0.1（2026-11-22）

## 1. 决策：Type = W3C WoT Thing Model（TM），由 Ditto 原生解析

依据：Ditto 官方文档 `basic-wot-integration.md`（Ditto 主分支，核查于 2026-11-22）。

- Ditto 2.4 引入 WoT 集成，3.0 起默认开启。
- `definition` 字段可以填 TM 的 HTTP(S) URL；Thing 和 Feature 两级都可以。
- 支持 `tm:extends`（继承）、`tm:ref`（导入）、`tm:submodel`（组合，映射为 Feature，Feature ID 取 `instanceName`）。
- 创建 Thing 时按 TM 自动生成骨架。
- **3.6 起默认按 TM 校验所有写入**；可以配置为强制、禁止或只记录警告。修改 definition 会触发重新校验，可以借此做模型版本演进。
- 支持 `tm:optional`、Ditto 扩展本体 `ditto:category`（属性分组）和 `ditto:deprecationNotice`（弃用说明）。
- 能自动生成 Thing Description（TD）；3.9 起，生成的 TD 按调用者的访问权限裁剪。

由此带来的结果：
- 不需要 `extended-api-for-eclipse-ditto`，P0 里的许可证风险随之消除。
- Type 是 **W3C 标准格式**，与 OpenTwins v2（WoT）的方向一致，也能与 Azure DTDL 一一对照。
- Type 库本身就是一组 `.tm.jsonld` 文件，用 git 管理，由 compose 里的静态 HTTP 服务提供。离线部署也可以用。

## 2. 对标映射

| 概念 | 本架构（WoT TM on Ditto） | Azure DTDL / ADT | ThingWorx | OpenTwins v1 | PI AF |
|---|---|---|---|---|---|
| 类型 | Thing Model | Interface | Thing Template / Shape | Type | Element Template |
| 继承 | `tm:extends` | `extends` | Template 继承 | — | 模板继承 |
| 组合 | `tm:submodel` → Feature | Component | Thing Shape | Composition | 子元素 |
| 属性 | properties（Feature 属性） | Property / Telemetry | Property | Feature property | Attribute |
| 命令/事件 | actions / events → Ditto messages | Command | Service / Event | — | — |
| 关系（跨 Thing） | **约定**：attributes + RQL 搜索（见 §6） | Relationship | Network | `_parents` | 层级 + 引用 |
| 实例 | Ditto Thing | Digital twin | Thing | Twin | Element |

## 3. 三层模型

```
L3 层级 Thing     site / area / cell（仅 attributes，ISA-95 路径）
        │ attributes.parentId
L2 资产 Thing     g1-001 / panda-001 / piperx-001 / pump-set-01   ← definition = 资产 TM
        │ tm:submodel（每个部件实例一个 Feature）
L1 部件 Feature   joint_* / battery / controller / bearing_de     ← definition = 部件 TM
        │ tm:extends
L0 基类           monitored-component（PHM 通用属性）
```

复用发生在 L0/L1：所有部件都继承同一个 PHM 基类，同一种部件 TM 在机器人和核电资产之间复用。L2 只是"清单"：列出由哪些部件组成。

## 4. Type 库清单

| TM 文件 | 层 | 关键属性 | 首个使用者 |
|---|---|---|---|
| `base/monitored-component-1.0.0` | L0 | `phm` 分组：`healthIndex`（0–1）、`anomalyScore`、`rulHours`、`condition`（normal/watch/alert/fault）、`lastAssessedAt`、`modelRef`；event `conditionChanged` | 所有部件 |
| `component/rotating-actuator-1.0.0` | L1 | status：`position`、`velocity`、`torque`、`motorPosition`、`current`、`busVoltage`、`windingTemperature`、`driverTemperature`、`faultCode`；configuration：`gearRatio`、`ratedTorque`、`maxTemperature` | 三台机器人的关节、核电泵电机、阀门电动执行机构 |
| `component/battery-pack-1.0.0` | L1 | `soc`、`voltage`、`current`、`temperature`、`cycleCount`、`soh` | G1 |
| `component/controller-1.0.0` | L1 | `cpuTemperature`、`cpuLoad`、`commLatencyMs`、`faultCodes`、`firmwareVersion` | 三台机器人 |
| `component/bearing-1.0.0` | L1 | `vibrationRms`、`vibrationPeak`、`temperature`；configuration：bearing geometry | 核电泵（P4） |
| `component/centrifugal-pump-1.0.0` | L1 | `flow`、`suctionPressure`、`dischargePressure` | 核电泵（P4），**P4 唯一新增的部件 TM** |
| `asset/humanoid-unitree-g1-29dof-1.0.0` | L2 | 29 个关节 + battery + controller | G1 29 自由度（P1 首台） |
| `asset/arm-franka-panda-1.0.0` | L2 | 7 个关节 + controller (+ gripper) | Panda |
| `asset/arm-agilex-piperx-1.0.0` | L2 | 6 个关节 + gripper + controller | PiperX |
| `asset/motor-pump-set-1.0.0` | L2 | motor + 2 × bearing + pump | 核电虚拟资产 |
| `asset/asset-group-1.0.0` | L3 | `isa95Level`、`isa95Path` | 层级节点 |

厂商差异全部通过 `tm:optional` 表达，不派生"G1 关节""Franka 关节"这样的子类。只有当某个厂商有**额外**属性时，才用 `tm:extends` 加一层。

## 5. 信号覆盖矩阵（RotatingActuator，已对照 SDK 源码核查）

| 属性 | G1（unitree_hg `MotorState`） | Panda（libfranka `RobotState`） | PiperX（piper_sdk 反馈） | 核电泵电机（P4） |
|---|---|---|---|---|
| position | `q` | `q` | 高速反馈 | — |
| velocity | `dq` | `dq` | 高速反馈 | 转速 |
| torque | `tau_est` | `tau_J`（关节力矩传感器） | — | 可选 |
| motorPosition | — | `theta` | — | — |
| current | — | — | 高速反馈电流 / `bus_current` | 定子电流 |
| busVoltage | `vol` | — | `vol` | — |
| windingTemperature | `temperature[0..1]`* | — | `motor_temp` | 绕组温度 |
| driverTemperature | — | — | `foc_temp` | — |
| faultCode | `motorstate` | `joint_collision`, 错误标志 | `foc_status` 各标志位 | 报警点 |

\* G1 的两个温度通道具体含义待真机确认。PiperX 高速反馈的字段名在 P1 时逐个核对。

**各台机器人现成可做的 PHM 特征**（直接来自上表，不需要新算法）：
- G1：绕组温度 → ProgPy 热模型、RUL。
- Panda：`theta - q`（电机侧与连杆侧位置差）→ 关节弹性和减速器磨损指标；外力估计残差。
- PiperX：电流 × 温度 → 过载趋势；驱动器故障标志统计。
- 核电泵：电流、振动、温度 → APR / AAKR 异常检测。

## 6. 约定（全部为配置，不写代码）

- **Thing ID**：`<namespace>:<asset>`，例如 `lab.robots:g1-001`、`plant.sim:pump-set-01`。
- **Feature ID** = 关节名，**直接取 MuJoCo Menagerie / URDF 中的关节名**。孪生、3D 和仿真共用这唯一的命名来源。
- **单位**：SI，在 TM 的 `unit` 字段声明。
- **速率分层**：Feature 属性只存 1–10 Hz 的状态和 PHM 结果。原始高频数据进 InfluxDB，tag 用 `thing_id` 和 `feature_id`，与 Ditto 完全同名，这就是 PI AF 那种"把时序数据挂到资产上"的上下文化。
- **层级/关系**：attributes 里放 `parentId`、`isa95Path`，用 Ditto 搜索 RQL 查询，例如 `like(attributes/isa95Path,"lab/cell-1/*")`。
- **版本**：TM URL 中带 semver。升级时修改 definition，由 Ditto 校验旧数据是否兼容新模型。
- **TM 托管**：compose 中的 nginx 提供 `http://models.local/...`，内容来自 git 仓库 `type-library/`。

## 7. 示例（说明结构，非最终文件）

`component/rotating-actuator-1.0.0.tm.jsonld`（节选）：

```json
{
  "@context": ["https://www.w3.org/2022/wot/td/v1.1",
               {"ditto": "https://ditto.eclipseprojects.io/wot/ditto-extension#"}],
  "@type": "tm:ThingModel",
  "title": "Rotating Actuator",
  "version": {"model": "1.0.0"},
  "links": [{"rel": "tm:extends", "type": "application/tm+json",
             "href": "http://models.local/base/monitored-component-1.0.0.tm.jsonld"}],
  "tm:optional": ["/properties/torque", "/properties/motorPosition", "/properties/current",
                  "/properties/busVoltage", "/properties/windingTemperature",
                  "/properties/driverTemperature"],
  "properties": {
    "position":           {"type": "number", "unit": "rad",   "ditto:category": "status", "readOnly": true},
    "velocity":           {"type": "number", "unit": "rad/s", "ditto:category": "status", "readOnly": true},
    "windingTemperature": {"type": "number", "unit": "Cel",   "ditto:category": "status", "readOnly": true},
    "gearRatio":          {"type": "number",                  "ditto:category": "configuration"}
  }
}
```

`asset/arm-franka-panda-1.0.0.tm.jsonld`（节选）：

```json
{
  "@type": "tm:ThingModel",
  "title": "Franka Panda",
  "links": [
    {"rel": "tm:submodel", "instanceName": "joint1",
     "href": "http://models.local/component/rotating-actuator-1.0.0.tm.jsonld", "type": "application/tm+json"},
    {"rel": "tm:submodel", "instanceName": "controller",
     "href": "http://models.local/component/controller-1.0.0.tm.jsonld", "type": "application/tm+json"}
  ],
  "properties": {
    "serialNumber": {"type": "string"},
    "kinematicModelUri": {"type": "string"},
    "parentId": {"type": "string"},
    "isa95Path": {"type": "string"}
  }
}
```

## 8. 已知限制与处理方式

| 限制 | 处理 |
|---|---|
| 组合只有一层（Thing → Feature），Feature 不能再嵌套 | 深层结构拆成多个 Thing，用 `parentId` 关联。例如"泵组"Thing 下挂"电机"Feature，而不是嵌套三层 |
| Ditto 没有原生关系模型和图查询 | attributes 约定 + RQL；对比 ADT 的 Relationship，这是**明确的差距**，在能力矩阵里如实标注 |
| TM 必须能通过 HTTP 下载 | compose 内置 nginx 托管 |
| `model-placeholders` 不受 Policy 保护 | 不在占位符中放敏感信息；厂商差异用静态 `tm:optional` 表达，不用占位符 |
| `tm:optional` 与校验的交互细节、G1 温度通道含义 | P1 实测 |
| G1 有 29 个关节，资产 TM 较冗长 | 这是声明式配置，可接受；不为它写生成脚本 |

## 9. 胶水代码预估

- Type 库：0 行代码（纯 JSON-LD）。
- 实例化：每台机器人一个 `PUT /things/{id}` 的 JSON 文件，用 curl 提交（0 行代码）。
- 适配器只负责"SDK 字段 → TM 属性名"的映射，各自计入原预算（≤ 300 行/个）。

## 10. 已决定（2026-11-22）

1. 关节名（Feature ID）统一采用 MuJoCo MJCF 中的关节名；厂商 SDK 的索引到名称的映射放在适配器配置里。
   - 补充（2026-11-23）：实验室的 G1 经真机探测确认为 **29 自由度**（DDS `rt/lowstate` 中 0–28 号电机全部在线），用户已确认。关节名直接取 Menagerie `unitree_g1/g1.xml` 的 29 个关节，其顺序与 DDS 电机索引 0–28 一一对应：左右腿各 6、腰 yaw/roll/pitch、左右臂各 7（shoulder pitch/roll/yaw、elbow、wrist roll/pitch/yaw）。索引表见 `unitree_mujoco/unitree_robots/g1/g1_joint_index_dds.md`；额定力矩按电机型号取自 `unitree_ros/robots/g1_description/motor_info.md`。
2. PHM 结果在每次评估后写回 Ditto 的 Feature `phm` 分组，评估周期为分钟级。
3. P4 的核电虚拟资产选"泵—电机—轴承"组合（`asset/motor-pump-set`）。
