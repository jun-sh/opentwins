# P3 PHM 链路（G1，2026-11-23）

## 数据流

```
InfluxDB raw/telemetry ──(任务 phm-downsample-30s, 每分钟)──▶ phm_agg/telemetry_30s ──(6 h 窗口)──▶ phm-worker（每 120 s）
   ├─ PyOD ECOD   → anomalyScore（最近 5 min 平均分 / 训练阈值；1 = 1% 污染率阈值；训练集：滑动 6 h，或固定健康基线）
   ├─ 漂移 → driftSigma（最近 5 min 各信号中位数偏离同一基线中位数的倍数，以基线标准差为单位，取最大；温度只计升高）
   ├─ ProgPy JointThermal → rulHours（到 maxTemperature 的时间，上限 24 h）+ 热裕度
   ├─ healthIndex = min(热裕度, 1 − max(0, anomalyScore−1)/2, 1 − driftSigma/20)
   └─ condition：fault（faultCode≠0 或 T≥Tmax）/ alert（RUL<1 h 或 score≥2 或 drift≥10）/ watch（RUL<8 h 或 score≥1）/ normal
        │
        ├─▶ Ditto：HTTP PATCH /api/2/things/<id>/features（merge-patch，只写 phm 分组 + lastAssessedAt + modelRef）
        ├─▶ InfluxDB phm_agg/phm（供 Grafana 画趋势）
        └─▶ Event Frame（condition 离开/回到 normal 时）
              ├─ InfluxDB phm_agg/event_frame：phase=start|end，condition，reason，durationS（end）
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
- 滑动基线（G1）：训练集是最近 6 h，工况一变分数就升高，缓慢退化会被学进基线而检不出；固定基线只适合重复节拍的工况（见下节）。
- ECOD 分数在远超基线的数据上饱和（PiperX joint2 约 1.2），到不了 alert 的 2.0：异常分数只回答"是否偏离"，严重程度由 `driftSigma` 分级（见下文「严重度分级」）。`driftSigma` 只写 InfluxDB（TM 没有这个属性，加属性要升 TM 版本），Ditto 里通过 `condition`、事件 `reason` 和 `healthIndex` 体现。
- Telegraf 只入库 20–30% 原始样本（见 HANDOFF §6），对 30 s 聚合影响不大。
- **无新数据（离线）**：关节超过 10 min（`PHM_STALE_S`）没有数据时不评估，不崩溃也不写假值：Ditto 保留上一次的 `healthIndex/anomalyScore/condition`（`lastAssessedAt` 显示其时间），`rulHours` 改为 -1（TM 定义的"未估计"），InfluxDB `phm` 写 `condition="stale"`、`conditionLevel=-1`。TM 的 `condition` 枚举没有 `unknown`/`stale`，要在 Ditto 里显式表示需给 `monitored-component` TM 升版本加枚举值（核心改动，待决定）。

## 检出验证（2026-11-26，PiperX 仿真磨损）

- 场景：MuJoCo 仿真 PiperX，`--sim-wear joint2=0.5`（joint2 阻尼和摩擦每小时 +0.5），其余 5 个关节不加磨损作为对照。仿真从 2026-11-24 11:49 UTC 开始连续运行 47 h；joint2 绕组温度 52 → 91 °C。
- 方法：用 worker 自身代码离线回放（只读），每 10 min 评估一次，统计首次报警时间和误报。脚本：会话临时目录 `replay_eval.py`（monkeypatch `classify` 收集结果，不进仓库）。

| 配置 | joint2 首次 watch | 5 个对照关节误报 | joint2 事件数 | joint2 分数 p50 / max |
|---|---|---|---|---|
| 原版：滑动 6 h 基线、无防抖（线上 47 h 实际记录） | 无趋势，分数在 1.0 附近来回 | 0 | **82 次开关** | ~0.9 / 1.06 |
| 滑动基线 + 防抖 | +7.3 h（压线，靠保持阈值 0.8 维持） | 0 | 1 | 0.84 / 1.02 |
| **固定基线 + 防抖（已上线）** | **+3.5 h**（基线结束后 1.5 h；此时阻尼仅 +1.75） | **0** | 1，持续保持 | 1.17 / 1.22 |

- 三种配置的 `fault` 都在 +14.5 h（仿真驱动器在绕组 > 70 °C 时置 `motor_overheating`）。热 RUL 没有提前量：稳态温度低于 `maxTemperature` 时一直是上限 24 h，超过后几小时内降到 0；`healthIndex`（热裕度）从 0.6 平滑降到 0，是最好的趋势指标。
- 改动：`PHM_FIXED_BASELINE`（重复节拍的机器人：Panda、PiperX）用固定健康时段 `PHM_BASELINE_S`（2 h）训练 ECOD，起点取 InfluxDB `phm_agg/phm_baseline` 最新一条（`from` = Unix 秒；缺失时取该机器人第一条聚合数据 + 60 s 并写入）。防抖：连续 2 个周期越线才升级，低于 `PHM_CLEAR_RATIO`（0.8）× 阈值才解除。G1 动作不固定，仍用滑动基线。
- **维修 / 换件后重设基线**：写一条新的 `phm_baseline`（`from` = 维修后的健康时刻），然后重启 worker：
  `printf 'phm_baseline,thing_id=lab.robots:piperx-001 from=%s %s\n' $(date +%s) $(date +%s) | curl -H "Authorization: Token $INFLUX_TOKEN" "http://127.0.0.1:18086/api/v2/write?org=phm&bucket=phm_agg&precision=s" --data-binary @-`
- 当前基线：PiperX 2026-11-24 11:51:15 UTC；Panda 2026-11-26 15:22:10 UTC（Panda 没有 11-24 的聚合数据；它没有磨损，任何时段都健康）。
- 仿真磨损现在按 UTC 墙钟 24 h 周期（`--sim-wear-cycle-h 24`）：每天 00:00 UTC 归零（相当于检修），重启不清零；joint2 约 +3.5 h 进入 watch、约 +14.5 h fault，每天重复一次，可持续观察。
- 未覆盖：真机数据；多种磨损形态（只有阻尼/摩擦线性增长）；Panda 的误报只在线上观察（回放时 Panda 只有 7 h 聚合数据）。

## Atlas CMMS 评估（未部署）

- 仓库 Grashjs/cmms，最新 v1.9.0；**AGPL-3.0**（另有商业许可证，白标和高级功能需要 `LICENSE_KEY`）。
- 组成：postgres 16、api（Spring Boot，`intelloop/atlas-cmms-backend`）、frontend、MinIO 兼容存储（compose 用的是 `pgsty/silo` 镜像，不是官方 minio）、nginx，共 5 个容器；需要 `JWT_SECRET_KEY` 等密钥，首次使用要注册管理员账号。
- 认证是 JWT；有对外 webhook（工单/请求状态变化），README 没提 MQTT/IoT，"meter trigger 自动建工单"未在文档中确认。
- **不部署的原因**：5 个容器（含非官方对象存储镜像）、要建账号，比本阶段其他部分都重；另外 AGPL 和 Grafana 一样需要交付前法务意见。
- **工单触发方案（建议，零代码）**：Ditto connectivity 新建一个 HTTP-push 连接，目标为 Atlas API 的"创建工单/请求"端点，`topics: _/_/things/live/messages`，用 Ditto 的 payload mapping（JavaScript）把 `conditionChanged` 且 `to ∈ {alert, fault}` 的消息转换成工单 JSON（标题 = `<thing>/<feature> <condition>`，描述 = reason + Grafana 链接），`Authorization: Bearer <JWT>` 放在目标 header。工单号可以写回 `phm` 之外的属性用于去重（需在 TM 里加可选字段）。Atlas 工单状态变化可以反向用 webhook 推给 Ditto HTTP API。**具体端点路径和请求体未经源码确认**，部署时先看运行实例的 OpenAPI 文档。

## 严重度分级（2026-11-27）

- 问题：ECOD 用尾部概率打分，最近窗口完全落在基线分布之外后概率到底，分数停在约 1.2，磨损再重也只报 watch；fault 来自仿真器的过温标志，不是 PHM 自己的判断。
- 做法：`driftSigma` = 最近 5 min 每个信号的中位数相对基线中位数偏离几个基线标准差，取所有信号的最大值，并记录是哪个信号。温度只计升高（冷启动降温不算磨损）；标准差下限为 max(1% × |中位数|, 0.001)，防止近似常数的信号把值放大。基线与 ECOD 相同（固定基线机器人用固定时段，G1 用滑动 6 h）。`PHM_ALERT_DRIFT`（默认 10）触发 alert，防抖规则与分数相同（连续 2 个周期越线，低于 0.8 × 阈值解除）；`PHM_WATCH_DRIFT` 默认关闭（inf）。
- 标定（11-24 14:00 → 11-27 10:50 回放，每 10 min）：

| 关节 | driftSigma 最大值 | 状态 |
|---|---|---|
| Panda 7 个关节（无磨损） | 0.7–1.4 | 全部 normal |
| PiperX 5 个对照关节 | 2.0–3.8（仿真适配器重启时温度瞬变；温度不单向计算时为 5.9） | 全部 normal |
| PiperX joint2（磨损） | 30.1 | watch → alert（11-24 23:20，windingTemperature 10.7σ）→ fault（11-25 02:20） |

- 每天的磨损周期（00:00 UTC 归零）：watch 约 03:00（ECOD），alert 约 11:00（drift ≥ 10），fault 约 14:30（仿真过温标志），alert 比 fault 早约 3.5 h。阈值 10 约为对照关节最大值的 2.6 倍。
- Grafana：`PHM Fleet Overview` 和 `PHM Health per Robot` 各加一个 driftSigma 曲线面板（阈值线 10）。
- 局限：阈值只在一种仿真磨损上标定；真机的工况变化（换任务、负载变化）也会推高漂移，固定基线机器人换工况后要重设基线。
