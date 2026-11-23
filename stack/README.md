# PHM reference stack — P1

Central services of the digital-twin / PHM reference architecture (see `../planning/`).
All components are unmodified upstream images; this directory only holds configuration.

| Service | Image | Host port | Role |
|---|---|---|---|
| mosquitto | eclipse-mosquitto 2.1.4 | `0.0.0.0:11883` | edge → centre MQTT (auth + ACL) |
| Ditto (policies, things, things-search, connectivity, gateway, ui) + mongodb | eclipse/ditto 3.9.9, mongo 7.0.48 | — | twin state, WoT Type validation |
| nginx | nginx 1.30.7 | `127.0.0.1:18080` | Ditto API/UI (`/api`, `/ui/`) + Type library (`/models/`) |
| influxdb | influxdb 2.10.1 | `127.0.0.1:18086` | raw high-rate history (bucket `raw`) |
| telegraf | telegraf 1.40.3 | — | MQTT → InfluxDB, disk buffer |
| grafana | grafana 12.4.9 | `127.0.0.1:13000` | dashboards (folder *PHM*) |

## Run

```bash
./scripts/init-env.sh        # once: .env with random secrets, nginx/mosquitto credential files
docker-compose up -d
./scripts/provision.sh       # Ditto connection + policies + Things from connections/ and things/
./scripts/smoke-test.sh      # publishes fake Panda data, checks Ditto + InfluxDB
```

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
| `adapters/g1_dds_mqtt.py` | 154 | G1 29-DoF DDS (`rt/lowstate`, `bmsstate`) → MQTT; subscribe-only. Run on the G1 jump host: `PYTHONPATH=<dir with paho> python g1_dds_mqtt.py --iface enp6s0 --mqtt-host <DGX>`; needs `MQTT_EDGE_PASSWORD` |

## Known limits (P1)

- Telegraf disk buffer is experimental upstream and not size-capped: watch the `telegraf-buffer` volume.
- Panda gripper is not modelled; no real robot adapter yet (needs the Franka system version).
- MQTT ACLs are configured but not covered by the smoke test (MQTT 3.1.1 silently drops denied publishes).
