# P3 PHM 链路（G1，2026-11-23）

## 数据流

```
InfluxDB raw/telemetry ──(Flux, 30 s 聚合, 6 h 窗口)──▶ phm-worker（每 120 s）
   ├─ PyOD ECOD   → anomalyScore（最近 5 min 平均分 / 训练阈值；1 = 1% 污染率阈值）
   ├─ ProgPy JointThermal → rulHours（到 maxTemperature 的时间，上限 24 h）+ 热裕度
   ├─ healthIndex = min(热裕度, 1 − max(0, anomalyScore−1)/2)
   └─ condition：fault（faultCode≠0 或 T≥Tmax）/ alert（RUL<1 h 或 score≥2）/ watch（RUL<8 h 或 score≥1）/ normal
        │
        ├─▶ Ditto：HTTP PATCH /api/2/things/<id>/features（merge-patch，只写 phm 分组 + lastAssessedAt + modelRef）
        ├─▶ InfluxDB raw/phm（供 Grafana 画趋势）
        └─▶ Event Frame（condition 离开/回到 normal 时）
              ├─ InfluxDB raw/event_frame：phase=start|end，condition，reason，durationS（end）
              └─ Ditto 事件：features/<f>/outbox/messages/conditionChanged（TM 已定义的可选事件）
```

- 代码：`stack/phm/phm_worker.py`、`stack/phm/thermal_model.py`；独立 compose 项目 `phm-analytics`，加入 `phm_default` 网络。
- 部署：`cd stack/phm && docker-compose -p phm-analytics --env-file ../.env up -d --build`。**必须带 `-p`**：`../.env` 里的 `COMPOSE_PROJECT_NAME=phm` 会覆盖 compose 文件的 `name:`，否则会和主服务栈混成一个项目。
- 日志：`docker logs -f phm-analytics-phm-worker-1`（`[fit]` 拟合参数，`[cycle]` 每轮耗时，`[frame]` 状态迁移）。
- 参数都是环境变量（见 `phm_worker.py` 顶部）：周期、窗口、阈值、`PHM_DEFAULT_MAX_TEMP`。
- **历史回放（只读，不写 Ditto/InfluxDB）**：`docker run --rm --network phm_default -e DITTO_USER -e DITTO_USER_PASSWORD -e INFLUX_TOKEN phm-worker:0.1 2026-11-23T09:00:00Z 2026-11-23T10:30:00Z`，按给定时刻依次评估并打印结果和状态迁移。已用 09:00/10:30/11:40 UTC 验证数值随时间变化，用 11:00 UTC（断线期间）验证 29 个关节都判为 stale。

## 设计选择

- **写回 Ditto 用 HTTP API，不用 MQTT `phm/state`**：MQTT 只有 `edge` 账号能写 `phm/state`，中心服务复用边缘凭据不合适；新增 MQTT 账号要改 mosquitto 配置（另一会话负责）。HTTP 走 nginx 的 OWNER 账号，核心改动 0 行。
- **Event Frame = InfluxDB 记录 + Ditto 事件**：InfluxDB 是持久记录（Grafana 注释、重启后恢复未结束的 frame），Ditto `conditionChanged` 是实时通知（给 CMMS 等订阅者），复用 TM 里已有的事件定义。没有引入新组件。
- **phm 历史也写 InfluxDB**：Grafana 没有 Ditto 数据源（Infinity 插件需安装），写一份 `phm` measurement 最简单。
- **Flux 只用 mean/min/max**：这些聚合会下推到存储引擎；`stddev` 不下推，1 kHz 数据上 2 h 窗口超时。多个分支共用一个 `from()` 变量也会阻止下推，所以每个分支单独 `from()`。
- 热模型：一阶集总 `dT/dt = (t_amb + k·τ² − T)/tau`，按关节每小时用 ProgPy `estimate_params` 在最近 2 h 上拟合（有界），`simulate_to_threshold` 求到 `t_max` 的时间；稳态温度低于 `t_max` 时直接报上限 24 h。

## 局限 / 待确认

- **`maxTemperature` 未知**：G1 关节过温限值未查到宇树文档，worker 用占位 80 °C（`PHM_DEFAULT_MAX_TEMP`）。确认后写入孪生 `features/<joint>/properties/configuration/maxTemperature`，worker 自动优先使用。
- 机器人多数时间静止，热模型拟合经常落在边界（tau=60 s、k=50），RUL 基本是上限 24 h；要有带载数据才有意义。
- ECOD 训练集是最近 6 h 的同一关节数据，没有"健康基线"概念；机器人工况一变 anomalyScore 就会升高。
- Telegraf 只入库 20–30% 原始样本（见 HANDOFF §6），对 30 s 聚合影响不大。
- **无新数据（离线）**：关节超过 10 min（`PHM_STALE_S`）没有数据时不评估，不崩溃也不写假值：Ditto 保留上一次的 `healthIndex/anomalyScore/condition`（`lastAssessedAt` 显示其时间），`rulHours` 改为 -1（TM 定义的"未估计"），InfluxDB `phm` 写 `condition="stale"`、`conditionLevel=-1`。TM 的 `condition` 枚举没有 `unknown`/`stale`，要在 Ditto 里显式表示需给 `monitored-component` TM 升版本加枚举值（核心改动，待决定）。

## Atlas CMMS 评估（未部署）

- 仓库 Grashjs/cmms，最新 v1.9.0；**AGPL-3.0**（另有商业许可证，白标和高级功能需要 `LICENSE_KEY`）。
- 组成：postgres 16、api（Spring Boot，`intelloop/atlas-cmms-backend`）、frontend、MinIO 兼容存储（compose 用的是 `pgsty/silo` 镜像，不是官方 minio）、nginx，共 5 个容器；需要 `JWT_SECRET_KEY` 等密钥，首次使用要注册管理员账号。
- 认证是 JWT；有对外 webhook（工单/请求状态变化），README 没提 MQTT/IoT，"meter trigger 自动建工单"未在文档中确认。
- **不部署的原因**：5 个容器（含非官方对象存储镜像）、要建账号，比本阶段其他部分都重；另外 AGPL 和 Grafana 一样需要交付前法务意见。
- **工单触发方案（建议，零代码）**：Ditto connectivity 新建一个 HTTP-push 连接，目标为 Atlas API 的"创建工单/请求"端点，`topics: _/_/things/live/messages`，用 Ditto 的 payload mapping（JavaScript）把 `conditionChanged` 且 `to ∈ {alert, fault}` 的消息转换成工单 JSON（标题 = `<thing>/<feature> <condition>`，描述 = reason + Grafana 链接），`Authorization: Bearer <JWT>` 放在目标 header。工单号可以写回 `phm` 之外的属性用于去重（需在 TM 里加可选字段）。Atlas 工单状态变化可以反向用 webhook 推给 Ditto HTTP API。**具体端点路径和请求体未经源码确认**，部署时先看运行实例的 OpenAPI 文档。
