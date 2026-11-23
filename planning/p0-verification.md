# P0 核查报告（2026-11-22）

数据来源：GitHub API（star、最近推送、6 个月提交数、许可证、release）+ 网络检索。数字是核查当日的快照。

## 1. 结论摘要

| # | 结论 | 影响 |
|---|---|---|
| 1 | OpenTwins v1 主仓库近 6 个月仅 2 次提交（均为文档），核心贡献者 2 人，无 GitHub release | 不能把 OpenTwins 当作"平台"依赖，只当作**参考集成方案 + 两个插件** |
| 2 | ERTIS 正在开发 OpenTwins v2（WoT + Dgraph + Redpanda + TimescaleDB + Dapr），官方声明 WIP、无前端、不可用于生产 | v1 是唯一可用版本，但已非主力方向；架构需与 OpenTwins 解耦 |
| 3 | Type/Composition 能力实际在 `extended-api-for-eclipse-ditto`（无 LICENSE 文件，镜像 tag 为 `latest`）和 `grafana-app-opentwins`（Apache-2.0）中 | **法律风险**：无许可证 = 默认保留所有权利；核电交付不可接受，需向作者确认或替代 |
| 4 | Eclipse Ditto 非常活跃（3.9.9，2026-11-19），OpenTwins chart 仍锁在 Ditto 3.3.7 | 直接用 Ditto 官方 compose + 新版本，不跟 OpenTwins chart |
| 5 | OpenTwins chart 依赖 `bitnamilegacy/mongodb` 镜像 | 换成官方 `mongo` 镜像 |
| 6 | InfluxDB 3 Core 默认查询窗口约 72 小时（基于 Parquet 文件数上限，可调） | PHM 需要月级趋势 → 底座用 **InfluxDB 2.x**（仍在维护，2.10.1 @ 2026-11-17） |
| 7 | Telegraf 磁盘缓冲（`buffer_strategy = "disk"`）自 1.32 起提供，至今仍标为 experimental，且**不限制磁盘占用** | 可用于演示断网续传；需加磁盘监控，核电场景要单独评估 |
| 8 | OpenPMX：个人项目（1 名贡献者，5 star，2026-04 起，LICENSE 未被 GitHub 识别） | **不采用**为核心组件，可作为 UI 参考 |
| 9 | CMMS：Atlas CMMS（Grashjs/cmms，AGPL-3.0，873 star，v1.9.0 @ 2026-09）活跃；openMAINT（AGPL，2.4，SourceForge 分发，源码可见性有争议） | 首选 Atlas CMMS，P3 再接入 |
| 10 | ProgPy 活跃（v1.9.0 @ 2026-10-23），许可证 NASA Open Source Agreement（NOSA），非 GPL 兼容 | 可用；NOSA 条款需法务过目 |
| 11 | MuJoCo Menagerie 有 `unitree_g1`、`franka_emika_panda`、`agilex_piper` | 三台都有现成仿真模型；**Piper 模型是标准 PiPER，非 PiPER-X**，运动学差异需确认 |
| 12 | franka_ros2 当前分支基于 ROS 2 Jazzy，示例全部针对 FR3 | 你的 Panda（FER）需先查**机器人系统版本**，按 libfranka 兼容矩阵选版本，可能需要旧版 franka_ros2 或直接用 libfranka |
| 13 | piper_sdk：固件 ≥ 1.8-8 需使用 `C_PiperInterface_V3`；第三方文档提示 PiPER-X 兼容性需单独确认 | 先读出 PiperX 的固件版本 |

## 2. 组件健康度与许可证

| 组件 | 最近推送 | 版本 | 许可证 | 备注 |
|---|---|---|---|---|
| eclipse-ditto/ditto | 2026-11-22 | 3.9.9 | EPL-2.0 | 6 个月内 ≥100 次提交 |
| ertis-research/opentwins | 2026-11-17 | chart 0.6.5 | Apache-2.0 | 主要是文档 |
| ertis-research/grafana-app-opentwins | 2026-04-15 | 面向 Grafana 12 | Apache-2.0 | `grafanaDependency >=10.0.0` |
| ertis-research/extended-api-for-eclipse-ditto | 2026-05-04 | `latest` | **无** | 风险项 |
| ertis-research/kafka-ml | 2026-11-04 | — | MIT | 暂不使用 |
| eclipse-hono/hono | 2026-11-10 | — | EPL-2.0 | 暂不使用 |
| influxdata/influxdb | 2026-11-20 | 2.10.1 / 3.12.2 | Apache-2.0/MIT | 选 2.x |
| influxdata/telegraf | 2026-11-20 | 1.40.3 | MIT | |
| grafana/grafana | 2026-11-22 | 13.3.1 | **AGPL-3.0** | 插件仅在 12 上验证过 |
| eclipse-mosquitto | 2026-11-19 | 2.x | EPL-2.0 / EDL-1.0 | |
| nasa/progpy | 2026-10-23 | 1.9.0 | NOSA | |
| yzhao062/pyod | 2026-11-22 | 3.6.9 | BSD-2 | |
| Grashjs/cmms (Atlas) | 2026-11-21 | 1.9.0 | **AGPL-3.0** | |
| ika-rwth-aachen/mqtt_client | 2026-11-11 | — | MIT | ROS 2 ↔ MQTT |
| open62541 | 2026-11-22 | — | MPL-2.0 | |
| FreeOpcUa/opcua-asyncio | 2026-11-18 | — | LGPL-3.0 | P4 用于 OPC UA 模拟 |
| unitree_sdk2 / unitree_ros2 | 2026-11-19 / 07-02 | — | BSD-3 | sdk2 自带 g1 示例 |
| frankarobotics/libfranka / franka_ros2 | 2026-09 / 10 | — | Apache-2.0 | 见结论 12 |
| agilexrobotics/piper_sdk | 2026-10-14 | — | MIT | 见结论 13 |
| mujoco_menagerie | 2026-11-10 | — | 每个模型单独许可 | Piper MIT，Panda Apache-2.0，G1 为 Unitree 版权声明 |

AGPL 说明：内部使用、不修改分发时无额外义务；若将修改版作为网络服务提供给第三方，需开放修改。核电交付前需要法务结论。

## 3. docker-compose 服务清单（草案）

| 服务 | 镜像/来源 | 阶段 | 说明 |
|---|---|---|---|
| mosquitto | eclipse-mosquitto:2 | P1 | 边缘 → 中心的 MQTT 入口 |
| ditto（gateway/policies/things/things-search/connectivity/nginx/ui） | Ditto 官方 `deployment/docker` compose，3.9.x | P1 | 孪生状态（1–10 Hz） |
| mongodb | 官方 mongo 镜像 | P1 | Ditto 存储 |
| influxdb | influxdb:2.x | P1 | 高频原始数据 + 特征 |
| telegraf | telegraf:1.40 | P1 | mqtt_consumer → influxdb，死区/降采样 |
| grafana | grafana:12.x（先锁 12，验证 13） | P1 | + grafana-app-opentwins 插件 |
| ditto-extended-api | ertis/ditto-extended-api（锁定 digest） | P2 | Type/Composition；许可证未决 |
| phm-worker | 自建镜像：ProgPy + PyOD | P3 | 胶水 |
| event-frame | 自建 | P3 | 胶水；存储待定（见下） |
| atlas-cmms + postgres | Grashjs/cmms | P3 | 工单 |
| opcua-sim | opcua-asyncio | P4 | 虚拟核电资产 |

不纳入：Hono（Ditto connectivity 直连 MQTT 已足够）、Kafka/Zookeeper/RabbitMQ（只有用 Kafka-ML 时才需要）。

边缘侧（各机器人旁的工控机，不在中心 compose 中）：unitree_sdk2 / libfranka / piper_sdk 适配器 + ros2 mqtt_client。

## 4. 需要决策 / 跟进的事项

1. **extended-api 许可证**：联系 ERTIS 请求补充许可证；否则只用 Ditto 原生能力（Thing + definition + 属性引用）重新表达 Type/Composition，Grafana 侧只保留 Apache-2.0 的插件部分。
2. ~~对 OpenTwins 的依赖程度~~ **已决定（2026-11-22）**：主干为 Ditto + InfluxDB + Grafana；OpenTwins 只复用概念（Type/Composition）和 Apache-2.0 插件，平台层不依赖。
3. **Event Frame 存储**：放在 InfluxDB（事件 measurement + Grafana 注解）还是 Atlas CMMS 自带的 Postgres。
4. **现场信息**（需要你在真机上确认）：
   - Franka：机器人系统版本（Desk → Settings 中查看），是 Panda/FER 还是 FR3
   - PiperX：固件版本（`GetPiperFirmwareVersion()`），以及是否为 PiPER-X 型号
   - ~~G1：型号（23/29 自由度）、固件版本、是否 EDU 版~~ **已确认（2026-11-23）**：G1 **29 自由度**（真机探测 29 个电机在线，用户确认；最初按 23 自由度登记有误），定为 P1 首台真机。主控固件版本无法经 DDS 读取（`LowState.version=[0,0]`），需在宇树 App 中查看；BMS 固件为 1.3
