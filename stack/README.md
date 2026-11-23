# PHM reference stack — P1

Central services of the digital-twin / PHM reference architecture (see `../planning/`).
All components are unmodified upstream images; this directory only holds configuration.

| Service | Image | Host port | Role |
|---|---|---|---|
| mosquitto | eclipse-mosquitto 2.1.4 | `0.0.0.0:11883` | edge → centre MQTT (auth + ACL) |
| Ditto (policies, things, things-search, connectivity, gateway, ui) + mongodb | eclipse/ditto 3.9.9, mongo 7.0.48 | — | twin state, WoT Type validation |
| nginx | nginx 1.30.7 | `127.0.0.1:18080` | Ditto API/UI (`/api`, `/ui/`) + Type library (`/models/`) |
| influxdb | influxdb 2.10.1 | `127.0.0.1:18086` | raw high-rate history (bucket `raw`) |
| telegraf | telegraf 1.40.3 | — | MQTT → InfluxDB, memory buffer |
| grafana | grafana 12.4.9 | `127.0.0.1:13000` | dashboards (folder *PHM*) |
| phm-worker (project `phm-analytics`) | built from `phm/` (python 3.11, progpy 1.9.0, pyod 3.6.9) | — | P3 PHM assessment every 120 s → Ditto `phm` |

## Run

```bash
./scripts/init-env.sh        # once: .env with random secrets, nginx/mosquitto credential files
docker-compose up -d
./scripts/provision.sh       # Ditto connection + policies + Things from connections/ and things/
./scripts/smoke-test.sh      # publishes fake Panda data, checks Ditto + InfluxDB
cd phm && docker-compose -p phm-analytics --env-file ../.env up -d --build   # PHM worker (-p is required: .env sets COMPOSE_PROJECT_NAME=phm)
```

InfluxDB measurements in bucket `raw`: `telemetry` (edge raw), `phm` (PHM results per feature), `event_frame` (abnormal episodes, `phase`=start/end).

Credentials are in `.env` (git-ignored): Ditto `DITTO_USER` (default `admin`) / `DITTO_USER_PASSWORD`, Grafana `admin` / `GRAFANA_ADMIN_PASSWORD`.

## Edge contract (what an adapter must publish)

MQTT user `edge`, password `MQTT_EDGE_PASSWORD`.

| Topic | Payload | Rate | Consumer |
|---|---|---|---|
| `phm/raw/<thing_id>/<feature_id>` | `{"samples":[{"ts":<unix µs>,"<tm property>":<number>,...}]}` | batched high-rate | Telegraf → InfluxDB `telemetry`, tags `thing_id`, `feature_id` |
| `phm/state/<thing_id>` | Ditto Protocol `merge` on `/features` with `content-type: application/merge-patch+json`, `response-required: false` | 1–10 Hz | Ditto connection `phm-mqtt-ingest` |

Field names = WoT Thing Model property names; IDs = Ditto IDs. Ditto rejects a state message whose
Thing ID differs from the topic (connection enforcement) and any value violating the Thing Model.

## Type library

`type-library/` is served at `http://phm-models/models/...` inside the network and referenced from
Thing/Feature `definition`s. Ditto generates the Thing skeleton from the asset TM's `tm:submodel`s and
validates every write. Ditto blocks Thing Model downloads from private addresses by default; the
`things` service allow-lists only `phm-models`.

## Glue code register

| File | Lines | Purpose |
|---|---|---|
| `scripts/init-env.sh` | 31 | generate secrets and credential files |
| `scripts/provision.sh` | 40 | PUT declarative JSON to the Ditto API |
| `scripts/smoke-test.sh` | 27 | end-to-end check |
| `adapters/systemd/g1-adapter.service` | 15 | user unit for the adapter on the G1 jump host (config, not code) |
| `adapters/g1_dds_mqtt.py` | 161 | G1 29-DoF DDS (`rt/lowstate`, `bmsstate`) → MQTT; subscribe-only. Run on the G1 jump host: `PYTHONPATH=<dir with paho> python g1_dds_mqtt.py --iface enp6s0 --mqtt-host <DGX>`; needs `MQTT_EDGE_PASSWORD` |
| `phm/phm_worker.py` | 244 | P3 PHM worker: InfluxDB 30 s aggregates → PyOD ECOD `anomalyScore` + ProgPy thermal `rulHours` → Ditto `phm` (HTTP merge patch), InfluxDB `phm` and `event_frame`, Ditto `conditionChanged` event; marks joints without fresh data `stale`; `phm_worker.py <ISO time>...` replays history read-only. See `../planning/p3-phm.md` |
| `phm/thermal_model.py` | 73 | ProgPy `PrognosticsModel`: first-order joint thermal model, parameter fit, time to `maxTemperature` |
| `phm/Dockerfile`, `phm/docker-compose.yml` | 34 | worker image and its own compose project `phm-analytics` (config, not code) |
| `adapters/panda_franka_mqtt.py` | 208 | Franka Panda/FR3 libfranka `RobotState` (`read_once()` loop, ~1 kHz) → MQTT; read-only, never commands motion. `--backend pylibfranka` (FR3, system ≥ 5), `panda_py` (Panda, system 4.x), `fake` (offline test). `python panda_franka_mqtt.py --backend <b> --robot-ip <FCI ip> --mqtt-host <DGX>`; needs `MQTT_EDGE_PASSWORD`. Not yet run on the real robot |
| `adapters/piperx_can_mqtt.py` | 204 | AgileX PiPER / PiPER X `piper_sdk` (SocketCAN) feedback → MQTT; read-only, never sends enable/mode/motion frames. `--backend sdk --sdk-version V3` (firmware ≥ 1.8-8; else V2) or `fake`. `python piperx_can_mqtt.py --can can0 --mqtt-host <DGX>`; needs `MQTT_EDGE_PASSWORD`. Not yet run on the real arm |
| `plant-sim/pump_set_opcua_sim.py` | 190 | P4: asyncua (FreeOpcUa) OPC UA server simulating a motor-pump set with injectable DE-bearing wear; stands in for a plant PLC/DCS. Not part of the twin path |
| `plant-sim/telegraf-opcua.conf` | 206 | P4: OPC UA → edge contract with Telegraf `inputs.opcua` + `outputs.mqtt` (JSONata payloads); config, not code. This is the whole OPC UA "adapter" |
| `plant-sim/docker-compose.yml`, `Dockerfile.*` | 40 | P4: separate compose project `phm-plant` on network `phm_default`; configs baked into images |

## P4 plant simulation (OPC UA pump set)

```bash
cd plant-sim && docker-compose -p phm-plant --env-file ../.env up -d --build   # own project; core stack untouched
```

- `pump-sim`: OPC UA server `opc.tcp://<host>:14840/plant-sim/` (bound to `PHM_BIND`), namespace `urn:opentwins:plant-sim`,
  nodes `PumpSet01.{Motor,BearingDE,BearingNDE,Pump,Controller,Alarms,Sim}.*`, security None (lab only).
- Degradation: `PumpSet01.Sim.BearingWear` (0–1, writable) grows at `Sim.BearingWearRate` (default 0.5 per hour,
  env `SIM_BEARING_WEAR_RATE`; `SIM_TIME_SCALE` speeds up simulated time); at 1 the bearing is "replaced" (`Sim.AutoReplace`).
  Write `BearingWear` from any OPC UA client to inject a fault; alarm bits go to `motor.faultCode`, names to `controller.faultCodes`.
- `telegraf-opcua`: 10 Hz raw → `phm/raw/plant.sim:pump-set-01/<feature>`, 1 Hz state → `phm/state/...` (as user `edge`).
- Twin: `things/plant.sim_pump-set-01.json` (asset TM `motor-pump-set`); Grafana dashboard *Pump Set (OPC UA, P4)*.

## Known limits (P1)

- Telegraf uses a memory buffer (3M metrics ≈ 100 s of one G1 at ~30k metrics/s): a longer InfluxDB outage, or a Telegraf restart, loses raw samples. The disk buffer cannot sustain G1 rates (it made Telegraf stall and mosquitto drop ~75% of the raw stream), so do not switch back to it; the `telegraf-buffer` volume is now unused. Size `metric_buffer_limit` up when more robots are added.
- Panda gripper is not modelled; the Panda adapter is only tested with `--backend fake` (no robot access yet).
- MQTT ACLs are configured but not covered by the smoke test (MQTT 3.1.1 silently drops denied publishes).
